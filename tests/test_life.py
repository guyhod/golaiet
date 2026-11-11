"""The life kinds, the board and the import, on an invented board: a garden,
a boat, a stretching habit. Nothing here comes from a real one."""
import datetime
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from agent import tools
from core import life
from core.kinds import campaign, practice
from core.management.commands import import_life
from core.models import Tracker

DAY = datetime.date(2031, 3, 10)


def days(*iso):
    return {datetime.date.fromisoformat(day) for day in iso}


# ---------------- practice: arithmetic over event days ----------------

def red(**subject):
    return {"color": "red", "started": "2031-03-01", **subject}


def green(**subject):
    return {"color": "green", "started": "2031-03-01", **subject}


def test_a_red_practice_counts_days_since_the_last_occurrence():
    tile = practice.tile(red(alert_after=3), days("2031-03-02", "2031-03-08"), DAY)
    assert (tile["n"], tile["since"], tile["unit"], tile["state"]) == (2, "2031-03-08", "days since", "warn")
    assert tile["sub"] == "last Mar 8 · alert at 3"
    assert tile["dots"][-3:] == ["ok", "none", "none"] and len(tile["dots"]) == 14


@pytest.mark.parametrize("last, state", [("2031-03-10", "good"), ("2031-03-09", "good"), ("2031-03-08", "warn"),
                                         ("2031-03-07", "bad"), ("2031-03-01", "bad")])
def test_a_red_practice_warns_the_day_before_its_threshold(last, state):
    assert practice.tile(red(alert_after=3), days(last), DAY)["state"] == state


def test_a_red_practice_without_a_threshold_never_alerts():
    tile = practice.tile(red(alert_after=0), set(), DAY)
    assert (tile["n"], tile["state"], tile["sub"]) == (9, "good", "last Mar 1")


def test_a_green_practice_is_a_streak_since_the_last_failure():
    tile = practice.tile(green(), days("2031-03-04"), DAY)
    assert (tile["n"], tile["unit"], tile["state"], tile["sub"]) == (6, "days", "good", "streak · since Mar 4")
    assert tile["dots"].count("bad") == 1 and tile["dots"][-7] == "bad"


def test_a_failure_last_night_resets_the_streak_and_says_so():
    tile = practice.tile(green(), days("2031-03-04", "2031-03-10"), DAY)
    assert (tile["n"], tile["state"], tile["sub"]) == (0, "warn", "reset · last night failed")


def test_a_practice_started_today_is_day_one_not_a_failure():
    tile = practice.tile(green(started="2031-03-10"), set(), DAY)
    assert (tile["n"], tile["state"], tile["sub"]) == (0, "good", "day 1 · started Mar 10")


def test_one_day_is_singular_and_a_note_replaces_the_caption():
    tile = practice.tile(green(note="no screens after ten"), days("2031-03-09"), DAY)
    assert (tile["n"], tile["unit"], tile["sub"]) == (1, "day", "no screens after ten")


def test_a_practice_subject_is_checked():
    assert practice.validate_subject(red(alert_after=4))["alert_after"] == 4
    for subject in (red(color="blue"), red(started="1/3/2031"), green(alert_after=3), red(alert_after=-1), red(since="2031-03-01")):
        with pytest.raises(ValueError):
            practice.validate_subject(subject)


@pytest.fixture
def stretch(db):
    return tools.create_tracker("stretch", "Stretching", "practice", red(alert_after=3), "Any ten minutes count.", "weekly")


def test_a_practice_has_no_jobs_and_is_not_judged(stretch):
    assert stretch["jobs"] == [] and Tracker.objects.get(slug="stretch").view == "campaign_map"
    with pytest.raises(ValueError, match="not judged"):
        tools.record_assessment("stretch", {"level": "good"}, "It went well.")


def test_the_event_day_is_the_jerusalem_day_not_the_utc_one(stretch):
    """A bare date is Jerusalem midnight, which is still the evening before in
    UTC; a report late in the UTC evening is already tomorrow in Jerusalem."""
    tools.record_observation("stretch", "2031-03-08", "", "Stretched before breakfast.")
    tools.record_observation("stretch", "2031-03-08T22:30:00+00:00", "", "Stretched after midnight.")
    tracker = Tracker.objects.get(slug="stretch")
    assert tracker.observations.order_by("observed_at").first().observed_at.date() == datetime.date(2031, 3, 7)
    assert practice.event_days(tracker.observations.all()) == days("2031-03-08", "2031-03-09")


