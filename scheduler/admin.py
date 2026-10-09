from django.contrib import admin

from .models import Job, JobRun


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "tracker", "enabled", "trigger", "schedule", "next_run_time", "last_run", "last_status")
    list_filter = ("kind", "enabled", "trigger")
    search_fields = ("name",)


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ("job", "started_at", "finished_at", "status", "cost_usd", "summary_short")
    list_filter = ("status", "job")
    readonly_fields = ("job", "started_at", "finished_at", "status", "summary", "log", "cost_usd", "session_id")

    @admin.display(description="summary")
    def summary_short(self, run):
        return run.summary[:80]
