"""Run the bundled engine from any working directory; no desktop application is required."""
from __future__ import annotations

import argparse
from datetime import datetime
import importlib
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from threading import Event
import time
import json

sys.dont_write_bytecode = True

from chouzhen_core.models import Analysis, Cancelled


def emit(value, stream=None):
    print(json.dumps(value, ensure_ascii=False), file=stream or sys.stdout, flush=True)


def environment():
    result = {"python": sys.version.split()[0], "python_executable": sys.executable,
              "packages": {}, "tools": {}, "missing": []}
    if sys.version_info < (3, 12):
        result["missing"].append("Python 3.12+")
    for module_name in ("numpy", "cv2"):
        try:
            module = importlib.import_module(module_name)
            result["packages"][module_name] = module.__version__
        except (ImportError, OSError) as error:
            result["missing"].append(f"{module_name}: {error}")
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        result["tools"][name] = path
        if path is None:
            result["missing"].append(name)
    if result["tools"]["ffmpeg"]:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        check = subprocess.run([result["tools"]["ffmpeg"], "-hide_banner", "-encoders"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=10, creationflags=flags)
        if check.returncode or "libx264" not in check.stdout:
            result["missing"].append("FFmpeg with libx264")
    result["ready"] = not result["missing"]
    return result


def new_workdir(video: Path, requested: Path | None):
    if requested is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        requested = video.parent / "chouzhen-output" / f"{video.stem}-{stamp}"
    destination = requested.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("输出目录必须为空；请使用新目录，或复用已有 analysis.json 重新导出。")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def output_path(path: Path, extension: str, overwrite: bool):
    destination = path.resolve()
    if destination.suffix.lower() != extension:
        raise ValueError(f"输出文件应使用 {extension} 扩展名。")
    if destination.exists() and not overwrite:
        raise ValueError("目标文件已存在，请使用其他文件名；确需覆盖时加 --overwrite。")
    return destination


def summary(result: Analysis, project: Path):
    from chouzhen_core.planning import cut_ranges, removed_frames
    removed = sum(end - start for start, end in cut_ranges(result))
    payload = {
        "analysis": str(project.resolve()), "source": result.media.path,
        "preset": result.preset, "kills": len(result.kills),
        "edited_kills": sum(event.removed > 0 for event in result.kills),
        "removed_seconds": round(removed, 6),
        "source_duration_seconds": result.media.duration,
        "events": [{"id": event.id, "time_seconds": round(event.time, 6),
                    "applied": event.removed > 0,
                    "removed_frames": removed_frames(event, result.media.fps) if event.enabled else 0,
                    "reason": event.reason, "thumbnail": event.thumbnail}
                   for event in result.kills],
    }
    payload["status"] = "completed" if removed else "no_edits"
    if not result.kills:
        payload["notice"] = "未识别到自己的击杀；请检查视角和 HUD，不能据此断定录像没有击杀。"
    return payload


def parser():
    root = argparse.ArgumentParser(description="无畏契约录像：识别自己的击杀并自动抽帧")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="只检查运行环境，不安装依赖")
    for command in ("run", "analyze"):
        child = commands.add_parser(command, help="分析并导出" if command == "run" else "只分析，保存剪辑方案")
        child.add_argument("video", type=Path)
        child.add_argument("--output-dir", type=Path, help="空输出目录；默认在录像旁新建任务目录")
        child.add_argument("--preset", choices=("natural", "snappy"), default="natural")
        if command == "run":
            child.add_argument("--preview", action="store_true", help="输出最高 720p 预览，默认输出原分辨率")
    export = commands.add_parser("render", help="复用分析文件导出 MP4")
    export.add_argument("analysis", type=Path)
    export.add_argument("--output", "-o", required=True, type=Path)
    export.add_argument("--preview", action="store_true")
    export.add_argument("--overwrite", action="store_true")
    edit = commands.add_parser("edit", help="修改预设、逐次开关或删帧数，保存为新方案")
    edit.add_argument("analysis", type=Path)
    edit.add_argument("--output", "-o", type=Path)
    edit.add_argument("--preset", choices=("natural", "snappy"))
    edit.add_argument("--disable", type=int, nargs="+", default=[], metavar="ID")
    edit.add_argument("--enable", type=int, nargs="+", default=[], metavar="ID")
    edit.add_argument("--frames", action="append", default=[], metavar="ID=N")
    edit.add_argument("--overwrite", action="store_true")
    return root


