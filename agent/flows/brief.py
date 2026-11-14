"""The Friday brief: a conversation that a job starts.

The prompt is built in code from the board and the week's rows; the session
is the conversation's own, resumed, so the questions it asks are in the same
session Guy's answers will land in. It runs with read-only tools and its
text goes out as an ordinary message.

It carries its own stopping rule, because the written brief it replaces went
unanswered for weeks while everything else went on: after three delivered
briefs in a row with no question taken up within 48 hours, the job switches
itself off and says so once. Whether a message took up a question is a
reading, so the session gives it, as one last line the flow strips before
sending. It reads from the rows and not from what it remembers: the prompt
carries the previous brief as it was delivered and Guy's messages of the 48
hours after it, so a session that was compacted, or whose own last brief was
lost on the way, judges the same text.

Each delivered brief gets one verdict. A run's summary starts with the brief
it judged (`judged=<message id> answered=<verdict>`), so a Friday whose brief
did not go out is not a second "no" for the brief before it. The switch-off
notice is not a brief, and after it the count starts again: when Guy enables
the job, only briefs delivered since then are counted."""
import datetime
import re
from zoneinfo import ZoneInfo

from django.conf import settings

from agent.flows import conversation_turn, outcome
from agent.prompts import REPLY_SYSTEM_PROMPT as SYSTEM_PROMPT
from agent.runner import ClaudeRunner
from chat import telegram
from chat.models import Conversation, Message
from core import kinds, life
from core.kinds import campaign, practice
from core.models import Tracker
from scheduler.models import JobRun

ALLOWED_TOOLS = ["mcp__golaiet__list_trackers", "mcp__golaiet__get_tracker", "mcp__golaiet__search_observations"]
TOOLS: list[str] = []
UNANSWERED_IN_A_ROW = 3
ANSWER_WITHIN = datetime.timedelta(hours=48)
# A line that is nothing but the verdict, wherever it stands and whatever the case, markup or
# punctuation around it: the model writes "**Answered:** No." as readily as the form it was asked
# for, and sometimes adds a line after it. A sentence of the brief that begins with the word is
# not one: the word must be followed by a separator and at most two words. Only a whole word is
# a verdict: "not sure" is not "no".
VERDICT = re.compile(r"^[\s*_`>#-]*answered[*_`]*\s*[:=-]+[\s*_`]*(\w+(?: \w+)?)?[\s*_`.!]*$\n?", re.I | re.M)
VERDICTS = ("yes", "no", "first")
JUDGED = re.compile(r"^judged=(\d+) answered=(\w+)")
SWITCHED_OFF = ("The Friday brief is switched off: three in a row went by with no question taken up. "
                "To bring it back, tick `enabled` on the job `brief` in the admin, under Jobs.")


def week_of(day: datetime.date) -> str:
    """The week as the rows have it, for the prompt."""
    board = life.board(day)
    since = day - datetime.timedelta(days=7)
    trackers = Tracker.objects.filter(kind__in=kinds.LIFE).exclude(status=Tracker.Status.ARCHIVED)
    passed = [f"- {item['campaign']}: {item['label']} ({item['date']})" for item in board["trail"]
              if datetime.date.fromisoformat(item["at"]) >= since]
    moved = []
    for tracker in trackers.filter(kind="practice"):
        days = sorted(event for event in practice.event_days(tracker.observations.all()) if event >= since)
        if days:
            moved.append(f"- {tracker.title}: reported on {', '.join(f'{event:%a %d}' for event in days)}")
    overdue = [f"- {item['title']}: check date {item['since']}" for item in board["burning"] if item["why"] == life.OVERDUE]
    if board["burning_more"]:
        overdue.append(f"- and {board['burning_more']} more burning items not listed here")
    proposals = []
    for tracker in trackers.filter(kind="campaign"):
        latest = tracker.assessments.order_by("-at").first()
        proposals += [f"- {tracker.title}: {station['label']}" for station in campaign.stations_of(latest.state if latest else {})
                      if station["state"] == "proposed"]
    parts = (("Passed this week", passed), ("Practices that moved this week", moved),
             ("Check dates that have gone by", overdue), ("Proposals still open, to keep or to drop", proposals))
    return "\n\n".join(f"{title}:\n" + ("\n".join(lines) or "- nothing") for title, lines in parts)


