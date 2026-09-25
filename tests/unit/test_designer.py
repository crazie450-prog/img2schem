import json
from pathlib import Path

import pytest
from fixtures.designer import synthetic
from fixtures.designer.synthetic import response, tool

from img2schem.config import Budgets, BudgetUSD, Settings
from img2schem.designer.pricing import usage_cost, worst_case
from img2schem.designer.session import run_design
from img2schem.designer.tools import OP_CLASSES, DesignState, tool_specs
from img2schem.designer.transport import ReplayTransport, request_digest
from img2schem.engine.ops import OpsDoc

SETTINGS = Settings().claude
BUDGET = BudgetUSD(warn=1.0, stop=5.0)


class Scripted:
    """A transport answering from a list and keeping every request."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []

    def send(self, request, progress=None):
        self.requests.append(json.loads(json.dumps(request)))
        return self.turns.pop(0)


def new_state():
    return DesignState(OpsDoc(), None, Budgets())


def design(turns, budget=BUDGET, state=None):
    state = state or new_state()
    t = Scripted(turns)
    return state, t, run_design(state, "a watchtower", "SYSTEM", tool_specs(), SETTINGS, budget, t)


def test_tools_are_generated_from_the_op_models():
    specs = {t["name"]: t for t in tool_specs()}
    assert {f"add_{c.model_fields['op'].default}" for c in OP_CLASSES} <= set(specs)
    loft = specs["add_loft"]["input_schema"]
    assert "op" not in loft["properties"] and "keys" in loft["required"]
    assert "from" in specs["add_box"]["input_schema"]["properties"]  # aliases, as in ops.json
    assert len(json.dumps(specs["add_define"])) < 3000  # nested ops are not the whole union again
    assert "render_views" not in {t["name"] for t in tool_specs(render=False)}
    assert all(t["eager_input_streaming"] for t in specs.values())


@pytest.mark.replay
def test_replay_builds_the_recorded_design(tmp_path):
    state = new_state()
    t = ReplayTransport(synthetic.write(tmp_path / "s.jsonl"))
    r = run_design(state, "a watchtower", "SYSTEM", tool_specs(), SETTINGS, BUDGET, t)
    assert (r.stopped, r.turns, r.summary) == ("finished", 3, "A three-storey stone watchtower with a spiral stair.")
    assert [o.id for o in state.doc.ops] == ["floors", "walls", "door", "windows", "stair", "roof"]
    assert state.doc.style["roof.stairs"] == "minecraft:brick_stairs"
    assert not [i for i in state.issues if i.severity == "error"]
    assert r.cost_usd == pytest.approx(3 * usage_cost("claude-opus-5-5", synthetic.USAGE))
    assert r.text == ["A 7x7 stone watchtower, 3 storeys, with a spiral stair and a hip roof."]
    counts = state.compiled.grid.counts()
    assert counts["minecraft:wooden_door@3"] == 1 and any("oak_stairs" in b for b in counts)


def test_tool_results_go_back_with_errors_and_images():
    turns = [*synthetic.TURNS[:1],
             response([tool(4, "add_box", {"id": "bad", "from": [0, 0, 0], "to": [1, 1, 1], "mat": "nope:block@99"}),
                       tool(5, "add_walls", {"id": "walls", "footprint": synthetic.FOOT, "y0": 1, "height": 3}),
                       tool(6, "render_views", {"views": ["iso", "top"]})]),
             response([{"type": "text", "text": "Done."}], stop="end_turn")]  # fmt: skip
    state, t, r = design(turns)
    results = t.requests[2]["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["toolu_004", "toolu_005", "toolu_006"]  # one message, in order
    assert results[0]["is_error"] and "meta" in results[0]["content"]
    assert results[1]["is_error"] and "exists" in results[1]["content"]  # duplicate id
    images = [c for c in results[2]["content"] if c["type"] == "image"]
    assert len(images) == 2 and images[0]["source"]["media_type"] == "image/png"
    assert r.stopped == "end_turn" and [o.id for o in state.doc.ops] == ["floors", "walls"]
    # the conversation is replayed to the API as sent: thinking blocks unchanged, tools and system cached
    assert t.requests[1]["messages"][1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert t.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert t.requests[0]["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert t.requests[0]["output_config"] == {"effort": "medium"} and t.requests[0]["model"] == "claude-opus-5-5"


def test_history_is_append_only_and_blocks_come_back_unchanged():
    """Preserved thinking: system, tools and every earlier message stay byte-identical across turns."""
    odd = {"type": "text", "text": "note", "citations": None}  # even None fields are passed back as received
    turns = [response([{"type": "thinking", "thinking": "updates", "signature": "s1"}, odd,
                       tool(1, "get_state_summary", {})]),
             response([tool(2, "render_views", {"views": ["iso"]})]),
             response([tool(3, "finish", {"summary": "x"})])]  # fmt: skip
    state = new_state()
    state.execute("add_box", {"id": "b", "from": [0, 0, 0], "to": [1, 1, 1], "mat": "minecraft:stone"})
    _, t, r = design(turns, state=state)
    for a, b in zip(t.requests, t.requests[1:], strict=False):
        assert json.dumps(b["messages"][: len(a["messages"])]) == json.dumps(a["messages"])
        assert (a["system"], a["tools"], a["betas"]) == (b["system"], b["tools"], b["betas"])
    assert t.requests[1]["messages"][1]["content"][1] == odd
    assert r.text == ["updates", "note"]  # progress notes arrive as thinking text


def test_same_op_failing_three_times_is_skipped():
    bad = {"id": "tower", "from": [0, 0, 0], "to": [0, 300, 0], "mat": "minecraft:stone"}  # taller than a world
    turns = [response([tool(i, "add_box", bad)]) for i in range(3)] + [response([], stop="end_turn")]
    state, t, r = design(turns)
    last = t.requests[3]["messages"][-1]["content"][0]["content"]
    assert "rolled back" in last and "skip it" in last
    assert r.warnings == ["op 'tower' failed 3 times; skipped"] and state.doc.ops == []


def test_budget_warns_then_stops_before_passing_the_limit():
    heavy = {"input_tokens": 100_000, "output_tokens": 30_000, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 0}  # $1.00 a turn at $4 / $20 per million
    turns = [response([tool(i, "get_state_summary", {})], usage=heavy) for i in range(10)]
    state, t, r = design(turns)
    assert r.stopped == "budget" and "--budget large" in r.warnings[-1]
    assert "past the default budget's $1.00 warning" in r.warnings[0]
    worst = worst_case(["claude-opus-5-5", "claude-opus-5"], 120_000, 32000)
    assert r.cost_usd <= BUDGET.stop and r.cost_usd + worst > BUDGET.stop


def test_a_truncated_turn_runs_no_tools():
    turns = [response([tool(1, "add_box", {"id": "b", "from": [0, 0, 0], "to": [3, 3, 3]})], stop="max_tokens"),
             response([], stop="end_turn")]  # fmt: skip
    state, t, r = design(turns)
    assert state.doc.ops == [] and "max_tokens" in t.requests[1]["messages"][-1]["content"][0]["content"]


def test_refusal_stops():
    state, t, r = design([response([{"type": "text", "text": "..."}], stop="refusal")])
    assert r.stopped == "refusal" and len(t.requests) == 1


def test_state_editing_and_rollback():
    s = new_state()
    assert not s.execute("set_style", {"slots": {"w": "minecraft:stone", "x": "minecraft:dirt"}}).is_error
    assert not s.execute("add_box", {"id": "a", "from": [0, 0, 0], "to": [4, 0, 4], "mat": "$w"}).is_error
    r = s.execute("replace_op", {"id": "a", "op": {"op": "box", "id": "a", "from": [0, 0, 0], "to": [5, 0, 5],
                                                   "mat": "$w"}})  # fmt: skip
    assert not r.is_error and json.loads(r.content)["op"]["cells"] == 36
    bad = s.execute("add_box", {"id": "sky", "from": [0, 0, 0], "to": [0, 260, 0], "mat": "$w"})
    assert bad.is_error and "R10.2" in bad.content and [o.id for o in s.doc.ops] == ["a"]  # rolled back
    assert s.compiled.grid.nonair() == 36
    assert s.execute("set_style", {"slots": {"x": None}}).is_error is False and "x" not in s.doc.style
    assert s.execute("delete_op", {"id": "missing"}).is_error
    assert not s.execute("delete_op", {"id": "a"}).is_error and s.doc.ops == []
    assert s.execute("finish", {"summary": "ok"}).done and s.summary == "ok"
    assert s.execute("nope", {}).is_error and s.execute("add_box", "not json").is_error


def test_opus_5_5_prices():
    from img2schem.designer.pricing import price

    p = price("claude-opus-5-5")
    assert (p.input, p.output, p.cache_write, p.cache_read) == (4.0, 20.0, 5.0, 0.20)
    assert price("claude-opus-5").cache_read == pytest.approx(0.5)
    assert worst_case(["claude-opus-5-5", "claude-opus-5"], 0, 10_000) == pytest.approx(0.25)  # the dearer one


def test_request_digest_is_stable():
    assert request_digest({"b": 1, "a": [1, 2]}) == request_digest({"a": [1, 2], "b": 1})


def test_live_transport_request_and_stream_parsing():
    """The SDK path without network: a mock HTTP server answers with a streamed tool call."""
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    from img2schem.designer.transport import LiveTransport

    events = [
        {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant",
                                              "model": "claude-opus-5-5", "content": [], "stop_reason": None,
                                              "usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1",
                                                                     "name": "add_box", "input": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta",
                                                             "partial_json": '{"id": "b", "to": [2, 2, 2]}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 42}},
        {"type": "message_stop"},
    ]  # fmt: skip
    sent = {}

    def handler(request):
        sent["body"], sent["beta"] = json.loads(request.content), request.headers.get("anthropic-beta")
        body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    client = anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(
        transport=httpx2.MockTransport(handler)))  # fmt: skip
    seen = []
    request = {"model": "claude-opus-5-5", "max_tokens": 1000, "messages": [{"role": "user", "content": "hi"}],
               "tools": tool_specs()[:1], "thinking": {"type": "adaptive", "display": "updates"},
               "betas": ["thinking-display-updates-2026-08-18"], "cache_control": {"type": "ephemeral"}}
    msg = LiveTransport("claude-opus-5", client=client).send(request, lambda k, t: seen.append((k, t)))
    assert msg["content"][0]["input"] == {"id": "b", "to": [2, 2, 2]} and msg["usage"]["output_tokens"] == 42
    assert seen == [("tool", "add_box")]
    assert sent["body"]["stream"] is True and sent["body"]["fallbacks"] == [{"model": "claude-opus-5"}]
    assert "server-side-fallback" in sent["beta"] and "thinking-display-updates" in sent["beta"]
    assert sent["body"]["tools"][0]["eager_input_streaming"] and "betas" not in sent["body"]
    assert "betas" in request  # the caller's request is not modified


def test_live_transport_sends_the_workspace_header(monkeypatch):
    pytest.importorskip("anthropic")
    from img2schem.designer.transport import LiveTransport

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_123")
    assert LiveTransport().client.default_headers["anthropic-workspace-id"] == "wrkspc_123"
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID")
    assert "anthropic-workspace-id" not in LiveTransport().client.default_headers



LIVE = Path(__file__).parents[1] / "fixtures" / "designer" / "watchtower_live.session.jsonl"


@pytest.mark.replay
def test_replay_of_the_owners_first_live_session():
    """A real Opus 5.5 session (the owner's watchtower, 2026-09-25). With the owner's palette it rebuilds the
    same 776-block tower; without one (CI) the two ops that need palette families are rejected and reported."""
    import os

    from img2schem.models import Palette

    pal_path = os.environ.get("IMG2SCHEM_TEST_PALETTE")
    pal = Palette.model_validate_json(Path(pal_path).read_text(encoding="utf-8")) if pal_path else None
    state = DesignState(OpsDoc(), pal, Budgets())
    r = run_design(state, "x", "S", tool_specs(), SETTINGS, BUDGET, ReplayTransport(LIVE))
    assert (r.stopped, r.turns) == ("finished", 5) and r.cost_usd == pytest.approx(0.3313, abs=1e-4)
    assert r.summary.startswith("I built a small stone-brick watchtower")
    assert r.usage[1]["cache_read_input_tokens"] == 30354  # the prompt prefix was read from the cache
    if pal is None:
        assert "rail" not in [o.id for o in state.doc.ops] and len(state.doc.ops) == 18
    else:
        assert len(state.doc.ops) == 20 and state.compiled.grid.nonair() == 776


def test_critique_passes_follow_finish():
    calls = []

    def critique(n):
        calls.append(n)
        return [{"type": "text", "text": f"CRITIQUE {n}"}]

    state = new_state()
    t = Scripted(synthetic.PHOTO_TURNS)
    r = run_design(state, [{"type": "text", "text": "photo brief"}], "S", tool_specs(), SETTINGS, BUDGET, t,
                   critique=critique, critique_passes=2)  # fmt: skip
    assert (r.stopped, r.turns, r.critique_passes, calls) == ("finished", 3, 2, [1, 2])
    assert r.summary == "Close enough: the rest is cosmetic."
    msg = t.requests[1]["messages"][-1]["content"]  # tool results first, then the critique
    assert [b["type"] for b in msg] == ["tool_result", "tool_result", "tool_result", "text"]
    assert msg[-1]["text"] == "CRITIQUE 1" and [o.id for o in state.doc.ops] == ["walls", "roof"]
    once = run_design(new_state(), "b", "S", tool_specs(), SETTINGS, BUDGET, Scripted(synthetic.PHOTO_TURNS),
                      critique=critique, critique_passes=1)  # fmt: skip
    assert (once.turns, once.critique_passes, once.summary) == (2, 1, "Added the roof slab.")


def test_photo_brief_and_critique_sheet(tmp_path):
    from PIL import Image

    from img2schem.designer.critique import critique_message, photo_brief
    from img2schem.models import BlockGrid

    p = tmp_path / "house.png"
    Image.new("RGB", (3000, 1500), (200, 180, 160)).save(p)
    brief = photo_brief([p, p], "make it 1.5x scale")
    assert [b["type"] for b in brief] == ["image", "image", "text"]
    assert "same building" in brief[-1]["text"] and "1.5x scale" in brief[-1]["text"]
    g = BlockGrid.empty(4, 6, 3)
    g.fill((0, 0, 0), (3, 5, 2), "minecraft:stone")
    msg = critique_message(p, g, None, 1, 2, tmp_path / "c.png")
    assert msg[0]["type"] == "image" and "pass 1 of 2" in msg[1]["text"]
    sheet = Image.open(tmp_path / "c.png")
    assert sheet.height == 520 + 28 and sheet.width > 1000  # photo, iso and front side by side


HOUSE2 = Path(__file__).parents[1] / "fixtures" / "designer" / "house2_photo_live.session.jsonl"


@pytest.mark.replay
def test_replay_of_the_owners_photo_session_with_critique():
    """A real Opus 5.5 photo design (the owner's house 2, prompt v1): critique pass 1 found the plan mirrored and
    rebuilt it with 30 replace_op calls; pass 2 found only cosmetic differences."""
    critiques = []

    def critique(n):
        critiques.append(n)
        return [{"type": "text", "text": f"critique {n}"}]

    state = DesignState(OpsDoc(), None, Budgets())
    r = run_design(state, "photo", "S", tool_specs(), SETTINGS, BUDGET, ReplayTransport(HOUSE2),
                   critique=critique, critique_passes=2)  # fmt: skip
    assert (r.stopped, r.turns, r.critique_passes, critiques) == ("finished", 15, 2, [1, 2])
    assert r.cost_usd == pytest.approx(0.8352, abs=1e-4) and r.cost_usd < BUDGET.warn
    assert any("mirrored" in t for t in r.text)
    assert state.doc.ops  # without the owner's palette some ops are rejected, but the build stands


HOUSE3 = Path(__file__).parents[1] / "fixtures" / "designer" / "house3_photo_live.session.jsonl"


@pytest.mark.replay
def test_replay_of_the_owners_photo_session_prompt_v2():
    """House 3 on prompt v2: the right way round from the start, so the critique passes found only small
    differences (21 turns, $0.77)."""
    state = DesignState(OpsDoc(), None, Budgets())
    r = run_design(state, "photo", "S", tool_specs(), SETTINGS, BUDGET, ReplayTransport(HOUSE3),
                   critique=lambda n: [{"type": "text", "text": "c"}], critique_passes=2)  # fmt: skip
    assert (r.stopped, r.turns, r.critique_passes) == ("finished", 21, 2)
    assert r.cost_usd == pytest.approx(0.7721, abs=1e-4)
    assert r.summary.startswith("Nothing was mirrored")
