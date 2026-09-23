from typer.testing import CliRunner

from img2schem.cli import app
from img2schem.models import BlockGrid
from img2schem.stages.export_schem import write_schem

runner = CliRunner()


def test_inspect_preview_validate(tmp_path, monkeypatch):
    monkeypatch.setenv("IMG2SCHEM_CONFIG", str(tmp_path / "cfg.yaml"))
    monkeypatch.chdir(tmp_path)
    g = BlockGrid.empty(5, 5, 5)
    g.fill((0, 0, 0), (4, 4, 4), "minecraft:stone")
    p = write_schem(tmp_path / "cube.schem", g, 4189)

    r = runner.invoke(app, ["inspect", str(p), "--json"])
    assert r.exit_code == 0, r.output
    assert '"dims_wxhxl": [\n  5,\n  5,\n  5\n ]' in r.output and '"minecraft:stone": 125' in r.output

    r = runner.invoke(app, ["preview", str(p), "--out", str(tmp_path / "prev")])
    assert r.exit_code == 0 and (tmp_path / "prev" / "preview_iso.png").is_file()

    r = runner.invoke(app, ["validate", str(p)])
    assert r.exit_code == 0, r.output

    (tmp_path / "junk.schem").write_bytes(b"not nbt")
    assert runner.invoke(app, ["inspect", str(tmp_path / "junk.schem")]).exit_code == 2


def test_instance_use_path(tmp_path, monkeypatch, launchers):
    monkeypatch.setenv("IMG2SCHEM_CONFIG", str(tmp_path / "cfg.yaml"))
    monkeypatch.setenv("IMG2SCHEM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    inst = launchers["curseforge"][0] / "Instances" / "Neo Pack"
    r = runner.invoke(app, ["instance", "use", str(inst)])
    assert r.exit_code == 0, r.output
    assert "neoforge" in r.output
    r = runner.invoke(app, ["palette", "build", "--json"])
    assert r.exit_code == 0, r.output
    assert '"neomasonry": 1' in r.output
