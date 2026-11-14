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

A practice that is first mentioned inside the replayed window is not in the
starting state: the case that expects it as a new tracker has to create it,
and the agent names it itself. The practice that case's run creates stands
for the expected one from then on.

The CLI keeps a transcript of every session in its state folder. The replay
gives it a temporary one and removes it at the end, so nothing of the
messages stays on disk outside the scratch database."""
import datetime
import json
import os
import shutil
import tempfile
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


def read_cases(path: Path) -> tuple[list[tuple[dict, datetime.datetime, str | None]], list[str]]:
    """The cases that can be compared, each with the time it was sent and the
    practice it should create, if any; and the ids of the rest. Everything
    that would stop a case halfway is refused here."""
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    zone = ZoneInfo(settings.TIME_ZONE)
    practices = {expected["tracker"] for case in cases for expected in effects(case, "event")}
    wrong, seen, compared = [], set(), []
    for case in cases:
        if case["id"] in seen:
            wrong.append(f"{case['id']}: the id repeats")
        seen.add(case["id"])
        if not effects(case, "event"):
            continue
        clock = case["sent"].get("time") or case["sent"].get("assumed_time")
        try:
            sent_at = datetime.datetime.fromisoformat(f"{case['sent']['date']}T{clock}").replace(tzinfo=zone)
        except ValueError:
            wrong.append(f"{case['id']}: `sent` needs a date and a time or an assumed_time that can be read, got "
                         f"{case['sent'].get('date')!r} {clock!r}")
            continue
        born = sorted({expected["tracker"] for expected in effects(case, "new_tracker")} & practices)
        if len(born) > 1:
            wrong.append(f"{case['id']}: it expects {len(born)} new practices, and which is which cannot be told")
        compared.append((case, sent_at, born[0] if born else None))
    if wrong:
        raise CommandError("no session was run: " + "; ".join(wrong))
    return compared, [case["id"] for case in cases if not effects(case, "event")]


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
        compared, unread = read_cases(options["cases"])
        # The credentials are the switch: nothing is sent. In the environment as well, because the tool
        # server is another process that reads `.env` for whatever the environment it is given lacks.
        settings.TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"] = ""
        call_command("seed_jobs", verbosity=0)
        state = tempfile.mkdtemp(prefix="golaiet-replay-")
        settings.CLAUDE_CONFIG_DIR = state
        try:
            missed = self.run_cases(compared, options["only"])
        finally:
            shutil.rmtree(state, ignore_errors=True)
        if unread:
            self.stdout.write(f"not run, to be read by hand: {', '.join(unread)}")
        if missed:
            raise CommandError(f"{missed} case(s) did not file what was expected")
        self.stdout.write("every event landed")

    def run_cases(self, compared: list[tuple[dict, datetime.datetime, str | None]], only: str | None) -> int:
        reply = Job.objects.get(name="reply")
        stands_for = {}   # the slug the agent gave a practice it created → the id the cases know it by
        missed = 0
        for case, sent_at, born in compared:
            if only and case["id"] != only:
                continue
            conversation = Conversation.objects.create(chat_id=f"replay-{case['id']}")
            message = Message.objects.create(conversation=conversation, direction=Message.Direction.IN,
                                             text=case["text"], sent_at=sent_at)
            run = execute_job(reply, message_id=message.pk)
            wanted = {(expected["tracker"], expected["date"]) for expected in effects(case, "event")}
            problems = []
            created = list(Tracker.objects.filter(kind="practice", created_by_message_id=message.pk))
            if born and len(created) != 1:
                problems.append(f"it should create one practice ({born}) and created {len(created)}")
            elif born:
                stands_for[created[0].slug] = born
            filed = Observation.objects.filter(job_run=run, tracker__kind="practice").select_related("tracker")
            got = {(stands_for.get(observation.tracker.slug, observation.tracker.slug), day.isoformat())
                   for observation in filed for day in practice.event_days([observation])}
            # A practice created with the day as its start counts from that day as it would from an event on it.
            got |= {(stands_for[tracker.slug], tracker.subject["started"]) for tracker in created
                    if tracker.slug in stands_for} & wanted
            if got != wanted:
                problems.append(f"wanted {sorted(wanted)}, filed {sorted(got)}")
            if run.status != "done":
                problems.append(f"the run ended {run.status}")
            answer = Message.objects.filter(job_run=run, direction=Message.Direction.OUT).first()
            missed += bool(problems)
            self.stdout.write(f"{'MISS' if problems else 'ok  '} {case['id']} sent {sent_at:%Y-%m-%d %H:%M} ${run.cost_usd or 0}")
            for problem in problems:
                self.stdout.write(f"     {problem}")
            self.stdout.write(f"     reply: {(answer.text if answer else run.summary)[:300]}")
        return missed
