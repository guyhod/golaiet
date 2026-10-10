"""The tracker kinds: one module per kind, found by name.

A kind owns the shape of a tracker's subject, of its observations' payload and
of its assessments' state; its ordered LEVELS (coolest first); the prompts that
collect and judge for it; the rule that turns a new assessment into an alert
(alert_for); and the jobs a new tracker of that kind gets. Adding a kind is a
code change; adding a tracker of an existing kind is rows."""
from importlib import import_module

NAMES = ("topic",)

# Cadence words the agent may use, as crontab in settings.TIME_ZONE.
CADENCES = {
    "hourly": "0 * * * *",
    "daily": "0 7 * * *",
    "weekly": "0 7 * * mon",
}


def choices() -> list[tuple[str, str]]:
    return [(name, name) for name in NAMES]


def get(name: str):
    if name not in NAMES:
        raise ValueError(f"unknown tracker kind {name!r}; known: {', '.join(NAMES)}")
    return import_module(f"core.kinds.{name}")


def validate(values: dict, schema: dict[str, tuple[type, bool]], label: str) -> dict:
    """Check a JSON dict against {field: (type, required)}. Unknown keys are an
    error, not ignored: a silently dropped key is how a $16 run happened in the
    investment engine (a misspelled param nobody noticed)."""
    if not isinstance(values, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(values) - set(schema)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    for field, (expected_type, required) in schema.items():
        if field not in values:
            if required:
                raise ValueError(f"{label} is missing required field {field!r}")
            continue
        value = values[field]
        if value is None and not required:
            continue
        if isinstance(value, bool) or not isinstance(value, (expected_type, int) if expected_type is float else expected_type):
            raise ValueError(f"{label}.{field} must be {expected_type.__name__}, got {type(value).__name__}")
    return values
