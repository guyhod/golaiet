"""The admin is Guy's control board (2026-11-02): trackers are added, edited
and removed here as well as from Telegram, jobs and their runs are read and
rescheduled here, and every tracker has a page with the prompts its next runs
would get. Writes go through the same functions the agent's tools use."""
from importlib import import_module

from django import forms
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from agent import tools
from . import kinds
from .models import Alert, Assessment, Focus, Observation, Tracker


class TrackerForm(forms.ModelForm):
    cadence = forms.ChoiceField(
        choices=[(word, word) for word in kinds.CADENCES], initial="daily",
        help_text="How often its sessions run. A kind's fixed schedules (a country's desk, a topic's Monday judge) stay.")

    class Meta:
        model = Tracker
        fields = ("slug", "title", "kind", "subject", "brief", "status", "view", "view_params", "cadence")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["cadence"].initial = tools.cadence_of(self.instance) or "weekly"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") and cleaned.get("subject") is not None:
            try:
                cleaned["subject"] = kinds.get(cleaned["kind"]).validate_subject(cleaned["subject"])
            except ValueError as problem:
                self.add_error("subject", str(problem))
        return cleaned


@admin.register(Tracker)
class TrackerAdmin(admin.ModelAdmin):
    form = TrackerForm
    list_display = ("slug", "title", "kind", "status", "view", "created_at", "prompts")
    list_filter = ("kind", "status")
    search_fields = ("slug", "title", "brief")

    def get_changeform_initial_data(self, request):
        return {"view": "feed"}

    def save_model(self, request, tracker, form, change):
        if not change:
            tracker.view = kinds.get(tracker.kind).VIEW
        tracker.save()
        tools.sync_jobs(tracker, form.cleaned_data["cadence"])

    @admin.display(description="prompts")
    def prompts(self, tracker):
        return format_html('<a href="{}">next runs</a>', reverse("admin:core_tracker_prompts", args=[tracker.pk]))

    def get_urls(self):
        return [path("<path:object_id>/prompts/", self.admin_site.admin_view(self.prompts_page), name="core_tracker_prompts")] + super().get_urls()

    def prompts_page(self, request, object_id):
        """Every job of the tracker with its flow's system prompt and the prompt the next run would get, as text."""
        tracker = get_object_or_404(Tracker, pk=object_id)
        parts = []
        for job in tracker.jobs.order_by("name"):
            flow = import_module(job.target.rsplit(".", 1)[0])
            rendered = flow.prompt(tracker) or "(nothing to judge: no observation filed since the last judgment)"
            parts.append(f"{'=' * 100}\n{job.name} · {job.schedule} · {job.target}\n{'=' * 100}\n\n"
                         f"--- system prompt ---\n{flow.SYSTEM_PROMPT}\n\n--- prompt of the next run ---\n{rendered}")
        return HttpResponse("\n\n\n".join(parts) or "no jobs", content_type="text/plain; charset=utf-8")


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ("tracker", "observed_at", "summary_short", "source_url", "job_run")
    list_filter = ("tracker",)
    search_fields = ("summary", "source_url")
    date_hierarchy = "observed_at"

    @admin.display(description="summary")
    def summary_short(self, observation):
        return observation.summary[:100]


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("tracker", "at", "level", "reason_short", "job_run")
    list_filter = ("tracker",)
    search_fields = ("reason",)
    filter_horizontal = ("evidence",)

    @admin.display(description="reason")
    def reason_short(self, assessment):
        return assessment.reason[:100]


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("tracker", "level", "text_short", "created_at", "delivered_at", "delivery_error")
    list_filter = ("tracker", "level")

    @admin.display(description="text")
    def text_short(self, alert):
        return alert.text[:100]


@admin.register(Focus)
class FocusAdmin(admin.ModelAdmin):
    list_display = ("tracker", "view", "set_at", "set_by_message", "note")
