from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json


@dataclass
class Media:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    video_start: float
    has_audio: bool
    size: int
    modified_ns: int
    origin: float = 0.0

    def verify_source(self) -> None:
        stat = Path(self.path).stat()
        if (stat.st_size, stat.st_mtime_ns) != (self.size, self.modified_ns):
            raise ValueError("录像已变化，请重新分析。")


@dataclass
class Kill:
    id: int
    time: float
    confidence: float
    burst_start: float | None = None
    safe_start: float | None = None
    safe_end: float | None = None
    cut_start: float | None = None
    cut_end: float | None = None
    enabled: bool = True
    reason: str = ""
    thumbnail: str = ""
    cut_points: list[float] = field(default_factory=list)

    @property
    def removed(self) -> float:
        if not self.enabled or self.cut_start is None or self.cut_end is None:
            return 0.0
        return max(0.0, self.cut_end - self.cut_start)


@dataclass
class Analysis:
    media: Media
    kills: list[Kill] = field(default_factory=list)
    preset: str = "natural"
    schema_version: int = 1
    detector: str = "self-highlight-avatar-v1"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> Analysis:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("不支持这份分析文件的版本。")
        data["media"] = Media(**data["media"])
        data["kills"] = [Kill(**item) for item in data["kills"]]
        result = cls(**data)
        result.media.verify_source()
        return result

    @property
    def removed(self) -> float:
        return sum(k.removed for k in self.kills)


class Cancelled(Exception):
    pass
