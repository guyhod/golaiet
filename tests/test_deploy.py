"""deploy.sh with `ssh`, `git` and the smoke's python stood in for by scripts
of the test's own, first on the PATH: what it refuses, what it asks of the
host and in which order. There is no host to try it on; what only a
host can show is not shown here."""
import os
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy.sh"
COMMIT, BEFORE = "c0ffee0000000000000000000000000000000000", "0ddba11"

SSH = """#!/bin/sh
echo "$*" >> "$STAND_IN/asked"
case "$*" in
    *"manage.py shell"*) cat > "$STAND_IN/sent-to-shell"
        # The second asking, after the build, answers from its own file when the test wrote one.
        if grep -q "docker compose build" "$STAND_IN/asked" && [ -f "$STAND_IN/state-after-the-build" ]; then cat "$STAND_IN/state-after-the-build"; else cat "$STAND_IN/state"; fi
        exit "$(cat "$STAND_IN/state-exit")" ;;
    *"backup_db"*) cat "$STAND_IN/backup"; exit "$(cat "$STAND_IN/backup-exit")" ;;
    *"docker compose build"*) exit "$(cat "$STAND_IN/build-exit")" ;;
    *"up -d --wait"*) exit "$(cat "$STAND_IN/up-exit")" ;;
    *"rev-parse HEAD"*|*"rev-parse --short HEAD"*) echo %s ;;
esac
""" % BEFORE

GIT = """#!/bin/sh
case "$*" in
    "rev-parse --abbrev-ref HEAD") cat "$STAND_IN/branch" ;;
    "status --porcelain --untracked-files=no") cat "$STAND_IN/changes" ;;
    "rev-parse HEAD") cat "$STAND_IN/head" ;;
    "rev-parse origin/main") echo %s ;;
    "rev-parse --verify --quiet "*) [ -s "$STAND_IN/known" ] && cat "$STAND_IN/known" || exit 1 ;;
    "rev-parse --short "*) echo c0ffee0 ;;
    "merge-base --is-ancestor "*) exit "$(cat "$STAND_IN/ancestor-exit")" ;;
    "ls-tree -r --name-only %s") if [ -f "$STAND_IN/tree-before" ]; then cat "$STAND_IN/tree-before"; else cat "$STAND_IN/tree"; fi ;;
    "ls-tree -r --name-only "*) cat "$STAND_IN/tree" ;;
    "log -1 "*) echo "c0ffee0 a commit of the tests" ;;
esac
""" % (COMMIT, BEFORE)

SMOKE = """#!/bin/sh
echo "smoke SMOKE_URL=$SMOKE_URL $*" >> "$STAND_IN/asked"
exit "$(cat "$STAND_IN/smoke-exit")"
"""


@pytest.fixture
def host(tmp_path):
    """A host that is ready: nothing running, the database at the commit's migrations, everything answering.
    A test changes a file to change what the stand-ins say."""
    for name, script in (("ssh", SSH), ("git", GIT), ("python", SMOKE)):
        (tmp_path / name).write_text(script)
        (tmp_path / name).chmod(0o755)
    for name, said in {"branch": "main\n", "changes": "", "head": COMMIT + "\n", "known": "", "ancestor-exit": "0",
                       "tree": "core/migrations/0001_initial.py\ncore/migrations/0002_initial.py\ncore/models.py\nchat/migrations/0001_initial.py\n",
                       "state": "6 objects imported automatically.\napplied core 0001_initial\napplied core 0002_initial\napplied chat 0001_initial\napplied auth 0001_initial\n",
                       "state-exit": "0", "backup": "/backups/backup-2031-03-01T101500Z.dump  65000 bytes\nmigrations: core 0002_initial\ncore_tracker 4\n",
                       "backup-exit": "0", "build-exit": "0", "up-exit": "0", "smoke-exit": "0", "asked": ""}.items():
        (tmp_path / name).write_text(said)
    return tmp_path


