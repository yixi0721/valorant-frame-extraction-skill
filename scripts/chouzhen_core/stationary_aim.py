"""Build the render timeline from visually reviewed, zero-based source frames."""
from __future__ import annotations

from bisect import bisect_left
from pathlib import Path
from threading import Event
import json

from .media import executable, run_capture
from .models import Analysis, Media
from .planning import remaining_ranges


def source_timestamps(media: Media, cancel: Event | None) -> list[float]:
    data = json.loads(run_capture([
        executable("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", media.path,
    ], cancel))
    frames = data["frames"]
    if not frames or any("best_effort_timestamp_time" not in frame for frame in frames):
        raise ValueError("源视频缺少显示时间戳，无法按复核帧号剪接。")
    times = [float(frame["best_effort_timestamp_time"]) - media.origin for frame in frames]
    if any(left >= right for left, right in zip(times, times[1:])):
        raise ValueError("源视频显示时间戳未严格递增，无法区分剪接边界。")
    return times


def frame_index(value: int, count: int) -> int:
    if type(value) is not int or not 0 <= value < count:
        raise ValueError(f"源帧号 {value!r} 无效，有效范围为 0 到 {count - 1}。")
    return value


def reviewed_aim(analysis: Analysis, path: Path, cancel: Event | None = None):
    review = json.loads(path.read_text(encoding="utf-8-sig"))
    if (path.parent / review["source"]).resolve() != Path(analysis.media.path).resolve():
        raise ValueError("复核明细与分析方案指向不同的源录像。")
    times = source_timestamps(analysis.media, cancel)
    count = len(times)
    if review.get("source_frames", count) != count:
        raise ValueError("复核明细的源帧数与录像不符。")

    candidates = {event.id: event for event in analysis.kills}
    events = {}
    intervals = []
    flashes = set()
    feedback = set()
    for group in review["kills"]:
        event_id = group["source_analysis_id"]
        if event_id not in candidates or event_id in events:
            raise ValueError(f"复核明细中的击杀 ID {event_id} 无法对应唯一的原始候选。")
        event = candidates[event_id]
        shots = {frame_index(frame, count) for frame in group["retained_muzzle_flash_frames"]}
        flashes.update(shots)
        if group.get("first_feedback_frame") is not None:
            feedback.add(frame_index(group["first_feedback_frame"], count))
        frame_total = 0
        for item in group["removed_intervals"]:
            start = frame_index(item["start_frame"], count)
            end = frame_index(item["end_frame_exclusive"], count)
            if not (start < end and 0 <= times[start] < times[end] <= analysis.media.duration):
                raise ValueError(f"击杀 {event_id} 的删除区间 [{start}, {end}) 无效。")
            if item.get("first_retained_action") == "开枪" and end not in shots:
                raise ValueError(f"击杀 {event_id} 的第 {end} 帧未标记为枪口闪光。")
            intervals.append((start, end))
            frame_total += end - start
        events[event_id] = {
            "id": event_id, "time_seconds": round(event.time, 6), "thumbnail": event.thumbnail,
            "applied": bool(frame_total), "cut_intervals": len(group["removed_intervals"]),
            "removed_frames": frame_total,
        }

    intervals.sort()
    protected = sorted(flashes | feedback)
    previous_end = -1
    for start, end in intervals:
        if start <= previous_end:
            raise ValueError(f"区间 [{start}, {end}) 覆盖上一段删除区间或它的首个保留帧。")
        index = bisect_left(protected, start)
        if index < len(protected) and protected[index] < end:
            raise ValueError(f"区间 [{start}, {end}) 包含需保留的开枪或击杀反馈帧 {protected[index]}。")
        previous_end = end

    cuts = [(times[start], times[end]) for start, end in intervals]
    report = {
        "preset": "stationary-aim", "review": str(path.resolve()), "source": analysis.media.path,
        "source_duration_seconds": analysis.media.duration, "candidates": len(candidates),
        "kills": len(events), "edited_kills": sum(event["applied"] for event in events.values()),
        "cut_intervals": len(cuts), "retained_shots": len(flashes),
        "removed_frames": sum(end - start for start, end in intervals),
        "removed_seconds": round(sum(end - start for start, end in cuts), 6),
        "events": list(events.values()), "status": "completed" if cuts else "no_edits",
    }
    return remaining_ranges(analysis.media.duration, cuts), report
