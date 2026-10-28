"""`country_risk`: one country's security and political situation, researched
on the web by one session a week that files its sources as observations and
one judgment as the assessment: a peace score with its reason, an overview, a
12–24 month outlook, and the six lenses. Ported from the conflict map
(geo_status_bashboard/research/country.py): same rubric, same heat
definitions. Where the port filed an open list of conflicts, the record now
judges a fixed set of lenses every run: on 2026-10-24 and 2026-10-26 France
was filed cold while Paris rioted, because the one search on unrest came back
stale and "found nothing" was accepted as calm. Every lens needs a page
opened in the last 30 days, calm included. The level is the hottest lens,
derived here and never asked of the agent."""
import json
from datetime import date, timedelta

import pycountry
from django.utils import timezone

from core.kinds import level_change_alert, validate

VIEW = "globe"

# Coolest first. calm is a lens with nothing of its kind in the last year.
LEVELS = ("calm", "dormant", "cold", "warm", "hot")

# The one definition of each heat. The research prompt renders this dict, so the
# agent grades lenses by exactly what is written here; the globe's legend
# (dashboard/src/views/Globe.tsx) copies these lines, change both together.
HEAT_DEFINITIONS = {
    "hot": "organized violence in the last 30 days, or imminent",
    "warm": "violence with casualties in the last 12 months, or active mobilization",
    "cold": "tension without violence in the last 12 months",
    "dormant": "frozen or historic, no activity in over a year, could reignite",
    "calm": "nothing of the kind in the last 12 months",
}

# What is judged for every country, every run. Rendered into the prompt; the
# globe's lens switch and record copy the keys and words, change both together.
LENSES = {
    "security": "armed conflict, terrorism, insurgency, and standoffs with other states",
    "internal_stability": "unrest on the street: protests, riots, strikes, violent crime, and the economy as it drives them",
    "political_stability": "the government and institutions: censure, elections, constitutional crises, power grabs",
    "antisemitism": "violence, intimidation and incidents against Jews, and the state's response",
    "islam": "Islamist extremism and tension around Islam: radicalization, violence or intimidation in its name, "
             "friction with Jews and the wider society, and the state's response",
    "migration": "migration and integration: arrivals, camps, deportations, and violence or unrest around migrants",
}

# A heat comes down only once this long has passed since the latest event it
# rested on: a riot is not over because this week's search did not find it.
HOLD_DAYS = 30
MAX_SEARCHES = 14

# A peace score move of this much or more between two judgments is a trend.
TREND_STEP = 5

PEACE_SCORE_RUBRIC = """Peace score rubric:
90-100 no armed conflict, stable institutions, low violent crime, low exposure to a wider war.
70-89 stable with notable friction: political polarization, some crime, or distant exposure to a wider war.
50-69 real risks: cold conflicts that could turn, high crime in places, contested institutions, meaningful exposure to a regional war.
30-49 serious: recurring violence, insurgency or terrorism in parts of the country, fragile institutions.
0-29 active war, occupation or state collapse."""

SUBJECT_SCHEMA = {
    "iso3": (str, True),
    "name": (str, False),       # filled from the ISO list
    "numeric": (str, False),    # filled from the ISO list: the id the globe's polygons carry
}

# An observation is one source the research session used.
PAYLOAD_SCHEMA = {
    "title": (str, False),
    "undated": (bool, False),   # the page shows no date; observed_at is then the day it was read
}

STATE_SCHEMA = {
    "level": (str, False),               # derived from the lenses; a value that disagrees is an error
    "peace_score": (int, True),
    "peace_score_reason": (str, True),
    "overview": (str, True),
    "outlook": (str, True),
    "lenses": (dict, True),              # every key of LENSES, each a LENS_SCHEMA record
    "trend": (str, False),               # derived from the previous judgment's score
    "peace_score_change": (int, False),  # derived likewise
}

LENS_SCHEMA = {
    "heat": (str, True),
    "summary": (str, True),
    "detail": (str, True),
    "latest_event": (str, False),        # YYYY-MM-DD of the latest event the heat rests on; required for warm and hot
    "source_urls": (list, True),
    "held_until": (str, False),          # derived: the day the previous heat may come down
}
# Longer text is rejected, not cut: the prompt states the limits, so it is the agent breaking them.
TEXT_LIMITS = {"summary": 300, "peace_score_reason": 300}

DEFAULT_JOBS = ({"kind": "assess", "target": "agent.flows.research.run"},)


def country(iso3: str):
    found = pycountry.countries.get(alpha_3=(iso3 or "").upper())
    if found is None:
        raise ValueError(f"subject.iso3 {iso3!r} is not an ISO 3166-1 alpha-3 code")
    return found


