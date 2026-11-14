# Life migration: moving Golaiet out of the Obsidian vault into this repo

Status: **decided, 2026-11-11.** This is the plan for Phase 4 ("life") of
[ROADMAP.md](ROADMAP.md), second version (2026-11-10). It is complete on
its own: the decisions it rests on are written out in the next section, so
nothing else has to be read to build from it. The sentences those decisions
change in ROADMAP, VISION and LINEAGE are changed (§9). Nothing is
committed and nothing is built yet; building starts at Step 0.

**Rule of this phase: nothing from the vault's content enters this repo.**
No names, messages, counts or examples taken from it, in documents, tests or
fixtures. The vault-side diagnosis, the evidence behind this plan and every
file that holds real data live in the vault under `Golaiet/WIP/merge/`;
commands take vault paths as arguments; tests run on invented fixtures.
Examples below are invented. The first version of this plan (2026-11-08,
reviewed 2026-11-09) held vault details and is archived there too.

After this migration there is one agent for life (this repo's, reached over
Telegram), one scheduler, one screen, and the vault holds only what Guy
writes.

## The decisions this plan rests on

Guy decided the first six on 2026-11-11, all as recommended, and amended
the seventh the same day. [DECISIONS.md](DECISIONS.md) keeps the same rows
as the repo's record, under the codes in brackets; a decision amended later
is amended there and here in the same commit.

| Decision | What was decided | Where it shows here |
|---|---|---|
| Where life input comes from [D13] | The Telegram conversation. The Inbox is not read. The Claude chat that updates the vault today stops updating the board: a life update said anywhere else is answered with "send it to Telegram". | §2, §3.4 |
| How the vault system and this one overlap [D14] | No double run. Import, check that the two boards are equal, then one week with Telegram as the only input and the Desktop runs paused, not deleted. | Steps 1, 2, 5 |
| What stops at cutover [D15] | All the Desktop runs, and with them everything they write into the vault and scan there. Status and check dates live on the board. A check date that goes by shows as burning until Guy moves it. The weekly summary waits for the Phase 5 digest. | §3.3, §6, Step 5 |
| What Golaiet writes into the vault [D16] | One thing: a note appended to a lane's own vault file when Guy asks for one. A task he dictates becomes a station on the board, not a line in `TODO.md`. What a tracker records is not copied into topic files. | §3.2, §3.5 |
| The Friday brief [D17] | In Telegram, Friday 07:30, three questions at most. It is switched off after three delivered briefs in a row with no question answered within 48 hours: an answer is a message that takes up one of the questions, and a Friday on which the brief was not delivered does not count. | §3.6, Step 4 |
| When the host is off [D18] | Stay on the Mac. Keep it rarely off (Docker Desktop at login, no sleep on power, the restart policy), know when it is (a watcher outside the stack), and one rule for the rest: a message that got no reply was not recorded, and forwarding it again files it with its original time. Move to an always-on host when the watcher's log shows the stack unreachable for more than 24 hours twice in a month. | Step 0, §3.4, §8 |
| Who adds what to the board [D10, decided 2026-10-09, amended 2026-11-11] | Guy creates trackers through chat, and only he promotes. Since the amendment the agent also opens lanes and stations on its own from what comes up in a conversation, marked `proposed`. Progress, burning and focus are recorded only on Guy's words. A practice, or a tracker that collects on a schedule, is opened only when he says. | §3.2, §3.4, §3.6 |

Earlier decisions this plan leans on, unchanged:

- One React app, built static, behind its own nginx container [D6]. The
  Life screen is a screen of that app, not a second build.
- No memory written by the agent through Phase 4; what carries over is the
  resumed session and the briefs [D7].
- One agent, many trackers; behaviour lives in briefs [D8].
- One fixed set of tables, a kind's shape in validated JSON, no table per
  tracker [D3]. The `link` table that row names is not needed here.
- Everything runs on this Mac under docker compose [D11].

Guy's direction for after this phase is §11.

## 1. What this plan starts from

**The premise, from the vault side.** Guy's input is the conversation; the
Inbox files are written by the sessions that take his messages. The
evidence for that sentence is in the vault and stays there. LINEAGE §3
already records the other half: the written channel back to him went quiet,
and a chat he actually reads is the fix.

**This repo, as it is.** Phases 0 to 3 are built; the last commit is from
2026-11-02. Six facts matter for Phase 4:
- The stack stayed down after the Mac rebooted on 2026-11-02 until it was
  started by hand on 11-05. The fix (`restart: always` on the app services)
  sits uncommitted in the working tree, and nothing outside the stack
  notices when it is down.
- The database has no backup.
- The poller stores a message without the time it was sent
  (`chat/poller.py` drops Telegram's `date`; `created_at` is the time of
  storing). After an outage every queued message would be dated to the
  minute the stack came back.
- The reply flow hands the model the bare text, and the containers run on
  UTC: the model cannot know what "today" is in Jerusalem.
- A message with no text (a voice note, a photo) is dropped without an
  answer.
- `list_trackers` returns every tracker with its whole latest state. With 38
  country records that is, by the sizes in the code, about 150 KB, above the
  25,000 tokens the CLI allows a tool result by default. To be confirmed
  with one call on the live stack.