def deploy(host, *arguments, typed="yes\n", **settings):
    environment = {"PATH": f"{host}:{os.environ['PATH']}", "STAND_IN": str(host), "PY": str(host / "python"),
                   "test_env_file": str(host / "no-such-env"), "DEPLOY_SSH": "the-host", "DEPLOY_DIR": "/srv/golaiet",
                   "DEPLOY_URL": "http://the-host:8003", **settings}
    done = subprocess.run([str(DEPLOY), *arguments], input=typed, env=environment, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr, (host / "asked").read_text().splitlines()


def test_it_asks_first_and_then_dumps_by_exec_moves_the_host_and_smokes_from_here(host):
    code, said, asked = deploy(host)
    assert code == 0, said
    assert "About to bring the host (the-host, /srv/golaiet) to c0ffee0 a commit of the tests" in said and "Go on? Type yes" in said
    assert [line.split("&& ", 1)[-1] for line in asked] == [
        "docker compose exec -T scheduler python manage.py shell",
        "git rev-parse HEAD",
        f"git fetch --quiet origin && git checkout --quiet --detach {COMMIT} && docker compose build",
        "docker compose exec -T scheduler python manage.py shell",
        "docker compose exec -T scheduler python manage.py backup_db",
        "docker compose up -d --wait",
        "docker compose ps --status running --services | grep -qx scheduler",
        "docker compose logs scheduler | grep -q 'scheduler starting'",
        "smoke SMOKE_URL=http://the-host:8003 -m pytest -m smoke tests/smoke",
        "git rev-parse --short HEAD",
    ]
    assert all(line.startswith("the-host cd '/srv/golaiet' && ") for line in asked if not line.startswith("smoke"))
    assert not any("compose run" in line for line in asked), "a `run` would start the migrate service before the dump"
    assert "JobRun.objects.filter(status=\"running\")" in (host / "sent-to-shell").read_text()
    assert f"The host runs {BEFORE}. Before, it ran {BEFORE}. The dump from before: /backups/backup-2031-03-01T101500Z.dump." in said


def test_without_a_yes_nothing_is_asked_of_the_host_and_with_the_option_it_does_not_ask(host):
    code, said, asked = deploy(host, typed="y\n")
    assert code == 1 and "Not deployed: you did not say yes." in said and asked == []
    code, said, asked = deploy(host, "--yes", typed="")
    assert code == 0 and "Go on?" not in said and len(asked) == 10


@pytest.mark.parametrize("file,content,sentence", [
    ("branch", "host\n", "is not on main"),
    ("changes", " M core/models.py\n", "has changes that are not committed"),
    ("head", "0000000000000000000000000000000000000000\n", "is not at origin/main. What is deployed is what was pushed"),
])
def test_it_refuses_unless_this_working_copy_is_what_was_pushed(host, file, content, sentence):
    (host / file).write_text(content)
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and f"Not deployed: " in said and sentence in said and asked == []


@pytest.mark.parametrize("missing", ["DEPLOY_SSH", "DEPLOY_DIR", "DEPLOY_URL"])
def test_it_refuses_without_its_three_settings_and_reads_them_from_the_env_file_too(host, missing):
    code, said, asked = deploy(host, "--yes", **{missing: ""})
    assert code == 1 and f"{missing} is not set" in said and asked == []
    (host / "an-env").write_text(f"OTHER=1\n{missing}=from-the-file\n")
    code, said, asked = deploy(host, "--yes", **{missing: "", "test_env_file": str(host / "an-env")})
    assert code == 0, said


def test_it_refuses_while_a_run_is_running_and_names_the_jobs(host):
    (host / "state").write_text("running research:prt\nrunning reply\napplied core 0001_initial\n")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "runs are running on the host ( reply research:prt )" in said and "wait for them to end" in said
    assert len(asked) == 1, "after asking how the host stands, nothing more"


def test_a_host_whose_scheduler_does_not_answer_and_one_without_backup_db_are_refused_in_words(host):
    (host / "state-exit").write_text("1")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "the scheduler's container on the host did not answer" in said and len(asked) == 1

    (host / "state-exit").write_text("0")
    (host / "backup").write_text("Unknown command: 'backup_db'\nType 'manage.py help' for usage.\n")
    (host / "backup-exit").write_text("1")
    (host / "asked").write_text("")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "the code the host runs now has no backup_db" in said
    assert asked[-1].endswith(f"git checkout --quiet --detach {BEFORE} && docker compose build"), "the working copy and the images were put back"
    assert not any("up -d" in line for line in asked), "nothing was recreated"


def test_a_build_that_fails_and_a_run_that_started_during_it_recreate_nothing_and_put_the_host_back_with_its_images(host):
    back = f"git checkout --quiet --detach {BEFORE} && docker compose build"
    (host / "state-after-the-build").write_text("running research:prt\napplied core 0001_initial\n")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "runs started on the host during the build ( research:prt )" in said
    assert "it built again there, so its images hold what runs" in said and "in Docker's cache" in said
    assert asked[-1].endswith(back) and not any("backup_db" in line or "up -d" in line for line in asked)

    (host / "build-exit").write_text("1")
    (host / "asked").write_text("")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "the images did not build on the host for c0ffee0. Nothing was recreated" in said
    assert asked[-1].endswith(back) and not any("backup_db" in line or "up -d" in line for line in asked)
    assert "could not be put back" in said and f"git checkout --detach {BEFORE} && docker compose build, before anything is started" in said


def test_going_back_is_the_same_command_with_a_commit_and_is_refused_across_a_migration(host):
    earlier = "ea111e0000000000000000000000000000000000"
    (host / "known").write_text(earlier + "\n")
    code, said, asked = deploy(host, "ea111e0", "--yes")
    assert code == 0 and any(f"checkout --quiet --detach {earlier}" in line for line in asked)

    (host / "tree").write_text("core/migrations/0001_initial.py\nchat/migrations/0001_initial.py\n")
    (host / "asked").write_text("")
    code, said, asked = deploy(host, "ea111e0", "--yes")
    assert code == 1 and "the host's database is ahead of that code: it has applied core/0002_initial" in said
    assert "pull_db /backups/<the dump from before that deploy> --takeover --replace" in said and len(asked) == 1

    (host / "known").write_text("")
    code, said, _ = deploy(host, "no-such", "--yes")
    assert code == 1 and "no-such is not a commit in this working copy" in said
    (host / "known").write_text(earlier + "\n")
    (host / "ancestor-exit").write_text("1")
    code, said, _ = deploy(host, "ea111e0", "--yes")
    assert code == 1 and "is not in origin/main's history" in said


@pytest.mark.parametrize("file", ["up-exit", "smoke-exit"])
def test_a_host_that_does_not_come_up_whole_is_told_the_way_back_that_works_with_the_scheduler_down(host, file):
    (host / file).write_text("1")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "did not come up whole on c0ffee0" in said
    assert f"It ran {BEFORE} before, and the dump from before is /backups/backup-2031-03-01T101500Z.dump" in said
    assert f"To go back, by hand on the host: git checkout --detach {BEFORE} && docker compose up -d --build" in said
    assert "./deploy.sh" not in said, "that begins by asking the scheduler, which is what is down"

    (host / "tree-before").write_text("core/migrations/0001_initial.py\nchat/migrations/0001_initial.py\n")
    (host / "asked").write_text("")
    code, said, asked = deploy(host, "--yes")
    assert code == 1 and "The commit that failed added migrations ( core/0002_initial )" in said
    assert f"docker compose down; git checkout --detach {BEFORE}; docker compose build; docker compose run --rm scheduler "\
           "python manage.py pull_db /backups/backup-2031-03-01T101500Z.dump --takeover --replace; docker compose up -d" in said
    assert "up -d --build" not in said and "What was written since that dump is lost." in said
