# Roadmap

Phases are gated. Each has an exit test Guy can run from Telegram and a
list of what it deliberately does not include. Nothing starts before the
decisions in [DECISIONS.md](DECISIONS.md) are made.

| Phase | Name | Proves |
|---|---|---|
| 0 | The loop | Telegram ↔ agent ↔ database, scheduled collection, survives restart |
| 1 | The screen | Dashboard with a generic view; focus pushed from a conversation |
| 2 | War risk | First real tracker kind: `country_risk` with the globe; `topic` kind for antisemitism and VRAM |
| 3 | Stocks | `stock` kind with price monitor, thresholds, alerts |
| 4 | Life | `campaign` and `practice` kinds; the Inbox becomes a collector; the Desktop run retires |
| 5 | Digest and memory | Weekly digest, cost view, agent memory if still wanted |

## Phase 0: the loop

Build: Django project, PostgreSQL, `tracker` / `observation` / `job` /
`job_run` / `conversation` / `message` tables, Telegram long poller,
scheduler, agent runner, MCP tools (`list_trackers`, `get_tracker`,
`create_tracker`, `update_tracker`, `record_observation`,
`search_observations`), one tracker kind: `topic`.

Exit test, from Telegram:
1. "Track VRAM pricing and supply weekly" creates a tracker and two jobs, and the reply names them.
2. The first collect run writes at least one observation with a source URL and a cost.
3. "What's new on VRAM?" is answered from the database, not from a fresh search.
4. Restart Django mid-conversation; the next message resumes the same session.
5. A forced billing marker in the CLI output stops the scheduler loop and the heartbeat shows it.

Not in Phase 0: dashboard, assessments, alerts, focus, any kind but
`topic`, memory files, more than one chat.

## Phase 1: the screen

Build: `assessment`, `alert`, `focus` tables; `record_assessment`,
`raise_alert`, `set_focus` tools; `assess` job for `topic`; dashboard shell
with the overview and the `feed` view; SSE focus stream; alert delivery to
Telegram.

Exit test:
1. The kiosk browser opens the dashboard URL and shows every active tracker as a tile.
2. "Show me VRAM" moves the screen to the VRAM feed within 5 s. "Show everything" returns to the overview.
3. A weekly assess run writes an assessment with a reason; a level change produces exactly one Telegram alert.
4. Stop the scheduler for longer than the stale threshold; the dashboard shows the stale banner.

Not in Phase 1: globe, metro map, price panel, filters, drill-down beyond
the tracker's own observations.

## Phase 2: war risk and topics

Build: `kinds/country_risk` ported from the conflict map (research prompt,
validator, heat taxonomy, peace-score rubric), the `globe` view with the
drawer as the sidebar, trend computed from consecutive assessments. Seed
`ISR` and its neighbours. Create the antisemitism tracker as a `topic` with
a region list in its subject.

Exit test:
1. "What's the risk of war in Israel?" opens the globe on Israel with the drawer, and the reply quotes the latest peace score, its reason, and its change since the previous assessment.
2. A scheduled research run for a neighbour changes heat; the globe recolours on the next load and an alert arrives if the level crossed.
3. "What happened on antisemitism this week?" is answered from observations grouped by region.

Not in Phase 2: structured feeds (ACLED, GDELT), counterpart arcs, filters
by kind or scope, researching all 249 countries.

## Phase 3: stocks

Build: `kinds/stock` with a deterministic collect script (Yahoo batch
quote, 15 min in market hours), threshold assess rule, `price` view
(price line, thresholds, evidence list), a daily news collect session that
files observations against the ticker.

Exit test:
1. "Track CEG, good below 170" creates the tracker; the first tick lands within 15 minutes of market open.
2. Price at or below the line produces one alert and one open opportunity state; climbing back closes it without a second alert.
3. "Did anything change about my CEG thesis?" is answered from the news observations, with sources.

Not in Phase 3: the committee, the sanity gate, discovery, thesis
probability maths. The investment engine keeps running those until a tracker
asks for a judgment the thresholds cannot give.

## Phase 4: life

Build: `kinds/campaign` and `kinds/practice` with the `progress.md` schema
as payload, the Inbox collect job (reads
`/Users/guyhod/Kruv/Obsidian/Life/Golaiet/Inbox/`, checks byte counts, marks
lines, never edits content), the `campaign_map` view and the drawer's
History and Mentions. Import the current `progress.md` as the first state.

Exit test:
1. A dictated Inbox line about a workout resets the red counter on the next hourly run, and the line is marked done.
2. The wall screen shows the same map the React shell shows today, served from Golaiet instead of `data.js`.
3. A Friday question list arrives in Telegram instead of at the top of `Myself.md`, and an answer in Telegram updates the station.
4. For one week both systems run; their outputs are compared daily. Then the Desktop scheduled runs are turned off.

Not in Phase 4: changing the Inbox format, moving `Myself.md`, Siri
shortcut input.

## Phase 5: digest and memory

Build: Sunday digest job across all trackers; cost per tracker on the
dashboard; agent memory file, if Phase 0–4 show the agent repeating
mistakes that a resumed session does not catch.

Exit test: "What should I know from this week?" returns one message that
covers every tracker with a change, nothing that did not change, and the
week's total cost.
