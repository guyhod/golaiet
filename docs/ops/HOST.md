# The host

Where the stack runs, how it gets there, and how it is looked after. Written
2026-11-24. **On that day the stack still runs on the Mac and the move has
not happened**: everything below about a host other than the Mac is built
and tested in this repo and has never met a real machine. What that leaves
unproven is gathered at the end, as a list to work through on the first
night.

After the move the Mac is where the code is developed and tested, and its
database is a marked copy. The host runs only what `origin/main` holds, and
nobody edits code on it.

This file names no provider, no machine and no address: the repo is public.
"The host" is the always-on machine, "the private network" is the network
between Guy's own devices, and what belongs in `.env` is given by name.

## 1. What a host needs

- **A Linux machine with Docker, the compose plugin and `git`.** The repo
  is cloned with `git` and a deploy fetches with it. Nothing else is
  installed: no Python, no Node, no Postgres tools. The images are built on
  the host itself, so its processor's kind does not matter.
- **Memory: 8 GB, and a swap file.** An estimate, not a measurement. The
  scheduler runs up to ten agent sessions side by side and a reply to a
  message is an eleventh; each is a CLI process with a tool server of its
  own. Without swap a host that runs short kills a process, not a queue.
  The first Monday at 07:00, when the week's jobs fall together, is the
  time to look.
- **Outbound HTTPS, and no inbound port.** Telegram is polled, never
  called back. Nothing listens to the internet.
- **The dashboard answers the host's own address alone** (`127.0.0.1:8003`
  in `docker-compose.yml`), and that is not a setting. Other devices reach
  it because the private network's own proxy, on the host, hands that port
  on to the network. They use plain HTTP on the host's private name: the
  network encrypts, and a proxy that ended TLS would need
  `CSRF_TRUSTED_ORIGINS`, which this code does not set. SSH goes over the
  same network.
- **The admin has no login**, on Guy's word of 2026-11-24. On the Mac it
  answered the Mac alone. On the host it is open, to read and to write
  every row, to every device on the private network. So a machine or a
  person that is not Guy's is not let onto that network while this stands.
  The dump's token (section 7) guards the dump and nothing else.

### What `.env` holds

By name; the values are in no file of this repo. `.env.template` has the
same names with a line on each.

| Name | For |
|---|---|
| `DJANGO_SECRET_KEY`, `DB_PASSWORD` | required anywhere |
| `DJANGO_ALLOWED_HOSTS` | every name the dashboard is reached under: on the host, its private name beside `localhost,127.0.0.1` |
| `DJANGO_TIME_ZONE` | the clock the schedules are written in |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | the channel. On the live machine only: see section 3, the last steps |
| `CLAUDE_CODE_OAUTH_TOKEN` | the plan token the agent's sessions run on (section 9) |
| `CLAUDE_MODEL`, `CLAUDE_REPLY_MODEL`, `AGENT_TIMEOUT_SEC` | as on the Mac |
| `BACKUP_HOST_DIR` | the folder the dumps are written to, mounted at `/backups`. Unset: `~/Backups/golaiet`. Outside the working copy |
| `DUMP_TOKEN` | the secret both machines of a copy hold, 32 characters or more (section 7) |
| `HEARTBEAT_PING_URL` | the outside address the heartbeat calls (section 6). A secret |
| `VAULT_HOST_DIR` | not set on the host: the vault does not move, and `add_note` stays off there |
| `DEPLOY_SSH`, `DEPLOY_DIR`, `DEPLOY_URL` | on the Mac only: where `deploy.sh` finds the host (section 4) |

### Running a command where there is no virtualenv

The README and `CLAUDE.md` write commands for the Mac, with
`./.venv/bin/python` and `make`. A host has neither. There:

```bash
docker compose exec scheduler python manage.py <command>        # the stack is up
docker compose run --rm scheduler python manage.py <command>    # the scheduler is stopped
```

`run` starts the `db` and `migrate` services first, so the database is
migrated to the code before the command runs. A command that takes a file
sees only what the scheduler's container mounts: the backup folder at
`/backups`, and anything else by `-v /path/on/the/host:/in/the/container:ro`
on that one `run`. Of the `Makefile`, `up`, `stack`,
`stack-without-scheduler`, `logs` and `down` need no virtualenv; where there
is no `make` either, each is the one or two `docker compose` lines under its
name.

