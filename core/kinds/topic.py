"""`topic`: anything described by a query the agent researches on the web —
antisemitism by region, VRAM supply and pricing, a company's hiring. The
generic kind; three of the four requests in the brief need nothing else."""
from core.kinds import validate

VIEW = "feed"

# Coolest first. The dashboard orders tiles by position in this tuple.
LEVELS = ("quiet", "watch", "elevated", "critical")

SUBJECT_SCHEMA = {
    "query": (str, True),        # what to search for, in the agent's words
    "regions": (list, False),    # optional country codes or region names to split by
}

PAYLOAD_SCHEMA = {
    "region": (str, False),
    "category": (str, False),    # e.g. incident, policy, price, supply
    "severity": (int, False),    # 1 (minor) … 5 (major), the agent's call
    "figure": (float, False),    # a number the fact carries (a price, a count)
    "unit": (str, False),
}

STATE_SCHEMA = {
    "level": (str, True),        # one of LEVELS
    "score": (float, False),     # 0 (nothing going on) … 100 (as bad as this topic gets), the agent's call
}

# The collect job runs at the cadence of the request ("weekly"); the judge runs
# weekly an hour after the Monday collect, so the week's findings are filed first.
ASSESS_SCHEDULE = "0 8 * * mon"
DEFAULT_JOBS = (
    {"kind": "collect", "target": "agent.flows.collect.run"},
    {"kind": "assess", "target": "agent.flows.assess.run", "schedule": ASSESS_SCHEDULE},
)

MAX_NEW_OBSERVATIONS_PER_RUN = 10


def validate_subject(subject: dict) -> dict:
    return validate(subject, SUBJECT_SCHEMA, "subject")


def validate_payload(payload: dict) -> dict:
    return validate(payload, PAYLOAD_SCHEMA, "payload")


def validate_state(state: dict) -> dict:
    validate(state, STATE_SCHEMA, "state")
    if state["level"] not in LEVELS:
        raise ValueError(f"state.level must be one of {', '.join(LEVELS)}, got {state['level']!r}")
    return state


def alert_for(tracker, previous, new) -> str | None:
    """The alert rule: a level change is told to Guy, the same level again is
    not. A tracker with no judgment yet counts as the coolest level."""
    before = previous.level if previous else LEVELS[0]
    if before == new.level:
        return None
    return f"{tracker.title}: {before} → {new.level}. {new.reason}"


def collect_prompt(tracker, recent_observations) -> str:
    recent = "\n".join(
        f"- {observation.observed_at:%Y-%m-%d} {observation.source_url or '(no url)'}: {observation.summary}"
        for observation in recent_observations) or "- (none yet)"
    regions = tracker.subject.get("regions")
    region_line = f"Split findings by region where it matters: {', '.join(regions)}.\n" if regions else ""
    return (
        f"You are collecting observations for the tracker \"{tracker.title}\" (slug: {tracker.slug}).\n\n"
        f"Query: {tracker.subject['query']}\n{region_line}\n"
        f"Standing brief:\n{tracker.brief}\n\n"
        f"Already recorded (do not file these again):\n{recent}\n\n"
        "Search the web for what is new since the most recent observation above (or the last 7 days if none). "
        "Prefer primary sources and major press. For each distinct fact worth keeping, call "
        "record_observation once with the source URL, the date it was published, a one-or-two-sentence "
        f"summary in your own words with the figure if there is one, and a payload with only these fields: "
        f"{', '.join(PAYLOAD_SCHEMA)}. File at most {MAX_NEW_OBSERVATIONS_PER_RUN} observations. "
        "If nothing new was found, record nothing and say so. "
        "Finish with one short paragraph: what you filed and what you skipped."
    )


def assess_prompt(tracker, observations, previous) -> str:
    listed = "\n".join(
        f"- id {observation.pk} · {observation.observed_at:%Y-%m-%d} · {observation.summary}"
        f" ({observation.source_url or 'no url'})"
        for observation in observations) or "- (none)"
    if previous:
        previous_line = (f"Previous judgment ({previous.at:%Y-%m-%d}): level {previous.level}"
                         f"{', score ' + str(previous.state['score']) if previous.state.get('score') is not None else ''}."
                         f" Reason then: {previous.reason}")
    else:
        previous_line = "No previous judgment: this is the first."
    return (
        f"You are judging the tracker \"{tracker.title}\" (slug: {tracker.slug}).\n\n"
        f"Query: {tracker.subject['query']}\n\n"
        f"Standing brief:\n{tracker.brief}\n\n"
        f"{previous_line}\n\n"
        f"Observations filed since then (newest first):\n{listed}\n\n"
        f"Decide the level now: one of {', '.join(LEVELS)}, where {LEVELS[0]} means nothing that needs Guy's "
        f"attention and {LEVELS[-1]} means he should act or decide today. Optionally a score from 0 to 100. "
        "Then call record_assessment exactly once with state, a reason of two to four sentences that cites dates "
        "and figures from the observations, and evidence_ids listing the ids you relied on. Judge only from the "
        "observations above and the brief; never invent. Finish with one line: the level and why in a few words."
    )
