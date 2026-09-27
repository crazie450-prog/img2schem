import json

import pytest
from fixtures.designer import synthetic
from typer.testing import CliRunner

from img2schem.cli import app
from img2schem.designer.history import History, resolve_build

runner = CliRunner()


def test_versions_undo_redo_and_branching(tmp_path):
    ops = tmp_path / "hut.ops.json"
    h = History(ops)
    assert h.commit("one", kind="design") == 1 and h.commit("two", kind="edit") == 2
    assert ops.read_text() == "two"
    assert h.step(-1)["n"] == 1 and ops.read_text() == "one"
    with pytest.raises(ValueError, match="nothing to undo"):
        h.step(-1)
    assert h.step(+1)["n"] == 2
    with pytest.raises(ValueError, match="nothing to redo"):
        h.step(+1)
    h.step(-1)
    assert h.commit("three", kind="edit") == 2  # an edit after an undo drops the undone version
    reloaded = History(ops)
    assert [v["n"] for v in reloaded.versions] == [1, 2] and reloaded.current == 2
    assert (h.dir / "v002.ops.json").read_text() == "three" and ops.read_text() == "three"


def test_existing_ops_file_becomes_version_one(tmp_path):
    ops = tmp_path / "a.ops.json"
    ops.write_text("hand-written")
    h = History(ops)
    h.ensure_started()
    h.ensure_started()  # only once
    assert [v["kind"] for v in h.versions] == ["import"] and (h.dir / "v001.ops.json").read_text() == "hand-written"


def test_resolve_build(tmp_path):
    assert resolve_build("watchtower").as_posix() == "builds/watchtower.ops.json"
    assert resolve_build("x/y.ops.json").as_posix() == "x/y.ops.json"


@pytest.mark.replay
def test_design_edit_undo_redo_from_the_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("IMG2SCHEM_CONFIG", str(tmp_path / "cfg.yaml"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    design = synthetic.write(tmp_path / "design.jsonl")
    edit = synthetic.write(tmp_path / "edit.jsonl", synthetic.EDIT_TURNS)
    same = synthetic.write(tmp_path / "same.jsonl", synthetic.NO_CHANGE_TURNS)

    r = runner.invoke(app, ["design", "a watchtower", "--name", "tower", "--replay", str(design), "--no-copy"])
    assert r.exit_code == 0, r.output
    build = tmp_path / "builds" / "tower.ops.json"
    v1 = json.loads(build.read_text())
    r = runner.invoke(app, ["edit", "tower", "gable roof, mossy base", "--replay", str(edit), "--no-copy"])
    assert r.exit_code == 0, r.output
    v2 = json.loads(build.read_text())
    roof = next(o for o in v2["ops"] if o["id"] == "roof")
    assert roof["type"] == "gable" and v2["style"]["base"] == "minecraft:mossy_cobblestone"
    assert [o["id"] for o in v2["ops"]] == [o["id"] for o in v1["ops"]] + ["base"]  # ids and order kept
    assert "version 2" in r.output

    r = runner.invoke(app, ["edit", "tower", "add a gable roof", "--replay", str(same), "--no-copy"])
    assert r.exit_code == 0 and "no change" in r.output
    r = runner.invoke(app, ["history", "tower"])
    assert r.exit_code == 0 and "gable roof, mossy base" in r.output and "design" in r.output

    assert runner.invoke(app, ["undo", "tower", "--no-copy"]).exit_code == 0
    assert json.loads(build.read_text()) == v1
    assert runner.invoke(app, ["redo", "tower", "--no-copy"]).exit_code == 0
    assert json.loads(build.read_text()) == v2
    assert runner.invoke(app, ["redo", "tower", "--no-copy"]).exit_code == 4  # nothing to redo
    assert runner.invoke(app, ["edit", "missing", "x", "--no-copy"]).exit_code == 4


def test_edit_brief_carries_the_ops_and_leaves_renders_out(tmp_path):
    from img2schem.config import Budgets, BudgetUSD, Settings
    from img2schem.designer.session import run_design
    from img2schem.designer.tools import DesignState, tool_specs
    from img2schem.designer.transport import ReplayTransport
    from img2schem.engine.ops import OpsDoc

    t = ReplayTransport(synthetic.write(tmp_path / "e.jsonl", synthetic.NO_CHANGE_TURNS))
    run_design(DesignState(OpsDoc(), None, Budgets()), "BRIEF", "S", tool_specs(render=False), Settings().claude,
               BudgetUSD(warn=1, stop=5), t)  # fmt: skip
    assert t.requests[0]["messages"][0]["content"] == "BRIEF"
    assert "render_views" not in [x["name"] for x in t.requests[0]["tools"]]
