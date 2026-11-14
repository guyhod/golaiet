"""Replay real messages through the reply flow and compare what was filed.

    manage.py replay <cases.json>

Test tooling for the question the import cannot answer: given Guy's words
and the time he sent them, does the conversation file the right practice on
the right day? Each case is a message with its sent time and what it should
produce. Only a case that expects a practice event can be compared; the
others (a lane changed, a definition reworded) depend on the state at the
time, are not run, and are listed at the end to be read by hand. The cases
are real messages and stay in the vault; this command takes their path.

It runs one real session per compared case, each in a conversation of its
own so that no case answers with the earlier ones in mind, on a scratch
database imported up to the day before the first message, with Telegram
off. It refuses a database that has ever held a conversation, and it checks
every case before the first session is spent.

What is compared is each practice's event days before and after the case's
run: every expected day is there afterwards, every day the run added was
expected, and no day that was there is gone. A day an earlier case already
filed, reported again, is therefore no miss. An expected event may carry
`or`, other days that are as fair a reading of the message.

A practice that is first mentioned inside the replayed window is not in the
starting state: the case that expects it as a new tracker has to create it,
and the agent names it itself. The practice that case's run creates stands
for the expected one from then on, so that case is run even when it expects
no event. A later case on a practice that was never created is not
comparable, which is said and is not a miss.

A run that ends on the plan's usage limit says nothing about the model, and
every later run would end the same way: the replay stops there and counts
neither that case nor the ones after it.

`--list` reads the cases file and prints which cases would be run, which
only bear a practice and which are set aside. It runs no session and needs
no database.

Nothing a replayed session does may leave the scratch database: Telegram's
token and the vault's folder are emptied before the first run, so nothing
is sent and no note is written, and a replayed session has the tool
server's tools and no web tool.

The CLI keeps a transcript of every session in its state folder. The replay
gives it a temporary one and removes it at the end, so nothing of the
messages stays on disk outside the scratch database."""
import datetime
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from chat.models import Conversation, Message
from agent.flows import reply as reply_flow
from agent.runner import MCP_SERVER_NAME
from core.kinds import practice
from core.models import Observation, Tracker
from scheduler.dispatcher import execute_job
from scheduler.models import Job


def effects(case: dict, effect: str) -> list[dict]:
    return [expected for expected in case["expected"] if expected["effect"] == effect]


# What the replay reads of an expected effect, by effect. The other effects are not compared, and
# nothing is asked of them: an answer that should file nothing names no tracker at all.
NEEDS = {"event": ("tracker", "date"), "new_tracker": ("tracker",)}


@dataclass
class Case:
    id: str
    text: str
    sent_at: datetime.datetime
    events: list[tuple[str, set[str]]]   # (practice, the days that meet it: its date and any `or`)
    bears: str | None                    # the practice this case should create, by the id the cases know it by
    may_create: bool                     # it expects a new tracker of some kind, so a practice it creates is no surprise


