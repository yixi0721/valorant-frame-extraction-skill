import os
from pathlib import Path

import pytest

from chouzhen_core.engine import analyze


def test_user_sample_kills_and_edit_boundaries(tmp_path):
    supplied = os.environ.get("CHOUZHEN_REFERENCE_VIDEO")
    if not supplied:
        pytest.skip("Set CHOUZHEN_REFERENCE_VIDEO to the supplied 25-second validation video.")
    result = analyze(Path(supplied), tmp_path)
    expected = [6.06, 17.58, 19.42, 20.28]
    assert len(result.kills) == 4
    for event, timestamp in zip(result.kills, expected):
        assert event.time == pytest.approx(timestamp, abs=0.12)
    assert [k.id for k in result.kills if k.removed > 0] == [2, 4]
    assert result.removed == pytest.approx(0.5, abs=0.017)
    for event in result.kills:
        if event.removed:
            assert event.cut_start >= event.burst_start + 0.049
            assert event.cut_end <= event.time - 0.099
