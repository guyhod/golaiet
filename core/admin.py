from django.contrib import admin

from .models import Alert, Assessment, Focus, Observation, Tracker


@admin.register(Tracker)
class TrackerAdmin(admin.ModelAdmin):
    list_display = ("slug", "title", "kind", "status", "view", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("slug", "title", "brief")


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