**What the first version got wrong.** It built a file reader, a line marker
and a shadow mode around an input that is not used. It stored a campaign as
a fold over one assessment per transition, where every other kind in this
repo reads the latest assessment as the state. Its parallel week needed two
processors for one stream of messages. The review of 2026-11-09 was right on
each point it checked and added the machinery those choices required; the
choices were the problem.

## 2. The design in five statements

1. **The conversation is the collector.** A Telegram message is the
   dictation. The reply flow files what Guy reports, and every row it writes
   leads back to his words (`job_run` → the message).
2. **Rows are the live state; nothing is folded and no counter is stored.**
   A practice is its events. A campaign is its latest assessment.
3. **The board is one read.** `GET /api/life` returns the object the vault
   shell draws today, and a Life screen draws it.
4. **The vault keeps what Guy writes.** Golaiet appends a note there when he
   asks for one, and nothing else.
5. **Friday is a conversation that a job starts.** The brief is posted from
   the conversation's own session, so his answers land where the questions
   are.

The pattern underneath is the one the repo already has: an entity with live
state, facts appended, judgments appended, the kind module owning the shape.
Phase 4 adds two kind modules and no table.

## 3. What is built

| Piece | Where | New lines (estimate) |
|---|---|---|
| Kind `practice` | `core/kinds/practice.py` | 80 |
| Kind `campaign` | `core/kinds/campaign.py` | 180 |
| The board | `core/life.py`, `GET /api/life` | 150 |
| Import | `core/management/commands/import_life.py` | 160 |
| Reply flow: sent time, life rules, one session at a time | `chat/` (one migration), `agent/flows/reply.py`, `agent/prompts.py` | 50 |
| Tools | `agent/tools.py` | 70 |
| Friday brief | `agent/flows/brief.py`, one seeded job | 60 |
| Replay (test tooling) | `agent/management/commands/replay.py` | 70 |
| Life screen | `dashboard/src/views/life/`, a `.life` section in `styles.css` | 1,600 TypeScript, 200 CSS |
| Outside the stack | `ops/watch.sh`, `ops/backup.sh`, two launchd entries | 60 |
| Tests | pytest, Vitest, one Playwright scenario | 600 Python, 250 TypeScript |

Two migrations (the kind choices; `Message.sent_at`). No new table, no new
dependency in the image or the dashboard.

### 3.1 `practice`: events in, arithmetic out

- `title` is the label. `brief` says what counts as an event and how it is
  dated. The rules that lived in a pasted run prompt move here, one practice
  at a time, where Guy can read and edit them.
- `subject`: `color` (`green` is a streak and an event is a failure; `red`
  is a gap and an event is an occurrence), `started`, `alert_after` (red
  only), `note`, `rank`.
- One observation per reported event: `observed_at` is the day it counts
  for, `summary` is Guy's words, no URL, no payload. The event day is the
  Jerusalem date of `observed_at` (a bare date is stored as Jerusalem
  midnight, which is the evening before in UTC). A day with at least one
  event is an event day, so the same report sent twice counts once. A wrong
  entry is corrected by another observation with
  `payload = {"retracts": id}`; neither counts.
- Computed at read time from the event days: `since = max(started, last
  event)`, the counter, good / warn / bad, the caption and the 14 dots. These
  are the rules of `derive()` in the vault's `render_dashboard.py`, moved as
  one pure function.
- No assessments, no jobs, no alerts: `validate_state` refuses, because a
  practice is not judged.
- `status` does what a `shown` flag would: `active` is on the board;
  `paused` is off the board and still recorded; `archived` is retired.
  Hiding a practice is `update_tracker(status="paused")`, an argument the
  tool already has.

### 3.2 `campaign`: the latest assessment is the lane

- `subject` holds identity and presentation: `short`, `layout`, `rank`,
  `file` (the vault file its notes go to), `path`. `status` works as for a
  practice: a `paused` lane is not drawn and still feeds the panels.
- The latest assessment's `state` is the lane as it stands: tracks of
  stations (`id`, `label`, `state`, `date`, `check`, `note`, flags), the
  lane's `check` and `target_by`, its burning and focus flags with their
  reasons, and one `next` action. Reading a lane is reading one row of a
  couple of kilobytes.
