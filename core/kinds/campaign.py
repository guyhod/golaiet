"""Something Guy is moving forward: a lane of stations on the life map.

The latest assessment's state is the lane as it stands: tracks of stations,
the lane's dates, its burning and focus flags with their reasons, one next
action. Reading a lane is reading one row.

A change is submitted small and stored whole. record_assessment is given only
what changes; validate_state applies it to the previous state and returns the
whole lane. A station the change does not name is untouched by construction:
a model that never retypes a label cannot reword it.

The kind has no clock: a station that becomes passed says which day. It has
no schedule and raises no alert."""
import copy

from core.kinds import iso_day, validate

VIEW = "campaign_map"
LEVELS = ("steady", "focus", "burning")
STATES = ("passed", "current", "ahead", "proposed", "decision", "ref")
LAYOUTS = ("wide", "card")

SUBJECT_SCHEMA = {
    "short": (str, False),    # the lane's name on the map, when the title is long
    "layout": (str, False),   # wide or card; left out, the map decides by the number of stations
    "rank": (int, False),     # position on the map
    "file": (str, False),     # the vault file this lane's notes are appended to
    "path": (str, False),     # where the lane sits in Guy's own outline, shown in the Burning panel
}
PAYLOAD_SCHEMA = {"station": (str, False)}

LANE_FIELDS = ("check", "target_by", "note", "focus", "focus_rank", "focus_why", "burning", "burning_rank",
               "burning_since", "burning_why", "next")
TRACK_FIELDS = ("caption", "mini", "stations")
STATION_FIELDS = ("id", "label", "state", "date", "check", "note", "rank", "burning", "burning_why", "burning_title",
                  "focus", "focus_title", "options", "requires", "join", "join_next", "ref")
DERIVED = ("level", "changed")


def jobs(subject: dict) -> tuple[dict, ...]:
    return ()


def validate_subject(subject: dict) -> dict:
    subject = validate(subject, SUBJECT_SCHEMA, "subject")
    if subject.get("layout") is not None and subject["layout"] not in LAYOUTS:
        raise ValueError(f"subject.layout must be one of {', '.join(LAYOUTS)}")
    return subject


def validate_payload(payload: dict) -> dict:
    return validate(payload, PAYLOAD_SCHEMA, "payload")


def validate_state(change: dict, previous=None) -> dict:
    """The change applied to the previous lane; what comes back is stored."""
    return apply(previous.state if previous else None, change)


def alert_for(tracker, previous, new) -> None:
    return None


def stations_of(state: dict) -> list[dict]:
    return [station for track in state.get("tracks", []) for station in track.get("stations", [])]


def level_of(state: dict) -> str:
    stations = stations_of(state)
    if state.get("burning") or any(station.get("burning") for station in stations):
        return "burning"
    if state.get("focus") or any(station.get("focus") for station in stations):
        return "focus"
    return "steady"


def _refuse_unknown(values: dict, known: tuple, label: str) -> None:
    unknown = set(values) - set(known)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")


def check(state: dict) -> None:
    """Refuses a lane that is not valid, in words the agent can act on."""
    _refuse_unknown(state, LANE_FIELDS + ("tracks",) + DERIVED, "state")
    if state.get("burning") and not state.get("burning_why"):
        raise ValueError("a burning lane carries its reason: burning_why")
    if state.get("focus") and not state.get("focus_why"):
        raise ValueError("a lane in focus carries its reason: focus_why")
    for field in ("check", "target_by"):
        if field in state:
            iso_day(state[field], f"state.{field}")
    if "next" in state:
        action = state["next"]
        if not isinstance(action, dict) or set(action) - {"text", "hot"} or not str(action.get("text", "")).strip():
            raise ValueError('state.next must be {"text": ..., "hot": true or false}')
    seen = set()
    for position, track in enumerate(state.get("tracks", [])):
        name = repr(track.get("caption", position))
        _refuse_unknown(track, TRACK_FIELDS, f"track {name}")
        current = [station.get("id") for station in track.get("stations", []) if station.get("state") == "current"]
        if len(current) > 1:
            raise ValueError(f"track {name} has two current stations: {', '.join(map(str, current))}")
        for station in track.get("stations", []):
            label = f"station {station.get('id')!r}"
            _refuse_unknown(station, STATION_FIELDS, label)
            if not station.get("id") or not station.get("label"):
                raise ValueError(f"{label} needs an id and a label")
            if station["id"] in seen:
                raise ValueError(f"duplicate station id {station['id']!r}")
            seen.add(station["id"])
            if station.get("state") not in STATES:
                raise ValueError(f"{label}: state must be one of {', '.join(STATES)}, got {station.get('state')!r}")
            for field in ("date", "check"):
                if field in station:
                    iso_day(station[field], f"{label}.{field}")
            if station.get("burning") and not station.get("burning_why"):
                raise ValueError(f"{label} is burning without a reason: burning_why")
            if station["state"] == "passed" and not station.get("date"):
                raise ValueError(f"{label} is passed: give `date`, the day it happened")


