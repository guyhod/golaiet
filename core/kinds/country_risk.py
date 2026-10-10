"""`country_risk`: one country's security and political situation, researched
on the web by one session a week that files its sources as observations and
one judgment as the assessment: a peace score with its reason, an overview, a
12–24 month outlook, and the country's conflicts. Ported from the conflict map
(geo_status_bashboard/research/country.py): same rubric, same heat and kind
definitions, same validator. The level is the hottest conflict's heat, derived
from the conflict list and never asked of the agent."""
import pycountry

from core.kinds import level_change_alert, validate

VIEW = "globe"

# Coolest first. calm is a researched country with no conflict at all.
LEVELS = ("calm", "dormant", "cold", "warm", "hot")

# The one definition of each heat. The research prompt renders this dict, so the
# agent grades conflicts by exactly what is written here; the globe's legend
# (dashboard/src/views/Globe.tsx) copies these lines, change both together.
HEAT_DEFINITIONS = {
    "hot": "organized violence in the last 30 days, or imminent",
    "warm": "violence with casualties in the last 12 months, or active mobilization",
    "cold": "tension without violence in the last 12 months",
    "dormant": "frozen or historic, no activity in over a year, could reignite",
}

CONFLICT_KIND_DEFINITIONS = {
    "war": "interstate or large-scale armed conflict",
    "insurgency": "armed non-state groups against the state",
    "terrorism": "violence against civilians by non-state groups, meant to spread fear",
    "civil_unrest": "protests, riots, strikes",
    "political": "constitutional crisis, power grabs, contested elections",
    "sectarian": "religious, ethnic or communal rifts",
    "diplomatic": "state-to-state tension without violence",
    "crime": "organized or violent crime that shapes daily safety",
    "economic": "sanctions, blockades, resource disputes",
}
SCOPES = ("internal", "external")
PLACE_KINDS = ("city", "area")
MAX_CONFLICTS = 12
MAX_SEARCHES = 8

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
    "level": (str, False),               # derived from the conflicts; a value that disagrees is an error
    "peace_score": (int, True),
    "peace_score_reason": (str, True),
    "overview": (str, True),
    "outlook": (str, True),
    "conflicts": (list, True),
    "trend": (str, False),               # derived from the previous judgment's score
    "peace_score_change": (int, False),  # derived likewise
}

CONFLICT_SCHEMA = {
    "title": (str, True), "kind": (str, True), "scope": (str, True), "heat": (str, True),
    "summary": (str, True), "detail": (str, True), "parties": (list, True), "since": (str, False),
    "place": (dict, False), "counterpart_iso3": (str, False), "source_urls": (list, True),
}
PLACE_SCHEMA = {"name": (str, True), "kind": (str, True), "latitude": (float, True), "longitude": (float, True)}
# Longer text is rejected, not cut: the prompt states the limits, so it is the agent breaking them.
TEXT_LIMITS = {"title": 150, "summary": 300, "since": 20, "peace_score_reason": 300}

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


def _choice(values: dict, field: str, allowed, label: str) -> None:
    if values[field] not in allowed:
        raise ValueError(f"{label}.{field} must be one of {', '.join(allowed)}, got {values[field]!r}")


def validate_conflict(conflict: dict, label: str) -> dict:
    validate(conflict, CONFLICT_SCHEMA, label)
    _limited(conflict, label)
    _choice(conflict, "kind", CONFLICT_KIND_DEFINITIONS, label)
    _choice(conflict, "scope", SCOPES, label)
    _choice(conflict, "heat", HEAT_DEFINITIONS, label)
    for text_field in ("title", "summary", "detail"):
        if not conflict[text_field].strip():
            raise ValueError(f"{label}.{text_field} must not be empty")
    if not all(isinstance(party, str) for party in conflict["parties"]):
        raise ValueError(f"{label}.parties must be a list of strings")
    urls = conflict["source_urls"]
    if not urls or not all(isinstance(url, str) and url.startswith(("http://", "https://")) for url in urls):
        raise ValueError(f"{label}.source_urls needs at least one http(s) URL: an unsourced conflict is not kept")
    place = conflict.get("place")
    if place is not None:
        validate(place, PLACE_SCHEMA, f"{label}.place")
        _choice(place, "kind", PLACE_KINDS, f"{label}.place")
        if not (-90 <= place["latitude"] <= 90 and -180 <= place["longitude"] <= 180):
            raise ValueError(f"{label}.place coordinates are out of range")
        if len(place["name"]) > 100:
            raise ValueError(f"{label}.place.name must be at most 100 characters")
    if conflict.get("counterpart_iso3"):
        conflict["counterpart_iso3"] = country(conflict["counterpart_iso3"]).alpha_3
    return conflict


