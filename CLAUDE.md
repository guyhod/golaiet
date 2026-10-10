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
- **Heat and conflict kind definitions live once**, in
  `core/kinds/country_risk.py`; the research prompt renders them and the
  globe's legend copies them. Change both together.
- **One scheduler registrar.** APScheduler jobs are added only in
  `manage.py run_scheduler`, never in `AppConfig.ready()`.

## Running

```bash
cp .env.template .env            # fill in: DB_PASSWORD, TELEGRAM_*, CLAUDE_CODE_OAUTH_TOKEN
make stack                       # the whole thing: db, migrate, web, scheduler, dashboard on 8003
make logs

# Host dev instead (stop the compose scheduler first: two pollers on one bot conflict)
make up && make migrate          # Postgres on 5435, then the schema
./.venv/bin/python manage.py seed_jobs
make scheduler                   # job loop + Telegram poller
make run                         # Django admin + API on 8003
make dashboard-dev               # Vite on 5174, /api proxied to 8003
make test
```

## Layout

```
config/      settings, urls, wsgi
core/        Tracker, Observation, Assessment, Alert, Focus, kinds/ (one module per tracker kind: topic, country_risk)
scheduler/   Job, JobRun, jobs.py (rows→APScheduler), dispatcher.py, run_scheduler, seed_jobs
chat/        Conversation, Message, telegram.py (send + getUpdates), poller.py, alerts.py (delivery)
agent/       runner.py (CLI subprocess), tools.py (the functions), prompts.py,
             management/commands/mcp_tools.py (the tool server), flows/{reply,collect,assess,research}.py
api/         django-ninja read-only API (health, trackers, alerts, focus + its SSE stream)
dashboard/   Vite + React app with its own Dockerfile (node build → nginx) and nginx.conf;
             src/views/ is the view registry (feed, globe), src/views/globe/ the MapLibre globe
tests/       pytest-django
docs/        the planning documents
```