def test_two_reports_of_one_day_count_once_and_a_retraction_removes_both(stretch):
    tools.record_observation("stretch", "2031-03-05", "", "Stretched.")
    tools.record_observation("stretch", "2031-03-05T18:00:00", "", "Stretched, said again.")
    wrong = tools.record_observation("stretch", "2031-03-09", "", "Stretched.")
    tools.record_observation("stretch", "2031-03-10", "", "That was not me.", {"retracts": wrong["id"]})
    assert practice.event_days(Tracker.objects.get(slug="stretch").observations.all()) == days("2031-03-05")


# ---------------- campaign: a small change in, the whole lane out ----------------

LANE = {"check": "2031-03-20", "tracks": [{"caption": "Beds", "stations": [
    {"id": "dig", "label": "Dig the beds", "state": "passed", "date": "2031-03-06"},
    {"id": "fence", "label": "Mend the fence", "state": "current", "date": "2031-03-01"},
    {"id": "shed", "label": "Paint the shed", "state": "ahead"}]}]}


def lane():
    return campaign.apply(None, LANE)


def station(state, station_id):
    return next(item for item in campaign.stations_of(state) if item["id"] == station_id)


def test_a_change_names_only_what_changes_and_the_rest_is_untouched():
    before = lane()
    after = campaign.apply(before, {"stations": [{"id": "fence", "state": "passed", "date": "2031-03-09"}]})
    assert station(after, "fence") == {"id": "fence", "label": "Mend the fence", "state": "passed", "date": "2031-03-09"}
    assert station(after, "dig") == station(before, "dig") and station(after, "shed") == station(before, "shed")
    assert after["changed"] == ["fence"] and after["check"] == "2031-03-20" and after["level"] == "steady"
    assert station(before, "fence")["state"] == "current", "the previous state is not edited in place"


def test_a_pass_says_which_day_and_an_old_date_does_not_stand_in():
    with pytest.raises(ValueError, match="give `date`"):
        campaign.apply(lane(), {"stations": [{"id": "fence", "state": "passed"}]})


def test_a_new_station_needs_a_label_and_a_track_and_is_ahead():
    after = campaign.apply(lane(), {"stations": [{"id": "gate", "label": "Hang the gate", "track": "Beds", "after": "dig"},
                                                 {"id": "pond", "label": "Dig a pond", "track": "Water", "state": "proposed"}]})
    assert [item["id"] for item in after["tracks"][0]["stations"]] == ["dig", "gate", "fence", "shed"]
    assert station(after, "gate")["state"] == "ahead" and after["tracks"][1] == {
        "caption": "Water", "stations": [{"state": "proposed", "id": "pond", "label": "Dig a pond"}]}
    with pytest.raises(ValueError, match="needs label"):
        campaign.apply(lane(), {"stations": [{"id": "gate", "track": "Beds"}]})


def test_flags_carry_reasons_and_the_level_follows_them():
    with pytest.raises(ValueError, match="burning_why"):
        campaign.apply(lane(), {"burning": True})
    burning = campaign.apply(lane(), {"focus": True, "focus_why": "spring", "stations": [
        {"id": "shed", "burning": True, "burning_why": "rain is coming"}]})
    assert burning["level"] == "burning"
    cooled = campaign.apply(burning, {"stations": [{"id": "shed", "burning": None, "burning_why": None}]})
    assert cooled["level"] == "focus" and "burning" not in station(cooled, "shed")
    assert campaign.apply(cooled, {"focus": None, "focus_why": None})["level"] == "steady"


