"""The life board: everything the Life screen draws, in one read.

Built from the rows each time it is asked for and never stored: the pulse row
from the practices' event days, the map from each campaign's latest
assessment, and the panels (burning, focus, the week ahead, what passed,
next actions) from both. `today` is the Jerusalem date; the caller passes it,
so a test can stand on any day, and the caps on each list, so the import's
check can compare whole lists."""
import copy
import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from core.kinds import campaign, iso_day, practice, short_day
from core.models import Tracker

CAPS = {"pulse": 7, "burning": 3, "focus": 3, "next": 7, "horizon_days": 7, "trail_days": 14, "trail": 7, "lanes": 9}
# Stations that are still open: the ones a check date is waiting on.
OPEN = ("current", "ahead")
OVERDUE = "check date passed, nothing set since"


def today() -> datetime.date:
    return timezone.now().astimezone(ZoneInfo(settings.TIME_ZONE)).date()


def _lane(tracker: Tracker, state: dict) -> dict:
    """A campaign as the map draws it: identity from the tracker, the rest from its latest state."""
    subject = tracker.subject
    lane = {"id": tracker.slug, "title": tracker.title, "short": subject.get("short", tracker.title)}
    for field in ("layout", "path"):
        if field in subject:
            lane[field] = subject[field]
    if tracker.status == Tracker.Status.PAUSED:
        lane["hidden"] = True
    lane.update(copy.deepcopy({field: value for field, value in state.items()
                               if field not in campaign.DERIVED and field != "next"}))
    lane.setdefault("tracks", [])
    return lane


def _station_title(lane: dict, station: dict) -> str:
    return f"{lane['title']} — {station['label']}"


def _flagged(lanes: list[dict], day: datetime.date) -> tuple[list[dict], list[dict]]:
    """Burning and focus: the flags Guy set, on a lane or on a station (a
    flagged lane speaks for its stations), then every check date that has
    gone by. An overdue check is derived here, like a counter, and burns
    until he moves or drops the date."""
    burning, focus = [], []
    for lane in lanes:
        if lane.get("burning"):
            burning.append({"title": lane["title"], "since": lane.get("burning_since", ""),
                            "why": lane.get("burning_why", ""), "path": lane.get("path", lane["title"]),
                            "rank": lane.get("burning_rank", 99), "campaign": lane["id"]})
        if lane.get("focus"):
            focus.append({"title": lane["title"], "why": lane.get("focus_why", ""),
                          "rank": lane.get("focus_rank", 99), "campaign": lane["id"]})
        for track in lane["tracks"]:
            for station in track.get("stations", []):
                if station.get("burning") and not lane.get("burning"):
                    path = " › ".join(part for part in (lane["title"], track.get("caption", ""), station["label"]) if part)
                    burning.append({"title": station.get("burning_title") or _station_title(lane, station), "since": "",
                                    "why": station.get("burning_why", ""), "path": path, "rank": 99,
                                    "campaign": lane["id"], "station": station["id"]})
                if station.get("focus") and not lane.get("focus"):
                    focus.append({"title": station.get("focus_title") or _station_title(lane, station),
                                  "why": station.get("focus_why", ""),
                                  "rank": 99, "campaign": lane["id"], "station": station["id"]})
    for lane in lanes:
        for due, station in _checks(lane):
            if due < day and not (station or lane).get("burning"):
                burning.append({"title": _station_title(lane, station) if station else lane["title"],
                                "since": short_day(due), "why": OVERDUE, "path": lane.get("path", lane["title"]),
                                "rank": 100, "campaign": lane["id"], **({"station": station["id"]} if station else {})})
    return sorted(burning, key=lambda item: item["rank"]), sorted(focus, key=lambda item: item["rank"])


def _checks(lane: dict) -> list[tuple[datetime.date, dict | None]]:
    """The dates a lane is waiting on: its own check date, or, when it has
    none, those of its open stations."""
    if lane.get("check"):
        return [(iso_day(lane["check"], "check"), None)]
    return [(iso_day(station["check"], "check"), station) for station in campaign.stations_of(lane)
            if station.get("state") in OPEN and station.get("check")]


def _horizon(lanes: list[dict], day: datetime.date, caps: dict) -> list[dict]:
    """The next week, a day at a time: checks and target dates."""
    days: dict[datetime.date, list[dict]] = {}

    def add(due: datetime.date, item: dict) -> None:
        if 0 <= (due - day).days <= caps["horizon_days"]:
            days.setdefault(due, []).append(item)

    for lane in lanes:
        for due, station in _checks(lane):
            if station:
                add(due, {"label": f"{lane['short']}: {station['label']}", "kind": "check", "campaign": lane["id"],
                          "station": station["id"]})
            else:
                add(due, {"label": lane["short"], "kind": "check", "campaign": lane["id"]})
        if lane.get("target_by"):
            add(iso_day(lane["target_by"], "target_by"),
                {"label": f"{lane['short']} — due", "kind": "target", "campaign": lane["id"]})
    return [{"date": due.isoformat(), "label": short_day(due) + (" · today" if due == day else ""), "today": due == day,
             "items": sorted(days[due], key=lambda item: item["label"])} for due in sorted(days)]


