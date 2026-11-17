import numpy as np

from chouzhen_core.detection import Row, RowTracker, similarity


def row(seed, y=96):
    image = np.random.default_rng(seed).integers(0, 255, (44, 210), dtype=np.uint8)
    return Row(1450, y, 0.95, image)


def test_colored_avatar_can_be_learned():
    avatar = np.random.default_rng(2).integers(0, 255, (34, 62, 3), dtype=np.uint8)
    assert similarity(avatar, avatar.copy()) > 0.99


def test_persistent_and_moving_rows_are_not_new_kills():
    tracker = RowTracker()
    for t in (1, 1.1, 1.2):
        tracker.update([row(1)], t)
    for t in (1.3, 1.4, 1.5):
        tracker.update([row(1), row(2, 135)], t)
    for t in (2.0, 2.1, 2.2):
        tracker.update([row(2, 96)], t)
    assert [event.time for event in tracker.events] == [1, 1.3]


def test_new_row_while_old_one_disappears_keeps_same_count_but_is_new_kill():
    tracker = RowTracker()
    for t in (1, 1.1, 1.2):
        tracker.update([row(1)], t)
    for t in (1.3, 1.4, 1.5):
        tracker.update([row(2)], t)
    assert len(tracker.events) == 2


def test_rows_visible_at_video_start_are_not_counted_as_new_kills():
    tracker = RowTracker()
    for t in (0, 0.1, 0.2, 0.3):
        tracker.update([row(1)], t)
    assert not tracker.events


def test_one_frame_flash_is_not_a_kill():
    tracker = RowTracker()
    tracker.update([row(1)], 1)
    tracker.update([], 1.1)
    tracker.update([], 3)
    assert not tracker.events