- A change is **submitted small and stored whole**. `record_assessment`
  takes only what changes, for example
  `{"stations": [{"id": "s2", "state": "passed", "date": "2026-11-10"}]}`.
  `validate_state(change, previous)` applies it to the previous state and
  returns the whole lane, which is what is stored. Stations the change does
  not name are untouched by construction: a model that never retypes a label
  cannot reword it.
  - a lane field replaces the stored one, and `null` removes it;
  - a station with a known id takes the given fields; a new id needs
    `label` and `track`, and is `ahead` unless the change says otherwise;
  - `dropped: [id]` removes a station; `tracks` in full is accepted (the
    importer's form, and the way to regroup) only when no station vanishes
    unnamed;
  - derived on write: `level` (burning, focus or steady) and `changed` (the
    ids this change touched);
  - refused, loudly, so the agent can fix and call again: two `current` in
    one track, a duplicate id, an unknown state or field, a field of the
    wrong type (a rank that is text, a flag that is not true or false), a
    date that is not ISO, a station passed without the `date` it happened, a
    burning or focus flag without its reason, on a lane or on a station,
    `level` or `changed` passed in. The kind has no clock: a pass says which
    day. A state that was accepted can always be drawn: the board never
    fails on a stored lane.
- A campaign assessment must cite at least one observation of that lane
  filed by the run that makes the change: the fact in Guy's words, from the
  message being answered. Earlier observations may be cited beside it, not
  instead of it; the import, which has no run, cites the log rows it wrote.
  This is the decided rule that only Guy promotes (D10) and the vault's
  first rule (no status that cannot be verified), enforced in
  `record_assessment`.
- What the agent adds on its own is a proposal (D10 as amended on
  2026-11-11): a station in state `proposed`, on the lane it belongs to or
  on a lane the agent opens for a subject that came up, with the message it
  came from as evidence. A proposal changes no status: `proposed` stations
  are drawn apart and are not counted. Progress, burning and focus change
  only on Guy's words. This half of the rule is in the prompt, not in the
  validator, which cannot tell whose idea a change was. When the map is
  full, a new lane shows in the quiet list until Guy moves it up.
- A task is a station. It goes on the lane it belongs to, or on one lane
  that is not drawn, `tasks`, whose stations still feed Burning, the horizon
  and "Passed — last 14 days". The vault's `watches[]` and the closures its
  log filed under names that are not lanes land there.
- No jobs and no alerts in this phase.

### 3.3 The board and the Life screen

- `GET /api/life` returns the `View` of the vault shell's `lib/types.ts`
  without `log` and `inbox`: pulse, burning, focus, horizon, trail, next,
  lanes, quiet. One function, `core.life.board(today)`, builds it from the
  rows; "today" is the Jerusalem date. Empty fields are omitted.
- Derived there, like the counters, and never written: a check date that
  has gone by shows as burning, with its date, until Guy moves or drops it.
- The Life screen is the fifth tab; a tracker of either kind names the view
  `campaign_map`, which the registry in ARCHITECTURE §7 already lists. A
  pushed focus on a lane or a practice switches to the screen and opens it.
  The wall browser opens `/life`: no tab bar, the screen pinned, the stale
  banner kept; a push about a tracker of another kind is ignored there, and
  a drawer a push opened closes by itself, since the wall has no keyboard.
- The port restyles the shell in this dashboard's plain CSS and adds no
  dependency. The metro map (325 lines of SVG with no class names) moves
  unchanged, with the palette; the panels, the drawer and the header get a
  `.life` section in `styles.css`. Bringing Tailwind in was checked and
  rejected: its utilities sit in cascade layers that this app's unlayered
  rules override, its sizes are in `rem` against an 18 px root inside a
  fixed 1920×1080 grid, and the shell's `--muted` would overwrite the
  existing one. A second build entry for the shell would avoid all three
  and contradict the decided "one React app" (D6).
- The drawer shows one list, History: the tracker's observations through
  the existing `GET /api/trackers/{slug}`. Assessments have their own
  parameter there, `assessments` (default 10), and do not follow `limit`: a
  country's assessment is its whole record, and the screens that ask for
  50 or 100 observations must not pull as many of those. The drawer asks
  for as many assessments as observations. A fact belongs to a station's history when
  it names the station (`payload.station`, which the importer writes) or was
  the evidence for a change that touched it (`changed`). The vault shell's
  second list, Mentions, matched keywords against raw Inbox lines; with
  every fact filed on a tracker it has nothing to match.
- Life trackers are left out of the List screen: they have their own.

### 3.4 The conversation

- `Message.sent_at` holds Telegram's own time for the message (for a
  forwarded message, the original's, from `forward_origin.date`: to be
  confirmed with one forwarded message in Step 2; the poller falls back to
  now when an update carries no time). The prompt is one line with the
  Jerusalem date, weekday and time the message was sent, then the text; the
  end-to-end fake skips that line. Dates are counted from it, never from
  now.
- A message with no text gets a one-line answer instead of silence.
- One conversation, one session at a time: the reply flow and the Friday
  brief take the same in-process lock around the CLI call, so two runs never
  resume the same session together.
- Tools, ten after this phase:

| Tool | Change | Why |
|---|---|---|
| `list_trackers(kind=None)` | one compact row per tracker; filter by kind | §1: the listing does not fit a tool result |
| `update_tracker(…, title=None)` | a title can change; a life tracker's subject is merged field by field, `null` removes | a practice gets renamed when its definition does; a partial subject must not drop the lane's place on the map |
| `create_tracker`, `update_tracker`, `get_tracker`, `record_assessment` | a life tracker's result carries `on_board` | a practice beyond the pulse row's seven, or a tenth lane once it has stations, is recorded and not drawn, and the reply should say so |
| `create_tracker`, `update_tracker` | a `null` in a life subject is a field left out and is never stored | a stored null rank cannot be sorted against the other ranks, and the board would fail on every read |
| `record_assessment` | calls the kind's evidence rule when it has one; `campaign` does | §3.2 |
| `create_tracker` | `cadence` gets a default; a kind with no jobs ignores it | life kinds have no schedule |
| `record_observation`, `create_tracker` | wording: the new kinds' fields; for life, `summary` is Guy's words | the docstring is what the model reads |
| `add_note(slug, text)` | new: appends a dated line to the lane's vault file | §3.5 |

