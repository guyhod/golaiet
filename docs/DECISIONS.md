# Decisions

Each row is a proposal with a recommendation. Status is `proposed` until
Guy decides; then it becomes `decided` with the date, and it is not
reopened. Codes (D1…) are for this table only; prose written for Guy
glosses them in plain words.

| # | Decision | Recommendation | Why | Alternatives | Status |
|---|---|---|---|---|---|
| D1 | How Telegram delivers Guy's messages to Golaiet: our process asks Telegram for new messages (long polling), or Telegram calls a public URL on our host (webhook). Telegram itself is settled. | **Long polling** | Runs on the Mac with no public URL, no ngrok, no secret. The Organism's webhook path needs all three. Latency is a second or two. | Webhook (needed only if the host gets a public address) | **decided 2026-10-09** |
| D2 | How the agent touches Golaiet | **MCP server over the ORM** (stdio, ~9 typed tools). Detail in §D2 below. | Typed arguments, validation at the boundary, no Bash in sessions, no HTTP auth to invent. The CLI supports `--mcp-config` headless. | HTTP API called with curl (Organism style); `manage.py` commands via Bash | **decided 2026-10-09** |
| D3 | Observation storage | **A fixed set of shared tables in PostgreSQL; every tracker's rows tagged by tracker, payload in JSONB validated per kind; relationships in one `link` table. Not Neo4j.** Detail in §D3 below. | Agents never alter schema. New tracker is rows, not DDL. The real queries are "by tracker, by time"; the graph parts are one or two hops. | A table per tracker; Neo4j | **decided 2026-10-09** |
| D4 | Order of migration | **War risk (globe) → stocks → life** | The two new asks fit the conflict-map research pattern and need the globe anyway. Life works today and has the most guardrails to port. | Life first; stocks first | **decided 2026-10-09** |
| D5 | New repo or grow an existing one | **New repo `golaiet`, copy modules in, freeze sources at parity** | Each source has a single-purpose data model baked in. Copying is cheaper than un-baking. | Extend `investment_engine` | **decided 2026-10-09** |
| D6 | Dashboard delivery | **One React app, built static, served by Django at a URL** | Removes the `file://` + Obsidian Sync hop and the 2-minute polling it forced. SSE for focus becomes possible. | Keep `data.js` export for the kiosk | **decided 2026-10-09** |
| D7 | Agent memory | **None in Phase 0–4 beyond resumed sessions and tracker briefs** | Memory the agent writes is the hardest thing to review. Add a git-tracked file only when a repeated mistake is observed. | Organism-style `MEMORY.md` from day one | **decided 2026-10-09** |
| D8 | Agent count | **One agent, many trackers; behaviour in briefs** | Avoids the org chart. A brief is editable text Guy can read in admin. | Manager + collector agents (Organism) | **decided 2026-10-09** |
| D9 | LLM runtime | **Claude Code CLI headless, `--safe-mode`, plan auth** | All three sources use it; plan subscription pays. SDK would switch to API billing. | Anthropic SDK with API key | **decided 2026-10-09** |
| D10 | Who promotes `proposed` items and who may create a tracker | **Guy creates trackers through chat; the agent proposes and never promotes life stations on its own** | The Desktop runs overreached when the chat went quiet. | Let the agent create trackers from observed themes | **decided 2026-10-09** |
| D11 | Hosting | **This Mac, everything under docker compose (db, web, scheduler), the CLI inside the scheduler image with a plan OAuth token as investment_engine does** | One `docker compose up` on the Mac; same pattern already proven in investment_engine. NUC/VM later per its `HOST_SPEC.md`. | Host processes under launchd; cloud | **decided 2026-10-09** |

## D2 in detail: the MCP server

MCP (Model Context Protocol) is the standard way to give a Claude session
tools. An MCP server is a small program the Claude CLI starts as a child
process and talks to over stdin/stdout. Each tool has a name, typed
parameters, and a description; the model sees them like built-in tools.

What Golaiet ships:

```
agent/mcp.json              tells the CLI which server to start
  { "mcpServers": { "golaiet": { "command": "python",
                                 "args": ["manage.py", "mcp_tools"] } } }

api/management/commands/mcp_tools.py
  a Django management command that runs the MCP server loop (official
  Python SDK). Each tool is a plain function using the ORM:

    @tool
    def create_tracker(slug, title, kind, subject, brief, cadence):
        kind_module = kinds.get(kind)          # validates subject
        tracker = Tracker.objects.create(...)
        kind_module.default_jobs(tracker, cadence)
        return {"slug": slug, "first_run_at": ...}
```

A reply session is launched as:

```
claude -p --safe-mode --output-format json --resume <session_id>
       --mcp-config agent/mcp.json
       --allowedTools "mcp__golaiet__*,WebSearch,WebFetch"
       "<prompt built from the Telegram message>"
```

The model then calls `create_tracker(...)` or `set_focus(...)` the way it
calls WebSearch. The server runs inside the same Python environment as
Django, so there is no HTTP, no token, no second service to secure, and
every argument is validated before it reaches the database.

Why not curl against an HTTP API: the model has to compose JSON by hand in
Bash, which means Bash is allowed in sessions, and the API needs its own
auth. The Organism took that route because its agents ran in a separate
container. Golaiet's agent runs on the same host.

### Why a server at all, and not a plain function call

