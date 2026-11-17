from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from threading import Event
import json
import os
import shutil
import subprocess

from .models import Cancelled, Media

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def executable(name: str) -> str:
    result = shutil.which(name)
    if result is None:
        raise RuntimeError(f"未找到 {name}，请安装 FFmpeg 并加入 PATH。")
    return result


def check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def run_capture(arguments: list[str], cancel: Event | None = None) -> str:
    with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=CREATE_FLAGS) as process:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    process.kill()
                    process.communicate()
                    raise Cancelled()
        if process.returncode:
            raise RuntimeError(stderr.decode("utf-8", errors="replace")[-3000:])
        return stdout.decode("utf-8", errors="replace")


def probe(path: Path, cancel: Event | None = None) -> Media:
    path = path.resolve(strict=True)
    data = json.loads(run_capture([executable("ffprobe"), "-v", "error", "-show_streams",
                                  "-show_format", "-of", "json", str(path)], cancel))
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("文件中没有视频画面。")
    duration = float(data["format"].get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise ValueError("无法读取视频时长。")
    fps = float(Fraction(video.get("r_frame_rate", "60/1")))
    if fps <= 0:
        raise ValueError("无法读取视频帧率。")
    stat = path.stat()
    origin = float(data["format"].get("start_time", 0))
    return Media(str(path), duration, video["width"], video["height"], fps,
                 float(video.get("start_time", 0)) - origin,
                 any(s["codec_type"] == "audio" for s in data["streams"]),
                 stat.st_size, stat.st_mtime_ns, origin)


def frame_times(media: Media, start: float, end: float, cancel: Event | None = None) -> list[float]:
    # read_intervals may seek to the preceding keyframe; filter the returned PTS explicitly.
    data = json.loads(run_capture([
        executable("ffprobe"), "-v", "error", "-select_streams", "v:0",
        "-read_intervals", f"{max(0, start + media.origin):.6f}%{end + media.origin:.6f}", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", media.path,
    ], cancel))
    return [float(f["best_effort_timestamp_time"]) - media.origin for f in data.get("frames", [])
            if "best_effort_timestamp_time" in f
            and start <= float(f["best_effort_timestamp_time"]) - media.origin <= end]