def _trail(lanes: list[dict], day: datetime.date, caps: dict) -> list[dict]:
    """What passed in the last two weeks, newest first."""
    passed = []
    for lane in lanes:
        for station in campaign.stations_of(lane):
            if station["state"] == "passed" and (day - iso_day(station["date"], "date")).days <= caps["trail_days"]:
                passed.append({"at": station["date"], "date": short_day(iso_day(station["date"], "date")),
                               "label": station["label"], "campaign": lane["short"], "lane": lane["id"],
                               "station": station["id"]})
    return sorted(passed, key=lambda item: item["at"], reverse=True)[:caps["trail"]]


def _drawn(lanes: list[dict], caps: dict) -> tuple[list[dict], list[str]]:
    """The lanes the map has room for, and the names of the rest. A paused
    lane is never drawn; when the map is full, flagged lanes keep their place."""
    shown = [lane for lane in lanes if not lane.get("hidden")]
    quiet = [lane["short"] for lane in lanes if lane.get("hidden")]
    if len(shown) > caps["lanes"]:
        keep = [lane for lane in shown if lane.get("focus") or lane.get("burning")]
        keep += [lane for lane in shown if lane not in keep][:max(0, caps["lanes"] - len(keep))]
        quiet += [lane["short"] for lane in shown if lane not in keep]
        shown = [lane for lane in shown if lane in keep]
    for lane in shown:
        longest = max((max([station.get("rank", position) for position, station in enumerate(track.get("stations", []))]
                           + [-1]) + 1 for track in lane["tracks"]), default=0)
        stations = campaign.stations_of(lane)
        lane["_wide"] = lane.get("layout") == "wide" or (
            lane.get("layout") != "card" and (longest >= 5 or any(station.get("ref") for station in stations)))
        counted = [station for station in stations if station["state"] not in ("proposed", "ref")]
        meta = [f"{sum(station['state'] == 'passed' for station in counted)} / {len(counted)}"]
        if lane.get("target_by"):
            meta.append(f"by {short_day(iso_day(lane['target_by'], 'target_by'))}")
        elif lane.get("check"):
            meta.append(f"chk {short_day(iso_day(lane['check'], 'check'))}")
        lane["_meta"] = " · ".join(meta)
    return shown, quiet


def on_board(slug: str) -> bool:
    """Whether the tracker is drawn today: a practice in the pulse row, a campaign on the map."""
    drawn = board(today())
    return slug in [item["id"] for item in drawn["pulse"] + drawn["lanes"]]


def _rank(tracker: Tracker) -> int:
    """Where the tracker stands in its row. One without a rank goes last, and so does one whose
    rank is not a number: a subject edited by hand in the database must not take the board down."""
    rank = tracker.subject.get("rank")
    return rank if isinstance(rank, (int, float)) and not isinstance(rank, bool) else 999


def board(day: datetime.date, caps: dict = CAPS) -> dict:
    trackers = sorted(Tracker.objects.filter(kind__in=("practice", "campaign"),
                                             status__in=(Tracker.Status.ACTIVE, Tracker.Status.PAUSED)),
                      key=lambda tracker: (_rank(tracker), tracker.slug))
    pulse = [{"id": tracker.slug, "label": tracker.title,
              **practice.tile(tracker.subject, practice.event_days(tracker.observations.all()), day)}
             for tracker in trackers if tracker.kind == "practice" and tracker.status == Tracker.Status.ACTIVE]
    lanes, actions = [], []
    for tracker in trackers:
        latest = tracker.assessments.order_by("-at").first() if tracker.kind == "campaign" else None
        if latest is None:
            continue
        lanes.append(_lane(tracker, latest.state))
        if latest.state.get("next"):
            action = latest.state["next"]
            actions.append({"text": action["text"], "source": lanes[-1]["short"], "lane": tracker.slug,
                            "hot": bool(action.get("hot"))})
    burning, focus = _flagged(lanes, day)
    shown, quiet = _drawn(lanes, caps)
    return {
        "today": day.isoformat(),
        "pulse": pulse[:caps["pulse"]],
        "burning": burning[:caps["burning"]], "burning_more": max(0, len(burning) - caps["burning"]),
        "focus": focus[:caps["focus"]], "focus_more": max(0, len(focus) - caps["focus"]),
        "horizon": _horizon(lanes, day, caps),
        "trail": _trail(lanes, day, caps),
        # Hot first, then the order of the lanes.
        "next": sorted(actions, key=lambda action: not action["hot"])[:caps["next"]],
        "lanes": shown,
        "quiet": quiet,
    }
