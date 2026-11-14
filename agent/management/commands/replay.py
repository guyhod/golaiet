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
run: every expected day is there afterwards, and every day the run added
was expected. A day an earlier case already filed, reported again, is
therefore no miss. An expected event may carry `or`, other days that are as
fair a reading of the message.

A practice that is first mentioned inside the replayed window is not in the
starting state: the case that expects it as a new tracker has to create it,
and the agent names it itself. The practice that case's run creates stands
for the expected one from then on, so that case is run even when it expects
no event. A later case on a practice that was never created is not
comparable, which is said and is not a miss.

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
from core.kinds import practice
from core.models import Observation, Tracker
from scheduler.dispatcher import execute_job
from scheduler.models import Job


def effects(case: dict, effect: str) -> list[dict]:
    return [expected for expected in case["expected"] if expected["effect"] == effect]


@dataclass
class Case:
    id: str
    text: str
    sent_at: datetime.datetime
    events: list[tuple[str, set[str]]]   # (practice, the days that meet it: its date and any `or`)
    bears: str | None                    # the practice this case should create, by the id the cases know it by


def read_cases(path: Path) -> tuple[list[Case], list[str]]:
    """The cases that are run, and the ids of the rest. A case is run when it
    expects a practice event, or when it should create a practice that some
    case expects an event on. Everything that would stop a case halfway is
    refused here, in words that name the case."""
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    zone = ZoneInfo(settings.TIME_ZONE)
    wrong, seen = [], set()
    for position, case in enumerate(cases):
        name = case.get("id") or f"case {position + 1} (it has no id)"
        if name in seen:
            wrong.append(f"{name}: the id repeats")
        seen.add(name)
        if not isinstance(case.get("sent"), dict) or "text" not in case or not isinstance(case.get("expected"), list):
            wrong.append(f"{name}: a case needs `sent`, `text` and a list `expected`")
            continue
        for expected in case["expected"]:
            missing = [field for field in ("effect", "tracker") if not expected.get(field)]
            if expected.get("effect") == "event" and not expected.get("date"):
                missing.append("date")
            if missing:
                wrong.append(f"{name}: an expected effect has no {' and no '.join(missing)}")
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

    def handle(self, *args, **options):
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
                                   "run the cases together, or that one first")
        # The credentials are the switch: nothing is sent. In the environment as well, because the tool
        # server is another process that reads `.env` for whatever the environment it is given lacks.
        settings.TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"] = ""
        call_command("seed_jobs", verbosity=0)
        state = tempfile.mkdtemp(prefix="golaiet-replay-")
        settings.CLAUDE_CONFIG_DIR = state
        try:
            missed, left = self.run_cases(cases)
        finally:
            shutil.rmtree(state, ignore_errors=True)
        if unread:
            self.stdout.write(f"not run, to be read by hand: {', '.join(unread)}")
        if missed:
            raise CommandError(f"{missed} case(s) did not file what was expected")
        self.stdout.write("every event landed" + (f" in the cases that could be compared; {left} could not" if left else ""))

    def run_cases(self, cases: list[Case]) -> tuple[int, int]:
        """(cases that missed, cases that could not be compared)."""
        reply = Job.objects.get(name="reply")
        # Guy's standing conventions, as the import left them on his conversation's row.
        conventions = Conversation.objects.filter(chat_id=str(settings.TELEGRAM_CHAT_ID)).values_list("conventions", flat=True).first() or ""
        to_be_born = {case.bears for case in cases if case.bears}
        stands_for = {}   # the slug the agent gave a practice it created → the id the cases know it by
        missed = left = 0
        for case in cases:
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
            problems = []
            created = list(Tracker.objects.filter(kind="practice", created_by_message_id=message.pk))
            if case.bears and len(created) != 1:
                problems.append(f"it should create one practice ({case.bears}) and created {len(created)}")
            elif case.bears:
                stands_for[created[0].slug] = case.bears
            after = event_days(stands_for)
            # A practice created with a start in the past was told of that day: the start is the report.
            # A start on the day the message was sent is only the default, and proves nothing.
            told = {(case.bears, tracker.subject["started"]) for tracker in created
                    if tracker.slug in stands_for and tracker.subject["started"] < case.sent_at.date().isoformat()}
            for slug, fair in case.events:
                if not any((slug, day) in after | told for day in fair):
                    problems.append(f"wanted {slug} on {' or '.join(sorted(fair))}; its days are now "
                                    f"{sorted(day for name, day in after if name == slug) or 'none'}")
            for slug, day in sorted(after - before):
                if not any(slug == wanted and day in fair for wanted, fair in case.events):
                    problems.append(f"added {slug} on {day}, which was not expected")
            if run.status != "done":
                problems.append(f"the run ended {run.status}")
            answer = Message.objects.filter(job_run=run, direction=Message.Direction.OUT).first()
            missed += bool(problems)
            self.stdout.write(f"{'MISS' if problems else 'ok  '} {case.id} sent {case.sent_at:%Y-%m-%d %H:%M} ${run.cost_usd or 0}")
            for problem in problems:
                self.stdout.write(f"     {problem}")
            self.stdout.write(f"     reply: {(answer.text if answer else run.summary)[:300]}")
        return missed, left