## 2. Raising a host from nothing

**From a clone and an empty database**, for a stack with no history:

```bash
git clone <the repo's HTTPS address> golaiet && cd golaiet
cp .env.template .env        # and fill it in
docker compose up -d --build
docker compose exec scheduler python manage.py seed_jobs
```

**From a dump**, which is also how a lost host is raised again. The dump
goes into the backup folder first (`BACKUP_HOST_DIR`), with its `.json`
beside it if it has one:

```bash
git clone <the repo's HTTPS address> golaiet && cd golaiet
cp .env.template .env        # and fill it in
docker compose build
docker compose run --rm scheduler python manage.py pull_db /backups/<the dump> --takeover
docker compose up -d
docker compose exec scheduler python manage.py seed_jobs
```

The `run` brings up the database and migrates it empty; a database that was
only migrated counts as empty, so no `--replace` is needed. `--takeover`
makes the result the live database: from a file the command cannot ask
whether the dump's source is stopped, and says that it took your word.
`seed_jobs` adds any job the code has gained since the dump; rows that are
there are left alone.

## 3. The night of the move

The Mac is the source and the host is where the stack will run. There are
two ways to carry the database, then one ending for both. Read the whole
section before the first step, and section 10 before the night.

Before either way, on the host: section 1 is done, the repo is cloned,
`.env` is filled in (with the bot's token: the host is about to be the live
one), and `docker compose build` has run.

### By address

The host fetches the dump from the Mac itself and asks it how it stands.
This needs the Mac to run this code, since the code before it has no dump
endpoint and no scheduler's lock.

1. On the Mac, in `.env`: `DUMP_TOKEN`, and in `DJANGO_ALLOWED_HOSTS` the
   name the host will use for the Mac. Without the name Django answers 400
   and the pull says so. On the host, `.env` holds the same `DUMP_TOKEN`.
2. On the Mac: `make stack`, so that it runs this code and `web` has read
   the two settings. Better days before the night than on it: the night
   should not be the first time this code runs the live stack. The two
   settings can be added later, and `docker compose up -d web` then has
   `web` read them.
3. On the Mac: hand its dashboard (`127.0.0.1:8003`) on to the private
   network, as the host's is.
