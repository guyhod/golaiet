"""A habit Guy keeps count of: mornings begun with a stretch, days since the boat was aired.

A practice is its events and nothing else. `green` is a streak, and an event
is a failure that resets it; `red` is a gap, and an event is an occurrence
that closes it. One observation per reported event, dated to the day it
counts for, in Guy's words. The counter, the colour of the tile, the caption
and the fourteen dots are arithmetic over the event days, done when the board
is read and never stored: a stored counter is a second copy of the events and
the two drift apart.

A practice is not judged, has no schedule and raises no alert. A wrong entry
is corrected by a second observation whose payload names the first
(`{"retracts": id}`); neither counts."""
import datetime
from zoneinfo import ZoneInfo

from django.conf import settings

from core.kinds import iso_day, short_day, validate

VIEW = "campaign_map"
LEVELS = ()
COLORS = ("green", "red")
DOTS = 14

SUBJECT_SCHEMA = {
    "color": (str, True),
    "started": (str, True),       # the day counting began; the counter runs from it until the first event
    "alert_after": (int, False),  # red only: days of gap at which the tile turns bad
    "note": (str, False),         # replaces the caption under the counter
    "rank": (int, False),         # position in the pulse row
}
PAYLOAD_SCHEMA = {"retracts": (int, False)}


def jobs(subject: dict) -> tuple[dict, ...]:
    return ()


def validate_subject(subject: dict) -> dict:
    # A null is a field left out: stored, it would be sorted and counted with as if it were a value.
    subject = {field: value for field, value in validate(subject, SUBJECT_SCHEMA, "subject").items() if value is not None}
    if subject["color"] not in COLORS:
        raise ValueError(f"subject.color must be one of {', '.join(COLORS)}")
    iso_day(subject["started"], "subject.started")
    if "alert_after" in subject:
        if subject["color"] != "red":
            raise ValueError("subject.alert_after is for a red practice: a streak has no gap to alert on")
        if subject["alert_after"] < 0:
            raise ValueError("subject.alert_after must be 0 (never) or a number of days")
    return subject


def validate_payload(payload: dict) -> dict:
    return validate(payload, PAYLOAD_SCHEMA, "payload")


def validate_state(state: dict, previous=None) -> dict:
    raise ValueError("a practice is not judged: file the event with record_observation, on the day it counts for")


def alert_for(tracker, previous, new) -> None:
    return None


def event_days(observations) -> set[datetime.date]:
    """The days that count: the Jerusalem date of every observation that is
    neither a retraction nor retracted. A bare date is stored as Jerusalem
    midnight, which is the evening before in UTC, so the day is read in
    Jerusalem and not from the stored instant. Two reports of one day are one
    day."""
    observations = list(observations)
    retracted = {observation.payload["retracts"] for observation in observations if "retracts" in observation.payload}
    zone = ZoneInfo(settings.TIME_ZONE)
    return {observation.observed_at.astimezone(zone).date() for observation in observations
            if "retracts" not in observation.payload and observation.pk not in retracted}


def tile(subject: dict, days: set[datetime.date], today: datetime.date) -> dict:
    """One tile of the pulse row."""
    events = sorted(days)
    since = max([iso_day(subject["started"], "subject.started")] + events)
    count = (today - since).days
    green = subject["color"] == "green"
    dots = []
    for back in range(DOTS - 1, -1, -1):
        day = today - datetime.timedelta(days=back)
        dots.append(("bad" if day in days else "ok") if green else ("ok" if day in days else "none"))
    if green:
        state = "good"
        if count == 0 and today in days:
            caption, state = "reset · last night failed", "warn"
        elif count == 0:
            caption = f"day 1 · started {short_day(since)}"
        else:
            caption = f"streak · since {short_day(since)}"
    else:
        threshold = subject.get("alert_after", 3) or 0
        if threshold and count >= threshold:
            state = "bad"
        elif threshold and count >= max(threshold - 1, 1):
            state = "warn"
        else:
            state = "good"
        caption = f"last {short_day(since)} · alert at {threshold}" if threshold else f"last {short_day(since)}"
    note = subject.get("note", "")
    unit = ("day" if count == 1 else "days") + ("" if green else " since")
    return {"color": subject["color"], "n": count, "since": since.isoformat(), "note": note,
            "events": [day.isoformat() for day in events], "unit": unit, "sub": note or caption, "dots": dots,
            "state": state}
