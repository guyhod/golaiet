"""One Telegram message in, one reply out. Executed off-schedule by the poller
through the `reply` job, so every exchange has a JobRun with its cost."""
import logging

from chat import alerts, telegram
from chat.models import Message
from agent.prompts import REPLY_SYSTEM_PROMPT
from agent.runner import ClaudeRunner

log = logging.getLogger(__name__)

ALLOWED_TOOLS = ["mcp__golaiet__*", "WebSearch", "WebFetch"]
# Built-in tools the session has at all. Everything else (Bash, file edits…)
# is left out of the session's context, not merely denied.
TOOLS = ["WebSearch", "WebFetch"]

FAILURE_REPLY = "⚠️ I couldn't answer that: {reason}"


def run(job, run, *, message_id: int) -> dict:
    message = Message.objects.select_related("conversation").get(pk=message_id)
    conversation = message.conversation
    message.job_run = run
    message.save(update_fields=["job_run"])

    result = ClaudeRunner().run(
        message.text, system_prompt=REPLY_SYSTEM_PROMPT, allowed_tools=ALLOWED_TOOLS, tools=TOOLS,
        resume=conversation.session_id or None,
        env={"GOLAIET_JOB_RUN_ID": run.pk, "GOLAIET_MESSAGE_ID": message.pk},
    )
    if result.session_id:
        conversation.session_id = result.session_id
        conversation.save(update_fields=["session_id"])

    failed = result.is_error or result.is_billing_abort
    reply_text = FAILURE_REPLY.format(reason=result.text[:300]) if failed else result.text
    outgoing = Message.objects.create(conversation=conversation, direction=Message.Direction.OUT,
                                      text=reply_text, job_run=run)
    outgoing.telegram_message_id = telegram.send(reply_text, chat_id=conversation.chat_id)
    outgoing.save(update_fields=["telegram_message_id"])
    alerts.deliver(run)
    return {
        "summary": ("billing: " if result.is_billing_abort else "error: " if failed else "") + result.text[:500],
        "cost_usd": result.cost_usd, "session_id": result.session_id, "failed": failed,
    }