def prompt(day: datetime.date, previous: Message | None) -> str:
    """The prompt the next run would get."""
    if previous is None:
        before = "No brief was delivered before this one: end with the line ANSWERED: first"
    else:
        zone = ZoneInfo(settings.TIME_ZONE)
        replies = Message.objects.filter(
            conversation=previous.conversation, direction=Message.Direction.IN,
            sent_at__gt=previous.created_at, sent_at__lte=previous.created_at + ANSWER_WITHIN).order_by("sent_at")
        said = "\n".join(f"[{reply.sent_at.astimezone(zone):%A %H:%M}] {reply.text}" for reply in replies)
        before = (f"Your previous brief, as it was delivered on {previous.created_at.astimezone(zone):%A %Y-%m-%d %H:%M}:\n"
                  f"<<<\n{previous.text}\n>>>\n"
                  f"Guy's messages in the 48 hours after it:\n<<<\n{said or '(none)'}\n>>>\n"
                  "Judge from these two blocks alone, not from what you remember: if one of his messages took up one "
                  "of that brief's questions, end with the line ANSWERED: yes; if none did, ANSWERED: no")
    return (
        f"[Scheduled: the Friday brief, {day:%A %Y-%m-%d}, {settings.TIME_ZONE} time. Guy did not write this message.]\n"
        "Write Guy's weekly brief from the rows below; use the read tools if a line needs its detail. Keep it short "
        "enough for a phone: what passed, what moved, what is stuck, then at most three questions, numbered, each one "
        "answerable in a line. Ask about what only he can say: an overdue check to move or drop, a proposal to keep "
        "or drop, a lane with nothing recorded. Record nothing now; his answers will come as ordinary messages. "
        "Write in the language he writes to you in.\n\n"
        f"{week_of(day)}\n\n{before}. Write that line in English, exactly as given and alone on the last line, whatever "
        "language the brief is in: it is for the scheduler and is removed before he sees the brief."
    )


def run(job, run) -> dict:
    conversation = Conversation.objects.filter(chat_id=str(settings.TELEGRAM_CHAT_ID)).first()
    if conversation is None or not Tracker.objects.filter(kind__in=kinds.LIFE).exists():
        return {"summary": "skipped: no conversation or no life trackers yet"}
    sent = Message.objects.filter(job_run__job=job, direction=Message.Direction.OUT, telegram_message_id__isnull=False)
    switched_off = sent.filter(text=SWITCHED_OFF).order_by("-created_at").first()
    briefs = sent.exclude(text=SWITCHED_OFF)
    if switched_off:
        briefs = briefs.filter(created_at__gt=switched_off.created_at)
    recent = list(briefs.order_by("-created_at")[:UNANSWERED_IN_A_ROW])
    previous = recent[0] if recent else None
    with conversation_turn:
        conversation.refresh_from_db()
        result = ClaudeRunner(model=settings.CLAUDE_REPLY_MODEL).run(
            prompt(life.today(), previous), system_prompt=SYSTEM_PROMPT,
            allowed_tools=ALLOWED_TOOLS, tools=TOOLS, resume=conversation.session_id or None,
            env={"GOLAIET_JOB_RUN_ID": run.pk})
        if result.session_id:
            conversation.session_id = result.session_id
            conversation.save(update_fields=["session_id"])
    report = outcome(result, "")
    if report["failed"]:
        return report
    given = [(match.group(1) or "").lower() for match in VERDICT.finditer(result.text)]
    answered = given[-1] if given and given[-1] in VERDICTS else "unknown"
    written = VERDICT.sub("", result.text).strip()
    verdicts = {}
    earlier = JobRun.objects.filter(job=job, status=JobRun.Status.DONE).exclude(pk=run.pk).order_by("started_at")
    for summary in earlier.values_list("summary", flat=True):
        judged = JUDGED.match(summary)
        if judged:
            verdicts[int(judged.group(1))] = judged.group(2)
    if previous:
        verdicts[previous.pk] = answered
    switch_off = len(recent) == UNANSWERED_IN_A_ROW and all(verdicts.get(brief.pk) == "no" for brief in recent)
    if not written and not switch_off:
        return dict(report, failed=True, summary="the session gave a verdict and no brief; nothing was sent")
    text = SWITCHED_OFF if switch_off else written
    outgoing = Message.objects.create(conversation=conversation, direction=Message.Direction.OUT, text=text, job_run=run)
    outgoing.telegram_message_id = telegram.send(text, chat_id=conversation.chat_id)
    outgoing.save(update_fields=["telegram_message_id"])
    delivered = "delivered" if outgoing.telegram_message_id else "not delivered"
    if switch_off and not outgoing.telegram_message_id:
        # Off without a word would look like a brief that simply stopped coming: the job stays on
        # and the run fails, which is announced like any failed run.
        return dict(report, failed=True, summary="the switch-off notice did not send; the brief stays on")
    if switch_off:
        job.enabled = False
        job.save(update_fields=["enabled"])
    return dict(report, summary=f"judged={previous.pk if previous else 'none'} answered={answered} {delivered}"
                                f"{' and switched off' if switch_off else ''} · {text[:400]}")
