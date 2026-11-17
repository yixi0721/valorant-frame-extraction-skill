from __future__ import annotations

from threading import Event
import math

from .media import frame_times
from .models import Analysis, Kill

PRESETS = {"natural": 0.25, "snappy": 0.60}


def apply_preset(analysis: Analysis, preset: str = "natural") -> None:
    if preset not in PRESETS:
        raise ValueError(f"未知抽帧强度：{preset}")
    analysis.preset = preset
    for event in analysis.kills:
        if event.safe_start is None or event.safe_end is None:
            event.cut_start = event.cut_end = None
            continue
        maximum = min(PRESETS[preset], event.safe_end - event.safe_start)
        frames = math.floor((maximum + 1e-6) * analysis.media.fps)
        if frames < 3:
            event.cut_start = event.cut_end = None
            event.reason = "射击间隔很短，保留原动作"
        else:
            event.cut_start = event.safe_start
            target = min(event.safe_end, event.safe_start + frames / analysis.media.fps)
            options = [point for point in event.cut_points if point <= target + 1e-6]
            event.cut_end = options[-1] if options else target
            event.reason = "压缩连续射击，保留开枪与击杀反馈"


def build_plan(analysis: Analysis, cancel: Event | None = None) -> None:
    for event in analysis.kills:
        if event.burst_start is None:
            event.reason = "未找到可靠的射击起点，保留原动作"
            continue
        # 3 frames of the opening shot and at least 100 ms ahead of the kill-feed onset stay intact.
        desired_start = event.burst_start + max(0.05, 3 / analysis.media.fps)
        desired_end = event.time - max(0.10, 5 / analysis.media.fps)
        if desired_end - desired_start < 3 / analysis.media.fps:
            event.reason = "射击间隔很短，保留原动作"
            continue
        timestamps = frame_times(analysis.media, event.burst_start, event.time, cancel)
        starts = [t for t in timestamps if t >= desired_start - 1e-6]
        ends = [t for t in timestamps if t <= desired_end + 1e-6]
        if starts and ends and ends[-1] - starts[0] >= 3 / analysis.media.fps:
            event.safe_start, event.safe_end = starts[0], ends[-1]
            event.cut_points = [t for t in timestamps if event.safe_start <= t <= event.safe_end]
        else:
            event.reason = "射击间隔很短，保留原动作"
    apply_preset(analysis, analysis.preset)


def set_removed_frames(event: Kill, frames: int, fps: float) -> None:
    if event.safe_start is None or event.safe_end is None:
        return
    duration = min(max(0, frames) / fps, event.safe_end - event.safe_start)
    event.cut_start = event.safe_start
    event.cut_end = (event.cut_points[min(max(0, frames), len(event.cut_points) - 1)]
                     if event.cut_points else event.safe_start + duration)


def removed_frames(event: Kill, fps: float) -> int:
    if event.cut_start is None or event.cut_end is None:
        return 0
    if event.cut_points:
        return sum(event.cut_start <= t < event.cut_end - 1e-6 for t in event.cut_points)
    return round((event.cut_end - event.cut_start) * fps)


def cut_ranges(analysis: Analysis) -> list[tuple[float, float]]:
    cuts = []
    for event in analysis.kills:
        if not event.enabled or event.cut_start is None or event.cut_end is None:
            continue
        start, end = event.cut_start, event.cut_end
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= analysis.media.duration):
            raise ValueError(f"击杀 {event.id} 的抽帧区间无效。")
        if end - start > 0.001:
            cuts.append((start, end))
    merged: list[tuple[float, float]] = []
    for start, end in sorted(cuts):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def keep_ranges(analysis: Analysis) -> list[tuple[float, float]]:
    segments = []
    cursor = 0.0
    for start, end in cut_ranges(analysis):
        if start > cursor:
            segments.append((cursor, start))
        cursor = end
    if cursor < analysis.media.duration:
        segments.append((cursor, analysis.media.duration))
    if not segments:
        raise ValueError("剪辑结果为空。")
    return segments


def source_to_output(time: float, analysis: Analysis) -> float:
    removed = 0.0
    for start, end in cut_ranges(analysis):
        if time < start:
            break
        removed += max(0, min(time, end) - start)
    return max(0.0, time - removed)


def output_to_source(time: float, analysis: Analysis) -> float:
    offset = 0.0
    for start, end in cut_ranges(analysis):
        if time < start - offset:
            break
        offset += end - start
    return min(analysis.media.duration, time + offset)
