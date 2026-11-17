from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
import cv2
import numpy as np

from .media import check_cancel
from .models import Kill, Media

Progress = Callable[[float, str], None]


def normalize(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(frame, (1920, 1080)) if frame.shape[:2] != (1080, 1920) else frame


@dataclass
class Row:
    x: int
    y: int
    confidence: float
    signature: np.ndarray


def signature(frame: np.ndarray, y: int) -> np.ndarray:
    # Victim name + portrait identify a record even when earlier records disappear and rows move.
    return cv2.cvtColor(frame[max(0, y - 4):y + 40, 1690:1900], cv2.COLOR_BGR2GRAY)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or min(a.shape[:2]) < 12:
        return 0.0
    inner = b[6:-6, 4:-4]
    return float(cv2.minMaxLoc(cv2.matchTemplate(a, inner, cv2.TM_CCOEFF_NORMED))[1])


class HudDetector:
    """Learn the local player's highlighted avatar from the video, never from a bundled hero crop."""

    def __init__(self) -> None:
        self.templates: list[np.ndarray] = []
        self.seed: tuple[np.ndarray, int] | None = None

    def _border_candidates(self, frame: np.ndarray) -> list[Row]:
        hsv = cv2.cvtColor(frame[80:370, 1200:1905], cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (20, 55, 145), (45, 255, 255))
        expanded = cv2.dilate(mask, np.ones((5, 1), np.uint8)) > 0
        scores = (expanded[:-33, :540] & expanded[33:, :540]).sum(axis=1)
        indices = np.flatnonzero(scores >= 55)
        if not len(indices):
            return []
        result = []
        for group in np.split(indices, np.where(np.diff(indices) > 1)[0] + 1):
            y = int(group[np.argmax(scores[group])])
            xs = np.flatnonzero(expanded[y, :540] & expanded[y + 33, :540])
            x = int(xs[0])
            patch = hsv[y + 8:y + 27, x + 65:min(x + 155, 705)]
            if not patch.size:
                continue
            green = ((patch[:, :, 0] >= 60) & (patch[:, :, 0] <= 100) &
                     (patch[:, :, 1] > 45) & (patch[:, :, 2] > 85)).mean()
            if green < 0.25:
                continue
            absolute_y, absolute_x = y + 80, x + 1200
            result.append(Row(absolute_x, absolute_y, min(0.99, float(scores[y]) / 120),
                              signature(frame, absolute_y)))
        return result

    def rows(self, frame: np.ndarray) -> list[Row]:
        result: list[Row] = []
        roi = frame[80:370, 1200:1840]
        for template in self.templates:
            response = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            for _ in range(7):
                _, confidence, _, (x, y) = cv2.minMaxLoc(response)
                if confidence < 0.78:
                    break
                absolute_y = y + 80
                if not any(abs(row.y - absolute_y) < 16 for row in result):
                    result.append(Row(x + 1200, absolute_y, confidence, signature(frame, absolute_y)))
                response[max(0, y - 20):y + 21, max(0, x - 65):x + 66] = -1
        if result:
            self.seed = None
            return sorted(result, key=lambda row: row.y)

        candidates = self._border_candidates(frame)
        if not candidates:
            self.seed = None
            return []
        candidate = max(candidates, key=lambda row: row.confidence)
        crop = frame[candidate.y + 2:candidate.y + 36, candidate.x:candidate.x + 62].copy()
        count = 1
        if self.seed is not None:
            old, old_count = self.seed
            if old.shape == crop.shape and similarity(old, crop) > 0.72:
                count = old_count + 1
        self.seed = (crop, count)
        if count >= 2 and len(self.templates) < 8:
            self.templates.append(crop)
        return candidates


@dataclass
class Track:
    patch: np.ndarray
    first_seen: float
    last_seen: float
    observations: int
    event: Kill | None = None
    initial: bool = False


class RowTracker:
    def __init__(self) -> None:
        self.tracks: list[Track] = []
        self.events: list[Kill] = []
        self.evidence: dict[int, np.ndarray] = {}

    def update(self, rows: list[Row], time: float) -> None:
        self.tracks = [track for track in self.tracks if time - track.last_seen < 1.5]
        used: set[int] = set()
        for row in rows:
            options = [(similarity(track.patch, row.signature), i)
                       for i, track in enumerate(self.tracks) if i not in used]
            score, index = max(options, default=(0.0, -1))
            if score >= 0.72:
                track = self.tracks[index]
                track.last_seen = time
                track.observations += 1
                if score > 0.88:
                    track.patch = row.signature
            else:
                index = len(self.tracks)
                track = Track(row.signature, time, time, 1, initial=time < 0.25)
                self.tracks.append(track)
            used.add(index)
            if track.observations >= 3 and track.event is None and not track.initial:
                track.event = Kill(len(self.events) + 1, track.first_seen, round(row.confidence, 3))
                self.events.append(track.event)
                self.evidence[track.event.id] = row.signature.copy()


def detect(media: Media, artifacts: Path, progress: Progress, cancel: Event | None = None) -> list[Kill]:
    capture = cv2.VideoCapture(media.path)
    if not capture.isOpened():
        raise RuntimeError("无法解码录像。")
    detector, tracker = HudDetector(), RowTracker()
    stride = max(1, round(media.fps / 12))
    index = 0
    try:
        while capture.grab():
            check_cancel(cancel)
            if index % stride == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    raise RuntimeError("读取视频画面失败。")
                time = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000 + media.video_start
                tracker.update(detector.rows(normalize(frame)), time)
                progress(min(0.65, time / media.duration * 0.65), f"正在识别 · {len(tracker.events)} 次击杀")
            index += 1
    finally:
        capture.release()
    artifacts.mkdir(parents=True, exist_ok=True)
    # Revisit each newly observed record at source frame rate; sampling is only for discovery.
    capture = cv2.VideoCapture(media.path)
    try:
        for event in tracker.events:
            template = tracker.evidence[event.id][6:-6, 4:-4]
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, event.time - 0.4 - media.video_start) * 1000)
            first_match = None
            consecutive = 0
            while True:
                check_cancel(cancel)
                ok, frame = capture.read()
                if not ok:
                    break
                time = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000 + media.video_start
                if time > event.time + 0.15:
                    break
                gray = cv2.cvtColor(normalize(frame)[75:380, 1685:1905], cv2.COLOR_BGR2GRAY)
                score = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1]
                if score >= 0.80:
                    first_match = time if first_match is None else first_match
                    consecutive += 1
                    if consecutive >= 2:
                        event.time = first_match
                        break
                else:
                    first_match, consecutive = None, 0
    finally:
        capture.release()
    return tracker.events


