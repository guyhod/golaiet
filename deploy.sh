#!/bin/bash
# Bring the host to what origin/main holds, from the Mac:  ./deploy.sh [commit] [--yes]
#
# What is deployed is what was pushed: the working copy has to be on main, with nothing uncommitted,
# at origin/main. With a commit of origin/main's history it goes back to that commit instead.
#
# Everything about the host comes from outside the repo, which is public: three settings, read from the
# environment or else from .env. DEPLOY_SSH is the SSH alias of the host, DEPLOY_DIR the folder of the
# working copy there, DEPLOY_URL the address the Mac reaches the host's dashboard at.
#
# In order: say what is about to happen and wait for a yes (--yes does not ask); refuse while a run is
# running on the host, since recreating the scheduler kills every session in flight; have the host
# fetch, move to the commit and build, while its old containers go on running the old images; ask
# again whether a run is running; take a dump of the database as it is; bring the stack up (the
# migrate service migrates); check from the Mac that it answers; print the commit the host runs and
# where the dump is.
#
# The build comes before the second asking and the dump because it takes minutes on a small machine:
# a run that started in those minutes would be killed by the recreate, and what was written in them
# would be missing from the dump "from before". If the build fails, or a run is running at the second
# asking, or the dump fails, nothing was recreated and the host's working copy goes back to the
# commit it ran.
#
# The dump is taken by `exec` in the scheduler's running container, which still holds the code from
# before. Never by `run`: that starts the migrate service first, and the dump "from before" would
# already hold the new schema.
set -eu
cd "$(dirname "$0")"

PY="${PY:-./.venv/bin/python}"
# test_ seam: tests/test_deploy.py points this at a file of its own, so the real .env is never read there.
env_file="${test_env_file:-.env}"

refuse() {
    echo "Not deployed: $*" >&2
    exit 1
}

setting() {
    local value="${!1:-}"
    if [ -z "$value" ] && [ -f "$env_file" ]; then
        value="$(sed -n "s/^$1=//p" "$env_file" | tail -1)"
    fi
    printf '%s' "$value"
}

ask=yes
target=""
for argument in "$@"; do
    case "$argument" in
        --yes) ask=no ;;
        -*) refuse "$argument is not an option of this command. It takes a commit and --yes." ;;
        *) target="$argument" ;;
    esac
done

host="$(setting DEPLOY_SSH)"
folder="$(setting DEPLOY_DIR)"
address="$(setting DEPLOY_URL)"
for name in DEPLOY_SSH DEPLOY_DIR DEPLOY_URL; do
    [ -n "$(setting "$name")" ] || refuse "$name is not set. Set DEPLOY_SSH (the host's SSH alias), DEPLOY_DIR (the folder of the working copy there) and DEPLOY_URL (the address this Mac reaches its dashboard at) in .env or in the environment."
done

git fetch --quiet origin
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || refuse "this working copy is not on main."
[ -z "$(git status --porcelain --untracked-files=no)" ] || refuse "this working copy has changes that are not committed."
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || refuse "main here is not at origin/main. What is deployed is what was pushed: push, or pull, first."
if [ -n "$target" ]; then
    commit="$(git rev-parse --verify --quiet "$target^{commit}")" || refuse "$target is not a commit in this working copy."
    git merge-base --is-ancestor "$commit" origin/main || refuse "$target is not in origin/main's history: the host runs only what is there."
else
    commit="$(git rev-parse origin/main)"
fi

on_host() {
    ssh "$host" "cd '$folder' && $1"
}

echo "About to bring the host ($host, $folder) to $(git log -1 --format='%h %s' "$commit")."
echo "A dump of its database is taken first. Its scheduler, web and dashboard are recreated: for some seconds nothing answers."
if [ "$ask" = yes ]; then
    printf 'Go on? Type yes: '
    read -r answer || answer=""
    [ "$answer" = yes ] || refuse "you did not say yes."
fi

# How the host stands, asked of its running code: which runs are running, and which migrations its database has.
how_it_stands() {
    on_host "docker compose exec -T scheduler python manage.py shell" <<'PYTHON'
from django.db.migrations.recorder import MigrationRecorder
from scheduler.models import JobRun
for run in JobRun.objects.filter(status="running").select_related("job"):
    print("running", run.job.name)
for app, name in MigrationRecorder.Migration.objects.values_list("app", "name"):
    print("applied", app, name)
PYTHON
}
running_in() {
    printf '%s\n' "$1" | sed -n 's/^running //p' | sort -u | tr '\n' ' '
}
WAIT_FOR_RUNS="Recreating the scheduler would kill their sessions: wait for them to end. A run that a killed scheduler left as running never will: set its status to failed in the admin."

state="$(how_it_stands)" || refuse "the scheduler's container on the host did not answer. This command deploys to a stack that is up: start it there first (docker compose up -d)."
running="$(running_in "$state")"
[ -z "$running" ] || refuse "runs are running on the host ( $running). $WAIT_FOR_RUNS"

