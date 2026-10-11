"""A listed company against the price Guy would buy it at. Ported from the
investment engine's price monitor: a tick every 15 minutes in market hours,
one symmetric rule against the good-below line, and a daily news session that
files what changed about the thesis in the brief.

Two levels. `opportunity` is the price at or below the line; `watch` is
everything else. The move into opportunity is the only alert: the engine
pushed only openings, because a close is a price going back up, which is on
the screen and not news.

Observations of two sorts share the tracker: a tick (no URL, payload with
price and source, filed by scheduler.scripts.prices) and a news item (URL,
no payload, filed by the collect session)."""
import re

from core.kinds import level_change_alert, validate

VIEW = "price"
LEVELS = ("watch", "opportunity")

SUBJECT_SCHEMA = {"ticker": (str, True), "good_below": (float, True)}
PAYLOAD_SCHEMA = {"price": (float, False), "source": (str, False)}
STATE_SCHEMA = {"level": (str, True), "price": (float, True), "good_below": (float, True)}

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# News only; the ticks come from one shared job (seed_jobs: `prices`).
DEFAULT_JOBS = ({"kind": "collect", "target": "agent.flows.collect.run"},)


def validate_subject(subject: dict) -> dict:
    subject = validate(subject, SUBJECT_SCHEMA, "subject")
    ticker = subject["ticker"].strip().upper()
    if not TICKER_RE.match(ticker):
        raise ValueError(f"subject.ticker {subject['ticker']!r} is not a ticker symbol")
    if subject["good_below"] <= 0:
        raise ValueError("subject.good_below must be a positive price")
    return {"ticker": ticker, "good_below": float(subject["good_below"])}


def validate_payload(payload: dict) -> dict:
    return validate(payload, PAYLOAD_SCHEMA, "payload")


def validate_state(state: dict, previous=None) -> dict:
    state = validate(state, STATE_SCHEMA, "state")
    if state["level"] not in LEVELS:
        raise ValueError(f"state.level must be one of {', '.join(LEVELS)}")
    return state


def alert_for(tracker, previous, new) -> str | None:
    text = level_change_alert(tracker, previous, new)
    return text if new.level == "opportunity" else None


def level_for(price: float, good_below: float) -> str:
    return "opportunity" if price <= good_below else "watch"


def collect_prompt(tracker, recent_observations) -> str:
    news = [observation for observation in recent_observations if observation.source_url]
    recent = "\n".join(f"- {observation.observed_at:%Y-%m-%d} {observation.source_url}: {observation.summary}"
                       for observation in news) or "- (none yet)"
    ticker = tracker.subject["ticker"]
    return (
        f"You are collecting news for the stock tracker \"{tracker.title}\" (slug: {tracker.slug}), ticker {ticker}.\n\n"
        f"Thesis and standing brief:\n{tracker.brief}\n\n"
        f"Already recorded (do not file these again):\n{recent}\n\n"
        f"Search the web for what is new about {ticker} since the most recent item above (or the last 7 days if "
        "none): results, guidance, contracts, regulation, management, anything that bears on the thesis. Prefer "
        "primary sources (filings, company releases) and major press. For each distinct fact worth keeping, call "
        "record_observation once with the source URL, the date it was published, and a one-or-two-sentence "
        "summary in your own words with the figure if there is one. Pass no payload: prices are filed by the "
        "price job, not by you. File at most 8 observations. If nothing new was found, record nothing and say so. "
        "Finish with one short paragraph: what you filed and what you skipped."
    )
