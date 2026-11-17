import json
from pathlib import Path

import pytest

from chouzhen import main, new_workdir
from chouzhen_core.models import Analysis, Kill, Media


@pytest.fixture
def project(tmp_path):
    # The edit command only needs source identity; rendering is tested separately with real media.
    source = tmp_path / "原始录像.mp4"
    source.write_bytes(b"source must remain unchanged")
    stat = source.stat()
    media = Media(str(source), 10, 1920, 1080, 60, 0, True, stat.st_size, stat.st_mtime_ns)
    plan = Analysis(media, [
        Kill(1, 2, 1, safe_start=1, safe_end=1.1, cut_start=1, cut_end=1.1,
             cut_points=[1, 1.016, 1.05, 1.067, 1.1]),
        Kill(2, 5, 1, safe_start=4, safe_end=4.2, cut_start=4, cut_end=4.2),
    ])
    path = tmp_path / "analysis.json"
    plan.save(path)
    return path, source


def test_edit_writes_new_plan_preserving_original_and_source_frame_boundaries(project, capsys):
    path, source = project
    original = path.read_bytes()
    assert main(["edit", str(path), "--frames", "1=2", "--disable", "2"]) == 0
    output = json.loads(capsys.readouterr().out)
    edited = Analysis.load(Path(output["analysis"]))
    assert edited.kills[0].cut_end == 1.05
    assert edited.kills[1].enabled is False
    assert output["removed_seconds"] == pytest.approx(0.05)
    assert path.read_bytes() == original
    assert source.read_bytes() == b"source must remain unchanged"


@pytest.mark.parametrize("arguments", [["--disable", "77"], ["--frames", "1=100"],
                                     ["--enable", "1", "--disable", "1"]])
def test_invalid_edit_does_not_write_a_plan(project, arguments, capsys):
    path, _ = project
    original = path.read_bytes()
    assert main(["edit", str(path), *arguments]) == 1
    assert "error" in json.loads(capsys.readouterr().err)
    assert path.read_bytes() == original
    assert not path.with_name("analysis.edited.json").exists()


def test_cli_never_renders_over_source_even_with_overwrite(project, capsys):
    path, source = project
    assert main(["render", str(path), "--output", str(source), "--overwrite"]) == 1
    assert "error" in json.loads(capsys.readouterr().err)
    assert source.read_bytes() == b"source must remain unchanged"


def test_reused_analysis_directory_is_not_overwritten(project):
    path, source = project
    original = path.read_bytes()
    with pytest.raises(ValueError):
        new_workdir(source, path.parent)
    assert path.read_bytes() == original
