# Lineage

What Golaiet takes from each source project, what it leaves, and the
lessons that were paid for and must not be re-learned. Paths are relative
to `/Users/guyhod/Kruv/dev/` unless stated.

## 1. From `investment_engine`

**Take**
| Piece | Path | Becomes |
|---|---|---|
| Scheduler as database rows, re-synced every 30 s, with run log and heartbeat | `scheduler/models.py`, `jobs.py`, `dispatcher.py`, `market_hours.py` | `scheduler/` nearly as-is |
| Headless Claude CLI runner, JSON extraction, retries, billing abort, cost tally | `scheduler/runner.py`, `scheduler/agent_flow.py` | `agent/runner.py` |
| Telegram sender with Markdown fallback and 24 h retry | `core/notifications.py` | `channels/telegram` outbound |
| Price fetch that reports "no data" rather than inventing a number | `core/market_data.py` | `kinds/stock` collect script |
| Threshold crossing → alert | `core/monitor.py` | `kinds/stock` assess rule |
| Thesis text in the database, editable, rendered into prompts | `core/thesis.py` | `tracker.brief` |
| Evidence filing with natural keys, dump/load | `core/evidence.py`, `core/evidence_corpus.py` | `observation` table conventions |
| Host move notes | `docs/ops/HOST_SPEC.md` | deployment §8 |

**Leave for now:** the committee deliberation (`core/committee.py`), the
sanity gate, discovery. They cost $2–7 per name and solve "which company
should I look at", not "has something changed about the one I hold". They
can return as an `assess` job for `kind=stock` when the tracker loop proves
it needs judgment beyond thresholds.

**Lessons (receipts in `PLAN.md`, `.claude/BEST_PRACTICES.md`, `.costs`,
`committee_experiment_findings.md`)**
- Native CLI subagent delegation is parallel consulting, not debate. Orchestrate deliberation from Python if deliberation is ever needed.
- Cheap models are not cheap when research loops dominate (decision D18). Pick the model per job kind, measure, then decide.
- Never register APScheduler jobs in `AppConfig.ready()`. `next_run_time=None` creates a paused job. Call `close_old_connections()` at the thread boundary.
- `--bare` strips the web tools. Prompt goes before variadic CLI flags.
- Unknown `params` keys must raise: a silently ignored key cost $16.
- Alerts are switched on by credentials alone, never by a separate flag (D27). The send happens outside database transactions.
- Failures must be loud. An outage must never look like an honest empty day (D21).
- Keep the billing-marker list current, or retries become a queue burner.
- A discovery agent must know the admission bar: 24 finds and 0 usable cost about $170.

## 2. From `geo_status_bashboard` (the conflict map)

**Take**
| Piece | Path | Becomes |
|---|---|---|
| Research prompt, peace-score rubric, strict validator, transactional replace | `research/country.py` | `kinds/country_risk` collect + assess |
| Natural language → validated map command | `research/ask.py`, `api/api.py` `/ask` | the agent's `set_focus` with view params |
| Heat and conflict-kind taxonomy, derived `country_heat()` | `core/models.py` | `kinds/country_risk` payload schema |
| Offline MapLibre globe, world-atlas join, antimeridian fix | `frontend/src/map/{createMap,countries,MapView}.ts(x)` | `dashboard/views/globe` |
| Colour-vision-checked heat palette, light and dark | `frontend/src/styles/tokens.css` | dashboard tokens |
| Typed API client | `frontend/src/api.ts` | pattern for `dashboard/api.ts` |
| Country seed | `core/management/commands/seed_countries.py` | migration data for `country_risk` |

**Leave:** the standalone app shell, `App.tsx`. The sidebar becomes the
dashboard drawer.