@pytest.mark.parametrize("change, message", [
    ({"stations": [{"id": "shed", "state": "current"}]}, "two current"),
    ({"stations": [{"id": "shed", "state": "done"}]}, "state must be one of"),
    ({"stations": [{"id": "shed", "colour": "red"}]}, "unknown fields"),
    ({"stations": [{"id": "shed", "check": "20/3"}]}, "YYYY-MM-DD"),
    ({"stations": [{"id": "shed", "track": "Beds"}]}, "new stations only"),
    ({"stations": [{"label": "Nameless"}]}, "needs an id"),
    ({"dropped": ["well"]}, "no station"),
    ({"level": "burning"}, "derived"),
    ({"changed": ["shed"]}, "derived"),
    ({"mood": "good"}, "unknown fields"),
    ({"next": {"text": ""}}, "state.next"),
    ({"tracks": [{"stations": [{"id": "dig", "label": "Dig the beds", "state": "ahead"}]}]}, "would vanish"),
    ({"tracks": LANE["tracks"], "stations": []}, "not both"),
    ({"tracks": [{"stations": [{"id": "dig", "label": "A", "state": "ahead"}, {"id": "dig", "label": "B", "state": "ahead"}]}],
      "dropped": ["fence", "shed"]}, "duplicate"),
])
def test_a_bad_change_is_refused_in_words(change, message):
    with pytest.raises(ValueError, match=message):
        campaign.apply(lane(), change)


def test_dropping_and_regrouping():
    assert [item["id"] for item in campaign.stations_of(campaign.apply(lane(), {"dropped": ["shed"]}))] == ["dig", "fence"]
    regrouped = campaign.apply(lane(), {"dropped": ["shed"], "tracks": [
        {"stations": [LANE["tracks"][0]["stations"][1]]}, {"caption": "Done", "stations": [LANE["tracks"][0]["stations"][0]]}]})
    assert [track.get("caption") for track in regrouped["tracks"]] == [None, "Done"] and regrouped["changed"] == ["shed"]


def test_the_tool_stores_the_whole_lane_from_a_small_change(db):
    tools.create_tracker("garden", "Garden", "campaign", {"short": "Garden"}, "The garden, bed by bed.", "weekly")
    tools.record_assessment("garden", LANE, "First state.")
    fact = tools.record_observation("garden", "2031-03-09", "", "The fence is mended.", {"station": "fence"})
    stored = tools.record_assessment("garden", {"stations": [{"id": "fence", "state": "passed", "date": "2031-03-09"}],
                                                "next": {"text": "Buy paint", "hot": True}}, "He said so.", [fact["id"]])
    assert stored["alert"] is None and stored["state"]["changed"] == ["fence"]
    assert len(campaign.stations_of(Tracker.objects.get(slug="garden").assessments.first().state)) == 3
    with pytest.raises(ValueError):
        campaign.validate_subject({"layout": "tall"})


# ---------------- the import and the board ----------------

PROGRESS = {
    "meta": {},
    "practices": [
        {"id": "stretch", "label": "Stretching", "color": "red", "since": "2031-03-08", "alert_after": 3,
         "events": ["2031-03-02", "2031-03-08"], "show": True},
        {"id": "no_snacks", "label": "No snacks", "color": "green", "since": "2031-03-05", "events": ["2031-03-05"], "show": True},
        {"id": "early_walk", "label": "Early walk", "color": "green", "since": "2031-03-01", "events": [], "show": False},
    ],
    "campaigns": [
        {"id": "garden", "title": "Garden", "short": "Garden", "check": "2031-03-12", "focus": True, "focus_rank": 1,
         "focus_why": "spring", "burning": False, "burning_why": "", "tracks": LANE["tracks"]},
        {"id": "boat", "title": "Boat repair", "short": "Boat", "hidden": True,
         "tracks": [{"caption": "", "stations": [{"id": "hull", "label": "Sand the hull", "state": "ahead", "check": "2031-03-15"}]}]},
    ],
    "watches": [{"id": "permit", "label": "Harbour permit", "since": "2031-02-01", "due": "2031-03-11",
                 "consequence": "no mooring without it", "source": "the harbour office", "burning": False},
                {"id": "paint", "label": "Paint the shed", "since": "2031-02-01"}],
    "next": [{"text": "Order timber", "source": "Garden", "hot": True}],
    "events": [{"date": "2031-03-14", "label": "Plant fair"}],
    "log": [
        {"at": "2031-02-20", "campaign": "Health", "station": "stretch", "label": "Stretching added", "from": "none", "to": "practice"},
        {"at": "2031-03-08", "campaign": "Health", "station": "stretch", "label": "Stretched for ten minutes", "from": "gap", "to": "event"},
        {"at": "2031-03-06", "campaign": "Garden", "station": "dig", "label": "The beds are dug", "from": "current", "to": "passed"},
        {"at": "2031-03-07", "campaign": "Kiln", "station": "glaze", "label": "First glaze fired", "from": "ahead", "to": "passed"},
        {"label": "a line with no date"},
    ],
}
EXTRAS = {"practices": {"stretch": "Any ten minutes count."}, "default_lane_brief": "Record what he reports.",
          "lanes": {"garden": {"brief": "Bed by bed.", "file": "Garden.md"}}}


