"""The schedule as rows. Job rows are the single source of truth for what
recurs; the scheduler process derives APScheduler jobs from them every 30 s,
so editing a job in admin takes effect live. JobRun is the run log, the cost
ledger and the heartbeat: no run in N minutes is itself the alarm."""
from django.db import models


class Job(models.Model):
    class Kind(models.TextChoices):
        REPLY = "reply"          # answer a Telegram message; executed off-schedule per message
        COLLECT = "collect"      # a tracker's collector
        ASSESS = "assess"        # a tracker's judge (next phase)
        DIGEST = "digest"        # cross-tracker summary (later phase)
        HEARTBEAT = "heartbeat"  # liveness record

    class Trigger(models.TextChoices):
        INTERVAL = "interval"
        CRON = "cron"
        MANUAL = "manual"        # never scheduled; executed off-schedule by code (the reply job, per message)

    name = models.CharField(max_length=200, unique=True, help_text="e.g. collect:vram-supply, heartbeat")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    tracker = models.ForeignKey("core.Tracker", null=True, blank=True, on_delete=models.CASCADE, related_name="jobs")
    enabled = models.BooleanField(default=True)
    trigger = models.CharField(max_length=10, choices=Trigger.choices, default=Trigger.CRON)
    schedule = models.CharField(
        max_length=100,
        blank=True,
        help_text="interval: seconds (e.g. 1800) · cron: 'm h dom mon dow' in the Django time zone (e.g. '0 7 * * mon') · manual: empty")
    target = models.CharField(max_length=300, help_text="Dotted path to a callable: run(job, **params)")
    params = models.JSONField(default=dict, blank=True)
    misfire_grace_sec = models.PositiveIntegerField(
        default=300, help_text="How late a missed run may still fire (e.g. after the Mac slept). Missed runs coalesce into one.")
    next_run_time = models.DateTimeField(null=True, blank=True,
                                         help_text="Written back by the scheduler process after each sync.")
    last_run = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class JobRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"
        SKIPPED = "skipped"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    summary = models.TextField(blank=True)
    log = models.TextField(blank=True)
    cost_usd = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True,
                                   help_text="The CLI's estimate. Under plan auth nothing is billed per token; it is telemetry.")
    session_id = models.CharField(max_length=64, blank=True, help_text="The Claude session this run used, if any.")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.job.name} @ {self.started_at:%Y-%m-%d %H:%M} · {self.status}"
