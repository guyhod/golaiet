"""The price job: every 15 minutes while New York is trading, one Yahoo request
for every active stock tracker, one tick observation per quote, and the
threshold rule from the stock kind. A script, not a session: nothing here
costs anything or needs a model.

The schedule is weekday afternoons in Jerusalem (seed_jobs); the clock that
decides is New York's, so the weeks when only one side has switched daylight
saving yield idle passes, not ticks outside trading. Holidays are not
modelled: a holiday is an idle pass with the last close as the price, which
cannot cross a line it did not cross on the trading day before.

Yahoo's spark endpoint is unofficial (the engine ran on it from 2026-07 to
2026-10 without a key); it rejects library user agents, so a browser one is
sent. Response order is not request order, so quotes are keyed by symbol."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone as dt_timezone
from zoneinfo import ZoneInfo

import httpx
from django.utils import timezone

from agent.tools import judge
from chat import alerts
from core.kinds import stock
from core.models import Observation, Tracker

log = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN, MARKET_CLOSE = time(9, 30), time(16, 0)
SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark?symbols={tickers}&range=1d&interval=1d"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
SOURCE = "yahoo"


@dataclass(frozen=True)
class Quote:
    ticker: str
    price: float
    at: datetime


def market_open(now: datetime | None = None) -> bool:
    local = (now or timezone.now()).astimezone(MARKET_TZ)
    return local.weekday() < 5 and MARKET_OPEN <= local.time() <= MARKET_CLOSE


def parse_spark(payload, fetched_at: datetime) -> dict[str, Quote]:
    """{"spark": {"result": [{"symbol", "response": [{"meta": {"regularMarketPrice", "regularMarketTime"}}]}]}}"""
    quotes = {}
    for item in (payload.get("spark") or {}).get("result") or []:
        responses = item.get("response") or []
        meta = responses[0].get("meta") if responses else None
        price = (meta or {}).get("regularMarketPrice")
        if not item.get("symbol") or not isinstance(price, (int, float)) or isinstance(price, bool):
            continue
        market_time = meta.get("regularMarketTime")
        at = datetime.fromtimestamp(market_time, tz=dt_timezone.utc) if isinstance(market_time, (int, float)) else fetched_at
        quotes[item["symbol"]] = Quote(item["symbol"], float(price), at)
    return quotes


def fetch_quotes(tickers: list[str]) -> dict[str, Quote]:
    response = httpx.get(SPARK_URL.format(tickers=",".join(tickers)), timeout=20, headers={"User-Agent": BROWSER_UA})
    response.raise_for_status()
    return parse_spark(response.json(), timezone.now())


def run(job, run) -> dict:
    if not market_open():
        return {"summary": "market closed"}
    trackers = list(Tracker.objects.filter(kind="stock", status=Tracker.Status.ACTIVE))
    if not trackers:
        return {"summary": "no stock trackers"}
    quotes = fetch_quotes([tracker.subject["ticker"] for tracker in trackers])
    ticks = judged = 0
    missing = []
    for tracker in trackers:
        ticker, good_below = tracker.subject["ticker"], tracker.subject["good_below"]
        quote = quotes.get(ticker)
        if quote is None:
            missing.append(ticker)
            continue
        tick = Observation.objects.create(tracker=tracker, observed_at=quote.at, summary=f"{ticker} {quote.price:.2f}",
                                          payload={"price": quote.price, "source": SOURCE}, job_run=run)
        ticks += 1
        level = stock.level_for(quote.price, good_below)
        previous = tracker.assessments.order_by("-at").first()
        if previous is not None and previous.level == level:
            continue
        relation = "at or below" if level == "opportunity" else "back above" if previous else "above"
        judge(tracker, {"level": level, "price": quote.price, "good_below": good_below},
              f"{ticker} {quote.price:.2f}, {relation} {good_below:.2f}.", [tick], job_run_id=run.pk)
        judged += 1
    delivered = alerts.deliver(run)
    summary = f"{ticks} ticks · {judged} level changes · {delivered} alerts sent"
    if missing:
        summary += f" · no quote for {', '.join(missing)}"
    return {"summary": summary, "failed": bool(missing) and not ticks}
