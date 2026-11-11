"""One Telegram message in, one reply out. Executed off-schedule by the poller
through the `reply` job, so every exchange has a JobRun with its cost."""
import logging
from zoneinfo import ZoneInfo

from django.conf import settings

from chat import alerts, telegram
from chat.models import Message
from agent.flows import conversation_turn, outcome
from agent.prompts import REPLY_SYSTEM_PROMPT as SYSTEM_PROMPT
from agent.runner import ClaudeRunner

log = logging.getLogger(__name__)

ALLOWED_TOOLS = ["mcp__golaiet__*", "WebSearch", "WebFetch"]
# Built-in tools the session has at all. Everything else (Bash, file edits…)
# is left out of the session's context, not merely denied.
TOOLS = ["WebSearch", "WebFetch"]

FAILURE_REPLY = "⚠️ I couldn't answer that: {reason}"


def prompt(message: Message) -> str:
    """The message under one line that says when it was sent. The containers
    run on UTC and the model has no clock, so "today" and "last night" are
    counted from this line, never from now."""
    sent = message.sent_at.astimezone(ZoneInfo(settings.TIME_ZONE))
    return f"[Sent {sent:%A %Y-%m-%d %H:%M}, Jerusalem time]\n{message.text}"


def run(job, run, *, message_id: int) -> dict:
    message = Message.objects.select_related("conversation").get(pk=message_id)
    conversation = message.conversation
    message.job_run = run
    message.save(update_fields=["job_run"])

    with conversation_turn:
        conversation.refresh_from_db()
        result = ClaudeRunner(model=settings.CLAUDE_REPLY_MODEL).run(
            prompt(message), system_prompt=SYSTEM_PROMPT, allowed_tools=ALLOWED_TOOLS, tools=TOOLS,
            resume=conversation.session_id or None,
            env={"GOLAIET_JOB_RUN_ID": run.pk, "GOLAIET_MESSAGE_ID": message.pk},
        )
        if result.session_id:
            conversation.session_id = result.session_id
            conversation.save(update_fields=["session_id"])

    report = outcome(result, "")
    reply_text = FAILURE_REPLY.format(reason=result.text[:300]) if report["failed"] else result.text
    outgoing = Message.objects.create(conversation=conversation, direction=Message.Direction.OUT,
                                      text=reply_text, job_run=run)
    outgoing.telegram_message_id = telegram.send(reply_text, chat_id=conversation.chat_id)
    outgoing.save(update_fields=["telegram_message_id"])
    alerts.deliver(run)
    return report
