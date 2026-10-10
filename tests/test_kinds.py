import pytest

from core import kinds
from core.kinds import topic


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError, match="unknown tracker kind"):
        kinds.get("stock")


def test_topic_subject_requires_query():
    with pytest.raises(ValueError, match="missing required field 'query'"):
        topic.validate_subject({"regions": ["FR"]})
    assert topic.validate_subject({"query": "x", "regions": ["FR", "UK"]})


def test_unknown_payload_field_is_rejected_not_dropped():
    with pytest.raises(ValueError, match="unknown fields: severty"):
        topic.validate_payload({"severty": 3})


def test_payload_types_are_checked():
    assert topic.validate_payload({"severity": 3, "figure": 12, "unit": "USD"}) == {"severity": 3, "figure": 12, "unit": "USD"}
    with pytest.raises(ValueError, match="severity must be int"):
        topic.validate_payload({"severity": "high"})
    with pytest.raises(ValueError, match="severity must be int"):
        topic.validate_payload({"severity": True})


def test_collect_prompt_lists_recent_and_caps(tracker):
    from django.utils import timezone
    from core.models import Observation
    Observation.objects.create(tracker=tracker, observed_at=timezone.now(), source_url="https://a.example/1", summary="HBM3E prices up 10%")
    prompt = topic.collect_prompt(tracker, tracker.observations.all())
    assert "https://a.example/1" in prompt and "HBM3E prices up 10%" in prompt
    assert f"at most {topic.MAX_NEW_OBSERVATIONS_PER_RUN}" in prompt
    assert tracker.brief in prompt


def test_topic_alert_rule_fires_on_level_change_only():
    from types import SimpleNamespace
    from core.kinds import topic
    tracker = SimpleNamespace(title="VRAM")
    watch = SimpleNamespace(level="watch", reason="Prices up.")
    assert topic.alert_for(tracker, None, SimpleNamespace(level="quiet", reason="Calm.")) is None
    assert topic.alert_for(tracker, None, watch) == "VRAM: quiet → watch. Prices up."
    assert topic.alert_for(tracker, watch, SimpleNamespace(level="watch", reason="Still.")) is None
    assert topic.alert_for(tracker, watch, SimpleNamespace(level="quiet", reason="Eased.")) == "VRAM: watch → quiet. Eased."
