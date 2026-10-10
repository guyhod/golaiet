# Architecture

Proposed. Every choice here that is not forced by the three source projects
is listed in [DECISIONS.md](DECISIONS.md) and waits for Guy.

## 1. Shape

One Django project, one PostgreSQL database, one scheduler process, one
React dashboard, one agent runtime. Same stack as both existing repos, so
code moves across without translation.

```
                 long-poll getUpdates
  Telegram ◀──────────────────────────▶ ┌──────────────── golaiet (Django) ────────────────┐
   (Guy)        sendMessage              │                                                  │
                                         │  channels/   scheduler/   api/   agent/  kinds/  │
                                         │                                                  │
  Dashboard ◀── GET /api/* , SSE focus ──│                   PostgreSQL                     │
  (React, served by Django)              └───────────────────────▲──────────────────────────┘
                                                                 │ MCP tools (stdio)
                                                 claude -p --output-format json --mcp-config …
                                                 (one session per conversation; one per job run)
```

The scheduler decides **what runs and when**. The agent decides **how**. The
dashboard decides nothing: it draws what the database says.

## 2. Components

| Component | Responsibility | Taken from |
|---|---|---|
| `chat/` | Long-poll `getUpdates`; one `Conversation` per chat; each inbound `Message` runs the `reply` job off-schedule through the same dispatcher as scheduled jobs; outbound `sendMessage` with Markdown → plain-text fallback | Organism `bridges/telegram.py`, investment_engine `core/notifications.py` |
| `scheduler/` | `Job` rows define the schedule; a single process re-syncs APScheduler from the table every 30 s; `JobRun` is the run log, cost ledger and heartbeat | investment_engine `scheduler/` (models, jobs, dispatcher, market_hours) |
| `agent/` | Builds the prompt, runs the Claude CLI headless with the MCP config, parses JSON, retries unparseable replies, aborts the whole loop on billing markers, tallies cost | investment_engine `scheduler/runner.py` + `agent_flow.py`; conflict map `research/runner.py` |
| `agent/tools` (MCP server) | The agent's only way to touch Golaiet: typed tools over the Django ORM (§5) | new |
| `kinds/` | One module per tracker kind: payload schema, default brief template, default jobs, assessment rules, view name | conflict map `research/country.py`, investment_engine `core/monitor.py` |
| `api/` | django-ninja: trackers, observations, assessments, focus (GET + SSE), health | both repos' `api/api.py` |
| `dashboard/` | Vite + React. Shell (header, alert banner, main view, drawer) + a view registry keyed by tracker kind | `Life/Golaiet/Claude/dashboard-react`, conflict map `frontend/src/map` |

## 3. Data model

Nine tables. Agents never change the schema. Everything agent-specific is a
row or a JSON payload validated by the tracker kind.

### tracker
| Column | Notes |
|---|---|
| slug, title | `country-risk/isr`, `stock/ceg`, `topic/vram-supply` |
| kind | `topic` / `country_risk` / `stock` / `campaign` / `practice` … selects payload schema and default view |
| subject | JSON: `{iso3:"ISR"}` / `{ticker:"CEG", good_below:170}` / `{query:"..."}` |
| brief | TEXT. Standing instructions for collecting and judging this tracker. Editable text, rendered into prompts. The thesis lives in text, never in code (investment_engine decision, 2026-07) |
| view, view_params | Default view and parameters for focus |
| status | active / paused / archived |
| created_by_message | FK → message. Which Telegram request asked for this |
| created_at, updated_at | |

### observation  (facts, never edited)
tracker FK · observed_at · source_url (unique per tracker, so a re-run
cannot duplicate) · kind · payload JSON (validated by tracker kind) ·
summary · job_run FK

