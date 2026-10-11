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
push runs unit, smoke and end-to-end checks. Next: life, Phase 4 in
[docs/ROADMAP.md](docs/ROADMAP.md). How to run: [CLAUDE.md](CLAUDE.md).

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
