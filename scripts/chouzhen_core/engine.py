from pathlib import Path
from threading import Event

from .detection import Progress, detect, inspect_shots
from .media import probe
from .models import Analysis
from .planning import build_plan


def analyze(source: Path, artifacts: Path, preset: str = "natural",
            progress: Progress = lambda value, text: None, cancel: Event | None = None) -> Analysis:
    progress(0, "正在读取录像")
    media = probe(source, cancel)
    events = detect(media, artifacts, progress, cancel)
    inspect_shots(media, events, artifacts, progress, cancel)
    result = Analysis(media, events, preset)
    progress(0.92, "正在生成抽帧方案")
    build_plan(result, cancel)
    result.save(artifacts / "analysis.json")
    progress(1, f"已识别 {len(events)} 次击杀")
    return result
