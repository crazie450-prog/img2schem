import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from fixtures.designer import synthetic  # noqa: E402

from img2schem.server.app import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("IMG2SCHEM_CONFIG", str(tmp_path / "cfg.yaml"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app(tmp_path / "builds", tmp_path / "out"))


def run(client, msg):
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json(msg)
        events = []
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] in ("done", "error"):
                if e["type"] == "done" and e.get("version"):
                    events.append(ws.receive_json())  # the export that follows
                return events


def test_status_and_empty_builds(client):
    s = client.get("/api/status").json()
    assert s["model"] == "claude-opus-5-5" and s["api_key"] is False and "large" in s["budgets"]
    assert client.get("/api/builds").json() == []
    assert client.get("/api/builds/nope").status_code == 404
    assert client.get("/api/builds/..").status_code in (400, 404)
    assert client.get("/api/builds/a.b").status_code == 400  # names can't reach outside builds/
    assert "img2schem" in client.get("/").text


def test_design_over_the_websocket_then_edit_undo_redo(client, tmp_path):
    session = synthetic.write(tmp_path / "s.jsonl")
    events = run(client, {"action": "design", "name": "tower", "prompt": "a watchtower", "replay": str(session)})
    kinds = [e["type"] for e in events]
    assert kinds[0] == "started" and "applied" in kinds and "grid" in kinds
    done = next(e for e in events if e["type"] == "done")
    assert (done["stopped"], done["version"]) == ("finished", 1)
    assert events[-1]["type"] == "exported" and events[-1]["blocks"] > 0
    grid = next(e for e in events if e["type"] == "grid")["grid"]
    assert len(grid["cells"]) % 5 == 0 and grid["blocks"][0]["name"] == "minecraft:air"

    (b,) = client.get("/api/builds").json()
    assert (b["name"], b["current"], b["versions"]) == ("tower", 1, 1)
    info = client.get("/api/builds/tower").json()
    doc = json.loads(info["ops"])
    g = client.get("/api/builds/tower/grid").json()
    assert g["total"] == 518 and len(g["cells"]) == 5 * 518  # thin walls: every block shows
    ids = [o["id"] for o in g["ops"]]
    cells = [g["cells"][i : i + 5] for i in range(0, len(g["cells"]), 5)]
    door = next(c for c in cells if g["blocks"][c[3]]["name"] == "minecraft:wooden_door@3")
    assert ids[door[4]] == "door"  # each cell names the op that placed it
    assert [a - b for a, b in zip(door[:3], g["origin"], strict=True)] == [3, 1, 0]  # design coordinates
    assert g["blocks"][door[3]]["state"] == "lower half, placed facing north"
    hidden = client.get("/api/builds/tower/grid", params={"hide": "roof,door"}).json()
    assert [o["id"] for o in hidden["ops"]] == [i for i in ids if i not in ("roof", "door")]
    assert hidden["total"] < g["total"]

    bad = client.put("/api/builds/tower/ops", json={"text": '{"ops": [\n  }'})
    assert bad.status_code == 400 and bad.json()["detail"]["line"] == 2
    invalid = client.put("/api/builds/tower/ops", json={"text": json.dumps({"ops": [{"op": "box", "id": "x"}]})})
    assert invalid.status_code == 400 and "from" in invalid.json()["detail"]["message"]
    doc["ops"] = [o for o in doc["ops"] if o["id"] != "windows"]
    saved = client.put("/api/builds/tower/ops", json={"text": json.dumps(doc), "instruction": "deleted windows"})
    saved = saved.json()
    assert saved["current"] == 2 and saved["versions"][-1]["kind"] == "manual"
    assert saved["versions"][-1]["instruction"] == "deleted windows"

    assert client.post("/api/builds/tower/undo").json()["current"] == 1
    assert client.post("/api/builds/tower/redo").json()["current"] == 2
    assert client.post("/api/builds/tower/redo").status_code == 409
    assert client.post("/api/builds/tower/nope").status_code == 404

    edit = synthetic.write(tmp_path / "e.jsonl", synthetic.EDIT_TURNS)
    events = run(client, {"action": "edit", "name": "tower", "instruction": "gable roof", "replay": str(edit)})
    assert next(e for e in events if e["type"] == "done")["version"] == 3


def test_run_errors_reach_the_page(client):
    events = run(client, {"action": "design", "name": "a hut", "prompt": "x"})
    assert events[-1]["type"] == "error" and "letters" in events[-1]["message"]
    events = run(client, {"action": "design", "name": "hut", "prompt": "a hut"})
    assert events[-1]["type"] == "error" and ".env" in events[-1]["message"]  # no API key
    events = run(client, {"action": "design", "name": "hut", "prompt": "x", "budget": "huge"})
    assert events[-1]["type"] == "error" and "no budget" in events[-1]["message"]


def test_stop_reaches_the_run(client, monkeypatch):
    import time

    from img2schem.server import app as server

    def design(*args, cb, **kwargs):
        deadline = time.monotonic() + 5
        while not cb.cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        raise server.runner.RunError(f"cancelled={cb.cancelled()}")

    monkeypatch.setattr(server.runner, "design", design)
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"action": "design", "name": "hut", "prompt": "a hut"})
        assert ws.receive_json()["type"] == "started"
        ws.send_json({"action": "stop"})
        assert ws.receive_json()["type"] == "stopping"
        assert ws.receive_json() == {"type": "error", "message": "cancelled=True"}


def test_grid_leaves_out_buried_blocks():
    from img2schem.models import BlockGrid
    from img2schem.server.grid import grid_payload

    g = BlockGrid.empty(5, 5, 5)
    g.fill((0, 0, 0), (4, 4, 4), "minecraft:stone")
    g.set(2, 4, 2, "minecraft:oak_stairs@2")  # a partial block: the one under it shows through
    p = grid_payload(g, None)
    assert p["total"] == 125 and len(p["cells"]) // 5 == 125 - 27 + 1
    stairs = next(b for b in p["blocks"] if b["name"] == "minecraft:oak_stairs@2")
    assert stairs["parts"] and stairs["opacity"] == 1.0


def test_serve_picks_a_free_port():
    import socket

    from img2schem.cli import _free_port, _port_free

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert not _port_free(taken)
        assert _free_port(taken) != taken
