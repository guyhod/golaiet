# CLAUDE.md

Guidance for Claude Code in this repo. The collaboration protocol and code
style in `/Users/guyhod/Kruv/CLAUDE.md` apply here in full.

## Read first

- `docs/VISION.md` for what a Tracker is and what "focus" means.
- `docs/ARCHITECTURE.md` for the processes, the data model and the flows.
  Section 6.1 and 6.2 describe one agent run end to end, including the
  tool server over the pipe.
- `docs/DECISIONS.md` before reopening any design question: decided rows
  are not relitigated.
- `docs/ROADMAP.md` for the current phase and its exit test.

## Rules specific to this repo

- **Nothing from the content of Guy's vault enters this repo**: no names,
  messages, labels, counts, dates of personal events or examples taken from
  it, in code, comments, tests, fixtures, documents, commit messages or any
  log that is kept. Tests run on invented data. What a command needs from
  the vault (the import, the replay) it takes by path at run time.
- **A migration that has been committed is not edited.** A change is a new
  migration: a database that already applied the old one would get nothing,
  `migrate` would report nothing to do, and `makemigrations --check` cannot
  see it.
- **`--safe-mode` and `--bare` are never passed to the CLI.** Safe mode
  disables `--mcp-config` servers; bare strips the web tools. Sessions are
  kept clean by `CLAUDE_CONFIG_DIR` and `--tools` instead (see
  `agent/runner.py`).
- **The tool server never prints.** `manage.py mcp_tools` owns stdout for
  the protocol; logging goes to stderr.
- **A prompt never repeats a value that lives in the data.** Tracker lists,
  cadences and schemas reach the model through tools, not prompt text.
- **Agents never alter the schema.** A new tracker is rows; a new kind is a
  module under `core/kinds/` plus a view.
- **The tool server never talks to Telegram.** Alerts a session raises are
  rows; the flow delivers them after the CLI has exited (`chat/alerts.py`).
- **Heat and conflict kind definitions, and the trend step, live once**, in
  `core/kinds/country_risk.py`; the research prompt renders them and the
  globe's legend copies them. Change both together.
- **One scheduler registrar.** APScheduler jobs are added only in
  `manage.py run_scheduler`, never in `AppConfig.ready()`.
- **A judgment is written once, by `agent.tools.judge`.** The tool the agent
  calls and the scripts that judge without a session (prices) both go through
  it, so the kind's alert rule and the run's provenance apply the same way.
- **No test sends a statement on a whole database, or one that ends a
  session.** The tests run on the Postgres of whatever stack is up on the
  machine, in a database beside the live one: creating, renaming or
  dropping a database and ending sessions are all in `core/restore.py`,
  which a unit test replaces whole, and they run for real only inside the
  end-to-end stack (`tests/e2e/stack_check.py`), on its own Postgres.
- **A copy is never a second live system.** A database pulled without
  `--takeover` is marked, and on a marked database no scheduler runs and
  nothing is sent to Telegram (`core/standing.py`). Nothing sets or clears
  the mark but `pull_db`, and never on the database of the running stack.
- **No host name, address, account or token in this repo.** It is public.
  Documents say "the host" and "the private network"; what a command needs
  it reads from `.env` by name.
- **Charts are Apache ECharts through `dashboard/src/chart.tsx`.** A view
  registers the chart types it draws and builds its option as a pure function
  (tested in Vitest); colours come from the CSS tokens, never literals.

## Running