@pytest.fixture
def vault(tmp_path):
    progress = tmp_path / "progress.md"
    progress.write_text("# the board\n\n```json\n" + json.dumps(PROGRESS) + "\n```\n", encoding="utf-8")
    extras = tmp_path / "extras.json"
    extras.write_text(json.dumps(EXTRAS), encoding="utf-8")
    return progress, extras


@pytest.fixture
def imported(db, vault):
    progress, extras = vault
    call_command("import_life", str(progress), "--extras", str(extras), verbosity=0)
    return progress, extras


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(db, vault, capsys):
    call_command("import_life", str(vault[0]), "--extras", str(vault[1]), "--dry-run")
    printed = capsys.readouterr().out
    assert Tracker.objects.count() == 0
    assert "practice early_walk" in printed and "NO BRIEF" in printed
    for reason in ("without a date", "watch paint", "1 timeline events"):
        assert reason in printed


def test_the_import_writes_trackers_events_and_one_state_per_lane(imported):
    stretch = Tracker.objects.get(slug="stretch")
    assert stretch.subject == {"color": "red", "started": "2031-02-20", "alert_after": 3, "rank": 0}
    assert stretch.brief == "Any ten minutes count." and stretch.view == "campaign_map"
    assert sorted(stretch.observations.values_list("summary", flat=True)) == [
        "(imported: an event day with no text in the log)", "Stretched for ten minutes"]
    assert Tracker.objects.get(slug="early_walk").status == "paused"
    garden = Tracker.objects.get(slug="garden")
    assert garden.subject == {"short": "Garden", "file": "Garden.md", "rank": 0} and garden.brief == "Bed by bed."
    state = garden.assessments.get().state
    assert state["level"] == "focus" and state["changed"] == [] and state["next"] == {"text": "Order timber", "hot": True}
    assert "burning" not in state and garden.assessments.get().evidence.get().payload == {"station": "dig"}
    tasks = Tracker.objects.get(slug="tasks")
    assert tasks.status == "paused" and tasks.brief == "Record what he reports."
    assert {item["id"]: item["state"] for item in campaign.stations_of(tasks.assessments.get().state)} == {
        "glaze": "passed", "permit": "ahead"}


def test_the_board_is_built_from_the_rows(imported):
    board = life.board(DAY)
    assert [(tile["id"], tile["n"], tile["state"]) for tile in board["pulse"]] == [("stretch", 2, "warn"), ("no_snacks", 5, "good")]
    assert [lane["id"] for lane in board["lanes"]] == ["garden"] and board["quiet"] == ["Boat", "Tasks"]
    garden = board["lanes"][0]
    assert (garden["_meta"], garden["_wide"], garden["short"]) == ("1 / 3 · chk Mar 12", False, "Garden")
    assert "next" not in garden and "level" not in garden
    assert board["focus"] == [{"title": "Garden", "why": "spring", "rank": 1, "campaign": "garden"}]
    assert board["burning"] == [] and board["burning_more"] == 0
    assert board["next"] == [{"text": "Order timber", "source": "Garden", "hot": True}]
    assert [(item["station"], item["campaign"]) for item in board["trail"]] == [("glaze", "Tasks"), ("dig", "Garden")]
    assert [(day["date"], [item["label"] for item in day["items"]]) for day in board["horizon"]] == [
        ("2031-03-11", ["Tasks: Harbour permit"]), ("2031-03-12", ["Garden"]), ("2031-03-15", ["Boat: Sand the hull"])]


def test_a_check_date_that_has_gone_by_burns_until_it_is_moved(imported):
    late = life.board(datetime.date(2031, 3, 16))
    assert [(item["campaign"], item.get("station"), item["since"], item["why"]) for item in late["burning"]] == [
        ("garden", None, "Mar 12", life.OVERDUE), ("boat", "hull", "Mar 15", life.OVERDUE),
        ("tasks", "permit", "Mar 11", life.OVERDUE)]
    garden = Tracker.objects.get(slug="garden")
    tools.record_observation("garden", "2031-03-16", "", "Look again at the end of the month.")
    tools.record_assessment("garden", {"check": "2031-03-30"}, "He moved the date.",
                            [garden.observations.order_by("-id").first().pk])
    assert "garden" not in [item["campaign"] for item in life.board(datetime.date(2031, 3, 16))["burning"]]


