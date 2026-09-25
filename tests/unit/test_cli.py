import json

import pytest
from typer.testing import CliRunner

from img2schem.cli import app
from img2schem.models import BlockGrid
from img2schem.stages.export_schem import write_schematic

runner = CliRunner()


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("IMG2SCHEM_CONFIG", str(tmp_path / "cfg.yaml"))
    monkeypatch.chdir(tmp_path)


def test_inspect_preview_validate(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    g = BlockGrid.empty(5, 5, 5)
    g.fill((0, 0, 0), (4, 4, 4), "minecraft:stone")
    g.set(0, 0, 0, "gregtech:gt.blockcasings@5")
    p = write_schematic(tmp_path / "cube.schematic", g)

    r = runner.invoke(app, ["inspect", str(p), "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["dims_wxhxl"] == [5, 5, 5] and out["counts"]["minecraft:stone"] == 124
    assert out["mods_required"] == ["gregtech"]

    r = runner.invoke(app, ["preview", str(p), "--out", str(tmp_path / "prev")])
    assert r.exit_code == 0 and (tmp_path / "prev" / "preview_iso.png").is_file()
    assert runner.invoke(app, ["validate", str(p)]).exit_code == 0

    (tmp_path / "junk.schematic").write_bytes(b"not nbt")
    assert runner.invoke(app, ["inspect", str(tmp_path / "junk.schematic")]).exit_code == 2


def test_instance_and_world_selection(tmp_path, monkeypatch, gtnh):
    _env(tmp_path, monkeypatch)
    r = runner.invoke(app, ["instance", "use", gtnh.game_dir])
    assert r.exit_code == 0, r.output
    assert "forge" in r.output
    r = runner.invoke(app, ["world", "list"])
    assert r.exit_code == 0 and "img2schem-test" in r.output
    r = runner.invoke(app, ["world", "use", "img2schem-test"])
    assert r.exit_code == 0, r.output
    assert "14 registered blocks" in r.output

    g = BlockGrid.empty(2, 1, 1)
    g.set(0, 0, 0, "minecraft:stone")
    g.set(1, 0, 0, "gregtech:not_registered")
    p = write_schematic(tmp_path / "x.schematic", g)
    r = runner.invoke(app, ["validate", str(p)])
    assert r.exit_code == 2 and "not_registered" in r.output
    assert runner.invoke(app, ["doctor"]).exit_code == 0


def test_palette_import_search_report(tmp_path, monkeypatch):
    from fixtures.jars.make import nei_dumps

    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("IMG2SCHEM_CACHE_DIR", str(tmp_path / "cache"))
    r = runner.invoke(app, ["palette", "import", str(nei_dumps(tmp_path / "dumps"))])
    assert r.exit_code == 0, r.output
    assert "1 dark_icon" in r.output and "usable for building" in r.output
    r = runner.invoke(app, ["palette", "search", "aluminum", "--shape", "stairs"])
    assert r.exit_code == 0 and "chisel:aluminum_stairs.1@8" in r.output
    assert runner.invoke(app, ["palette", "import", str(tmp_path / "missing")]).exit_code == 4


def test_compile_example_house(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    from img2schem.stages.export_schem import read_schematic

    src = Path("examples/house.ops.json").resolve()
    _env(tmp_path, monkeypatch)
    shutil.copy(src, tmp_path / "house.ops.json")
    r = runner.invoke(app, ["compile", "house.ops.json", "--out", "out"])
    assert r.exit_code == 0, r.output
    grid, info = read_schematic(tmp_path / "out" / "house.schematic")
    assert info.offset == (-(grid.shape[0] // 2), -1, 1)  # roof overhang at design z = -1
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["ops_count"] == 12 and report["validation"]["ok"]
    assert (tmp_path / "out" / "preview_iso.png").is_file()
    (tmp_path / "bad.json").write_text('{"ops": [{"op": "walls", "id": "w", "footprint": {"x0": 0, "z0": 0, "x1": 3, '
                                       '"z1": 3}, "height": 2, "mat": "$nope"}]}')  # fmt: skip
    r = runner.invoke(app, ["compile", "bad.json", "--out", "out2"])
    assert r.exit_code == 2 and "no slot" in r.output


def test_plan_then_compile(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    src = Path("examples/brick_house.spec.json").resolve()
    _env(tmp_path, monkeypatch)
    shutil.copy(src, tmp_path / "brick_house.spec.json")
    r = runner.invoke(app, ["plan", "brick_house.spec.json"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "brick_house.ops.json").is_file()
    r = runner.invoke(app, ["compile", "brick_house.ops.json", "--out", "out"])
    assert r.exit_code == 0, r.output
    assert runner.invoke(app, ["plan", "brick_house.spec.json", "--designer", "claude"]).exit_code == 4


def test_compile_accepts_a_spec_and_picks_up_edits(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    from img2schem.stages.export_schem import read_schematic

    _env(tmp_path, monkeypatch)
    shutil.copy(Path(__file__).parents[2] / "examples" / "brick_house.spec.json", tmp_path / "my.spec.json")
    r = runner.invoke(app, ["compile", "my.spec.json", "--out", "a"])
    assert r.exit_code == 0, r.output
    h2 = read_schematic(tmp_path / "a" / "my.schematic")[0].shape[1]
    spec = json.loads((tmp_path / "my.spec.json").read_text())
    spec["facade"]["storeys"] = 3
    (tmp_path / "my.spec.json").write_text(json.dumps(spec))
    r = runner.invoke(app, ["compile", "my.spec.json", "--out", "b"])
    assert r.exit_code == 0, r.output
    assert read_schematic(tmp_path / "b" / "my.schematic")[0].shape[1] == h2 + 5


def test_materials_from_a_photo_then_compile(tmp_path, monkeypatch):
    from fixtures.jars.make import nei_dumps
    from fixtures.synthetic.gen import photograph, render_facade
    from PIL import Image

    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("IMG2SCHEM_CACHE_DIR", str(tmp_path / "cache"))
    assert runner.invoke(app, ["palette", "import", str(nei_dumps(tmp_path / "dumps"))]).exit_code == 0
    elements = [{"kind": "window", "bbox": [0.1, 0.15, 0.25, 0.4]}, {"kind": "door", "bbox": [0.44, 0.55, 0.56, 1.0]}]
    facade, _ = render_facade(elements, wall=(88, 88, 88), roof=(91, 91, 91))
    photo, corners, _ = photograph(facade, facade.shape[0] - 400, seed=2)
    Image.fromarray(photo).save(tmp_path / "house.jpg")
    spec = {"facade": {"width_m": 10, "storeys": 1}, "elements": elements,
            "materials": {"wall": {}, "roof": {"rgb": [91, 91, 91]}}}  # fmt: skip
    (tmp_path / "h.spec.json").write_text(json.dumps(spec))
    arg = " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)
    r = runner.invoke(app, ["materials", "h.spec.json", "house.jpg", "--corners", arg, "--run", "run"])
    assert r.exit_code == 0, r.output
    updated = json.loads((tmp_path / "h.spec.json").read_text())
    assert updated["materials"]["wall"]["chosen"] == "minecraft:stonebrick"
    assert updated["materials"]["roof"]["chosen"]  # from the rgb hint (no --roof-box)
    assert (tmp_path / "run" / "debug_layout.png").is_file() and (tmp_path / "run" / "rectified.png").is_file()
    r = runner.invoke(app, ["compile", "h.spec.json", "--out", "out"])
    assert r.exit_code == 0, r.output


@pytest.mark.replay
def test_design_replays_a_session_and_compiles(tmp_path, monkeypatch):
    from fixtures.designer import synthetic

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _env(tmp_path, monkeypatch)  # isolated config, and no stray .env from the working folder
    session = synthetic.write(tmp_path / "s.jsonl")
    out = tmp_path / "run"
    r = runner.invoke(app, ["design", "a stone watchtower", "--name", "tower", "--replay", str(session),
                            "--out", str(out), "--no-copy"])  # fmt: skip
    assert r.exit_code == 0, r.output
    assert (out / "tower.schematic").is_file() and (out / "preview_iso.png").is_file()
    record = json.loads((out / "design.json").read_text())
    assert record["stopped"] == "finished" and record["turns"] == 3 and record["model"] == "claude-opus-5-5"
    assert json.loads((out / "report.json").read_text())["usage"]["design"]["turns"] == 3
    assert len(json.loads((out / "tower.ops.json").read_text())["ops"]) == 6


def test_design_live_needs_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _env(tmp_path, monkeypatch)
    r = runner.invoke(app, ["design", "a hut", "--out", str(tmp_path / "o")])
    assert r.exit_code == 4 and ".env" in r.output
    assert runner.invoke(app, ["design", "a hut", "--budget", "huge"]).exit_code == 4