```bash
cp .env.template .env            # fill in: DB_PASSWORD, TELEGRAM_*, CLAUDE_CODE_OAUTH_TOKEN
make stack                       # the whole thing: db, migrate, web, scheduler, dashboard on 8003
                                 # admin at http://127.0.0.1:8003/admin/, no login: the dashboard answers this machine's own address alone
make logs

# Host dev instead (stop the compose scheduler first: one scheduler per database, and a second one refuses)
make up && make migrate          # Postgres on 5435, then the schema
./.venv/bin/python manage.py seed_jobs
./.venv/bin/python manage.py research prt --lens antisemitism   # one country now; --lens studies one lens in depth
make scheduler                   # job loop + Telegram poller
make run                         # Django admin + API on 8003
make dashboard-dev               # Vite on 5174, /api proxied to 8003
make check                       # what CI runs on every push: pytest + migrations current + dashboard typecheck/Vitest
make smoke                       # after make stack: the deployed stack answers through nginx
make stack-without-scheduler     # the stack of a database that is a copy: a scheduler refuses one
make deploy                      # from the Mac: bring the host to origin/main (docs/ops/HOST.md)
make e2e                         # the chain with Claude and Telegram faked, Playwright at the screen (fresh stack on 8013)
```

## Testing

Three layers, and every push runs all three in GitHub Actions
(`.github/workflows/check.yml`); a red check does not ship.

- **Unit**: `tests/` (pytest against the Postgres on 5435) and the dashboard's
  `src/**/*.test.ts` (Vitest, pure modules only). A flow test stubs the CLI
  on `ClaudeRunner.run`; the tool-server test starts the real child process.
- **Smoke**: `tests/smoke/` against a running stack, `SMOKE_URL` names it.
  Marked `smoke`, so the default pytest run leaves it out.
- **End to end**: `docker-compose.e2e.yml` layers the fakes over the compose
  file. `tests/e2e/fake_claude.py` answers the CLI's command line with a
  scripted tool call over the real MCP server; `tests/e2e/fake_telegram.py`
  serves the two Bot API methods plus `/test/inbound` and `/test/outbound`
  for the driver. `dashboard/e2e/*.e2e.ts` are the scenarios: Phase 1's exit
  tests, and each phase adds its own. Claude and Telegram are the only fakes;
  a scenario that needs a third fake is asking for a seam, not a fake.

## Layout

```
config/      settings, urls, wsgi
core/        Tracker, Observation, Assessment, Alert, Focus, kinds/ (one module per tracker kind: topic, country_risk, stock,
             practice, campaign), life.py (the life board, built from the rows on every read),
             management/commands/import_life.py (the vault's board in, once; --check compares the two boards)
             standing.py (what this database is: the copy's mark and the scheduler's lock), backup.py (one dump, with its counts),
             restore.py (the statements on whole databases), management/commands/backup_db.py and pull_db.py (a dump in: a copy, or a takeover)
scheduler/   Job, JobRun, jobs.py (rows→APScheduler), dispatcher.py, run_scheduler, seed_jobs,
             scripts/ (jobs without a session: heartbeat with its outside call, prices, backup: the nightly dump)
chat/        Conversation, Message, telegram.py (send + getUpdates), poller.py, alerts.py (delivery)
agent/       runner.py (CLI subprocess), tools.py (the functions), prompts.py,
             management/commands/mcp_tools.py (the tool server), flows/{reply,collect,assess,research,brief}.py,
             management/commands/replay.py (recorded messages through the reply flow, on a scratch database)
api/         django-ninja read-only API (health, trackers, the life board, alerts, focus + its SSE stream)
             dump.py (GET /api/dump: the whole database to a machine that holds the token; not part of the read-only API)
dashboard/   Vite + React app with its own Dockerfile (node build → nginx) and nginx.conf;
             src/views/ is the view registry (feed, globe, price), src/views/globe/ the MapLibre globe,
             src/views/life/ the Life screen (view campaign_map; /life is the wall: that screen alone),
             src/chart.tsx the ECharts component every chart view shares, src/polled.ts the one way a screen reads the API;
             e2e/ the Playwright scenarios (playwright.config.ts)
tests/       pytest-django; smoke/ (against a running stack), e2e/ (the fakes behind docker-compose.e2e.yml, and stack_check.py:
             what only the built image and a running stack can show, run inside the end-to-end stack's scheduler)
docs/        the planning documents; ops/HOST.md (the machine the stack runs on: moving to it, deploying, backups, copies)
deploy.sh    on the Mac: bring the host to origin/main (make deploy); the host's alias, folder and address come from .env
```
