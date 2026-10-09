import pytest


@pytest.fixture
def tracker(db):
    from core.models import Tracker
    return Tracker.objects.create(slug="vram-supply", title="VRAM supply and pricing", kind="topic",
                                  subject={"query": "GDDR7 and HBM supply, pricing"}, brief="Watch vendor pricing and supply news.")
