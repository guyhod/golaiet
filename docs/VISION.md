# Vision

## 1. The pattern

Every one of the three source projects does the same five things to one
kind of subject:

```
Subject  ──▶  Collect  ──▶  Judge  ──▶  Show  ──▶  Tell
 (what)       (facts)      (state)     (screen)   (Telegram)
```

Golaiet gives that pattern one name, a **Tracker**, and one implementation.

| Term | Meaning | What it was called before |
|---|---|---|
| **Tracker** | One thing Guy is tracking: a subject plus standing instructions on how to collect and judge it | `Company`+`Thesis` / `Country` / campaign or practice |
| **Observation** | A dated fact from a source, attached to a tracker. Never edited | `Evidence` / conflict record / Inbox line |
| **Assessment** | A dated judgment about a tracker: a state, a reason, the observations it rests on. Append-only | `Evaluation`+`SanityCheck` / `peace_score`+heat / burning, focus, station state |
| **Alert** | An assessment that crossed a line and was pushed to Guy | opportunity Telegram / none / `alert` in `progress.md` |
| **View** | How a tracker kind is drawn on the dashboard | website table / globe + sidebar / metro map + drawer |
| **Focus** | Which tracker the dashboard is showing right now, and how | `openCountry(iso3)` / drawer selection |

A tracker is **data, not code**. Asking Golaiet to track something new
creates rows and schedules jobs. It does not deploy anything. Only a new
*kind* of tracker (a new payload shape or a new view) is a code change.

## 2. The four requests from the brief, through the pattern

| Request | Tracker kind | Subject | Collect | Judge | View | Tell |
|---|---|---|---|---|---|---|
| Antisemitism around the globe | `topic` | query + region list | scheduled LLM web research, sources cited | level per region + trend, with reason | feed now, map later | weekly digest; alert on level change |
| Risk of war in Israel | `country_risk` | `ISR` + neighbours | the conflict-map research prompt, on a schedule | heat + peace score with reason and history | globe + sidebar | alert on level change, details on request |
| A stock I hold | `stock` | ticker + thresholds | price every 15 min in market hours; news daily | threshold crossing; "thesis assumption changed" | price panel + evidence list | alert when a line is crossed |
| VRAM supply and pricing (InferSky) | `topic` | query | scheduled research of vendor pages, news | supply/price trend with reason | feed | digest; alert on a sharp change |

Three of the four need no new code once the `topic` and `country_risk`
kinds exist. That is the test of the framing.

## 3. Two interaction loops

### Loop A: a question changes the screen

```
Guy (Telegram): "what's the risk of war in Israel?"
Golaiet:  finds tracker country_risk/ISR
          sets focus = (ISR, globe, sidebar open)      ◀── the dashboard moves
          answers in Telegram from the latest assessment and observations
```

If the question has a tracker, the screen shows it and the reply is short.
If more is useful, the reply carries it. Guy does not touch the screen.

### Loop B: a request creates tracking

```
Guy (Telegram): "track VRAM pricing and supply, I'm looking at InferSky"
Golaiet:  no tracker matches
          creates tracker topic/vram-supply with a brief (standing instructions)
          schedules collect (daily) and assess (weekly) jobs
          confirms in one line: what it will watch, how often, when the first run is
later:    first collect run writes observations; dashboard shows them in the feed view
later:    "what's interesting this week?" is answered from observations across all trackers
```

If a tracker already exists but the request narrows or widens it, Golaiet
updates the brief instead of making a second tracker. Two trackers on one
subject is the drift bug from `Life/Golaiet` (the same value in two places
disagreed), so the agent is told to prefer updating.

## 4. What "focus" means, precisely

Focus is a single row: *which tracker, which view parameters, set when, set
by which message*. The dashboard subscribes to it and renders accordingly.

- Focus is **pushed by the agent**, never typed into the dashboard. The
  dashboard has no input of its own, exactly like the wall screen today.
- One focus at a time. "Show me everything" clears it and the dashboard
  returns to its overview.
- Focus carries view parameters, so "focus on Israel" opens the globe on
  `ISR` with the sidebar open, and "focus on CEG" opens the price panel.
- Clicking on the dashboard (a station, a country) is a **local** drill-down
  and does not change the shared focus row. Local always wins over pushed
  until the next push.

## 5. Non-goals

- **Not an org chart of agents.** The Organism's management layer
  (managers, feedback loops, promotion) is out of scope. Golaiet is one
  agent with many trackers. Specialised behaviour lives in tracker briefs,
  which are editable text, not in agent hierarchies.
- **Not a replacement for Obsidian as Guy's writing surface.** The voice
  Inbox stays where it is. Golaiet reads it; it does not own it.
- **Not multi-user.** One Telegram chat, one screen.
- **Not a per-tracker schema.** Agents never alter the database schema.
  Observations carry a JSON payload validated against the tracker kind.
- **Not a trading system and not a news reader.** It tracks what Guy asked
  for, and only that.