def validate_state(state: dict, previous=None) -> dict:
    """Checks the record field by field, derives the level from the conflicts
    and the trend from the previous judgment. Fails loudly on anything unsourced
    or out of the rubric, so the agent can fix it and call again."""
    validate(state, STATE_SCHEMA, "state")
    _limited(state, "state")
    if not 0 <= state["peace_score"] <= 100:
        raise ValueError(f"state.peace_score must be 0 to 100, got {state['peace_score']}")
    for text_field in ("peace_score_reason", "overview", "outlook"):
        if not state[text_field].strip():
            raise ValueError(f"state.{text_field} must not be empty")
    if len(state["conflicts"]) > MAX_CONFLICTS:
        raise ValueError(f"state.conflicts holds {len(state['conflicts'])}, at most {MAX_CONFLICTS} allowed; keep the most important")
    for index, conflict in enumerate(state["conflicts"]):
        validate_conflict(conflict, f"state.conflicts[{index}]")
    level = max((conflict["heat"] for conflict in state["conflicts"]), key=LEVELS.index, default=LEVELS[0])
    if state.get("level") not in (None, level):
        raise ValueError(f"state.level is derived from the conflicts ({level}); leave it out")
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


def research_prompt(tracker, previous) -> str:
    name, iso3 = tracker.subject["name"], tracker.subject["iso3"]
    heat_lines = "\n".join(f"- {heat}: {definition}" for heat, definition in HEAT_DEFINITIONS.items())
    kind_lines = "\n".join(f"- {kind}: {definition}" for kind, definition in CONFLICT_KIND_DEFINITIONS.items())
    if previous:
        previous_line = (f"Previous judgment ({previous.at:%Y-%m-%d}): peace score {previous.state['peace_score']}, level "
                         f"{previous.level}. Reason then: {previous.state['peace_score_reason']}")
    else:
        previous_line = "No previous judgment: this is the first."
    return "\n\n".join([
        f"Research {name} ({iso3}) for the tracker \"{tracker.title}\" (slug: {tracker.slug}).",
        f"Standing brief:\n{tracker.brief}",
        previous_line,
        f"Search the web for the latest, at most {MAX_SEARCHES} searches. Prefer primary and reputable sources (governments, UN "
        "agencies, International Crisis Group, ACLED, Reuters, AP, major national press). Never invent facts, dates or URLs.",
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
        "  \"conflicts\": [ {\n"
        "    \"title\": \"short name, max 150 characters\", \"kind\": <one of the kinds below>, \"scope\": \"internal\" | \"external\",\n"
        "    \"heat\": <one of the heats below>, \"summary\": \"one sentence, max 300 characters\",\n"
        "    \"detail\": \"1-3 paragraphs: what is happening, why, what changed recently\", \"parties\": [\"...\"],\n"
        "    \"since\": \"YYYY-MM-DD or YYYY\", \"place\": null | {\"name\": \"...\", \"kind\": \"city\" | \"area\", \"latitude\": <float>, \"longitude\": <float>},\n"
        "    \"counterpart_iso3\": null | \"ISO3 of the other state in an external conflict\", \"source_urls\": [\"https://...\"]\n"
        "  } ]\n"
        "}\n"
        "Do not set level: it is derived from the hottest conflict.",
        f"Heats (how violent the conflict is right now):\n{heat_lines}",
        f"Kinds:\n{kind_lines}",
        "Scope: internal is within the country's own society or state; external is with another state or a foreign actor. "
        "Place: pin a conflict to a city or an area when it is concentrated there, null when country-wide. Cover every active or "
        "frozen armed conflict, terrorism and insurgency; political crises; sectarian, ethnic or religious rifts; crime that shapes "
        f"daily life; diplomatic standoffs; economic warfare. Between 0 and {MAX_CONFLICTS} conflicts, most important first; a "
        "country with nothing notable returns an empty list. Every conflict needs at least one source URL you actually opened.",
        PEACE_SCORE_RUBRIC,
        "Finish with one line: the peace score, the level, and the change since the previous judgment in a few words.",
    ])