def edit_plan(args):
    from chouzhen_core.planning import apply_preset, set_removed_frames
    result = Analysis.load(args.analysis)
    if not (args.preset or args.enable or args.disable or args.frames):
        raise ValueError("请指定 --preset、--enable、--disable 或 --frames。")
    by_id = {event.id: event for event in result.kills}
    if set(args.enable) & set(args.disable):
        raise ValueError("同一次击杀不能同时启用和禁用。")
    frame_changes = {}
    for value in args.frames:
        try:
            event_id, frames = map(int, value.split("="))
        except ValueError:
            raise ValueError("--frames 格式为 击杀ID=删帧数，例如 2=8。") from None
        if event_id in frame_changes:
            raise ValueError(f"击杀 {event_id} 的帧数设置重复。")
        frame_changes[event_id] = frames
    unknown = (set(args.enable) | set(args.disable) | set(frame_changes)) - by_id.keys()
    if unknown:
        raise ValueError(f"没有这些击杀 ID：{sorted(unknown)}")
    if args.preset:
        apply_preset(result, args.preset)
    for event_id in args.disable:
        by_id[event_id].enabled = False
    for event_id in args.enable:
        by_id[event_id].enabled = True
    for event_id, frames in frame_changes.items():
        event = by_id[event_id]
        if event.safe_start is None or event.safe_end is None:
            raise ValueError(f"击杀 {event_id} 没有可抽帧区间，不能强行设置帧数。")
        maximum = (len(event.cut_points) - 1 if event.cut_points
                   else int((event.safe_end - event.safe_start) * result.media.fps + 1e-4))
        if not 0 <= frames <= maximum:
            raise ValueError(f"击杀 {event_id} 可设置为 0–{maximum} 帧。")
        set_removed_frames(event, frames, result.media.fps)
    target = args.output or args.analysis.with_name(args.analysis.stem + ".edited.json")
    target = output_path(target, ".json", args.overwrite)
    if target == Path(result.media.path).resolve():
        raise ValueError("剪辑方案不能覆盖原始录像。")
    result.save(target)
    return summary(result, target)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    cancel = Event()
    old_handlers = {}
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            old_handlers[signum] = signal.signal(signum, lambda *_: cancel.set())
    last_update = 0.0

    def progress(value, message):
        nonlocal last_update
        now = time.monotonic()
        if now - last_update >= 0.5 or value == 1:
            emit({"progress": round(value, 3), "message": message}, sys.stderr)
            last_update = now

    try:
        if args.command == "check":
            report = environment()
            emit(report)
            return 0 if report["ready"] else 2
        if sys.version_info < (3, 12):
            raise ValueError("请使用 Python 3.12 或更高版本。")
        if args.command == "edit":
            payload = edit_plan(args)
        elif args.command in ("run", "analyze"):
            from chouzhen_core.engine import analyze
            video = args.video.resolve(strict=True)
            directory = new_workdir(video, args.output_dir)
            scale = 0.45 if args.command == "run" else 1
            result = analyze(video, directory, args.preset,
                             lambda v, t: progress(v * scale, t), cancel)
            payload = summary(result, directory / "analysis.json")
            if args.command == "run":
                from chouzhen_core.rendering import render
                from chouzhen_core.media import probe
                target = directory / ("preview.mp4" if args.preview else "result.mp4")
                render(result, target, lambda v, t: progress(0.45 + v * 0.55, t), cancel, args.preview)
                payload["output"] = str(target)
                payload["output_duration_seconds"] = probe(target, cancel).duration
        elif args.command == "render":
            from chouzhen_core.rendering import render
            from chouzhen_core.media import probe
            result = Analysis.load(args.analysis)
            target = output_path(args.output, ".mp4", args.overwrite)
            render(result, target, progress, cancel, args.preview)
            payload = summary(result, args.analysis)
            payload["output"] = str(target)
            payload["output_duration_seconds"] = probe(target, cancel).duration
        payload["operation"] = args.command
        emit(payload)
        return 0
    except (Cancelled, KeyboardInterrupt):
        emit({"status": "cancelled"}, sys.stderr)
        return 130
    except ImportError as error:
        emit({"error": str(error), "hint": "使用 check 检查所选 Python 环境；运行依赖见 scripts/requirements.txt。"}, sys.stderr)
        return 1
    except Exception as error:
        emit({"error": str(error)}, sys.stderr)
        return 1
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
