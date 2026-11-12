"""Bring the vault's life board into the database, once, by Guy's hand.

    manage.py import_life <progress.md> --extras <json> [--dry-run] [--replace [--force]] [--events-until DATE]
    manage.py import_life <progress.md> --check [--on DATE] [--renderer PATH]

The file is the vault's data file: one JSON block of practices, campaigns,
watches, next actions and a log. Each practice becomes a tracker with one
observation per event day; each campaign becomes a tracker whose first
assessment is the lane as the file has it, with the lane's log rows as its
observations. Tasks that belong to no lane (the file's watches, and closures
its log filed under a name that is not a lane) go to one lane that is not
drawn. Briefs and the lanes' vault files come from the extras file, which
stays in the vault.

--replace starts over. Once the conversation has recorded anything on a life
tracker, that is no longer a rehearsal being repeated but Guy's record being
deleted, so it is refused without --force and says what would go.

--check writes nothing: it compares this repo's board with the vault's own
renderer on the same file, key by key and with every list whole, and fails
on a difference that is not one of the known ones."""
import copy
import datetime
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import life
from core.kinds import LIFE, campaign, iso_day, practice
from core.models import Assessment, Observation, Tracker

TASKS = "tasks"
NO_BRIEF = "(no brief yet: ask Guy what counts here and how it is dated before filing anything)"
NO_TEXT = "(imported: an event day with no text in the log)"
CAMPAIGN_IDENTITY = ("id", "title", "short", "tracks", "hidden")
EXTRAS_FIELDS = ("practices", "lanes", "default_lane_brief")
LANE_EXTRAS = ("brief", "file")
# The lists --check compares whole: a cut list can hide a missing item behind the cut.
WHOLE = 10 ** 6


def check_extras(data: dict, extras: dict) -> None:
    """An extras key nothing reads is refused: a brief under a mistyped id, or
    a section the import has no place for, would otherwise be dropped in
    silence and Guy would believe it was in."""
    unknown = sorted(set(extras) - set(EXTRAS_FIELDS))
    unknown += sorted(f"practices.{name}" for name in set(extras.get("practices", {})) - {item["id"] for item in data["practices"]})
    lanes = {item["id"] for item in data["campaigns"]} | {TASKS}
    for name, entry in extras.get("lanes", {}).items():
        if name not in lanes:
            unknown.append(f"lanes.{name}")
        unknown += sorted(f"lanes.{name}.{field}" for field in set(entry) - set(LANE_EXTRAS))
    if unknown:
        raise CommandError(f"the extras file has keys the import does not read: {', '.join(unknown)}")


