import json
from pathlib import Path
from threading import Event

import pytest

from chouzhen import main
from chouzhen_core.media import executable, probe, run_capture
from chouzhen_core.models import Analysis, Cancelled, Kill
from chouzhen_core.rendering import render


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("video") / "录屏 sample.mp4"
    run_capture([executable("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                 "testsrc2=size=320x180:rate=30:duration=3", "-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264",
                 "-preset", "ultrafast", "-c:a", "aac", "-y", str(path)])
    return path


@pytest.mark.parametrize("cut", [False, True])
def test_export_decodes_and_keeps_audio_in_sync(source, tmp_path, cut):
    result = Analysis(probe(source), [Kill(1, 1.5, 1, cut_start=1, cut_end=1.4)] if cut else [])
    output = render(result, tmp_path / "导出.mp4", lambda *_: None)
    data = json.loads(run_capture([executable("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(output)]))
    durations = [float(s["duration"]) for s in data["streams"]]
    assert max(durations) - min(durations) < 0.04
    assert max(durations) == pytest.approx(2.6 if cut else 3, abs=0.04)
    run_capture([executable("ffmpeg"), "-v", "error", "-i", str(output), "-f", "null", "-"])


def test_cancel_does_not_replace_existing_output(source, tmp_path):
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"keep original output")
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        render(Analysis(probe(source)), output, lambda *_: None, cancel)
    assert output.read_bytes() == b"keep original output"
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_source_is_never_overwritten(source):
    with pytest.raises(ValueError, match="原始录像"):
        render(Analysis(probe(source)), source, lambda *_: None)


def test_changed_source_invalidates_saved_project(source, tmp_path):
    copy = tmp_path / "copy.mp4"
    copy.write_bytes(source.read_bytes())
    result = Analysis(probe(copy))
    saved = tmp_path / "analysis.json"
    result.save(saved)
    copy.write_bytes(b"changed")
    with pytest.raises(ValueError, match="已变化"):
        Analysis.load(saved)


def test_render_reviewed_aim_counts_kills_separately_from_intervals(source, tmp_path, capsys):
    plan = tmp_path / "analysis.json"
    Analysis(probe(source), [Kill(1, 1, .9, cut_start=0, cut_end=1),
                             Kill(2, 1.1, .9), Kill(3, 2, .9)]).save(plan)
    cuts = tmp_path / "cuts.json"
    cuts.write_text(json.dumps({
        "source": str(source), "source_frames": 90, "kills": [
            {"source_analysis_id": 1, "retained_muzzle_flash_frames": [15, 22],
             "first_feedback_frame": 26, "removed_intervals": [
                 {"start_frame": 3, "end_frame_exclusive": 6, "first_retained_action": "恢复横移"},
                 {"start_frame": 10, "end_frame_exclusive": 15, "first_retained_action": "开枪"},
                 {"start_frame": 20, "end_frame_exclusive": 22, "first_retained_action": "开枪"}]},
            {"source_analysis_id": 3, "retained_muzzle_flash_frames": [55], "removed_intervals": []},
        ],
    }), encoding="utf-8")
    output = tmp_path / "stationary-aim.mp4"
    assert main(["render", str(plan), "--aim-cuts", str(cuts), "--output", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["candidates"], report["kills"], report["edited_kills"]) == (3, 2, 1)
    assert (report["cut_intervals"], report["retained_shots"], report["removed_frames"]) == (3, 3, 10)
    assert report["removed_seconds"] == pytest.approx(10 / 30, abs=2e-6)
    info = json.loads(run_capture([executable("ffprobe"), "-v", "error", "-show_streams",
                                   "-of", "json", str(output)]))
    video, audio = info["streams"]
    assert int(video["nb_frames"]) == 80
    assert float(audio["duration"]) == pytest.approx(80 / 30, abs=.04)
