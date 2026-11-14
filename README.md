# Golaiet

One agent that tracks the things Guy cares about, tells him when something
changes, and shows him where things stand.

**Status: Phase 3 built (2026-10-11).** Say "track X weekly" in Telegram and
a tracker, its jobs and its first observations follow; a weekly judge records
a level with its reason and a level change reaches Telegram; the dashboard at
`/` shows every tracker as a tile and "show me X" in chat opens it. Country
trackers (`country_risk`, ported from the conflict map) carry a sourced
record with a peace score and open on a globe. Stock trackers (`stock`,
ported from the investment engine) tick every 15 minutes in market hours,
alert once when the price reaches the line, and open on a price chart. Every
push runs unit, smoke and end-to-end checks. Phase 4, life, is built and not
yet cut over (2026-11-11): practices and campaigns are recorded from the
Telegram conversation and drawn on the Life screen (`/life` is the wall); the
steps and where each stands are in
[docs/LIFE_MIGRATION.md](docs/LIFE_MIGRATION.md). How to run:
[CLAUDE.md](CLAUDE.md).

## Operating it

**Bringing the running stack to the code in this folder.** `make stack`
rebuilds the images and runs the migrations. A job that code seeds (the
Friday `brief` is one) exists only after `seed_jobs` has run once:

```bash
make stack
docker compose exec scheduler python manage.py seed_jobs
make smoke
```

**The vault, for notes.** `add_note` writes only when `VAULT_HOST_DIR` in
`.env` names the vault's folder, and Docker Desktop shares that folder
(Settings › Resources › File sharing). Unset, the tool refuses.

**Running one job by hand.** Any job, by its name in admin:

```bash
docker compose exec scheduler python manage.py shell -c \
  "from scheduler.dispatcher import execute_job; from scheduler.models import Job; print(execute_job(Job.objects.get(name='brief')))"
```

This is a second process beside the scheduler, so it does not wait for a
reply that is being written: run `brief` when no message is in flight, or
the two would resume the conversation's session at once.

**The replay's scratch database.** The replay (Step 2 of the life plan)
runs real sessions on a database of its own, made beside the live one and
dropped afterwards. It refuses a database that holds a conversation, keeps
the CLI's transcripts in a temporary folder it removes, and needs
`CLAUDE_CODE_OAUTH_TOKEN` in `.env`:

```bash
docker exec golaiet-db sh -c 'createdb -U "$POSTGRES_USER" golaiet_scratch'
export DB_NAME=golaiet_scratch            # this shell only; every manage.py below goes to the scratch database
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py import_life <progress.md> --extras <extras.json> --events-until <the day before the first case>
./.venv/bin/python manage.py replay <cases.json>
unset DB_NAME
docker exec golaiet-db sh -c 'dropdb -U "$POSTGRES_USER" golaiet_scratch'
```

**The watcher and the nightly dump** run outside the stack, under launchd.
Nothing in this repo installs them. Before installing, `command -v docker`
must print a folder the plists' `PATH` lists (`/usr/local/bin`,
`/opt/homebrew/bin`, `/usr/bin`, `/bin`). A per-user install of Docker
Desktop puts it in `~/.docker/bin`: add that folder, by its full path, to
the `PATH` string in `ops/com.golaiet.backup.plist` first, or every dump
fails. The plists also name this folder by its full path; edit them if the
repo moves.

```bash
mkdir -p logs ~/Backups/golaiet
cp ops/com.golaiet.watch.plist ops/com.golaiet.backup.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.golaiet.watch.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.golaiet.backup.plist
launchctl kickstart gui/$(id -u)/com.golaiet.watch     # one run now: a line appears in logs/watch.log
launchctl kickstart gui/$(id -u)/com.golaiet.backup    # one dump now: a file in ~/Backups/golaiet, an `ok` line in logs/backup.log
```

`bootstrap` fails on an agent that is already loaded. After editing a plist,
copy it again, `bootout` the agent (below) and `bootstrap` it again.