4. On the Mac: **remove** the scheduler, `docker compose rm --stop --force scheduler`.
   Not `stop`: every service has `restart: always`, and a stopped container
   starts again when Docker does. Wait first until no run is running (the
   admin's job runs, or the refusal in the next step tells you).
5. On the host:

   ```bash
   docker compose run --rm scheduler python manage.py pull_db http://<the Mac's private name>:8003 --takeover
   ```

   It refuses, with what to do, unless the Mac says all three: it is not a
   copy, no scheduler holds its lock, no run is running.

### By file

Needs nothing of this code on the source: only a dump taken with the tools
it has.

1. On the Mac: remove the scheduler as in step 4 above, after the last run
   has ended.
2. On the Mac, the one line the old nightly script ran:

   ```bash
   docker exec golaiet-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > golaiet-move.dump
   ```

   or, when the Mac runs this code, `docker compose run --rm scheduler python manage.py backup_db`,
   which writes `backup-<time>.dump` into the Mac's backup folder, with the
   counts beside it as `backup-<time>.dump.json`, and prints the name.
3. Carry the file (and its `.json`, if there is one) into the host's backup
   folder, under the name it has.
4. On the host, with the name of the file that step 2 made:

   ```bash
   docker compose run --rm scheduler python manage.py pull_db /backups/<the file of step 2> --takeover
   ```

   A dump with no `.json` beside it is pulled all the same, and the command
   says that there was nothing to compare the restore with.

### The same end for both

5. **The conversation's session.** The agent's memory of the conversation
   is one file in the scheduler's `claude_state` volume; without it the
   next message opens a new session, which has Guy's conventions and the
   tools and none of what was said, the Friday brief's questions among it.
   `pull_db --takeover` prints whether the store it sees holds that
   session. To carry the store's sessions over, from the Mac:

   ```bash
   docker compose run --rm --no-deps -T scheduler tar -C /root/.claude -cf - projects \
     | ssh <the host> "cd <the folder> && docker compose run --rm --no-deps -T scheduler tar -C /root/.claude -xf -"
   ```

   Not tried. To check afterwards, on the host: the conversation's session
   id is on its row in the admin, and
   `docker compose run --rm --no-deps scheduler sh -c 'ls /root/.claude/projects/*/'`
   should list `<that id>.jsonl`.
6. On the host: `docker compose up -d`, then
   `docker compose exec scheduler python manage.py seed_jobs`. Send the bot
   a message and see it answered.
7. From the Mac: the smoke, `SMOKE_URL=http://<the host's private name>:8003 ./.venv/bin/python -m pytest -m smoke tests/smoke`.
8. On the Mac: `docker compose down`. Its scheduler was removed at the
   start, but its database is still the unmarked one that was live: until
   it is marked (step 10), a `make stack` or a `docker compose up` there,
   by habit or by a script, brings up a second live system on the same bot.
9. On the Mac: take `TELEGRAM_BOT_TOKEN` out of `.env`, now, before the
   copy's stack comes up in the next step: a container reads `.env` when it
   is created, so a token taken out later is still in every container that
   is running. The mark already keeps a copy from sending, and the token's
   absence is the second lock.
10. On the Mac: make its database a marked copy of the host's, one of two
    ways, then `make stack-without-scheduler`. From now a scheduler started
    on the Mac refuses.
    - **By file**, which needs nothing more than this code on the Mac
      (built: `docker compose build`). On the host,
      `docker compose exec scheduler python manage.py backup_db`; carry the
      file it names, with its `.json`, from the host's backup folder to the
      Mac's (on the host the files are root's: section 5); then on the Mac
      `docker compose run --rm scheduler python manage.py pull_db /backups/<that file> --replace`.
    - **By address**: `docker compose run --rm scheduler python manage.py pull_db http://<the host's private name>:8003 --replace`.
      This needs the Mac on this code and built, the same `DUMP_TOKEN` in
      both `.env` files, and the host's `web` started with that token and
      with the host's private name in `DJANGO_ALLOWED_HOSTS`. After the way
      by file none of that was needed until now.
11. On the Mac, the two launchd agents of the old watcher and backup, if
    they were ever installed. **This step does not wait for the night.**
    The agents run two scripts that left the repo when this code was merged
    into `main`: from the day the Mac's working copy holds this code they
    fail every hour and every night without a word. The check is one line,
    `launchctl list | grep golaiet`, and nothing printed means there is
    nothing to do. Otherwise:

    ```bash
    launchctl bootout gui/$(id -u)/com.golaiet.watch
    launchctl bootout gui/$(id -u)/com.golaiet.backup
    rm ~/Library/LaunchAgents/com.golaiet.watch.plist ~/Library/LaunchAgents/com.golaiet.backup.plist
    ```
12. Point the wall at the host's private name, set `HEARTBEAT_PING_URL` on
    the host (section 6), and set `DEPLOY_*` on the Mac (section 4).

### Turning back in the middle

- **Before the Mac's scheduler was removed**: nothing has changed.
- **After it was removed, before the host's stack came up** (up to step 6,
  where it comes up):
  on the Mac, `docker compose up -d`. Its database was never touched and is
  still the live one. On the host, leave the stack down; its database is an
  unmarked takeover, so before anything is started there again, pull a copy
  onto it or drop its volume.
- **After the host's stack came up and took a message**: the host is the
  live one, and going back is a move in the other direction. Remove the
  host's scheduler, pull on the Mac from the host with `--takeover --replace`,
  start the Mac's stack, and bring the host down. What the host recorded is
  then on the Mac.

## 4. A deploy, and going back

Development is on the Mac: a branch, `make check` and `make e2e`, a push,
the three checks on GitHub. Then, on the Mac:

```bash
./deploy.sh            # or: make deploy
./deploy.sh --yes      # does not ask
```