def read_cases(path: Path) -> tuple[list[Case], list[str]]:
    """The cases that are run, and the ids of the rest. A case is run when it
    expects a practice event, or when it should create a practice that some
    case expects an event on. Everything that would stop a case halfway is
    refused here, in words that name the case."""
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    zone = ZoneInfo(settings.TIME_ZONE)
    wrong, seen = [], set()
    for position, case in enumerate(cases):
        name = case.get("id") or f"case {position + 1}"
        if not case.get("id"):
            wrong.append(f"{name}: it has no id")
        if name in seen:
            wrong.append(f"{name}: the id repeats")
        seen.add(name)
        if not isinstance(case.get("sent"), dict) or "text" not in case or not isinstance(case.get("expected"), list):
            wrong.append(f"{name}: a case needs `sent`, `text` and a list `expected`")
            continue
        for expected in case["expected"]:
            missing = [field for field in ("effect", *NEEDS.get(expected.get("effect"), ())) if not expected.get(field)]
            if missing:
                wrong.append(f"{name}: an expected effect has no {' and no '.join(missing)}")
            other_days = expected.get("or", [])
            if expected.get("effect") == "event" and not (
                    isinstance(other_days, list) and all(isinstance(day, str) for day in other_days)):
                wrong.append(f"{name}: `or` must be a list of days, got {other_days!r}")
    if wrong:
        raise CommandError("no session was run: " + "; ".join(wrong))
    practices = {expected["tracker"] for case in cases for expected in effects(case, "event")}
    run, unread = [], []
    for case in cases:
        born = sorted({expected["tracker"] for expected in effects(case, "new_tracker")} & practices)
        if not effects(case, "event") and not born:
            unread.append(case["id"])
            continue
        if len(born) > 1:
            wrong.append(f"{case['id']}: it expects {len(born)} new practices, and which is which cannot be told")
        clock = case["sent"].get("time") or case["sent"].get("assumed_time")
        try:
            sent_at = datetime.datetime.fromisoformat(f"{case['sent'].get('date')}T{clock}").replace(tzinfo=zone)
        except ValueError:
            wrong.append(f"{case['id']}: `sent` needs a date and a time or an assumed_time that can be read, got "
                         f"{case['sent'].get('date')!r} {clock!r}")
            continue
        run.append(Case(case["id"], case["text"], sent_at, bears=born[0] if born else None,
                        may_create=bool(effects(case, "new_tracker")),
                        events=[(expected["tracker"], {expected["date"], *expected.get("or", [])})
                                for expected in effects(case, "event")]))
    if wrong:
        raise CommandError("no session was run: " + "; ".join(wrong))
    return run, unread


def event_days(stands_for: dict[str, str]) -> set[tuple[str, str]]:
    """Every practice's event days as they stand, under the ids the cases use."""
    return {(stands_for.get(tracker.slug, tracker.slug), day.isoformat())
            for tracker in Tracker.objects.filter(kind="practice")
            for day in practice.event_days(tracker.observations.all())}