**Lessons (receipts in `PLAN.md` decisions D1–D15, `docs/qa/2026-10-03-v0.md`)**
- `--safe-mode` for every headless call: 49k tokens and 114 s became 414 tokens and 3 s (D10).
- Cap thinking on interactive calls: 80 s became 14 s with a 1,500-token cap.
- Derive what can go stale (heat); store judgments with a date and a reason (peace score) (D5).
- "Calm" and "no data" are different everywhere. A missing list must never look like an answer.
- Validate LLM output against the database before the UI sees it. The model never sits in the render loop (D8).
- Keep undated sources rather than dropping the record. Reject over-length text, never truncate it.
- Ship geometry with the app; no network at render time (D7, D13).
- Map work needs browser QA; unit tests do not catch globe and antimeridian bugs (D15).
- Start with the agent as the only source; add structured feeds (ACLED, GDELT) when a coverage gap is observed, not before (D3).

**Not carried:** the conflict map has no history of briefs, so its trend is
the agent's opinion. Golaiet's append-only `assessment` table fixes that:
trend is computed from two dated scores.

## 3. From Obsidian `Life/Golaiet`

Full path: `/Users/guyhod/Kruv/Obsidian/Life/Golaiet/`.

**Take**
| Piece | Path | Becomes |
|---|---|---|
| The schema: practices (green streak / red gap), campaigns → tracks → stations, watches, next, append-only log with evidence | `progress.md` | `kinds/campaign`, `kinds/practice` payload schemas |
| Derivation engine: counters from `since` + events, red/green rules, atomic writes, validation exit codes | `Claude/render_dashboard.py` `derive()` | `kinds/practice` assess script |
| Metro map, drawer with History and Mentions, horizon bar, pulse row | `Claude/dashboard-react/src/components/*`, `lib/types.ts`, `lib/lookup.ts` | `dashboard/views/campaign_map` and the shell's drawer |
| Agent guardrails: entry gate, `wc -c` before read, mark-don't-edit the Inbox, backup + JSON check, skip windows | `WIP/ריצות מקומיות.md`, `/Users/guyhod/Kruv/Obsidian/Life/CLAUDE.md` | `kinds/campaign` collect job rules |
| Three-file memory pattern: `index`, `state`, `log` | `Claude/{index,state,log}.md` | open decision on agent memory |
| Design rationale: "a map, not a tree", gated stages, lessons from the dead `progress.guyhod.com` | `WIP/דשבורד — תוכנית.md` | VISION §5 |

**Leave:** the hourly Claude Desktop run as the executor. It is a pasted
prompt that cannot be versioned, runs in a VM on UTC with a wrong vault
path, and is blocked by weekly token limits. Golaiet's scheduler replaces
it, and the Inbox stays as the input surface.

**Lessons (receipts in `Claude/state.md`, `Claude/log.md`)**
- The same value in two places drifts apart. The router said an item was stuck for 3 weeks while the dashboard showed it passed. One source of truth per fact.
- A prompt says what to do; it never repeats a value that lives in the data. Hardcoded practice lists and `stale_after_hours` went stale.
- A counter is never stored; it is derived from `since` plus events. Silence is the default.
- State changes are evidence-gated: a station passes only with a dated Inbox line. New items enter as `proposed`; only Guy promotes them.
- Burning and focus are capped (3 each) and always carry a reason.
- Every log entry points back to the verbatim day it came from. Keyword matches are labelled as not-truth.
- Check the byte count before trusting a read: a FUSE cache returned an empty file and swallowed a dictation.
- The conversation channel went quiet: three Friday briefings unanswered, questions re-asked 5+ times, and the runs started making priority calls on their own. A chat channel that Guy actually reads (Telegram) is the fix, and the agent must never promote `proposed` items itself.

## 4. From `claude_interface` (The Organism)

Design reference only. Taken: the single task queue (`tasks` is the only
queue; triggers just flip rows to immediate), the conversation row as the
handle for `--resume`, Telegram parsing with priority keywords and media
extraction (`bridges/telegram.py`), the auto-reply rule, and the "runner is
the only committer" idea if agent memory is ever git-tracked. Not taken:
the two-layer Docker split, the manager/contributor hierarchy, per-agent
directories, webhooks. That repo is parked and stays parked.
