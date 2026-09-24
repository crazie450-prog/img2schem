import json

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