It needs `DEPLOY_SSH` (the host's SSH alias), `DEPLOY_DIR` (the working
copy's folder there) and `DEPLOY_URL` (the address the Mac reaches the
host's dashboard at), in `.env` or the environment. It deploys only what
was pushed: the Mac's working copy has to be on `main`, with no uncommitted
change, at `origin/main`. It says what it is about to do and waits for a
`yes`. Then, in order: it refuses while a run is running on the host; the
host fetches, moves to the commit and builds, while the old containers go
on running; it asks again whether a run is running; it takes a dump by
`exec` in the running scheduler, which still holds the code from before;
the stack comes up and the `migrate` service migrates; the smoke runs from
the Mac against the host. It prints the commit the host runs and where the
dump from before is. If anything stops it before the stack is recreated,
the host's working copy is put back and the host goes on running what it
ran.

**Going back** is the same command with a commit of `origin/main`'s
history: `./deploy.sh <commit>`.

**Going back across a migration** is refused by the command: the commit is
behind the database, and code never runs on a database from after it. It
is done by hand on the host, in this order, **and has not been tried**:

```bash
docker compose down
git checkout --detach <the commit>
docker compose build
docker compose run --rm scheduler python manage.py pull_db /backups/<the dump from before that deploy> --takeover --replace
docker compose up -d
```

The pull has to run under the code from before: under the newer code it
would migrate the older dump forward again. What was written since that
dump is lost. Telegram has already forgotten those messages, so Guy
forwards them again; a forwarded message is filed with its original time.

## 5. Backups

A job of the stack, `backup`, dumps the whole database every night at 03:15
into the backup folder: `nightly-<day>.dump`, a standard `pg_dump` archive,
with `nightly-<day>.dump.json` beside it (when it was taken, the head of
the migrations, the row count of every table). Thirty days are kept. The
job removes only files of its own prefix, and only after the night's dump
is in place; a night whose dump failed removes nothing, is a failed run,
and the failure notice reaches Telegram. The job exists after `seed_jobs`
has run once.

A dump by hand, which a deploy also takes: `docker compose exec scheduler python manage.py backup_db`.
Its file is `backup-<time>.dump`, and no code ever removes one. Both kinds
are readable by their owner only: a dump holds every row.

**Restoring one** is section 2's second half on a new host, and on a host
that is up:

```bash
docker compose rm --stop --force scheduler
docker compose run --rm scheduler python manage.py pull_db /backups/<the dump> --takeover --replace
docker compose up -d
```

The restore is compared, table by table, with the counts the dump wrote
down. The database that was there is kept beside the new one (section 7).
A dump that restores with stock tools when this code does not run:
`pg_restore -d <a database> <the dump>`.

**Not built:** a copy of the dumps that leaves the host. Until there is
one, a host that is lost takes its backups with it. Where that copy goes
and whether it is encrypted are Guy's to decide, and the move is not done
before it exists. The files are not encrypted where they lie. On a Linux
host the container writes them as root, readable by root alone: whoever
copies them off the host, or restores one with stock tools, does it as
root.

## 6. Knowing that it is down

Nothing inside the stack can say that the stack is down. When
`HEARTBEAT_PING_URL` is set, the heartbeat job calls it every half hour: an
outside service that expects the call and alerts Guy when the calls stop.
The account there is his. A call that fails does not fail the heartbeat;
the run's summary says that it failed and how. The address is a secret:
whoever holds it can keep the alarm quiet, and it is in no log.

**What it sees:** that the scheduler runs its jobs and the database
answers. **What it no longer sees**, which the old watcher on the Mac did
by reading `/api/health` through nginx: the web process or the dashboard
down while the scheduler lives. The wall going blank is the signal for
that.

A job that fails tells Guy in Telegram, once an hour for each job, as
before.

## 7. A copy

A copy of the live database, on another machine, for development or for a
machine that only reads:

```bash
docker compose run --rm scheduler python manage.py pull_db http://<the live machine's private name>:8003 --replace
make stack-without-scheduler
```

or the same with a dump file. Both machines hold the same `DUMP_TOKEN`; the
live one serves its dump at `/api/dump` only to a caller that sends it, one
dump at a time.

- **A copy is marked**, by a comment on its database, unless `--takeover`
  was given. On a marked database the scheduler refuses to start, and one
  that finds its database marked on a later tick stops; Telegram counts as
  not configured, so a flow run by hand sends nothing. The mark is not
  inside a dump, so it never travels.
- **A copy's stack is brought up without the scheduler**
  (`make stack-without-scheduler`). Under `restart: always` a scheduler on
  a copy would be started again for ever, a minute apart, and never read as
  up.
- **What `pull_db` refuses:** while a scheduler holds the lock on the
  database it would replace; to replace rows somebody wrote, without
  `--replace`; a dump newer than the code; a restore that does not hold
  what the dump counted; a takeover from an address whose source is a copy,
  has a scheduler alive or a run running.
- **What a pull keeps.** The dump is restored into a new database beside
  the live one and the two names are swapped. The database that was there
  stays as `<name>_before_<time>`: it is the way back, and no code drops
  it. Each pull prints the earlier ones with the statement that drops each:

  ```bash
  docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE \"<name>_before_<time>\";"'
  ```

  A pull that was killed can leave `<name>_incoming_<time>`; the next pull
  lists it the same way.
- **One scheduler on a database.** The scheduler holds a lock for as long
  as it lives; a second one on the same database refuses.

## 8. The vault and private files

The vault stays on the Mac. `add_note` is off on the host, and says so when
the agent tries it. A private data file that a command takes by path (a
board to import, a tracker's first record) is carried to the host by hand
and mounted for that one `run`, as section 1 shows.

## 9. Renewing the plan token

The agent's sessions run on Guy's plan through `CLAUDE_CODE_OAUTH_TOKEN`,
which lives about a year. When sessions start failing with a login error:
on any machine where he is logged in, `claude setup-token`; put the new
value into the host's `.env`; `docker compose up -d`, which recreates the
containers that read it. When `ANTHROPIC_API_KEY` is also set the plan
token wins, so nothing is billed to the API.

## 10. Not proven until there is a host

Everything here was tested with stand-ins, or inside the end-to-end stack
on one machine and one Postgres. To be worked through on the first night,
before anything depends on it:

1. **The private network's proxy** hands the dashboard on with no change to
   the compose file.
2. **A container reaches the other machine's private name**: `pull_db` by
   address runs in a container. An address in place of the name is the
   fallback.
3. **A pull between two machines**, with a real token, and its counts.
4. **An image built on the host's processor.** Only the Mac's kind was
   built.
5. **The default backup folder**, `~/Backups/golaiet`, as compose resolves
   it on the host; and the nightly job fired by its own schedule.
6. **`make stack-without-scheduler`** as a whole.
7. **The deploy command, all of it beyond its own logic**: that
   `manage.py shell` on the host reads what is sent through `ssh` and
   `docker compose exec -T`; `docker compose up -d --wait` with the one-off
   `migrate` service; the smoke over the private address.
8. **Going back across a migration**, by hand (section 4).
9. **Carrying the session store** between the two volumes (section 3,
   step 5).
10. **The outside call** against the real service, and its alert with the
    scheduler stopped by hand.
11. **Prices from the host**: the price job reads an unofficial endpoint
    that is known to limit data-centre addresses.
12. **Memory** on the first Monday at 07:00.
13. **A scheduler that starts during a pull**, and **a session that comes
    back between the rounds of the swap**: both stop or retry correctly
    against stand-ins only. On the night `web` is the one that comes back.
14. **A peer that vanishes**: the code's own database sessions carry
    keepalives; none was made to vanish.
15. **A forced drop** of a pull's new database with a session really left
    on it.

## 11. What replaced what

| Until the move, on the Mac | Now, in the stack |
|---|---|
| `ops/backup.sh` under launchd, nightly | the `backup` job (section 5) |
| restoring by hand with `pg_restore` and a count of five tables | `pull_db <file>`, which counts every table (sections 2 and 5) |
| `ops/watch.sh` under launchd, hourly, a macOS notification | the heartbeat's outside call (section 6) |
| `make stack` on the Mac | `deploy.sh` from the Mac (section 4) |
