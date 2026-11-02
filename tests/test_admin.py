"""The admin as Guy's control board: open without a login on the Mac, trackers
written through the same job sync the agent uses, prompts readable per tracker."""
import pytest
from django.test import Client

from core.models import Tracker
from scheduler.models import Job


@pytest.fixture(autouse=True)
def plain_static(settings):
    """The admin's pages name their static files through whitenoise's manifest, which only a collectstatic writes."""
    settings.STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@pytest.mark.django_db
def test_the_admin_opens_without_a_login():
    assert "Site administration" in Client().get("/admin/").content.decode()
    assert "REPLY_SYSTEM_PROMPT" in Client().get("/admin/prompts/").content.decode()


@pytest.mark.django_db
def test_a_tracker_added_in_the_admin_gets_its_jobs_and_a_bad_subject_is_refused():
    client = Client()
    fields = {"slug": "ceg", "title": "Constellation", "kind": "stock", "subject": '{"ticker": "ceg", "good_below": 170}',
              "brief": "Nuclear baseload.", "status": "active", "view": "feed", "view_params": "{}", "cadence": "daily"}
    response = client.post("/admin/core/tracker/add/", fields)
    assert response.status_code == 302
    tracker = Tracker.objects.get(slug="ceg")
    assert tracker.subject == {"ticker": "CEG", "good_below": 170.0} and tracker.view == "price"
    assert Job.objects.get(name="collect:ceg").schedule == "0 7 * * *"

    refused = client.post("/admin/core/tracker/add/", {**fields, "slug": "bad", "subject": '{"ticker": "???", "good_below": 1}'})
    assert refused.status_code == 200 and "is not a ticker symbol" in refused.content.decode()
    assert not Tracker.objects.filter(slug="bad").exists()

    changed = client.post(f"/admin/core/tracker/{tracker.pk}/change/", {**fields, "cadence": "weekly", "brief": "Nuclear baseload, bought low."})
    assert changed.status_code == 302
    assert Job.objects.get(name="collect:ceg").schedule == "0 7 * * mon"
    assert Tracker.objects.get(slug="ceg").brief == "Nuclear baseload, bought low."

    page = client.get(f"/admin/core/tracker/{tracker.pk}/prompts/").content.decode()
    assert "collect:ceg · 0 7 * * mon" in page and "Golaiet's collector" in page and "Nuclear baseload, bought low." in page

    assert client.post(f"/admin/core/tracker/{tracker.pk}/delete/", {"post": "yes"}).status_code == 302
    assert not Tracker.objects.filter(slug="ceg").exists() and not Job.objects.filter(name="collect:ceg").exists()