- The reply system prompt gains one paragraph, in this sense: *Life
  trackers are Guy's own life; he reports and you record. Read the tracker's
  brief before filing: it says what counts and how it is dated. A practice
  event is one observation on the day it counts for, in his words. A lane's
  progress, burning and focus change only on his words: file the fact on the
  lane, then record only what changes, citing it. A task is a station.
  Taking a tracker off the board pauses it; it is still recorded. Say what
  you recorded: tracker, date and the new count or state, in one line. When
  the tracker or the date is unclear, ask before filing. Nothing is edited:
  a wrong practice entry is retracted, a wrong change to a lane is corrected
  by a new change. The conversation is not only reports: questions and
  consultations on any subject are answered here. What a conversation brings
  up that belongs on the board and that he did not ask for, add as a
  proposal: a station in state `proposed`, on its lane or on a new one, and
  say that you did. Offer a practice or a tracker that collects on a
  schedule, and open it when he says yes. Files, the vault and repositories
  cannot be reached from here: say so in one line.* The paragraph is generic
  on purpose. Guy's own conventions are rows he can edit, not text in this
  repo. What counts for one practice is in its brief. What holds for every
  report is in `Conversation.conventions`, a text field shown in admin: the reply prompt
  carries it under the line that says when the message was sent, so a
  practice the agent creates in conversation, which has no brief of Guy's
  yet, is filed by the same rules.
- The reply flow's model becomes its own setting, so the conversation can
  run on a stronger model than the collectors. Whether the model is good
  enough for life is measured before cutover (Step 2), not assumed.

### 3.5 The vault

`VAULT_DIR` is a setting; compose mounts the vault into the scheduler
container only. One tool writes there, when Guy asks for a note: `add_note`
appends a line, dated the day the message was sent, to the file named in the
lane's `subject.file` and checks that the file grew by exactly what it wrote
(LINEAGE §3: check the byte count before trusting the file system). The
lane's `file` is Guy's to set, in admin or by the import: the agent's tools
refuse a subject that sets or changes it, and the tool writes only to an
existing `.md` file, so no conversation can point a note at another file.
What a tracker records is not copied into topic files. `TODO.md` is neither
read nor written. The end-to-end stack mounts an empty folder in the vault's
place whatever `.env` says.

### 3.6 Friday

A job `brief` (kind `digest`, Friday 07:30) builds its prompt in code from
the board and the week's rows: what passed, which practices moved, which
check dates have gone by, and which proposals are still open, to keep or to
drop. It runs on the conversation's own session with the
read-only tools and sends the text as an ordinary outgoing message, with at
most three questions. Guy's answers are ordinary messages in a session that
has seen the questions. The same flow is the seed of the Phase 5 digest
(ARCHITECTURE §4.5).

The stopping rule: when the last three delivered briefs each went 48 hours
with no question taken up, the job switches itself off and says so once.
Whether a question was taken up is judged by the session, from the rows and
not from its memory: the prompt carries the previous delivered brief's text
and Guy's messages of the 48 hours after it (by the time he sent them). The
verdict is the last line of the answer and nothing else.
One verdict per delivered brief: a run records which brief it judged, so a
Friday whose brief did not go out is not a second "no" for the one before
it. The switch-off notice is not a brief and is never judged; if it does not
send, the run fails and the job stays on. The brief is brought back by
ticking `enabled` on the job `brief` in admin (the notice says so; no tool
does it), and the count starts again from there: only briefs delivered
after the switch-off count.

### 3.7 Import

`manage.py import_life <progress.md> --extras <json>` creates the trackers
and their first rows. `--dry-run` prints what it would do and what it leaves
out; `--replace` drops the life trackers and imports again, and is refused
once the conversation has written an observation or a lane change on them,
unless `--force` is given: it says what would be lost, and `--force` by
itself is refused;
`--events-until <date>` leaves out later events and the practices the log
says were added after the date, whatever their first event (the replay's
starting state; lanes are not rewound, they are imported as they stand);
`--check` compares `core.life.board()` with the vault's own `derive()` on
the same file, both with their lists whole and the derived overdue checks
set aside. Beyond the three differences Step 1 names, `--check` tolerates
two more: a value the vault writes as empty (`""`, `false`, `null`, `[]`)
counts as absent, and a lane that is not drawn is compared by its name
only, since neither board carries more of it. An extras key the import
does not read is an error. Each lane's log rows become observations on it
(its history); each practice's event days become observations. Briefs and
the lanes' `file` come from the extras file, which lives in the vault and
has four keys: `practices`, `lanes`, `default_lane_brief` and `conventions`.
`conventions` is a list of sentences, the standing constraints the vault's
memory files hold today; it is written to the conversation of
`TELEGRAM_CHAT_ID` (§3.4), creating the row if there is none. Without the
key the row is left as it is, and `--dry-run` prints the sentences.