### assessment  (judgments, append-only)
tracker FK · at · state JSON (`level`, `score` as the kind defines; the
kind's `LEVELS` tuple orders them coolest first) · reason TEXT · evidence
(M2M to observation) · job_run FK. Model and cost are on the job run, not
repeated here.

Store the judgment with its date and reason; derive everything that can go
stale (conflict map decision D5 and `Life/Golaiet`'s "the counter is never
stored" rule).

### alert
tracker FK · assessment FK (nullable) · level · text · job_run FK ·
created_at · delivered_at · delivery_error. Raised by the kind's rule inside
`record_assessment` (level change) or by `raise_alert`; delivered by the flow
after the CLI has exited (`chat/alerts.py`), never by the tool server. The
tracker's latest alert is the open one: `raise_alert` at the same level
returns it instead of a second row. A failed send is recorded, not retried,
until a failed send is actually observed.

### job
tracker FK (nullable) · kind (`reply` / `collect` / `assess` / `digest` /
`heartbeat`) · trigger (`cron` / `interval` / `manual`) · schedule ·
target (dotted path for scripts, `agent` for a session) · params JSON ·
market_hours_only · enabled · next_run_at · conversation FK (reply jobs)

Unknown `params` keys raise. A $16 incident in investment_engine came from
a silently ignored key.

### job_run
job FK · started_at · finished_at · status · summary · log · cost_usd ·
session_id. Doubles as the heartbeat: no run in N minutes is itself an
alert. An outage must never look like a quiet day.

### conversation / message
conversation: channel · chat_id · session_id (for `--resume`) ·
last_message_at.
message: conversation FK · direction · text · telegram_message_id ·
created_at · job_run FK.

### focus  (singleton)
tracker FK (nullable) · view · view_params JSON · set_at · set_by_message
FK · note. Null tracker means overview.

## 4. Flows

### 4.1 Telegram message → reply
1. Poller receives an update, stores `Message(in)`, and calls `execute_job(reply, message_id=…)`: the one `reply` row (trigger `manual`, never scheduled) gets a `JobRun` per message, so an off-schedule run is not a different kind of run.
2. The dispatcher runs `claude -p --resume C.session_id` with the Golaiet system prompt and the MCP tools.
3. Agent reads trackers through tools, may call `set_focus`, answers.
4. Runner stores `session_id` on C, stores `Message(out)`, sends it. One job, one reply.

### 4.2 "Track X" → tracker
Inside 4.1 the agent calls `create_tracker(kind, subject, brief, cadence)`.
The kind module creates the default jobs (for `topic`: daily collect,
weekly assess). The reply states what will be watched, how often, and when
the first run is. Nothing runs until the scheduler picks the job up, so a
bad brief costs nothing.

### 4.3 Scheduled collect → assess → alert
```
collect job  : fresh session, prompt = kind template + tracker.brief + last N observations
               tools: WebSearch, WebFetch, record_observation          → observations
assess job   : fresh session, no built-in tools (--tools ""), or a script (kind decides)
               reads observations filed since the last assessment; skips if none → assessment
alert rule   : kind.alert_for(previous, new), applied by record_assessment     → alert → Telegram
```
Deterministic kinds (`stock` price monitor) skip the session entirely: a
script writes the observation and the threshold rule writes the alert. That
is how the investment engine spends $0 on an hour with nothing to judge.

### 4.4 Focus push
`set_focus` writes the singleton row. `GET /api/focus/stream` is a
server-sent-events endpoint; the dashboard holds it open and re-renders on
each event. Fallback: poll `GET /api/focus` every 5 s, which is what the
wall screen does today at 2 min.

### 4.5 Digest
`digest` job (Sunday, or on request): reads assessments and alerts of the
last 7 days across all trackers, writes one message. Replaces the Sunday
weekly summary of `Life/Golaiet` once that tracker kind exists.

## 5. The agent's tools (MCP, stdio)

| Tool | Does |
|---|---|
| `list_trackers()` | slug, title, kind, status, latest assessment level |
| `get_tracker(slug, observations=20)` | full brief, latest assessment, recent observations |
| `create_tracker(slug, title, kind, subject, brief, cadence)` | creates tracker + default jobs |
| `update_tracker(slug, brief?, cadence?, status?)` | prefer this over a second tracker on the same subject |
| `record_observation(slug, observed_at, source_url, summary, payload)` | validated by kind; duplicate URL is a no-op |
| `record_assessment(slug, state, reason, evidence_ids)` | append-only; applies the kind's alert rule |
| `raise_alert(slug, level, text)` | for judgment-based alerts outside the level rule; returns the open alert at the same level |
| `set_focus(slug?, view_params?, note?)` | no slug clears to the overview |
| `search_observations(query, slug?, since?)` | full-text over summaries |

Reply sessions get all tools plus WebSearch/WebFetch. Collect sessions get
only `record_observation` plus the web tools. Assess sessions get
`record_assessment` and `raise_alert` and no built-in tool at all
(`--tools ""`, probed 2026-10-10: the MCP tools stay). No session has Bash or the
file tools at all (`--tools` narrows the built-ins; MCP tools are unaffected).

## 6. Agent runtime

- **Runtime:** Claude Code CLI, headless: `claude --print --output-format json --mcp-config <per-run file> --strict-mcp-config`. **`--safe-mode` is never used**: probed 2026-10-09, it disables every MCP server including the one on the command line (init reported none). `--bare` is never used either: it strips the web tools. Host customisations are kept out by pointing `CLAUDE_CONFIG_DIR` at a directory of our own (the same tool probe: 27 s and 67k input tokens with the host config, 4 s and 50k with a clean one) and `--tools WebSearch,WebFetch` leaves Bash and the file tools out of the session entirely.
- **Identity:** one agent, "Golaiet". System prompt in `agent/CLAUDE.md`, versioned in this repo. A prompt says what to do; it never repeats a value that lives in the data (practice lists and thresholds went stale in `Life/Golaiet` prompts).
- **Continuity:** per-conversation `--resume`. A stale session id degrades to a fresh session and the new id is stored (Organism rule).
- **Thinking cap** on reply sessions (the conflict map's ask box went from 80 s to 14 s with a 1,500-token cap). No cap on collect sessions.
- **Cost:** every `JobRun` records `cost_usd`. Billing or quota markers in the CLI output stop the whole loop, not just the job. The marker list is a maintained file, because an unknown quota message once burned a queue.
- **Memory:** Phase 0 has none beyond resumed sessions and tracker briefs. Whether to add a git-tracked `MEMORY.md` the agent edits is an open decision.

### 6.1 One agent run, step by step

Four long-lived processes and two short-lived ones. All database access
goes through the Django ORM, in whichever process it happens.

| Process | Lifetime | What it is |
|---|---|---|
| PostgreSQL | always | `docker compose`, port 5435 |
| `web` | always | Django under gunicorn (threaded workers, so an open focus stream does not park one): `/api/*`, SSE focus stream, serves the dashboard |
| `scheduler` | always | `manage.py run_scheduler`: APScheduler loop, the Telegram long-poll thread, the agent runner |
| `claude` | per run | Anthropic's CLI, started by the scheduler, logged in with Guy's plan |
| `mcp_tools` | per run | `manage.py mcp_tools`: a Django process started **by the CLI**, speaks MCP over stdin/stdout |
| `dashboard` | browser | React app; talks only to `web` |

The MCP server is not a wrapper around Django. It **is** a Django process,
the same code and settings as `web` and `scheduler`, whose only job is to
expose the agent's functions (six in Phase 0, nine by Phase 1) to the CLI over a pipe.

```
Guy ──Telegram──▶ scheduler.poller ─▶ Message(in) + Job(reply)   [ORM → Postgres]
                                           │
                  scheduler.runner  ◀──────┘ claims the job
                        │ builds prompt (system prompt + tracker summary + message)
                        │ spawns:
                        ▼
                  claude --print --output-format json --resume <session> --mcp-config agent/runs/mcp-<uuid>.json
                         --strict-mcp-config --allowedTools "mcp__golaiet__*,WebSearch,WebFetch" --tools WebSearch,WebFetch
                        │
                        │ reads mcp.json → spawns its own child:
                        ├──────────────▶ python manage.py mcp_tools   (Django + ORM, stdio)
                        │                      ▲      │
                        │  model says:         │      │ runs the function:
                        │  create_tracker(...) ─┘      │ Tracker.objects.create(...)
                        │  ◀── result JSON ───────────┘ default jobs created      [ORM → Postgres]
                        │
                        │ model says: set_focus("country-risk/isr") ─▶ same path ─▶ Focus row updated
                        │ model writes final text, CLI exits with
                        │ { result, session_id, total_cost_usd }
                        ▼
                  scheduler.runner  ─▶ Message(out), Conversation.session_id, JobRun(cost)   [ORM → Postgres]
                        │
                        └──Telegram sendMessage──▶ Guy

                  web (SSE)  ──▶ dashboard sees the Focus row change, re-renders   [ORM → Postgres]
```

Who calls whom:
- The scheduler calls the CLI. The CLI calls the MCP server. Never the
  other way round: the MCP server cannot start an agent, send a Telegram
  message, or schedule anything. It can only run the nine functions.
- The CLI calls Anthropic's API itself, under the plan login. Golaiet never
  holds an API key.
- Nothing in an agent run talks to Telegram. The runner sends the reply
  after the CLI has exited, so a crashed session produces a failed JobRun
  and an error message, never a half-reply.
- A scheduled `collect` run is the same picture without the Telegram ends:
  the scheduler fires on cron, the runner spawns the CLI with a fresh
  session and only `record_observation` allowed, the CLI exits, the runner
  records cost. Deterministic kinds (price ticks) skip the CLI entirely and
  run a Python function in the scheduler process.

### 6.2 Inside step 4: the CLI and the tool server

**What the CLI is told.** The runner writes a small JSON file per run and
passes it with `--mcp-config`:

```json
{ "mcpServers": {
    "golaiet": {
      "command": "/Users/guyhod/Kruv/dev/golaiet/.venv/bin/python",
      "args":    ["manage.py", "mcp_tools"],
      "cwd":     "/Users/guyhod/Kruv/dev/golaiet",
      "env":     { "DATABASE_URL": "...", "GOLAIET_JOB_ID": "…", "GOLAIET_MESSAGE_ID": "…" }
} } }
```

The file is per run because `env` is how the tool server learns *which*
job and message it is serving. That is what lets `create_tracker` fill
`created_by_message` without the model having to pass ids around.

**What the CLI does with it.** On startup it runs that command as a child
process and keeps the child's stdin and stdout as a pipe. Everything on the
pipe is JSON-RPC 2.0, one JSON object per line. The sequence for a run:

```
CLI → server   {"method":"initialize", "params":{protocolVersion, clientInfo}}
server → CLI   {"result":{serverInfo:{name:"golaiet"}, capabilities:{tools:{}}}}
CLI → server   {"method":"notifications/initialized"}
CLI → server   {"method":"tools/list"}
server → CLI   {"result":{"tools":[ {name:"create_tracker", description:"…",
                                      inputSchema:{type:"object", properties:{…}, required:[…]}}, … ]}}
      … the CLI now shows the model a tool named mcp__golaiet__create_tracker …
      … model decides to call it …
CLI → server   {"method":"tools/call", "params":{"name":"create_tracker",
                 "arguments":{"slug":"topic/vram-supply","kind":"topic", …}}}
server → CLI   {"result":{"content":[{"type":"text","text":"{\"slug\":…,\"first_run_at\":…}"}]}}
      … CLI hands that text to the model as the tool result …
      (repeat tools/call as needed)
CLI exits  →   child gets EOF on stdin, exits too
```

The server never sends anything the CLI did not ask for. It answers
`tools/list` once and `tools/call` as many times as the model calls a tool.

**What the server is.** `manage.py mcp_tools` is an ordinary Django
management command. `manage.py` loads settings and the ORM before the
command body runs, so by the time the server starts, `Tracker.objects` and
the rest work exactly as in a view. The body uses the official `mcp` Python
package:

```python
from mcp.server.fastmcp import FastMCP
from golaiet.agent import tools          # the nine plain functions

server = FastMCP("golaiet")
for function in tools.ALL:               # create_tracker, record_observation, set_focus, …
    server.tool()(function)              # name, docstring and type hints become the schema
server.run(transport="stdio")            # blocks: read a line, dispatch, write a line
```

Each function reads `GOLAIET_JOB_ID` / `GOLAIET_MESSAGE_ID` from the
environment for provenance, validates its arguments against the tracker
kind, does its ORM work, and returns a dict. The `mcp` package turns the
dict into the JSON-RPC reply. An exception becomes an error result the
model can read, not a crash of the pipe.

**Database.** The server process opens its own PostgreSQL connection
through the ORM, as any Django process does. It writes in short
transactions, one per tool call. Two agent runs in parallel are two CLI
processes with two tool servers and two connections; PostgreSQL handles
that, and the scheduler bounds parallelism anyway.

**Constraints that come with the pipe.**
- stdout is the protocol channel. The server must never `print()`; all
  logging goes to stderr, which the CLI collects and the runner stores in
  `JobRun.log`.
- One server per CLI run. It lives exactly as long as the session and is
  killed with it on timeout, so there is nothing to clean up.
- The model only ever sees tool names, descriptions and schemas. It never
  sees Python, settings, or the database. Permission is the `--allowedTools`
  list on the CLI side: a collect session that is allowed only
  `mcp__golaiet__record_observation` cannot call `set_focus` even though
  the server offers it.

## 7. Dashboard

- One Vite + React app (`dashboard/`, no other dependencies), built to static files, served by Django at `/`: `dist/index.html` as a template, the hashed assets under `/static/`. No `file://`, no Obsidian Sync hop, so the kiosk opens a URL. `make dashboard` builds it on the host; the image builds it before `collectstatic`.
- Shell: header (heartbeat time, stale banner when the health endpoint says so, the latest alert of the last 24 h), main view. The drawer arrives with the globe.
- **View registry:** `{ feed, globe, price, campaign_map }`. A tracker kind names its view. `feed` is generic: assessment tile, observation list, provenance to sources. Every tracker gets `feed` for free on day one.
- Overview (no focus): tiles of all active trackers by latest level, hottest first (`level_rank` from the API, so the app knows no kind's levels). Click a tile: local drill-down into its view.
- Focus event (`/api/focus/stream`, one event per change, reconnects by itself): switch to the tracker's view with the pushed parameters, or back to the overview. Data refreshes once a minute; focus is immediate.
- Geometry ships with the app; no network at render time (conflict map rule, keeps a static export possible).

## 8. Deployment

Mac first, as the other two. Ports chosen not to collide: PostgreSQL 5435,
Django 8003, Vite dev 5174 (Organism uses 5432; investment_engine 5433,
8000, 8001; conflict map 5434, 8002, 5173). `docker compose` for the
database; Django and the scheduler on the host under launchd, because the
Claude CLI must run where the plan login lives. Moving to a NUC or VM
follows investment_engine's `docs/ops/HOST_SPEC.md`.

Telegram long polling needs no public URL, no ngrok and no webhook secret.
Alerts are enabled by the presence of the bot token and chat id, never by a
separate flag.