def validate_subject(subject: dict) -> dict:
    """Checks the code and fills the name and numeric id from the ISO list."""
    validate(subject, SUBJECT_SCHEMA, "subject")
    found = country(subject["iso3"])
    # The common name where ISO has one ('Iran', not 'Iran, Islamic Republic of').
    return {"iso3": found.alpha_3, "name": getattr(found, "common_name", found.name), "numeric": found.numeric}


def validate_payload(payload: dict) -> dict:
    return validate(payload, PAYLOAD_SCHEMA, "payload")


def _limited(values: dict, label: str) -> None:
    for field, limit in TEXT_LIMITS.items():
        if field in values and len(values[field]) > limit:
            raise ValueError(f"{label}.{field} must be at most {limit} characters, got {len(values[field])}")


def _day(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must be a YYYY-MM-DD date, got {value!r}") from None


def validate_lens(lens: dict, label: str) -> dict:
    validate(lens, LENS_SCHEMA, label)
    _limited(lens, label)
    if lens["heat"] not in HEAT_DEFINITIONS:
        raise ValueError(f"{label}.heat must be one of {', '.join(HEAT_DEFINITIONS)}, got {lens['heat']!r}")
    for text_field in ("summary", "detail"):
        if not lens[text_field].strip():
            raise ValueError(f"{label}.{text_field} must not be empty")
    urls = lens["source_urls"]
    if not urls or not all(isinstance(url, str) and url.startswith(("http://", "https://")) for url in urls):
        raise ValueError(f"{label}.source_urls needs at least one http(s) URL you opened: calm is sourced like anything else")
    if lens.get("latest_event") is not None:
        _day(lens["latest_event"], f"{label}.latest_event")
    elif lens["heat"] in ("warm", "hot"):
        raise ValueError(f"{label}.latest_event is required when the heat is {lens['heat']}: the date of the latest event")
    if "held_until" in lens:
        raise ValueError(f"{label}.held_until is derived; leave it out")
    return lens


def _hold(lens: dict, previous_lens: dict | None, today: date) -> dict:
    """Keeps the previous heat while its latest event is under HOLD_DAYS old."""
    if not previous_lens or previous_lens.get("latest_event") is None:
        return lens
    if LEVELS.index(lens["heat"]) >= LEVELS.index(previous_lens["heat"]):
        return lens
    may_cool_on = _day(previous_lens["latest_event"], "previous latest_event") + timedelta(days=HOLD_DAYS)
    if today >= may_cool_on:
        return lens
    return {**lens, "heat": previous_lens["heat"], "latest_event": previous_lens["latest_event"],
            "held_until": may_cool_on.isoformat()}


def validate_state(state: dict, previous=None, test_today: date | None = None) -> dict:
    """Checks the record lens by lens, holds a heat that is still inside its
    window, derives the level from the lenses and the trend from the previous
    judgment. Fails loudly on anything unsourced or out of the rubric, so the
    agent can fix it and call again."""
    validate(state, STATE_SCHEMA, "state")
    _limited(state, "state")
    if not 0 <= state["peace_score"] <= 100:
        raise ValueError(f"state.peace_score must be 0 to 100, got {state['peace_score']}")
    for text_field in ("peace_score_reason", "overview", "outlook"):
        if not state[text_field].strip():
            raise ValueError(f"state.{text_field} must not be empty")
    missing = set(LENSES) - set(state["lenses"])
    unknown = set(state["lenses"]) - set(LENSES)
    if missing or unknown:
        raise ValueError(f"state.lenses must hold exactly {', '.join(LENSES)}: every lens is judged every run"
                         + (f"; missing {', '.join(sorted(missing))}" if missing else "")
                         + (f"; unknown {', '.join(sorted(unknown))}" if unknown else ""))
    today = test_today or timezone.localdate()
    previous_lenses = (previous.state.get("lenses") or {}) if previous is not None else {}
    for key in LENSES:
        lens = validate_lens(state["lenses"][key], f"state.lenses.{key}")
        state["lenses"][key] = _hold(lens, previous_lenses.get(key), today)
    level = max((lens["heat"] for lens in state["lenses"].values()), key=LEVELS.index)
    if state.get("level") not in (None, level):
        raise ValueError(f"state.level is derived from the lenses ({level}); leave it out")
    state["level"] = level
    if previous is not None:
        change = state["peace_score"] - previous.state["peace_score"]
        state["peace_score_change"] = change
        state["trend"] = "improving" if change >= TREND_STEP else "worsening" if change <= -TREND_STEP else "stable"
    else:
        state.pop("peace_score_change", None)
        state.pop("trend", None)
    return state


alert_for = level_change_alert


def research_prompt(tracker, previous, lens: str | None = None) -> str:
    """The weekly brief judges all six lenses in one pass of at most MAX_SEARCHES
    searches, about two per lens; `lens` turns the run into a study of that one
    lens with every search spent on it, the other five carried over from the
    record on file. Guy asked for the first on 2026-10-28, Portugal on
    antisemitism, which the pass had judged on a single page."""
    name, iso3 = tracker.subject["name"], tracker.subject["iso3"]
    heat_lines = "\n".join(f"- {heat}: {definition}" for heat, definition in HEAT_DEFINITIONS.items())
    lens_lines = "\n".join(f"- {key}: {definition}" for key, definition in LENSES.items())
    if previous:
        previous_line = (f"Previous judgment ({previous.at:%Y-%m-%d}): peace score {previous.state['peace_score']}, level "
                         f"{previous.level}. Reason then: {previous.state['peace_score_reason']}")
        held = [f"{key}: {lens['heat']} since {lens['latest_event']}" for key, lens in (previous.state.get("lenses") or {}).items()
                if lens["heat"] in ("warm", "hot")]
        if held:
            previous_line += "\nHeats on file that only come down " + f"{HOLD_DAYS} days after their latest event: " + "; ".join(held)
    else:
        previous_line = "No previous judgment: this is the first."
    if lens is None:
        lens_brief = f"Six lenses, every one judged every run:\n{lens_lines}"
        search_brief = (f"Search the web for the latest, at most {MAX_SEARCHES} searches: at least one per lens, naming the "
                        "country and the lens's subject.")
    else:
        if lens not in LENSES:
            raise ValueError(f"lens must be one of {', '.join(LENSES)}")
        if not previous or not previous.state.get("lenses"):
            raise ValueError("a lens study needs a record with lenses on file: research the whole country first")
        others = {key: value for key, value in previous.state["lenses"].items() if key != lens}
        lens_brief = (f"This run studies one lens in depth, {lens}: {LENSES[lens]}. The other five lenses are not researched: "
                      "put them in the state exactly as on file, which is\n" + json.dumps(others, indent=1))
        search_brief = (f"Search the web for the latest, up to {MAX_SEARCHES} searches, all on {lens} in {name} from different "
                        "angles: incidents of the last 30 days and of the last 12 months, community and watchdog reports, "
                        "official statistics, and the state's response (police, prosecutors, courts, government).")
    return "\n\n".join([
        f"Research {name} ({iso3}) for the tracker \"{tracker.title}\" (slug: {tracker.slug}).",
        f"Standing brief:\n{tracker.brief}",
        previous_line,
        lens_brief,
        search_brief + " A search whose results are all older than 30 days is not a finding, it is a stale index: search "
        "again with different words in extended mode before concluding anything. Open the page a heat rests on; a calm lens "
        "needs an opened page from the last 30 days that covers the subject and shows nothing happening. Prefer primary and "
        "reputable sources (governments, UN agencies, International Crisis Group, ACLED, Reuters, AP, major national press). "
        "Never invent facts, dates or URLs.",
        "Step 1. For every page you rely on, call record_observation once: slug, observed_at = the page's date (or today's date "
        "with payload {\"undated\": true} when it shows none), source_url, a one-sentence summary of what the page says, and "
        "payload {\"title\": the page title}. Keep the ids it returns.",
        "Step 2. Call record_assessment exactly once with reason = the peace score reason, evidence_ids = the observation ids, "
        "and state of exactly this shape:\n"
        "{\n"
        "  \"peace_score\": <0-100 integer, rubric below>,\n"
        "  \"peace_score_reason\": \"one sentence, max 300 characters\",\n"
        "  \"overview\": \"2-4 sentences: the country's security and political situation today\",\n"
        "  \"outlook\": \"2-4 sentences: the next 12-24 months, including exposure to a wider regional or world war\",\n"
        "  \"lenses\": { <each lens key>: {\n"
        "    \"heat\": <one of the heats below>, \"summary\": \"one sentence, max 300 characters\",\n"
        "    \"detail\": \"1-3 paragraphs: what is happening, why, what changed recently\",\n"
        "    \"latest_event\": \"YYYY-MM-DD of the latest event the heat rests on; required for warm and hot, null when nothing dated\",\n"
        "    \"source_urls\": [\"https://... pages you opened\"]\n"
        "  } }\n"
        "}\n"
        "Do not set level: it is derived from the hottest lens. Do not set held_until: the judge keeps a warm or hot heat "
        f"until {HOLD_DAYS} days after its latest event, whatever this run finds.",
        f"Heats (how violent the lens is right now):\n{heat_lines}",
        PEACE_SCORE_RUBRIC,
        ("Finish with one line: the peace score, the level, and the change since the previous judgment in a few words."
         if lens is None else f"Refresh the peace score, its reason, the overview and the outlook only where {lens} changes "
         f"them. Finish with one line: the {lens} heat and what changed since the record on file."),
    ])
