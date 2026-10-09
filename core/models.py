"""What Guy tracks and what was seen about it.

A Tracker is data, not code: asking Golaiet to track something creates a row
and schedules jobs. Only a new *kind* (payload shape, view) is a code change
(core/kinds). Observations are facts with a source and a date, never edited;
judgments (assessments) come in the next phase as their own table."""
from django.db import models

from . import kinds


class Tracker(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        PAUSED = "paused"
        ARCHIVED = "archived"

    slug = models.SlugField(unique=True, help_text="e.g. vram-supply, israel, ceg")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=30, choices=kinds.choices(),
                            help_text="Selects the payload schema, the collect prompt and the default view.")
    subject = models.JSONField(default=dict, blank=True,
                               help_text="What is tracked, shaped by the kind: {query}, {iso3}, {ticker, good_below}…")
    brief = models.TextField(
        help_text="Standing instructions for collecting and judging this tracker. Rendered into every "
                  "prompt; editable here. The thesis lives in text, never in code.")
    view = models.CharField(max_length=30, default="feed")
    view_params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_by_message = models.ForeignKey(
        "chat.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_trackers",
        help_text="The Telegram message that asked for this tracker.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self):
        return f"{self.kind}/{self.slug}"


class Observation(models.Model):
    """A dated fact about one tracker. source_url is unique per tracker so a
    re-run cannot file the same page twice; an observation without a URL (a
    price tick, a dictated line) is allowed and not deduplicated here."""

    tracker = models.ForeignKey(Tracker, on_delete=models.CASCADE, related_name="observations")
    observed_at = models.DateTimeField(help_text="When the fact happened or was published, not when it was filed.")
    source_url = models.URLField(max_length=1000, blank=True)
    summary = models.TextField(help_text="One or two sentences, in the agent's words, with the figure if there is one.")
    payload = models.JSONField(default=dict, blank=True,
                               help_text="Structured fields, validated against the tracker kind's schema.")
    job_run = models.ForeignKey("scheduler.JobRun", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="observations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at"]
        constraints = [
            models.UniqueConstraint(fields=["tracker", "source_url"], condition=~models.Q(source_url=""),
                                    name="one_observation_per_tracker_source"),
        ]

    def __str__(self):
        return f"{self.tracker.slug} @ {self.observed_at:%Y-%m-%d}: {self.summary[:60]}"
