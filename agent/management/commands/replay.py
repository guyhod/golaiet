"""Replay real messages through the reply flow and compare what was filed.

    manage.py replay <cases.json>

Test tooling for the question the import cannot answer: given Guy's words
and the time he sent them, does the conversation file the right practice on
the right day? Each case is a message with its sent time and the practice
events it should produce. The cases are real messages and stay in the vault;
this command takes their path.

It runs one real session per case, on a scratch database imported up to the
day before the first message, with Telegram off. It refuses a database that
has ever held a conversation."""
import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from chat.models import Conversation, Message
from core.kinds import practice
from core.models import Observation
from scheduler.dispatcher import execute_job
from scheduler.models import Job


class Command(BaseCommand):
    help = "Feed recorded messages through the reply flow on a scratch database and compare the practice events filed."

    def add_arguments(self, parser):
        parser.add_argument("cases", type=Path)
        parser.add_argument("--only", help="run one case, by id")

    def handle(self, *args, **options):
        if Message.objects.exists():
            raise CommandError("this database holds a conversation: the replay runs on a scratch database only")
        settings.TELEGRAM_BOT_TOKEN = ""   # the credentials are the switch: nothing is sent
        call_command("seed_jobs", verbosity=0)
        reply = Job.objects.get(name="reply")
        conversation = Conversation.objects.create(chat_id="replay")
        zone = ZoneInfo(settings.TIME_ZONE)
        cases = json.loads(options["cases"].read_text(encoding="utf-8"))["cases"]
        missed = 0
        for case in cases:
            if options["only"] and case["id"] != options["only"]:
                continue
            sent = case["sent"]
            sent_at = datetime.datetime.fromisoformat(f"{sent['date']}T{sent.get('time') or sent.get('assumed_time')}").replace(tzinfo=zone)
            message = Message.objects.create(conversation=conversation, direction=Message.Direction.IN,
                                             text=case["text"], sent_at=sent_at)
            run = execute_job(reply, message_id=message.pk)
            filed = Observation.objects.filter(job_run=run, tracker__kind="practice").select_related("tracker")
            got = {(observation.tracker.slug, day.isoformat())
                   for observation in filed for day in practice.event_days([observation])}
            wanted = {(effect["tracker"], effect["date"]) for effect in case["expected"] if effect["effect"] == "event"}
            answer = Message.objects.filter(job_run=run, direction=Message.Direction.OUT).first()
            verdict = "ok  " if got == wanted and run.status == "done" else "MISS"
            missed += verdict == "MISS"
            self.stdout.write(f"{verdict} {case['id']} sent {sent_at:%Y-%m-%d %H:%M} ${run.cost_usd or 0}")
            if verdict == "MISS":
                self.stdout.write(f"     wanted {sorted(wanted)}\n     filed  {sorted(got)}")
            self.stdout.write(f"     reply: {(answer.text if answer else run.summary)[:300]}")
        if missed:
            raise CommandError(f"{missed} case(s) did not file what was expected")