class Command(BaseCommand):
    help = "Feed recorded messages through the reply flow on a scratch database and compare the practice events filed."

    def add_arguments(self, parser):
        parser.add_argument("cases", type=Path)
        parser.add_argument("--only", help="run one case, by id")
        parser.add_argument("--list", action="store_true", help="print which cases would be run and which are set aside; no session, no database")

    def handle(self, *args, **options):
        if options["list"]:
            cases, unread = read_cases(options["cases"])
            for title, ids in (("run and compared", [case.id for case in cases if case.events]),
                               ("run only to bear a practice", [case.id for case in cases if not case.events]),
                               ("set aside, to be read by hand", unread)):
                self.stdout.write(f"{title} ({len(ids)}): {', '.join(ids) or 'none'}")
            return
        if Message.objects.exists():
            raise CommandError("this database holds a conversation: the replay runs on a scratch database only")
        if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            raise CommandError("the replay gives the CLI an empty state folder, so the login must come from "
                               "CLAUDE_CODE_OAUTH_TOKEN; it is not set, and a login kept in the state folder would be left behind")
        cases, unread = read_cases(options["cases"])
        if options["only"]:
            bearer = {case.bears: case.id for case in cases if case.bears}
            cases = [case for case in cases if case.id == options["only"]]
            if not cases:
                raise CommandError(f"--only {options['only']}: no case of that id is one the replay runs")
            first = sorted({bearer[slug] for slug, _ in cases[0].events if slug in bearer} - {cases[0].id})
            if first:
                raise CommandError(f"--only {options['only']}: it reports on a practice that {', '.join(first)} creates; "
                                   "run without --only")
        # The credentials are the switch: nothing is sent. In the environment as well, because the tool
        # server is another process that reads `.env` for whatever the environment it is given lacks.
        settings.TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"] = ""
        # Some of the messages ask for a note, and a note is written under the vault's folder: with
        # none, the tool says that notes are switched off and nothing is written.
        settings.VAULT_DIR = os.environ["VAULT_DIR"] = ""
        # No web tools either: the messages are private and the comparison needs none, so a replayed
        # session has the tool server's tools and no built-in one.
        reply_flow.ALLOWED_TOOLS, reply_flow.TOOLS = [f"mcp__{MCP_SERVER_NAME}__*"], []
        call_command("seed_jobs", verbosity=0)
        state = tempfile.mkdtemp(prefix="golaiet-replay-")
        settings.CLAUDE_CONFIG_DIR = state
        try:
            missed, left, judged = self.run_cases(cases)
        finally:
            shutil.rmtree(state, ignore_errors=True)
        if unread:
            self.stdout.write(f"not run, to be read by hand: {', '.join(unread)}")
        landed = (f"{missed} case(s) did not file what was expected" if missed else "every event landed") + (
            f" in the cases that could be compared; {left} could not" if left and not missed else "")
        if judged < len(cases):
            raise CommandError(f"stopped at the plan's usage limit on {cases[judged].id}, which is not counted; "
                               f"the last case judged was {cases[judged - 1].id if judged else 'none'}; "
                               f"not run: {', '.join(case.id for case in cases[judged + 1:]) or 'none'}. Before it: {landed}")
        if missed:
            raise CommandError(landed)
        self.stdout.write(landed)

    def run_cases(self, cases: list[Case]) -> tuple[int, int, int]:
        """(cases that missed, cases that could not be compared, how many cases were judged: fewer
        than all of them when a run ended on the plan's usage limit)."""
        reply = Job.objects.get(name="reply")
        # Guy's standing conventions, as the import left them on his conversation's row.
        conventions = Conversation.objects.filter(chat_id=str(settings.TELEGRAM_CHAT_ID)).values_list("conventions", flat=True).first() or ""
        if not conventions.strip():
            self.stdout.write("the conversation's row has no conventions: the cases run without them")
        to_be_born = {case.bears for case in cases if case.bears}
        stands_for = {}   # the slug the agent gave a practice it created → the id the cases know it by
        missed = left = 0
        for judged, case in enumerate(cases):
            unborn = sorted({slug for slug, _ in case.events if slug in to_be_born} - set(stands_for.values()) - {case.bears})
            if unborn:
                left += 1
                self.stdout.write(f"n/c  {case.id} not comparable: {', '.join(unborn)} was never created by the case that should have")
                continue
            conversation = Conversation.objects.create(chat_id=f"replay-{case.id}", conventions=conventions)
            message = Message.objects.create(conversation=conversation, direction=Message.Direction.IN,
                                             text=case.text, sent_at=case.sent_at)
            before = event_days(stands_for)
            run = execute_job(reply, message_id=message.pk)
            if run.status == "failed" and run.summary.startswith("billing: "):
                return missed, left, judged
            problems = []
            created = list(Tracker.objects.filter(kind="practice", created_by_message_id=message.pk))
            if case.bears and len(created) != 1:
                problems.append(f"it should create one practice ({case.bears}) and created {len(created)}")
            elif case.bears:
                stands_for[created[0].slug] = case.bears
            elif created and not case.may_create:
                problems.append(f"it created a practice ({', '.join(tracker.slug for tracker in created)}), which was not expected")
            after = event_days(stands_for)
            # A red practice created with a start in the past was told of that day: the start is the
            # report. A start on the day the message was sent is only the default, and proves nothing.
            # On a green practice a start is the beginning of a streak, not the report of an event.
            told = {(case.bears, tracker.subject["started"]) for tracker in created
                    if tracker.slug in stands_for and tracker.subject["color"] == "red"
                    and tracker.subject["started"] < case.sent_at.date().isoformat()}
            for slug, fair in case.events:
                if not any((slug, day) in after | told for day in fair):
                    problems.append(f"wanted {slug} on {' or '.join(sorted(fair))}; its days are now "
                                    f"{sorted(day for name, day in after if name == slug) or 'none'}")
            for slug, day in sorted(after - before):
                if not any(slug == wanted and day in fair for wanted, fair in case.events):
                    problems.append(f"added {slug} on {day}, which was not expected")
            for slug, day in sorted(before - after):
                problems.append(f"removed {slug} on {day}, which was there before the run")
            if run.status != "done":
                problems.append(f"the run ended {run.status}")
            answer = Message.objects.filter(job_run=run, direction=Message.Direction.OUT).first()
            missed += bool(problems)
            self.stdout.write(f"{'MISS' if problems else 'ok  '} {case.id} sent {case.sent_at:%Y-%m-%d %H:%M} ${run.cost_usd or 0}")
            for problem in problems:
                self.stdout.write(f"     {problem}")
            self.stdout.write(f"     reply: {(answer.text if answer else run.summary)[:300]}")
        return missed, left, len(cases)
