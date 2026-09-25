# Test bed runbook (GTNH 1.7.10)

Expanded from SOW Appendix B, re-scoped per docs/SOW_GTNH.md. Record versions and results at the end of every
phase.

## Setup

1. `img2schem instance list` → GTNH shows loader `forge`, MC `1.7.10`, **WorldEdit = yes**.
   `img2schem instance use <name from the list>`.
2. In GTNH, create a **creative, superflat** world named `img2schem-test`. Never test in a survival world you
   care about. Quit to the title screen once so level.dat is written.
3. `img2schem world use img2schem-test` → lists registered blocks per mod. `img2schem doctor` → all green.
4. Pick a modded full block and a modded stairs block from the list (e.g. from `chisel` or another building
   mod) and run:
   `python examples/make_test_grids.py --modded-full <modid:name> --modded-stairs <modid:name>`
   The files are copied into the WorldEdit schematics folder shown by `doctor`.

## Paste checks

In game: `//schem list`, `//schem load img2schem_cube`, stand where the build should go **facing south**,
`//paste -a`. Expected: the front face 2 blocks in front of you, centered on you, with the bottom layer
replacing the block you stand on (D-015). `//undo` removes it.

- **Cube:** white wool face toward you, red wool face on your **right**, gold block at the top **left** corner
  of the white face.
- **House:** door in the middle of the facing wall; roof ridge running left–right with stairs rising toward
  the ridge from both sides; windows are glass panes connected in pairs.
- **Modded:** lower ring of stone-brick stairs rising toward the center; upper ring of your modded stairs,
  the row nearest you upside-down; modded pillar in the middle.
- No errors in chat or `logs/fml-client-latest.log` (a "Missing ID mapping" line means a name isn't registered).
- Block counts match `img2schem inspect`.

Then `//copy` + `//schem save reread` a pasted build and run `img2schem inspect` on the saved file: names
should be resolved (not `id:<n>`) and the counts should match.

## Results

### Phase 0

| Check | Result / notes |
|---|---|
| Versions (GTNH / Forge / WorldEdit) | GTNH 2.9.0-beta-1 / Forge 10.13.4.1614 / WorldEdit 6.3.0 (Prism, Java 25) |
| `instance list` shows WorldEdit = yes | ✅ |
| `world use` lists blocks per mod | ✅ 4357 blocks, 150 mods (`New World (1)`) |
| `img2schem_cube` orientation + offset | ✅ white toward player, red on the right, gold top-left |
| `img2schem_house`: stairs, door, panes | ✅ paste at (257,106,−125): front wall z=−123, x=247..266, door at (257,107,−123) meta 3; floor at the player's feet level (since changed to one block lower, D-015) |
| `img2schem_modded` pastes cleanly | ✅ `chisel:aluminum_stairs.1` + `chisel:woolen_clay`: both stair rings rise toward the center; only the north aluminum row upside-down, as designed |
| No "Missing ID mapping" / errors in chat | ✅ |
| `inspect` on a WorldEdit-saved file | ✅ `reread.schematic`: names resolved, WEOrigin (247,106,−123) = house min corner |
| Previews match the paste | ✅ |

### Phase 1 (in progress) — engine and template, owner's GTNH world

| Check | Result / notes |
|---|---|
| `examples/house.ops.json` (gable 1:1, logs, belt course, door) | ✅ pasted correctly |
| `examples/cottage.ops.json` (palette families, hip roof, porch in `keep` mode, chimney) | ✅ pasted correctly |
| `examples/brick_house.spec.json` via `compile SPEC.json` | ✅ after D-022 (flush windows; rebuilds replace img2schem's own file) |
| Spec edits (storeys, roof type) take effect on recompile | ✅ after D-022 |
| 1-storey variant keeps both door halves | ✅ after D-023 (a window had replaced the door's upper half) |
| `examples/tower.ops.json` (loft/sweep curves, 109 tall, ~26k blocks) | ✅ pasted correctly; a basis to refine for usability and detail (D-026) |
| Tower detail pass (D-027): smoothed blades, mullions, lights, spiral stair to the roof, terrace doors facing east | ⏳ to check in game: stair directions on the blades, walking up the spiral, terrace doors open outward and stay on, no mobs inside at night |
