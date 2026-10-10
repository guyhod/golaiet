"""What Guy tracks and what was seen about it.

A Tracker is data, not code: asking Golaiet to track something creates a row
and schedules jobs. Only a new *kind* (payload shape, view, levels) is a code
change (core/kinds). Observations are facts with a source and a date, never
edited. Assessments are judgments about them, append-only. An Alert is an
assessment pushed to Guy. Focus is the one row that says what the dashboard
shows."""
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


class Assessment(models.Model):
    """A dated judgment about one tracker, append-only. The state's shape is
    the kind's (topic: a level and an optional score); the reason is the
    agent's text; the evidence is the observations it relied on. What the
    judgment cost and which model made it live on the job run, not here."""

    tracker = models.ForeignKey(Tracker, on_delete=models.CASCADE, related_name="assessments")
    at = models.DateTimeField(auto_now_add=True)
    state = models.JSONField(default=dict, help_text="Validated against the tracker kind's state schema.")
    reason = models.TextField()
    evidence = models.ManyToManyField(Observation, blank=True, related_name="assessments")
    job_run = models.ForeignKey("scheduler.JobRun", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="assessments")

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.tracker.slug} @ {self.at:%Y-%m-%d}: {self.level}"

    @property
    def level(self) -> str:
        return str(self.state.get("level", ""))


class Alert(models.Model):
    """Something pushed to Guy about a tracker: the kind's rule raises one when
    an assessment changes the level; the agent raises one itself with
    raise_alert. The flow delivers it to Telegram after the session has
    exited; the tool server never sends. The latest alert of a tracker is the
    open one, so another at the same level is not raised until the level
    changes."""

    tracker = models.ForeignKey(Tracker, on_delete=models.CASCADE, related_name="alerts")
    assessment = models.ForeignKey(Assessment, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts")
    level = models.CharField(max_length=30)
    text = models.TextField()
    job_run = models.ForeignKey("scheduler.JobRun", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="alerts")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tracker.slug} {self.level}: {self.text[:60]}"


class Focus(models.Model):
    """What the dashboard shows right now: one row. A null tracker is the
    overview of every tracker; otherwise the tracker's own view. Written by
    set_focus from a conversation, read by GET /api/focus and its stream."""

    SINGLETON_PK = 1
    OVERVIEW = "overview"

    tracker = models.ForeignKey(Tracker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    view = models.CharField(max_length=30, default=OVERVIEW)
    view_params = models.JSONField(default=dict, blank=True)
    set_at = models.DateTimeField(auto_now=True)
    set_by_message = models.ForeignKey("chat.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                       help_text="The Telegram message that asked for this focus.")
    note = models.TextField(blank=True, help_text="One line shown on screen with the focus, e.g. what Guy asked.")

    class Meta:
        verbose_name_plural = "focus"

    def __str__(self):
        return f"focus: {self.tracker.slug if self.tracker else self.OVERVIEW}"

    @classmethod
    def current(cls) -> "Focus":
        focus, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return focus