Guy runs the import by hand. It is his act, not the agent's.

## 4. Explicitly not built, and what would bring each back

| Not built | Comes back when |
|---|---|
| Inbox reader, line marker, shadow mode | Guy types into the Inbox again |
| A parallel week with two processors | never: the replay (Step 2) answers the same question earlier |
| Practice alerts or a morning nudge | a red tile goes unnoticed for a week |
| Mentions across trackers | he asks where else something was said: one read endpoint over observations |
| Writing or reading `TODO.md`; a markdown copy of the board in the vault | he looks for a dictated task in the vault and it is not there |
| Voice notes | he sends one; the answer will have told him it was not read |
| The weekly summary | Phase 5's digest |
| A `link` table (decided as the store for relationships, D3), agent memory (decided: none through Phase 4, D7), an agent table (decided: one agent, D8) | their own decided rows |
| Session rotation | a reply slower than about 40 s, or a Friday answer that lands in a session without the questions. With consultations as a daily use this is expected soon after cutover (§11) |

## 5. Steps

Estimates are in evenings. Basis: Phase 3 took 22 commits over two days.
No step makes a paid API call; sessions run on the plan login and count
against its usage windows.

Before cutover the life rows in the live database are disposable: every
comparison starts with `import_life --replace --force` (Steps 2 and 4 leave
throwaway rows written through the conversation, which a bare `--replace`
refuses to delete), and what is verified live before Step 5 is verified
with throwaway content.

A step is done when its exit check has passed and a line under its heading
says so: the date and the evidence. That line is how the next session knows
where the work stands.

### Step 0 — the stack can be trusted (½–1 evening)

Commit the compose fix. Two settings on the Mac, Guy's to make: Docker
Desktop starts at login, and the Mac does not sleep while on power.
`ops/watch.sh` under launchd, hourly: reads `/api/health`, appends a line to
a log, and shows a notification when the heartbeat is older than 90
minutes. `ops/backup.sh` under launchd, nightly: `pg_dump` through the `db`
container into a folder outside the repo, 30 days kept.

**Exit check:** after a reboot the stack returns by itself and the
heartbeat is fresh within 35 minutes; with the scheduler stopped by hand a
notification appears; last night's dump restores into a scratch database
with the same row counts.

**Review fixes in, 2026-11-12.** `ops/backup.sh` logs the dump before it
prunes and clears a half dump left by a killed run; each script has a test;
the install and removal steps are in the README. Nothing is installed; the
exit check is open and is Guy's.

**Second review, 2026-11-14.** The watcher reads the heartbeat's time with
the Mac's `date` or GNU `date`, so its test runs wherever the checks run.
The README's steps now give the order (the first dump, then `make stack`,
then the reboot), a first dump by hand, where `docker` must be on the
plists' PATH, how to see a notification without the wait, and the restore
with the scratch database made first and the row counts that are compared.

### Step 1 — kinds, import, the board API (2 evenings)

§3.1, §3.2, §3.7 and `GET /api/life`. A spike of the pure functions already
runs against the real file (§10); this step turns it into the two kind
modules, `core/life.py` and the command, with tests on an invented fixture,
one of them at the date boundary of §3.1.

**Exit check:** `import_life --check` on the real `progress.md`, run on the
Mac: pulse, burning, focus, horizon and lanes equal; trail equal in stations
and dates; next equal as a set (the order becomes hot first, then lane
order); quiet equal plus the `tasks` lane.

**Done 2026-11-11.** `import_life --check` on the real file, imported into a
scratch database on the Mac: every key equal or one of the named differences
(trail by station and date, next as a set, quiet plus the tasks lane), today
and on five other days; on the two later days the only extra is the overdue
checks derived at read. `make check` green (101 pytest, 31 Vitest). Built
before Step 0's exit check, on Guy's word that the Mac actions come last.
Size: the import command is 267 lines against the 160 estimated; the 100
over are the `--check` comparison and the dry-run report, which the estimate
did not count.

**Review fixes in, 2026-11-12.** The campaign validator checks every
field's type, `--replace` is refused once the conversation has written,
`--events-until` leaves out practices that start later, an unknown extras
key is an error, and `--check` compares whole lists with the derived overdue
checks set aside. The exit check was run again with the stricter comparison,
on a scratch database from the real file: every key equal or one of the
three named differences, today and on three other days. `make check`: 150
pytest, 39 Vitest.

**Second review, 2026-11-14.** `--events-until` leaves out a practice the
log says was added after the date, whatever its first event; `--force`
without `--replace` is refused; §3.7 names the two differences `--check`
does not see.

### Step 2 — the conversation (1½–2 evenings)

§3.4 and §3.5. Then the replay: `manage.py replay <cases>` feeds real
messages, each with the time it was sent, through the reply flow against a
scratch database imported with `--events-until` the day before the first
message, with Telegram sending off, and compares the practice observations
written with the event days the vault recorded. It measures the one thing a
smaller model without the vault is most likely to get wrong: which practice
and which day. The cases stay in the vault.