def test_a_second_import_is_refused_and_replace_starts_over(imported, tracker):
    progress, extras = imported
    with pytest.raises(CommandError, match="already exist"):
        call_command("import_life", str(progress), verbosity=0)
    tools.record_observation("stretch", "2031-03-09", "", "Stretched.")
    call_command("import_life", str(progress), "--replace", "--events-until", "2031-03-05", verbosity=0)
    assert Tracker.objects.get(slug="stretch").observations.count() == 1
    assert Tracker.objects.get(slug="no_snacks").observations.count() == 1
    assert Tracker.objects.filter(slug=tracker.slug).exists(), "replace drops life trackers only"


def test_the_import_never_takes_another_trackers_slug(db, vault):
    Tracker.objects.create(slug="garden", title="Garden centres", kind="topic", subject={"query": "garden centres"}, brief="-")
    with pytest.raises(CommandError, match="already exist"):
        call_command("import_life", str(vault[0]), "--replace", verbosity=0)
    assert Tracker.objects.count() == 1


def test_the_api_serves_the_board_and_lists_the_new_kinds(imported, monkeypatch):
    monkeypatch.setattr(life, "today", lambda: DAY)
    board = Client().get("/api/life").json()
    assert board["today"] == "2031-03-10" and board == json.loads(json.dumps(life.board(DAY)))
    listed = {row["slug"]: row for row in Client().get("/api/trackers").json()}
    assert listed["garden"]["level"] == "focus" and listed["stretch"]["level"] is None


# ---------------- the check against the vault's renderer ----------------

RENDERER = '''
import json, pathlib
def validate(data): pass
def derive(data, today): return json.loads((pathlib.Path(__file__).parent / "board.json").read_text())
def jsonable(view): return view
'''


def test_the_check_passes_on_the_known_differences_and_fails_on_any_other(imported, tmp_path, capsys):
    progress, _ = imported
    old = life.board(DAY)
    old["quiet"] = ["Boat"]
    old["trail"] = [{**item, "label": "the log's own wording", "station": "garden." + item["station"]} for item in old["trail"]]
    old["lanes"][0].update(burning=False, burning_why="", note=None)
    renderer = tmp_path / "renderer.py"
    renderer.write_text(RENDERER)
    (tmp_path / "board.json").write_text(json.dumps(old))
    call_command("import_life", str(progress), "--check", "--on", "2031-03-10", "--renderer", str(renderer))
    printed = capsys.readouterr().out
    assert "quiet         equal plus the tasks lane" in printed and "trail         same stations and dates" in printed
    assert "lanes         equal" in printed and "DIFFERENT" not in printed
    old["pulse"][0]["n"] = 7
    (tmp_path / "board.json").write_text(json.dumps(old))
    with pytest.raises(CommandError, match="differ"):
        call_command("import_life", str(progress), "--check", "--on", "2031-03-10", "--renderer", str(renderer))
    assert "pulse         DIFFERENT" in capsys.readouterr().out


def test_overdue_checks_are_a_known_difference():
    late = {"title": "Garden", "since": "Mar 12", "why": life.OVERDUE, "path": "Garden", "rank": 100, "campaign": "garden"}
    flagged = {"title": "Boat", "since": "", "why": "leaks", "path": "Boat", "rank": 1, "campaign": "boat"}
    empty = {key: [] for key in ("pulse", "focus", "horizon", "trail", "next", "lanes", "quiet")}
    old = {**empty, "today": "2031-03-16", "burning": [flagged], "burning_more": 0, "focus_more": 0}
    new = {**old, "burning": [flagged, late]}
    verdicts = {key: (verdict, acceptable) for key, verdict, acceptable in import_life.compare(old, new)}
    assert verdicts["burning"] == ("equal plus 1 overdue check(s), derived at read", True)
    assert not import_life.compare(old, {**old, "burning": [late, flagged, {**flagged, "why": "other"}]})[2][2]