# Going back to code that is behind the database: the host has applied migrations that the commit does not have.
in_the_commit="$(git ls-tree -r --name-only "$commit" | sed -n 's#^\([a-z_]*\)/migrations/\([0-9][^/]*\)\.py$#\1 \2#p')"
ahead=""
while read -r kind app name; do
    [ "$kind" = applied ] || continue
    if printf '%s\n' "$in_the_commit" | grep -q "^$app " && ! printf '%s\n' "$in_the_commit" | grep -Fqx "$app $name"; then
        ahead="$ahead $app/$name"
    fi
done <<< "$state"
[ -z "$ahead" ] || refuse "the host's database is ahead of that code: it has applied$ahead, which the commit does not have. Code never runs on a database from after it. Going back across a migration is done by hand on the host, in this order: docker compose down; git checkout --detach <the commit>; docker compose build; docker compose run --rm scheduler python manage.py pull_db /backups/<the dump from before that deploy> --takeover --replace; docker compose up -d. What was written since that dump is lost."

before="$(on_host "git rev-parse HEAD" < /dev/null)"

# From here the host's working copy is at the new commit while its containers still run the old images.
# Whatever stops the deploy before the stack is recreated puts both back: the working copy, and the
# images. A build leaves its images under the names compose uses, so without a second build at the
# old commit the next `docker compose up` or `run` on the host, for any reason, would recreate the
# containers from the build that was refused, with its migrations and with no dump.
back_and_refuse() {
    if on_host "git checkout --quiet --detach $before && docker compose build" < /dev/null; then
        refuse "$* The host's working copy is back at the commit it ran and it built again there, so its images hold what runs. The next try will find the new build in Docker's cache."
    fi
    echo "And the host could not be put back to $before with its images: on the host, git checkout --detach $before && docker compose build, before anything is started or run there." >&2
    refuse "$*"
}

on_host "git fetch --quiet origin && git checkout --quiet --detach $commit && docker compose build" < /dev/null \
    || back_and_refuse "the images did not build on the host for $(git rev-parse --short "$commit"). Nothing was recreated: it goes on running what it ran."

state="$(how_it_stands)" || back_and_refuse "the scheduler's container on the host stopped answering during the build. Nothing was recreated."
running="$(running_in "$state")"
[ -z "$running" ] || back_and_refuse "runs started on the host during the build ( $running). $WAIT_FOR_RUNS Nothing was recreated."

if ! dump="$(on_host "docker compose exec -T scheduler python manage.py backup_db" < /dev/null 2>&1)"; then
    case "$dump" in
        *"Unknown command"*) back_and_refuse "the code the host runs now has no backup_db, so no dump can be taken before the change. Bring that host to this code once by hand, with a dump taken by the tools it has." ;;
        *) back_and_refuse "no dump could be taken on the host, so nothing was recreated there. It said: $(printf '%s\n' "$dump" | grep -v -e '^DETAIL:' -e '^CONTEXT:' | tail -1)" ;;
    esac
fi
dump_file="$(printf '%s\n' "$dump" | sed -n 's/^\(.*\.dump\)  [0-9]* bytes$/\1/p' | head -1)"
echo "The dump from before: $dump_file (the scheduler container's path; the host's backup folder holds it)."

came_up() {
    on_host "docker compose up -d --wait" < /dev/null \
        && on_host "docker compose ps --status running --services | grep -qx scheduler" < /dev/null \
        && on_host "docker compose logs scheduler | grep -q 'scheduler starting'" < /dev/null \
        && SMOKE_URL="$address" "$PY" -m pytest -m smoke tests/smoke
}
if ! came_up; then
    # Not `./deploy.sh <before>`: it begins by asking the scheduler, which is what is down.
    echo "The host did not come up whole on $(git rev-parse --short "$commit"). It ran $before before, and the dump from before is $dump_file." >&2
    added="$(git ls-tree -r --name-only "$commit" | sed -n 's#^\([a-z_]*\)/migrations/\([0-9][^/]*\)\.py$#\1/\2#p' \
        | grep -Fvx -f <(git ls-tree -r --name-only "$before" | sed -n 's#^\([a-z_]*\)/migrations/\([0-9][^/]*\)\.py$#\1/\2#p') | tr '\n' ' ' || true)"
    if [ -z "$added" ]; then
        echo "To go back, by hand on the host: git checkout --detach $before && docker compose up -d --build" >&2
    else
        echo "The commit that failed added migrations ( $added), so the database may be ahead of the code from before. To go back, by hand on the host, in this order (docs/ops/HOST.md, section 4):" >&2
        echo "  docker compose down; git checkout --detach $before; docker compose build; docker compose run --rm scheduler python manage.py pull_db $dump_file --takeover --replace; docker compose up -d" >&2
        echo "What was written since that dump is lost." >&2
    fi
    exit 1
fi

echo "The host runs $(on_host "git rev-parse --short HEAD" < /dev/null). Before, it ran $before. The dump from before: $dump_file."