**Exit check:** every event in the replay lands on the right practice and
the right day, or the miss is explained by a sentence added to that
practice's brief and the replay is run again; every message gets an answer
that names what was recorded. Messages that change a lane or a definition
depend on the state at the time and cannot be replayed; they are the reading
list for Step 5's first week. One more check, live and with throwaway
content: a consultation that brings up something for the board ends with a
`proposed` station and a reply that says so, and nothing else on that lane
has changed.

**Built 2026-11-11, exit check open.** §3.4 and §3.5 are in and tested with
the CLI stubbed (`make check`: 110 pytest; `make e2e`: 4 of 4). The exit
check itself needs Guy: the go-ahead for the replay's sessions, one
forwarded message, one live consultation. This is not the step's line.

**Review fixes in, 2026-11-12.** A lane change must cite a fact filed by
the same run; the lane's `file` is Guy's to set and `add_note` writes only
to an existing `.md` file, dated by the message; a life subject is merged
field by field; the tools' results say whether a tracker is drawn; the
replay gives each case its own conversation; the end-to-end stack never
mounts the vault. The exit check is still open.

**Second review, 2026-11-14.** A null in a life subject is dropped before
it is stored and the board sorts a stored one last; `record_assessment`
says whether the lane is drawn, so a tenth lane is reported when its
stations arrive. The replay runs only the cases that expect a practice
event and lists the others at the end as the reading list; it checks every
case (a time that cannot be read, an id that repeats) before the first
session; a practice first mentioned inside the replayed window is left out
of the starting state and is known afterwards by the tracker its case's run
created, and a case that should create one practice and creates none or two
is a miss said in words; the CLI's transcripts go to a temporary folder
that is removed, so a run leaves no transcript behind. The messages are
still in the scratch database until it is dropped, and the replay prints
the start of each reply to the terminal (corrected 2026-11-14: this line
said nothing of the messages stays on disk). The command
is about 140 lines against the 70 of §3: these rules were not counted. How
the scratch database is made and dropped is in the README.

**Third review, 2026-11-14.** A replay cannot reach the live database or
Telegram: every run's tool-server config names the database of the process
that started it (name, host and port, for every run and not only a replay),
and the replay empties the Telegram token in the environment the CLI and
its tool server inherit, not only in its own settings. Guy's conventions
for every report have a home: a field on the conversation, read by every
reply, filled by the import from the extras file's `conventions` and given
to each replayed case's conversation. The replay's comparison is each
practice's event days before and after the case's run: every expected day
is there afterwards and every day the run added was expected, so a second
report of a day is no miss; an expected event may carry `or`, other days
that are as fair a reading; in the case that creates a practice, its
`started` meets an expected day only when that day is before the day the
message was sent; a case that should create a practice a later case
reports on is run even when it expects no event, and passes when it
creates exactly one and adds no day; a case on a practice that was never
created is not comparable, said in words, spends no session and is not a
miss, and `--only` on such a case is refused with the id of the case to
run first; a case with no date, tracker or effect is refused by name. The
command is now about 210 lines.

### Step 3 — the Life screen and the wall (2–3 evenings)

§3.3.

**Exit check:** ROADMAP exit test 2, after a fresh `--replace --force`: `/life` on
the wall beside the vault's page shows the same lanes, stations and states
and the same panel content. The map is identical by construction; the
restyled panels are checked by eye.

**Built 2026-11-11, exit check open.** The screen is the fifth tab and
`/life` is the wall; `make check` (110 pytest, 37 Vitest) and `make e2e`
(7 of 7, three of them the Life scenario) are green. Rendered once against
the real board on a scratch database: the map, the panels and the drawer
draw. The exit check is Guy's eye on `/life` beside the vault's page after
the import. This is not the step's line.

