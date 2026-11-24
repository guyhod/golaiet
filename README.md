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

**Bringing the running stack to the code in this folder**, while the stack
runs on this machine. `make stack` rebuilds the images and runs the
migrations. A job that code seeds (the Friday `brief` and the nightly
`backup` are two) exists only after `seed_jobs` has run once. A host is
brought to `origin/main` from the Mac by `./deploy.sh` instead
([docs/ops/HOST.md](docs/ops/HOST.md)):

```bash
make stack
docker compose exec scheduler python manage.py seed_jobs
make smoke
```

**The vault, for notes.** `add_note` writes only when `VAULT_HOST_DIR` in
`.env` names the vault's folder, and Docker Desktop shares that folder
(Settings › Resources › File sharing). Unset, the tool refuses. The vault
stays on the Mac: on a host the tool is off.

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
`CLAUDE_CODE_OAUTH_TOKEN` in `.env`. It empties the Telegram token and
`VAULT_DIR` for its own run, so nothing is sent and no note is written.
`replay <cases.json> --list` prints which cases would be run, without a
session or a database:

```bash
docker exec golaiet-db sh -c 'createdb -U "$POSTGRES_USER" golaiet_scratch'
export DB_NAME=golaiet_scratch            # this shell only; every manage.py below goes to the scratch database
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py import_life <progress.md> --extras <extras.json> --events-until <the day before the first case>
./.venv/bin/python manage.py replay <cases.json>
unset DB_NAME
docker exec golaiet-db sh -c 'dropdb -U "$POSTGRES_USER" golaiet_scratch'
```

**Where it runs.** On the Mac, since 2026-10-10 and still on 2026-11-24.
Guy has decided to move the running stack to an always-on host; what that
takes is built and has not yet met a host. After the move the Mac is where
the code is developed, and its database is a marked copy on which no
scheduler starts. [docs/ops/HOST.md](docs/ops/HOST.md) is the whole of it:
what a host needs, the night of the move, a deploy and going back, and
what is not proven until there is a host.

**Backups.** A job of the stack, `backup`, dumps the database every night
into the folder `BACKUP_HOST_DIR` names (`~/Backups/golaiet` when unset),
thirty days kept, each dump with its row counts beside it. One by hand:

```bash
docker compose exec scheduler python manage.py backup_db
```

**Restoring a dump, or copying the database from another machine**, is
`pull_db`, run where the database is replaced. The dump is restored into a
new database beside the live one, compared with the counts it wrote down,
and swapped in by name; the database that was there is kept under a dated
name. The result is a marked copy unless `--takeover` is given:

```bash
docker compose rm --stop --force scheduler
docker compose run --rm scheduler python manage.py pull_db /backups/<the dump> --takeover --replace
docker compose up -d
```

**Knowing that it is down.** With `HEARTBEAT_PING_URL` set, the heartbeat
calls that address every half hour, and a service outside the stack alerts
when the calls stop.

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
| [docs/ops/HOST.md](docs/ops/HOST.md) | The machine the stack runs on: what it needs, moving to it, deploying, backups, copies, and what is unproven until there is one |

## Relationship to the existing repos

The three source projects are not modified. They keep running until the
corresponding Golaiet phase reaches parity, then they are frozen (not
deleted) as extraction sources. The Organism (`claude_interface`) is a design
reference for the Telegram loop and the single task queue, not a dependency.
