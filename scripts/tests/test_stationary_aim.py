import json

import pytest

from chouzhen_core import stationary_aim
from chouzhen_core.models import Analysis, Kill, Media


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    media = Media(str(tmp_path / "source.mp4"), .5, 320, 180, 30, .04, True, 1, 0, origin=10)
    analysis = Analysis(media, [Kill(2, .43, .9)])
    frames = [10.04, 10.07, 10.12, 10.18, 10.28, 10.35, 10.43, 10.46]
    monkeypatch.setattr(stationary_aim, "run_capture", lambda *_: json.dumps({
        "frames": [{"best_effort_timestamp_time": str(t)} for t in frames],
    }))
    group = {"source_analysis_id": 2, "retained_muzzle_flash_frames": [4],
             "first_feedback_frame": 6, "removed_intervals": []}
    path = tmp_path / "cuts.json"

    def apply(intervals):
        group["removed_intervals"] = [{"start_frame": a, "end_frame_exclusive": b} for a, b in intervals]
        path.write_text(json.dumps({"source": "source.mp4", "kills": [group]}), encoding="utf-8")
        return stationary_aim.reviewed_aim(analysis, path)

    return apply


def test_variable_frame_times_and_nonzero_origin_keep_the_first_flash(reviewed):
    segments, report = reviewed([(1, 4)])
    assert segments[0] == pytest.approx((0, .07))
    assert segments[1] == pytest.approx((.28, .5))
    assert report["removed_frames"] == 3
    assert report["removed_seconds"] == pytest.approx(.21)


@pytest.mark.parametrize("intervals", [[(3, 5)], [(5, 7)], [(0, 2), (2, 4)]])
def test_cannot_remove_a_marked_flash_feedback_or_resumed_movement(reviewed, intervals):
    with pytest.raises(ValueError, match="保留"):
        reviewed(intervals)
