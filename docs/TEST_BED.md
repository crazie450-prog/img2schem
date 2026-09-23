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
`//paste -a`. Expected: the front face 2 blocks in front of you, centered on you. `//undo` removes it.

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
| Versions (GTNH / Forge / WorldEdit) | GTNH 2.9.0-beta-1 / 10.13.4.1614 / 6.3.0 |
| `instance list` shows WorldEdit = yes | |
| `world use` lists blocks per mod | |
| `img2schem_cube` orientation + offset | |
| `img2schem_house`: stairs, door, panes | |
| `img2schem_modded` pastes cleanly | |
| `inspect` on a WorldEdit-saved file | |
| Previews match the paste | |