The model runs inside the Claude CLI, which is a separate process from
Django. A separate process cannot call a Python function in ours. Something
has to cross that boundary, and the three ways are an MCP server (stdio),
an HTTP API, or letting the model run Bash. MCP is the typed one.

**Probed 2026-10-09 on this Mac (CLI 2.1.296):** with `--mcp-config` and
`--strict-mcp-config` the server connects and the model calls the tool
(`SUM=42 RUN=run-42`, env passthrough confirmed). With `--safe-mode` added,
the init report lists no MCP servers at all, so safe mode is out.

The one way to make the tools *literally* plain Python functions is to host
the model loop inside our own process with the Claude Agent SDK. Verified
against the SDK docs on 2026-10-09:

- The SDK has an in-process server: `@tool` on an async function plus
  `create_sdk_mcp_server(tools=[...])`, passed to `query()`. No child
  process, no stdio, no JSON config. The tool is a function in our code.
- But the SDK is API-key billed. The overview states that Anthropic does
  not allow claude.ai login for products built on the Agent SDK and points
  to API-key auth. The headless CLI, by contrast, runs on the plan login.

So the question is coupled to D9 (plan auth vs API key):

| If D9 is… | Then the agent runs as… | And the tools are… |
|---|---|---|
| plan login (recommended) | `claude -p` child process | the same functions, wrapped in a ~20-line stdio MCP server |
| API key | Agent SDK `query()` in-process | the same functions, registered with `create_sdk_mcp_server` |

The tool functions themselves (name, schema, handler) have the same shape
in both. Golaiet writes them once in `agent/tools.py`; the wrapper is the
only part that changes if D9 ever flips. Recommendation stands: plan login,
therefore CLI, therefore a thin stdio server around the same functions.

## D3 in detail: shared tables, JSONB, and why not Neo4j

**Not one table.** A small fixed set, shared by every tracker:

| Table | One row is |
|---|---|
| `tracker` | a thing being tracked |
| `observation` | a dated fact about one tracker (price tick, news item, incident report, Inbox line) |
| `assessment` | a dated judgment about one tracker (score, level, reason) |
| `alert` | an assessment that was pushed to Guy |
| `link` | a typed edge between two rows: tracker→tracker (`counterpart`, `neighbour`, `interchange`, `supports_thesis`), assessment→observation (`evidence`) |

Every observation row carries `tracker_id`, `observed_at`, `source_url`,
`summary` and a `payload` JSONB column. The payload's shape is fixed per
tracker **kind** and validated on write:

```
stock:         {"price": 168.4, "currency": "USD"}
country_risk:  {"heat": "hot", "kind": "interstate", "parties": [...], "since": "2023-10"}
topic:         {"region": "FR", "severity": 3, "category": "attack"}
practice:      {"event": "workout", "outcome": "done"}
```

Querying is ordinary SQL through the Django ORM, scoped by tracker and
time, with JSONB operators for payload fields and a GIN index on `payload`:

```sql
-- price history for one stock
SELECT observed_at, payload->>'price' FROM observation
 WHERE tracker_id = :ceg ORDER BY observed_at;

-- antisemitism incidents in France this week
SELECT * FROM observation
 WHERE tracker_id = :antisemitism AND payload->>'region' = 'FR'
   AND observed_at > now() - interval '7 days';
```

No per-tracker SQL. The `kind` module owns the schema and the handful of
queries its view needs; a new tracker of an existing kind adds nothing.

**Why not a table per tracker:** every "track X" would run a migration,
the dashboard would need a query per table, and the agent would need
schema rights. The investment engine already had this shape in miniature
(`Evidence` + `EvidenceNode` + `PriceTick` all keyed by company) and it was
fine.

**Neo4j, honestly assessed.** The data does have graph shape in places:
thesis → nodes N0–N6 → companies → evidence; country ↔ counterpart country;
campaign station → interchange to another campaign's station. A graph
database would express those naturally.

Against it:
- The queries Golaiet actually runs are time-series filters by tracker
  ("last 7 days", "since the previous assessment", "price history"). That
  is what relational tables with a time index do best and what graph
  databases do worst.
- The graph parts are one or two hops deep. A `link` table with a type
  column answers "which countries neighbour Israel" or "which observations
  back this assessment" in one join.
- It is a second datastore to run, back up, secure and learn, with no
  Django ORM. All three source projects are Postgres, so every module we
  copy would need rewriting at the data layer.
- The thesis chain (N0–N6) was already modelled as `Node` rows in Postgres
  in the investment engine and worked; the part that was never built (the
  probability maths, milestone M3) was not blocked by the database.

Recommendation: PostgreSQL with JSONB and a `link` table. Revisit if a
real question needs three-plus hops or path queries ("every tracker that
shares evidence with anything that touched Iran"). The `link` table ports
to a graph store cleanly if that day comes.

## D8 follow-up: adding more agents later

Easy, and nothing is built for it now. An agent is three things: a system
prompt, an allowed-tools list, and a working directory. Today those are
constants in `agent/runner.py`. When a second agent is wanted, they become
rows in an `agent` table (slug, system_prompt, allowed_tools) and `job`
gets an `agent` foreign key defaulting to `golaiet`. One migration, no
change to the tool server or the scheduler. The Organism repo has this
exact table if it is ever needed (`claude_interface/api/models.py`).

## Already settled by the brief (not reopened)

- Chat interface is Telegram.
- One database holds all collected data.
- A scheduler activates the agent flows.
- The dashboard shows what is tracked, and conversation can move it (focus).
- Planning only now; no code until decisions land.