**Review fixes in, 2026-11-12.** A pushed focus opens its drawer once
(keyed on the focus row's `set_at`, remembered by the browser), and a lane
the map does not draw opens in full from Burning, the horizon, Next and the
trail. `make e2e`: 7 of 7. The exit check is still open.

**Second review, 2026-11-14.** A lane the map does not draw is read once
for both its stations and its history.

### Step 4 — Friday in Telegram (½–1 evening)

§3.6.

**Exit check:** the job, run by hand, posts a brief built from the week's
rows; an answer to one of its questions changes a station with that answer
as evidence (throwaway content).

**Built 2026-11-11, exit check open.** The flow, the seeded job and the
stopping rule are in and tested with the CLI stubbed (`make check`: 116
pytest). Whether a message took up a question is judged by the session, as
one last line the flow strips, from what the prompt gives it out of the
rows: the previous delivered brief and the messages of the 48 hours after
it (amended 2026-11-14; before, it rested on what the session remembered).
The flow is 112 lines
against the 60 estimated: the stopping rule and the week's facts were not
counted. The exit check (a brief run by hand, one answer) needs Guy. This is
not the step's line.

**Review fixes in, 2026-11-12.** The stopping rule counts each delivered
brief once, never judges its own switch-off notice, starts again after the
job is re-enabled, reads the verdict line leniently and stays on when the
notice does not send (§3.6). How the job is run by hand is in the README.
The exit check is still open.

**Second review, 2026-11-14.** The verdict no longer rests on what the
session remembers: the prompt carries the previous brief and the messages
that followed it, and a test gives them to a session that never saw the
brief. Only the last line is the verdict, and only a whole word counts.

### Step 5 — cutover and the first week (1 evening + 7 days)

**Gate:** Step 0's exit check still holds.

In one evening: the three Desktop runs are paused; `import_life --replace`
on the final `progress.md`, which refuses and lists what the conversation
recorded on the life trackers: that list is read, and when it holds only the
throwaway rows of Steps 2 and 4 the import is run again with `--force`;
`--check`; the wall browser opens `/life`; the
vault's `CLAUDE.md` gets a dated note that life is recorded through
Telegram, that status lives on the board, that a Claude session in the vault
no longer updates it, and which files are now archive.

**Exit check** (ROADMAP exit tests 1, 3 and 4 as reworded in §9): for seven
days Telegram is the only input. A message about a workout resets the red
counter within a minute and the reply names the date. The Friday brief
arrives and an answer changes a station. Every life message gets a reply
that names what was recorded, and nothing is fixed by hand in admin, or each
fix became a sentence in a brief. Then the three runs are deleted. Going
back inside the week: the runs are resumed and a session in the vault
re-enters the week from the message list in admin, about half an hour for a
week of messages.

Total: 7½–10 evenings and the week.

## 6. What changes for Guy on the day of cutover

- Life updates go to Telegram only. A reply names what was recorded and for
  which date; no reply within a few minutes means it was not recorded, and
  forwarding the message again files it with its original time.
- Consultations can happen in Telegram, where what comes out of them
  reaches the board as proposals he keeps or drops. The agent there cannot
  open the vault or a repository.
- The Claude chat stays for documents and code. It no longer updates the
  board.
- A task said to the agent lands on the board, not in `TODO.md`.
- The scheduled runs stop, and with them everything they wrote into the
  vault and scanned there, the weekly summary included, until Phase 5. The
  list of what each run does today and what becomes of it is in the vault
  note. `Myself.md` is his alone.
- A check date that goes by shows as burning until he moves or drops it;
  nothing moves it for him.
- The Friday brief arrives in Telegram at 07:30, short.
- The wall shows the same map from `/life`. The open-task count and the
  drawer's Mentions list are gone.

## 7. Size, against the benchmark

Guy's yardstick for this project is `investment_engine`: about 6,800 lines
of application Python, 6,300 lines of tests, 16 models, 53 commits.

| | Golaiet today | After Phase 4 |
|---|---|---|
| Application Python | 2,790 | about 3,600 |
| Dashboard TypeScript and CSS | 1,520 | about 3,300 |
| Tests (Python + TypeScript) | 1,455 | about 2,300 |
| Tables | 9 | 9 |
| Kinds, tools, flows, screens | 3, 9, 4, 4 | 5, 10, 5, 5 |

The same order of magnitude as the benchmark in application code, with
fewer tables because a kind carries its shape in validated JSON. The first
version with its review was heading, by estimate, for about twice the new
Python; what was removed is in §4, each with the condition that brings it
back. Tests stay lighter than the benchmark's one-to-one: about 600 lines
for the 800 of new Python, and about 250 for the screen, on its pure
modules, as the existing screens are tested.

## 8. Risks

- **The smaller model mis-dates or mis-files.** The session that did this
  until now was a larger model with the whole vault open. Measured by the
  replay before cutover; visible on every message because the reply names
  tracker and date; correctable by `retracts`. If the replay fails on
  dating, the reply flow's model is one setting.
- **The Mac is off.** Under 24 hours, messages wait at Telegram and are
  dated by their own sent time. Over 24 hours Telegram drops them. The
  watcher says when the stack is down, the reply that never came says what
  was not recorded, and a forwarded message keeps its time. An always-on
  host is the cure; the decided call on the host (D18) is to stay on the
  Mac for now and move when the stack is unreachable for more than 24
  hours twice in a month.
- **The Friday brief goes unanswered**, as LINEAGE §3 records for the
  written one. It costs one session a week and carries a stopping rule (the
  decided call on the brief, D17).
- **The restyle.** Panels can drift from today's look. The map cannot.
- **One long session.** The conversation resumes one Claude session, which
  grows with every tool result and every consultation. No change in this
  phase; it is the first thing to change after it (§11).
- **Proposals pile up.** An agent that adds on its own can fill the board
  with stations nobody asked for, a milder form of the overreach LINEAGE §3
  records. They change no status, they are drawn apart, and the Friday
  brief lists the open ones to keep or to drop.
- **The archive is frozen, not migrated.** History that is not on a lane or
  a practice stays readable in the vault and is not in the database; the
  import's dry run lists it.

## 9. Sentences changed with the decisions (2026-11-11)

Changed in the working tree with the decisions, to be committed with them.
ARCHITECTURE is the exception: its sentences describe what is built and
change in the step that builds each thing.

- DECISIONS: rows D13 to D18 decided; D10 amended (the agent adds
  proposals on its own).
- ROADMAP, a new closing section, "After Phase 5: the direction", in the
  words of §11 below.
- VISION §5: "It tracks what Guy asked for, and only that." → "It tracks
  what Guy asked for. What it adds on its own from a conversation is a
  proposal on the board until he says so."
- ROADMAP, the Phase 4 row of the table: "the Inbox becomes a collector" →
  "the conversation becomes the collector".
- ROADMAP Phase 4, build line → "`kinds/practice` (events as observations)
  and `kinds/campaign` (the lane as the latest assessment), `/api/life` and
  the Life screen (`campaign_map`) with the drawer's History, the life rules
  of the reply flow, one vault tool, the Friday brief. Import the current
  `progress.md` as the first state."
- ROADMAP exit test 1 → "A Telegram message about a workout resets the red
  counter within a minute, and the reply names the date it recorded."
- ROADMAP exit test 4 → "For one week Telegram is the only input and the
  Desktop runs are paused; every life message gets a reply naming what was
  recorded. Then the runs are deleted."
- ROADMAP non-goals → "reading the Inbox, moving `Myself.md` or `TODO.md`,
  voice notes, Siri shortcut input."
- VISION §5: "The voice Inbox stays where it is. Golaiet reads it; it does
  not own it." → "The vault stays his. Golaiet does not read it, and appends
  a note there only when asked."
- LINEAGE §3: "and the Inbox stays as the input surface" → "and the
  Telegram conversation is the input surface"; "a station passes only with
  a dated Inbox line" → "only with a dated message of Guy's"; in the Take
  table, "`kinds/practice` assess script" → "`kinds/practice`, computed at
  read"; "`dashboard/views/campaign_map` and the shell's drawer" →
  "`dashboard/views/life` (view `campaign_map`) and its drawer, History
  only"; "`kinds/campaign` collect job rules" → "the evidence rule of
  `kinds/campaign` and the byte check in `add_note`".
- ARCHITECTURE, with the steps that build them: §3, `message` gains
  `sent_at` (Step 2); §5 and §6, nine functions → ten (Step 2); §7, the
  overview leaves life trackers to their own screen (Step 3).

## 10. How this plan was checked (2026-11-10)

All of the evidence is in the vault, `Golaiet/WIP/merge/`.

- **The data model, by running it.** A spike of the pure functions (the
  practice arithmetic, the campaign change and its checks, the board, the
  import) over the real `progress.md`, compared with the vault's own
  `derive()` for today, four later dates and five past ones. Every key of
  the board is equal except the differences this plan names: the trail's
  label text, the order of next, the `tasks` lane in quiet, overdue checks
  from the day they pass, and old timeline events that are not imported. It
  ran on plain dicts; the date boundary of §3.1 is the one thing it could
  not cover.
- **The conversation, against six weeks of real messages.** Each was
  classified and given its path through the tools. What had no path changed
  the design: the sent time, the title change, tasks as stations, the date
  of a pass, pausing instead of rewriting a subject. What still has none is
  not for Telegram: reading a vault document, work on a repository.
- **The port, file by file.** The vault shell and this dashboard were read
  in full; the Tailwind conflicts and the drawer's data needs in §3.3 come
  from that reading, not from a build.
- **Against the code, by a second reader set on finding faults.** Its
  findings are folded in: the replay measures only what it can, the cutover
  gate no longer waits on something this plan does not build, a pass carries
  its date, history does not depend on the agent tagging a station, the
  brief and the reply cannot share a session at once, and everything the
  vault's runs do today is listed, with what becomes of it, in the vault
  note that §6 points to. The hooks this plan
  leans on exist as described: `validate_state(state, previous)` returns
  what is stored (`agent/tools.py`), `Message.job_run` ties a row to the
  message (`chat/models.py`), a kind with no jobs is legal (`sync_jobs`),
  and the conversation has one session (`chat.Conversation.session_id`).

## 11. After this phase: the direction Guy stated (2026-11-11)

Conversations in Telegram will be many and wide, on any subject,
consultations included; the board grows from them on its own; and later
Golaiet takes on independent tasks. This phase is built so that none of the
three needs a second design:

- **Wide conversations** need nothing new. The reply flow already answers
  what no tracker covers, and §3.4 stops telling it to send analysis
  elsewhere.
- **A board that grows on its own** is the proposal rule of §3.2: the
  `proposed` state exists, the evidence rule ties a proposal to the message
  it came from, and the Friday brief is where proposals are kept or dropped.
- **The board is the memory.** What should outlive a conversation is a row:
  a fact on a tracker, a proposed station. A session then does not have to
  live forever. That is why session rotation is a small change when its
  signal comes (§4): a new session opens with the recent exchanges, which
  are already rows in `message`, and with nothing else. The decided rule on
  agent memory (D7: none beyond resumed sessions and briefs) holds.
- **Independent tasks** have a seam and no design. A job is a row, a flow
  builds a prompt and runs one session, and what it finds comes back as
  observations and a message; the Friday brief is the first job that speaks
  to Guy without being asked. What a task may do, with which tools and at
  what cost are decisions to make before any of it is built (ROADMAP,
  "After Phase 5").
