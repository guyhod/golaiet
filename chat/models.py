"""The Telegram side: one Conversation per chat, every Message in and out.
The conversation row carries the Claude session id, so the agent resumes
where the thread left off."""
from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    channel = models.CharField(max_length=20, default="telegram")
    chat_id = models.CharField(max_length=64, unique=True)
    session_id = models.CharField(max_length=64, blank=True, help_text="Claude CLI session for --resume.")
    # Guy's own rules for every report.
    # A row and not prompt text: they are his to edit, and a practice the agent creates in
    # conversation has no brief of its own to carry them yet.
    conventions = models.TextField(blank=True, default="", help_text="Standing rules for every report, one per line. "
                                   "Every reply reads them, under the line that says when the message was sent.")
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.channel}:{self.chat_id}"


class Message(models.Model):
    class Direction(models.TextChoices):
        IN = "in"
        OUT = "out"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    text = models.TextField()
    # When Guy sent it, by Telegram's clock (for a forwarded message, when the original was sent).
    # Not created_at: after an outage every queued message is stored in the minute the stack came
    # back, and a report of "this morning" would be dated to that minute.
    sent_at = models.DateTimeField(default=timezone.now)
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    # The poller resumes from the highest update id it has stored, so a restart
    # never re-reads an update and never skips one. The field is the offset.
    telegram_update_id = models.BigIntegerField(null=True, blank=True, unique=True)
    job_run = models.ForeignKey("scheduler.JobRun", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="messages", help_text="The run that produced (out) or handled (in) it.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.direction} {self.created_at:%Y-%m-%d %H:%M}: {self.text[:60]}"