def ammo_mask(frame: np.ndarray) -> np.ndarray:
    roi = frame[1004:1047, 1260:1331].astype(np.int16)
    return ((roi.min(axis=2) > 190) & ((roi.max(axis=2) - roi.min(axis=2)) < 65)).astype(np.uint8)


def inspect_shots(media: Media, events: list[Kill], artifacts: Path, progress: Progress,
                  cancel: Event | None = None) -> None:
    # Decode only local windows. PTS, rather than frame_number / rounded_fps, drives the edit.
    capture = cv2.VideoCapture(media.path)
    try:
        for position, event in enumerate(events):
            check_cancel(cancel)
            start = max(0, event.time - 1.5)
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0, start - media.video_start) * 1000)
            previous = None
            changes: list[float] = []
            thumbnail = None
            while True:
                check_cancel(cancel)
                ok, frame = capture.read()
                if not ok:
                    break
                time = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000 + media.video_start
                if time > event.time + 0.13:
                    break
                frame = normalize(frame)
                mask = ammo_mask(frame)
                if previous is not None and 100 <= int(mask.sum()) <= 1400:
                    if np.count_nonzero(mask != previous) > 65 and time <= event.time + 0.015:
                        if not changes or time - changes[-1] >= 0.055:
                            changes.append(time)
                previous = mask
                if time >= event.time:
                    thumbnail = cv2.resize(frame, (480, 270))
            if thumbnail is not None:
                path = artifacts / f"kill-{event.id:03d}.jpg"
                cv2.imencode(".jpg", thumbnail)[1].tofile(str(path))
                event.thumbnail = str(path.resolve())
            prior = events[position - 1].time + 0.12 if position else 0
            changes = [time for time in changes if time > prior]
            if changes and event.time - changes[-1] <= 0.30:
                burst_start = changes[-1]
                for earlier, later in zip(reversed(changes[:-1]), reversed(changes[1:])):
                    if later - earlier > 0.25:
                        break
                    burst_start = earlier
                event.burst_start = burst_start
            progress(0.65 + (position + 1) / max(1, len(events)) * 0.25,
                     f"正在定位射击 · {position + 1}/{len(events)}")
    finally:
        capture.release()
