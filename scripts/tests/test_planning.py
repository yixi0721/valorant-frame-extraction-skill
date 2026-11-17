import pytest

from chouzhen_core.models import Analysis, Kill, Media
from chouzhen_core.planning import (apply_preset, cut_ranges, keep_ranges, output_to_source,
                            removed_frames, set_removed_frames, source_to_output)


def analysis(kills):
    return Analysis(Media("test.mp4", 10, 1920, 1080, 60, 0, True, 0, 0), kills)


def test_disabled_edits_and_overlapping_intervals():
    result = analysis([Kill(1, 3, 1, cut_start=1, cut_end=2),
                       Kill(2, 4, 1, cut_start=1.5, cut_end=3),
                       Kill(3, 6, 1, cut_start=5, cut_end=6, enabled=False)])
    assert cut_ranges(result) == [(1, 3)]
    assert keep_ranges(result) == [(0, 1), (3, 10)]


def test_time_mapping_across_cuts_and_at_seams():
    result = analysis([Kill(1, 3, 1, cut_start=1, cut_end=2),
                       Kill(2, 6, 1, cut_start=4, cut_end=4.5)])
    assert source_to_output(1.5, result) == 1
    assert output_to_source(1, result) == 2
    assert source_to_output(5, result) == 3.5
    assert output_to_source(3.5, result) == 5


def test_frame_adjustment_uses_real_pts_for_variable_frame_rate():
    event = Kill(1, 2, 1, safe_start=1, safe_end=1.1,
                 cut_points=[1, 1.016, 1.050, 1.067, 1.1])
    set_removed_frames(event, 2, 60)
    assert event.cut_end == 1.050
    assert removed_frames(event, 60) == 2
    set_removed_frames(event, 100, 60)
    assert event.cut_end == 1.1


def test_short_shot_is_preserved_and_presets_stay_within_safe_window():
    short = Kill(1, 3, 1, safe_start=1, safe_end=1.03)
    long = Kill(2, 6, 1, safe_start=4, safe_end=4.4)
    result = analysis([short, long])
    apply_preset(result, "natural")
    assert short.cut_start is None
    assert long.removed == pytest.approx(0.25)
    apply_preset(result, "snappy")
    assert long.cut_end <= long.safe_end


@pytest.mark.parametrize("start,end", [(-1, 2), (1, 11), (3, 2), (1, float("nan"))])
def test_invalid_edits_are_rejected(start, end):
    with pytest.raises(ValueError):
        keep_ranges(analysis([Kill(1, 5, 1, cut_start=start, cut_end=end)]))