The order the first time: install and take the first dump as above, which
is also the dump taken before the stack changes; then `make stack` and
`seed_jobs`; then the reboot that shows the stack comes back by itself.

**Seeing a notification.** The watcher speaks through `osascript`, which
macOS lists as Script Editor under System Settings › Notifications. The
first one may ask to be allowed, and a Focus hides it. To see one without
waiting for a stale heartbeat, point one run at an address nothing answers
on (it adds an `unreachable` line to `logs/watch.log`):

```bash
HEALTH_URL=http://127.0.0.1:9/ ops/watch.sh
```

With the scheduler stopped (`docker compose stop scheduler`), the hourly run
notifies once the last heartbeat is 90 minutes old; `MAX_AGE_MINUTES=1
ops/watch.sh` a few minutes after stopping shows the same notification
without the wait. Start it again with `docker compose start scheduler`.

**Restoring a dump**, into a database of its own beside the live one, and
comparing the row counts of the five tables that hold what cannot be
rebuilt. The restored counts are the live ones as of the dump: the live
side is ahead only by what was written since, in any of the five (trackers,
observations, assessments, messages, job runs).

```bash
counts="select 'core_tracker', count(*) from core_tracker union all select 'core_observation', count(*) from core_observation union all select 'core_assessment', count(*) from core_assessment union all select 'chat_message', count(*) from chat_message union all select 'scheduler_jobrun', count(*) from scheduler_jobrun"
docker exec golaiet-db sh -c 'createdb -U "$POSTGRES_USER" golaiet_restore'
docker exec -i golaiet-db sh -c 'pg_restore -U "$POSTGRES_USER" -d golaiet_restore' < ~/Backups/golaiet/golaiet-<day>.dump
docker exec golaiet-db sh -c 'psql -U "$POSTGRES_USER" -d golaiet_restore -Atc "$0"' "$counts"
docker exec golaiet-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' "$counts"
docker exec golaiet-db sh -c 'dropdb -U "$POSTGRES_USER" golaiet_restore'
```

To remove the two agents:

```bash
launchctl bootout gui/$(id -u)/com.golaiet.watch
launchctl bootout gui/$(id -u)/com.golaiet.backup
rm ~/Library/LaunchAgents/com.golaiet.watch.plist ~/Library/LaunchAgents/com.golaiet.backup.plist
```

## Why one project

Three projects were built separately and turned out to be the same machine
in different clothing:

| Project | Subject | Collects | Judges | Shows | Tells Guy |
|---|---|---|---|---|---|
| `investment_engine` | companies against investment theses | news, prices | committee verdict, buy thresholds | small website | Telegram alert |
| `geo_status_bashboard` | countries | LLM web research | conflict heat, peace score | 3D globe + sidebar | nothing |
| Obsidian `Life/Golaiet` | life campaigns, habits, watches | Guy's voice Inbox | burning / focus flags | metro-map wall screen | blocks in `Myself.md` |

Each one has its own scheduler, its own database, its own dashboard and its
own half of a notification channel. Golaiet keeps the pattern and builds it
once. See [docs/VISION.md](docs/VISION.md).

## Documents

| Doc | What's in it |
|---|---|
| [docs/VISION.md](docs/VISION.md) | The pattern (Tracker), the two interaction loops, what "focus" means, non-goals |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data model, request flows, agent runtime, deployment |
| [docs/LINEAGE.md](docs/LINEAGE.md) | What is taken from each existing project, and the lessons carried forward with their receipts |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases with exit criteria and explicit non-goals per phase |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Open decisions with a recommendation each, awaiting Guy |

## Relationship to the existing repos

The three source projects are not modified. They keep running until the
corresponding Golaiet phase reaches parity, then they are frozen (not
deleted) as extraction sources. The Organism (`claude_interface`) is a design
reference for the Telegram loop and the single task queue, not a dependency.
