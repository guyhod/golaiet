from django.contrib import admin

from .models import Observation, Tracker


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
