from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from uuid import uuid4
import subprocess

from .detection import Progress
from .media import CREATE_FLAGS, check_cancel, executable
from .models import Analysis, Cancelled
from .planning import keep_ranges


def render(analysis: Analysis, output: Path, progress: Progress,
           cancel: Event | None = None, preview: bool = False, *,
           segments: list[tuple[float, float]] | None = None) -> Path:
    analysis.media.verify_source()
    output = output.resolve()
    if output == Path(analysis.media.path).resolve():
        raise ValueError("导出文件不能覆盖原始录像。")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.stem}-{uuid4().hex[:8]}.partial.mp4")
    graph_path = partial.with_suffix(".filters.txt")
    log_path = output.with_suffix(".ffmpeg.log")
    if segments is None:
        segments = keep_ranges(analysis)
    expected = sum(end - start for start, end in segments)
    count = len(segments)
    graph = []
    graph.append(f"[0:v]split={count}" + "".join(f"[vs{i}]" for i in range(count)))
    if analysis.media.has_audio:
        graph.append(f"[0:a:0]asplit={count}" + "".join(f"[as{i}]" for i in range(count)))
    for i, (start, end) in enumerate(segments):
        graph.append(f"[vs{i}]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{i}]")
        if analysis.media.has_audio:
            duration = end - start
            fade = ""
            if count > 1 and duration > 0.02:
                fade = f",afade=t=in:d=0.003,afade=t=out:st={duration - 0.003:.6f}:d=0.003"
            graph.append(f"[as{i}]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS{fade}[a{i}]")
    inputs = "".join(f"[v{i}]" + (f"[a{i}]" if analysis.media.has_audio else "") for i in range(count))
    graph.append(inputs + f"concat=n={count}:v=1:a={int(analysis.media.has_audio)}[video]" +
                 ("[audio]" if analysis.media.has_audio else ""))
    if preview and analysis.media.height > 720:
        graph.append("[video]scale=-2:720[scaled]")
    graph_path.write_text(";\n".join(graph), encoding="utf-8")
    command = [executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-copyts", "-start_at_zero", "-i", analysis.media.path,
               "-filter_complex_script", str(graph_path), "-map",
               "[scaled]" if preview and analysis.media.height > 720 else "[video]"]
    if analysis.media.has_audio:
        command += ["-map", "[audio]", "-c:a", "aac", "-b:a", "192k"]
    command += ["-c:v", "libx264", "-preset", "veryfast" if preview else "fast",
                "-crf", "23" if preview else "18", "-pix_fmt", "yuv420p",
                "-r", f"{analysis.media.fps:.6f}", "-fps_mode", "cfr", "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats", str(partial)]
    process = None
    try:
        check_cancel(cancel)
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log,
                                       text=True, encoding="utf-8", creationflags=CREATE_FLAGS)
            lines: Queue[str] = Queue()

            def consume() -> None:
                assert process is not None and process.stdout is not None
                for line in process.stdout:
                    lines.put(line.strip())

            reader = Thread(target=consume, daemon=True)
            reader.start()
            while process.poll() is None:
                check_cancel(cancel)
                try:
                    line = lines.get(timeout=0.1)
                except Empty:
                    continue
                if line.startswith("out_time_us="):
                    value = line.split("=", 1)[1]
                    if value.lstrip("-").isdigit():
                        progress(min(0.99, max(0, int(value) / 1e6 / expected)), "正在生成预览" if preview else "正在导出")
            reader.join(timeout=1)
        if process.returncode:
            raise RuntimeError(log_path.read_text(encoding="utf-8")[-3000:] or "FFmpeg 导出失败。")
        check_cancel(cancel)
        partial.replace(output)
        progress(1.0, "预览就绪" if preview else "导出完成")
        return output
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if process is not None and process.stdout is not None:
            process.stdout.close()
        partial.unlink(missing_ok=True)
        graph_path.unlink(missing_ok=True)
