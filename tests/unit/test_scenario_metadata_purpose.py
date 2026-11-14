"""D-06: scenario purpose / review focus are scenario data (metadata), validated by the definition model."""

from pathlib import Path

import pytest
import yaml

from scenario_db.models.definition.usecase import Usecase, UsecaseMetadata

FIXTURE = Path(__file__).resolve().parents[2] / "db_Exynos2600_SM-S947B" / "02_definition"


def test_metadata_takes_purpose_and_review_focus():
    m = UsecaseMetadata(name="x", purpose="p", review_focus=["a", "b"])
    assert (m.purpose, m.review_focus) == ("p", ["a", "b"])
    assert UsecaseMetadata(name="y").review_focus == []


@pytest.mark.parametrize("path", sorted(FIXTURE.glob("uc-*.yaml")), ids=lambda p: p.stem)
def test_every_e2600_scenario_declares_its_purpose(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    usecase = Usecase.model_validate(doc)
    if usecase.metadata.canonical_usecase == "uc-cam-recording":
        # Exynos2700 inherits this scenario and keeps its own ejected copy (not changed here), so recording
        # uses the UI's fallback text until both projects take the metadata together
        assert usecase.metadata.purpose is None
        return
    assert usecase.metadata.purpose and len(usecase.metadata.purpose) > 20
    # recording keeps the recording-mode lenses (no review_focus); the other scenarios declare theirs
    recording = usecase.metadata.canonical_usecase in ("uc-cam-recording", "uc-cam-recording-apv")
    assert bool(usecase.metadata.review_focus) is not recording