def read_progress(path: Path) -> dict:
    block = re.search(r"```json\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
    if not block:
        raise CommandError(f"{path} holds no ```json block")
    return json.loads(block.group(1))


def _filled(record: dict) -> dict:
    """The record without its empty fields. 0 is a value (a rank), not empty."""
    return {field: value for field, value in record.items()
            if not (value is None or value is False or value == "" or value == [])}


def rows_of(data: dict, extras: dict, events_until: datetime.date | None = None) -> tuple[list[dict], list[str]]:
    """What the import would write, and what it leaves out and why. Pure: the
    command writes what this returns, and --dry-run prints it."""
    practices = {item["id"]: item for item in data["practices"]}
    campaigns = {item["id"]: item for item in data["campaigns"]}
    lane_by_name = {name: item["id"] for item in data["campaigns"] for name in (item["title"], item.get("short", item["title"]))}
    lanes_of_station = defaultdict(list)
    for item in data["campaigns"]:
        for station in campaign.stations_of(item):
            lanes_of_station[station["id"]].append(item["id"])

    left_out = []
    said = defaultdict(list)          # (practice, day) → what the log says happened
    added = defaultdict(list)         # practice → the days the log says it was added
    history = defaultdict(list)       # lane → (day, text, station or None)
    loose_tasks = {}
    for row in data["log"]:
        if "at" not in row:
            left_out.append("a log row without a date")
            continue
        text = row.get("label") or f"{row.get('from', '')} → {row.get('to', '')}"
        station_id = row.get("station", "")
        if station_id in practices:
            if row.get("to") in ("event", "reset") and row["at"] in practices[station_id].get("events", []):
                said[(station_id, row["at"])].append(text)
            elif row.get("to") == "practice":
                added[station_id].append(row["at"])
            else:
                left_out.append(f"{row['at']} {station_id}: a log row about the practice itself, not an event")
            continue
        prefix, _, bare = station_id.rpartition(".")
        lane = lane_by_name.get(row.get("campaign")) or (prefix if prefix in campaigns else None)
        if lane is None and len(lanes_of_station[bare]) == 1:
            lane = lanes_of_station[bare][0]
        if lane is None and bare in campaigns:
            lane = bare
        if lane is None:
            lane = TASKS
            if row.get("to") == "passed" and bare:
                loose_tasks[bare] = {"id": bare, "label": text, "state": "passed", "date": row["at"]}
            station = bare or None
        else:
            station = bare if bare in {known["id"] for known in campaign.stations_of(campaigns[lane])} else None
        history[lane].append((row["at"], text, station))

    trackers = []
    for rank, item in enumerate(data["practices"]):
        events = sorted(set(item.get("events", [])))
        # The start that reproduces the file's counter: the file's own `since` when nothing has happened yet,
        # else the earlier of the day the practice was added and its first event (a practice can be added
        # after the last time the thing happened, and its gap then counts from that earlier day).
        started = min(added[item["id"]] + events[:1]) if events else item["since"]
        if events_until and iso_day(started, "started") > events_until:
            # It did not exist yet on that day; imported, its counter would run backwards.
            left_out.append(f"practice {item['id']}: it starts after {events_until}")
            continue
        subject = _filled({"color": item["color"], "started": started, "note": item.get("note"),
                           "alert_after": item.get("alert_after", 3) if item["color"] == "red" else None})
        subject["rank"] = rank
        kept = [day for day in events if events_until is None or iso_day(day, "event") <= events_until]
        trackers.append({
            "slug": item["id"], "title": item["label"], "kind": "practice", "subject": subject,
            "brief": extras.get("practices", {}).get(item["id"]) or NO_BRIEF,
            "status": "paused" if item.get("show", True) is False else "active",
            "observations": [(day, " / ".join(said[(item["id"], day)]) or NO_TEXT, {}) for day in kept]})

    actions = {}
    for action in data.get("next", []):
        lane = lane_by_name.get(action.get("source"))
        if lane is None:
            raise CommandError(f"a next action names no lane: {action.get('source')!r}")
        if lane in actions:
            raise CommandError(f"two next actions for {lane!r}: a lane holds one")
        actions[lane] = {"text": action["text"], "hot": bool(action.get("hot"))}

    station_labels = {station["label"] for item in data["campaigns"] for station in campaign.stations_of(item)}
    for watch in data.get("watches", []):
        if watch["label"] in station_labels:
            left_out.append(f"watch {watch['id']}: it repeats a station that is already on a lane")
            continue
        note = " · ".join(part for part in (watch.get("consequence"), f"since {watch['since']}" if watch.get("since") else "",
                                            watch.get("source")) if part)
        loose_tasks[watch["id"]] = _filled({"id": watch["id"], "label": watch["label"], "state": "ahead",
                                            "check": watch.get("due"), "note": note, "burning": watch.get("burning"),
                                            "burning_why": (watch.get("consequence") or "flagged as burning in the vault") if watch.get("burning") else None})
    tasks = {"id": TASKS, "title": "Tasks", "hidden": True,
             "tracks": [{"stations": list(loose_tasks.values())}] if loose_tasks else []}

    for rank, item in enumerate(list(data["campaigns"]) + [tasks]):
        homeless = set(item) - set(campaign.LANE_FIELDS) - set(CAMPAIGN_IDENTITY) - set(campaign.SUBJECT_SCHEMA)
        if homeless:
            raise CommandError(f"campaign {item['id']!r} has fields the board has no place for: {', '.join(sorted(homeless))}")
        extra = extras.get("lanes", {}).get(item["id"], {})
        subject = _filled({"short": item.get("short"), "layout": item.get("layout"), "path": item.get("path"),
                           "file": extra.get("file")})
        subject["rank"] = rank
        state = _filled({field: item[field] for field in campaign.LANE_FIELDS if field in item})
        state["tracks"] = [_filled({**track, "stations": [_filled(station) for station in track.get("stations", [])]})
                           for track in item["tracks"]]
        if item["id"] in actions:
            state["next"] = actions[item["id"]]
        trackers.append({
            "slug": item["id"], "title": item["title"], "kind": "campaign", "subject": subject,
            "brief": extra.get("brief") or extras.get("default_lane_brief") or NO_BRIEF,
            "status": "paused" if item.get("hidden") else "active", "state": state,
            "observations": [(day, text, {"station": station} if station else {}) for day, text, station in history[item["id"]]]})

    if data.get("events"):
        left_out.append(f"{len(data['events'])} timeline events: they belong to no tracker")
    return trackers, left_out


def write(trackers: list[dict]) -> None:
    zone = ZoneInfo(settings.TIME_ZONE)
    for row in trackers:
        kind = practice if row["kind"] == "practice" else campaign
        tracker = Tracker.objects.create(slug=row["slug"], title=row["title"], kind=row["kind"], view=kind.VIEW,
                                         subject=kind.validate_subject(row["subject"]), brief=row["brief"],
                                         status=row["status"])
        filed = [Observation.objects.create(
            tracker=tracker, summary=text, payload=kind.validate_payload(payload),
            observed_at=datetime.datetime.combine(iso_day(day, "day"), datetime.time(), tzinfo=zone))
            for day, text, payload in row["observations"]]
        if row["kind"] == "campaign":
            # `changed` stays empty: the import touched no station, and a full list would
            # put every fact of the lane into every station's history.
            state = {**campaign.apply(None, row["state"]), "changed": []}
            assessment = Assessment.objects.create(tracker=tracker, state=state, reason="Imported from the vault's board.")
            assessment.evidence.set(filed)


def _loose(value):
    """The value without its empty fields at any depth: the board leaves out what the vault writes as empty."""
    if isinstance(value, dict):
        return {field: _loose(inner) for field, inner in value.items()
                if not (inner is None or inner is False or inner == "" or inner == [])}
    if isinstance(value, list):
        return [_loose(inner) for inner in value]
    return value


def compare(old: dict, new: dict) -> list[tuple[str, str, bool]]:
    """(key, verdict, acceptable) for every part of the board. Both boards
    are given with their lists whole. The overdue checks this repo derives at
    read are taken out first, and what is left must be equal, apart from the
    three differences the plan names."""
    overdue = [item for item in new["burning"] if item["why"] == life.OVERDUE]
    new = {**new, "burning": [item for item in new["burning"] if item not in overdue]}
    verdicts = []
    for key in ("today", "pulse", "burning", "burning_more", "focus", "focus_more", "horizon", "trail", "next", "lanes", "quiet"):
        before, after = _loose(old.get(key)), _loose(new.get(key))
        if before == after:
            verdict = "equal" + (f", {len(overdue)} overdue check(s) derived at read set aside" if key == "burning" and overdue else "")
        elif key == "trail" and ([(item["at"], str(item.get("station") or "").rpartition(".")[2]) for item in old[key]]
                                 == [(item["at"], item["station"]) for item in new[key]]):
            verdict = "same stations and dates (the label is the station's, not the log's)"
        elif key == "next" and (sorted(json.dumps(_loose(item), sort_keys=True) for item in old[key])
                                == sorted(json.dumps(_loose({**item, "lane": None}), sort_keys=True) for item in new[key])):
            verdict = "same actions, hot first then lane order"
        elif key == "quiet" and [name for name in new[key] if name != "Tasks"] == old[key]:
            verdict = "equal plus the tasks lane"
        else:
            verdict = "DIFFERENT"
        verdicts.append((key, verdict, verdict != "DIFFERENT"))
    return verdicts


class Command(BaseCommand):
    help = "Import the vault's life board (progress.md), or check this repo's board against the vault's renderer."

    def add_arguments(self, parser):
        parser.add_argument("progress", type=Path)
        parser.add_argument("--extras", type=Path, help="JSON with the briefs and the lanes' vault files")
        parser.add_argument("--dry-run", action="store_true", help="print what would be written and what is left out")
        parser.add_argument("--replace", action="store_true", help="drop the life trackers and import again")
        parser.add_argument("--force", action="store_true",
                            help="with --replace: also when the conversation has recorded on the life trackers")
        parser.add_argument("--events-until",
                            help="the replay's starting state: practice events after this day, and practices that start "
                                 "after it, are left out; lanes are imported as they stand, not as they stood then")
        parser.add_argument("--check", action="store_true", help="write nothing; compare the board with the vault's renderer")
        parser.add_argument("--on", help="the day --check compares on (default: today in Jerusalem)")
        parser.add_argument("--renderer", type=Path, help="default: Claude/render_dashboard.py beside the progress file")

    def handle(self, *args, **options):
        data = read_progress(options["progress"])
        if options["check"]:
            return self.check_board(data, options)
        extras = json.loads(options["extras"].read_text(encoding="utf-8")) if options["extras"] else {}
        check_extras(data, extras)
        until = iso_day(options["events_until"], "--events-until") if options["events_until"] else None
        trackers, left_out = rows_of(data, extras, until)
        for row in trackers:
            stations = f", {len(campaign.stations_of(row['state']))} stations" if row["kind"] == "campaign" else ""
            brief = "" if row["brief"] != NO_BRIEF else ", NO BRIEF"
            self.stdout.write(f"{row['kind']:8s} {row['slug']:20s} {row['status']:7s} {len(row['observations']):3d} observations{stations}{brief}")
        for reason in left_out:
            self.stdout.write(f"left out: {reason}")
        if options["dry_run"]:
            return
        with transaction.atomic():
            if options["replace"]:
                said = Observation.objects.filter(tracker__kind__in=LIFE, job_run__isnull=False).count()
                changed = Assessment.objects.filter(tracker__kind__in=LIFE, job_run__isnull=False).count()
                if (said or changed) and not options["force"]:
                    raise CommandError(f"--replace would delete what the conversation recorded: {said} observation(s) and "
                                       f"{changed} lane change(s) on the life trackers. Nothing was changed; "
                                       "--force deletes them.")
                Tracker.objects.filter(kind__in=LIFE).delete()
            taken = Tracker.objects.filter(slug__in=[row["slug"] for row in trackers]).values_list("slug", flat=True)
            if taken:
                raise CommandError(f"trackers already exist: {', '.join(taken)} (life trackers are replaced with --replace)")
            try:
                write(trackers)
            except ValueError as refused:
                raise CommandError(f"nothing was imported: {refused}")
        self.stdout.write(f"imported {len(trackers)} trackers")

    def check_board(self, data: dict, options: dict) -> None:
        path = options["renderer"] or options["progress"].parent / "Claude" / "render_dashboard.py"
        spec = importlib.util.spec_from_file_location("vault_renderer", path)
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        day = iso_day(options["on"], "--on") if options["on"] else life.today()
        renderer.validate(data)
        renderer.CAPS.update({name: WHOLE for name in ("pulse", "burning", "focus", "next_max", "trail_max", "lanes")})
        old = renderer.jsonable(renderer.derive(copy.deepcopy(data), day))
        whole = {**life.CAPS, **{name: WHOLE for name in ("pulse", "burning", "focus", "next", "trail", "lanes")}}
        verdicts = compare(old, life.board(day, whole))
        self.stdout.write(f"board on {day}:")
        for key, verdict, _ in verdicts:
            self.stdout.write(f"  {key:13s} {verdict}")
        if not all(acceptable for _, _, acceptable in verdicts):
            raise CommandError("the two boards differ")
