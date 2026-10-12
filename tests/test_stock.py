from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from agent import tools
from chat import alerts
from core.kinds import stock
from core.models import Tracker
from scheduler.dispatcher import execute_job
from scheduler.models import Job
from scheduler.scripts import prices


@pytest.fixture
def ceg(db):
    return tools.create_tracker("ceg", "Constellation Energy", "stock", {"ticker": " ceg ", "good_below": 170},
                                "Nuclear baseload for data centres; buy only at a discount.", "daily")


@pytest.fixture
def ticking(db, monkeypatch):
    """The price job with the market open, Yahoo replaced by one quote, Telegram recording."""
    call_command("seed_jobs", verbosity=0)
    monkeypatch.setattr(prices, "market_open", lambda now=None: True)
    sent = []
    monkeypatch.setattr(alerts.telegram, "send", lambda text, **kw: sent.append(text) or 1)
    monkeypatch.setattr(alerts.telegram, "configured", lambda: True)

    def tick(price):
        monkeypatch.setattr(prices, "fetch_quotes", lambda tickers: {"CEG": prices.Quote("CEG", price, timezone.now())})
        return execute_job(Job.objects.get(name="prices"))

    return tick, sent


def test_subject_normalises_the_ticker_and_rejects_nonsense():
    assert stock.validate_subject({"ticker": " ceg ", "good_below": 170}) == {"ticker": "CEG", "good_below": 170.0}
    with pytest.raises(ValueError, match="not a ticker"):
        stock.validate_subject({"ticker": "not a ticker", "good_below": 1})
    with pytest.raises(ValueError, match="positive"):
        stock.validate_subject({"ticker": "CEG", "good_below": 0})


@pytest.mark.django_db
def test_a_stock_tracker_gets_the_price_view_and_a_daily_news_job_only(ceg):
    assert Tracker.objects.get(slug="ceg").view == "price" and ceg["subject"] == {"ticker": "CEG", "good_below": 170.0}
    assert [(job["name"], job["schedule"]) for job in ceg["jobs"]] == [("collect:ceg", "0 7 * * *")]


@pytest.mark.django_db
def test_update_tracker_moves_the_line(ceg):
    updated = tools.update_tracker("ceg", subject={"ticker": "CEG", "good_below": 160})
    assert updated["subject"]["good_below"] == 160.0 and updated["changed"] == ["subject"]
    with pytest.raises(ValueError, match="unknown fields"):
        tools.update_tracker("ceg", subject={"ticker": "CEG", "good_below": 160, "stretched_above": 200})


def test_market_open_is_new_york_weekday_trading_hours():
    assert prices.market_open(datetime(2026, 10, 12, 9, 30, tzinfo=prices.MARKET_TZ))
    assert not prices.market_open(datetime(2026, 10, 12, 9, 29, tzinfo=prices.MARKET_TZ))
    assert not prices.market_open(datetime(2026, 10, 10, 12, 0, tzinfo=prices.MARKET_TZ))   # Saturday
    assert prices.market_open(datetime(2026, 10, 12, 23, 0, tzinfo=ZoneInfo("Asia/Jerusalem")))  # 16:00 New York
    assert not prices.market_open(datetime(2026, 10, 12, 23, 1, tzinfo=ZoneInfo("Asia/Jerusalem")))


def test_parse_spark_keys_by_symbol_and_reads_the_exchange_time():
    payload = {"spark": {"result": [
        {"symbol": "VST", "response": [{"meta": {"regularMarketPrice": 150.5, "regularMarketTime": 1760000000}}]},
        {"symbol": "CEG", "response": [{"meta": {"regularMarketPrice": 168.4}}]},
        {"symbol": "BAD", "response": [{"meta": {"regularMarketPrice": None}}]},
    ]}}
    fetched = datetime(2026, 10, 12, 14, 0, tzinfo=dt_timezone.utc)
    quotes = prices.parse_spark(payload, fetched)
    assert set(quotes) == {"VST", "CEG"}
    assert quotes["VST"].at == datetime.fromtimestamp(1760000000, tz=dt_timezone.utc)
    assert quotes["CEG"] == prices.Quote("CEG", 168.4, fetched)


@pytest.mark.django_db
def test_crossing_alerts_once_and_climbing_back_closes_quietly(ceg, ticking):
    tick, sent = ticking
    tracker = Tracker.objects.get(slug="ceg")
    assert tick(172.1).summary == "1 ticks · 1 level changes · 0 alerts sent"   # first judgment: watch, not news
    assert tick(171.0).summary == "1 ticks · 0 level changes · 0 alerts sent"
    crossing = tick(168.4)
    assert crossing.summary == "1 ticks · 1 level changes · 1 alerts sent"
    assert sent == ["🔔 Constellation Energy: watch → opportunity. CEG 168.40, at or below 170.00."]
    assert tracker.assessments.first().state == {"level": "opportunity", "price": 168.4, "good_below": 170.0}
    assert tick(169.0).summary == "1 ticks · 0 level changes · 0 alerts sent"
    assert tick(172.5).summary == "1 ticks · 1 level changes · 0 alerts sent"
    closed = tracker.assessments.first()
    assert closed.level == "watch" and closed.reason == "CEG 172.50, back above 170.00." and len(sent) == 1
    assert tracker.observations.filter(payload__has_key="price").count() == 5
    alert = tracker.alerts.get()
    assert alert.job_run == crossing and alert.delivered_at is not None
    assert list(closed.evidence.values_list("summary", flat=True)) == ["CEG 172.50"]


@pytest.mark.django_db
def test_closed_market_and_no_trackers_are_idle_passes(monkeypatch):
    call_command("seed_jobs", verbosity=0)
    job = Job.objects.get(name="prices")
    assert job.schedule == "*/15 15-23 * * mon-fri"
    monkeypatch.setattr(prices, "market_open", lambda now=None: False)
    assert execute_job(job).summary == "market closed"
    monkeypatch.setattr(prices, "market_open", lambda now=None: True)
    assert execute_job(job).summary == "no stock trackers"


@pytest.mark.django_db
def test_prices_endpoint_and_sourced_detail_separate_ticks_from_news(ceg, ticking):
    tick, _ = ticking
    tick(168.4)
    tools.record_observation("ceg", "2026-10-09", "https://news.example/ceg", "CEG signed a 20-year PPA.", None)
    client = Client()
    assert [point["price"] for point in client.get("/api/trackers/ceg/prices").json()] == [168.4]
    news = client.get("/api/trackers/ceg?sourced=true").json()["recent_observations"]
    assert [item["source_url"] for item in news] == ["https://news.example/ceg"]
    assert len(client.get("/api/trackers/ceg").json()["recent_observations"]) == 2