def _locate(state: dict, station_id: str):
    for track in state["tracks"]:
        for position, station in enumerate(track.get("stations", [])):
            if station["id"] == station_id:
                return track, position
    return None, None


def _set(target: dict, values: dict) -> None:
    """A given value replaces the stored one; null removes it."""
    for field, value in values.items():
        if value is None:
            target.pop(field, None)
        else:
            target[field] = value


def _add_station(state: dict, given: dict) -> None:
    missing = [field for field in ("label", "track") if field not in given]
    if missing:
        raise ValueError(f"new station {given['id']!r} needs {', '.join(missing)}")
    caption = given["track"] or ""
    track = next((track for track in state["tracks"] if track.get("caption", "") == caption), None)
    if track is None:
        track = {"caption": caption, "stations": []} if caption else {"stations": []}
        state["tracks"].append(track)
    stations = track.setdefault("stations", [])
    position = len(stations)
    if given.get("after"):
        ids = [station["id"] for station in stations]
        if given["after"] not in ids:
            raise ValueError(f"after: no station {given['after']!r} on track {caption!r}")
        position = ids.index(given["after"]) + 1
    station = {"state": "ahead"}
    _set(station, {field: value for field, value in given.items() if field not in ("track", "after")})
    stations.insert(position, station)


def apply(previous_state: dict | None, change: dict) -> dict:
    """The whole lane after the change, checked, with `level` and `changed`
    derived. `stations` changes or adds single stations; `dropped` removes
    them; `tracks` replaces the whole lane (the importer's form, and the way
    to regroup) and is refused when a station would vanish unnamed."""
    if not isinstance(change, dict):
        raise ValueError("state must be an object")
    for field in DERIVED:
        if field in change:
            raise ValueError(f"state.{field} is derived; leave it out")
    _refuse_unknown(change, LANE_FIELDS + ("stations", "dropped", "tracks"), "state")
    state = copy.deepcopy(previous_state) if previous_state else {}
    for field in DERIVED:
        state.pop(field, None)
    state.setdefault("tracks", [])
    dropped = list(change.get("dropped", []))
    changed = list(dropped)
    if "tracks" in change:
        if "stations" in change:
            raise ValueError("give `tracks` (the whole lane) or `stations` (a change), not both")
        before = {station["id"]: station for station in stations_of(state)}
        state["tracks"] = copy.deepcopy(change["tracks"])
        after = {station.get("id"): station for station in stations_of(state)}
        lost = set(before) - set(after) - set(dropped)
        if lost:
            raise ValueError(f"stations would vanish: {', '.join(sorted(lost))}; keep them or list them in `dropped`")
        changed += [station_id for station_id, station in after.items() if before.get(station_id) != station]
        dropped = []
    _set(state, {field: change[field] for field in LANE_FIELDS if field in change})
    for station_id in dropped:
        track, position = _locate(state, station_id)
        if track is None:
            raise ValueError(f"dropped: no station {station_id!r}")
        track["stations"].pop(position)
    for given in change.get("stations", []):
        if not isinstance(given, dict) or not given.get("id"):
            raise ValueError("every station in a change needs an id")
        track, position = _locate(state, given["id"])
        if track is None:
            _add_station(state, given)
        else:
            if "track" in given or "after" in given:
                raise ValueError(f"station {given['id']!r} exists; `track` and `after` are for new stations only")
            station = track["stations"][position]
            if given.get("state") == "passed" and station.get("state") != "passed" and "date" not in given:
                # A date it carried while open is not the day it passed; the check below asks for one.
                station.pop("date", None)
            _set(station, given)
        changed.append(given["id"])
    check(state)
    return {**state, "level": level_of(state), "changed": changed}
