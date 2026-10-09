"""`topic`: anything described by a query the agent researches on the web —
antisemitism by region, VRAM supply and pricing, a company's hiring. The
generic kind; three of the four requests in the brief need nothing else."""
from core.kinds import validate

VIEW = "feed"

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

# Jobs a new topic tracker gets. The cadence word from the request ("weekly")
# is the collect schedule. Assessment arrives in the next phase.
DEFAULT_JOBS = ({"kind": "collect", "target": "agent.flows.collect.run"},)

MAX_NEW_OBSERVATIONS_PER_RUN = 10


def validate_subject(subject: dict) -> dict:
    return validate(subject, SUBJECT_SCHEMA, "subject")


def validate_payload(payload: dict) -> dict:
    return validate(payload, PAYLOAD_SCHEMA, "payload")


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
