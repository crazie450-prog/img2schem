"""A hand-written (synthetic) designer session: the shape of a real recording, for replay tests without the API.
Real recordings (out/<run>/session.jsonl from `img2schem design`) can be added next to it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

USAGE = {"input_tokens": 2000, "output_tokens": 3000, "cache_creation_input_tokens": 20000,
         "cache_read_input_tokens": 0}  # fmt: skip


def tool(i: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"toolu_{i:03d}", "name": name, "input": args}


def response(content: list[dict[str, Any]], stop: str = "tool_use", usage: dict[str, int] | None = None,
             model: str = "claude-opus-5") -> dict[str, Any]:  # fmt: skip
    return {"id": "msg_x", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop, "usage": usage or USAGE}  # fmt: skip


FOOT = {"x0": 0, "z0": 0, "x1": 6, "z1": 6}
TURNS = [
    response([
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "A 7x7 stone watchtower, 3 storeys, with a spiral stair and a hip roof."},
        tool(1, "set_style", {"slots": {"wall": "minecraft:stonebrick", "floor": "minecraft:planks",
                                        "roof": "minecraft:brick_block", "roof.stairs": "minecraft:brick_stairs",
                                        "floor.stairs": "minecraft:oak_stairs", "door": "minecraft:wooden_door",
                                        "glass": "minecraft:glass_pane", "col": "minecraft:log"}}),
        tool(2, "add_floors", {"id": "floors", "footprint": FOOT, "ys": [0, 5, 10]}),
        tool(3, "add_walls", {"id": "walls", "footprint": FOOT, "y0": 1, "height": 13}),
    ]),
    response([
        tool(4, "add_door", {"id": "door", "pos": [3, 1, 0], "facing": "north"}),
        tool(5, "add_openings", {"id": "windows", "footprint": FOOT, "face": "back", "sills": [7, 12], "w": 1,
                                 "h": 2, "count": 2, "margin": 1}),
        tool(6, "add_spiral_stair", {"id": "stair", "center": [3, 3], "y0": 1, "y1": 10, "mat": "$floor.stairs",
                                     "column": "$col"}),
        tool(7, "add_roof", {"id": "roof", "footprint": FOOT, "y0": 14, "type": "hip"}),
        tool(8, "render_views", {"views": ["iso"]}),
    ]),
    response([tool(9, "finish", {"summary": "A three-storey stone watchtower with a spiral stair."})]),
]  # fmt: skip


def write(path: Path, turns: list[dict[str, Any]] | None = None) -> Path:
    path.write_text("".join(json.dumps({"response": t}) + "\n" for t in (turns or TURNS)), encoding="utf-8")
    return path
