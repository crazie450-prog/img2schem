# Test bed runbook

Expanded from SOW Appendix B. Record versions and results at the end of every phase (B3).

## B1. Primary: the owner's modded instance (single-player)

1. `img2schem instance list` → confirm the loader and MC version. Install the WorldEdit build for that
   loader + version from the official distribution if missing.
2. Create a **creative, superflat** world named `img2schem-test`. Never test in a survival world you care about.
3. Launch once so `config/worldedit/` exists. `img2schem doctor` shows the schematics folder; create it if missing.
4. `python examples/make_test_grids.py --modded-full <id> --modded-stairs <id>` (pick ids from
   `palette_report.json` / `palette.json`). With WorldEdit detected the files are copied into the schematics
   folder automatically (R8.10).
5. In game: `//schem list`, `//schem load img2schem_cube`, stand where the build should go **facing south**,
   `//paste -a`. Expected: the front facade 2 blocks in front of you, centered on you. `//undo` removes it.
6. Check each build:
   - no errors in chat or `logs/latest.log`;
   - orientation: on the cube, the **white** face is toward you, the **red** face is on your **right**, and the
     gold block is at the top **left** corner of the white face;
   - house: door in the middle of the facing wall, roof ridge running left–right, windows as panes;
   - stairs, slabs, panes and doors look right; modded blocks render; nothing falls;
   - block counts match `img2schem inspect`.
7. `//copy` + `//schem save <name>` a re-copy, then `img2schem inspect` it (this proves the reader on real files;
   WorldEdit 7.3 saves Sponge v3).

## B2. Vanilla compatibility: Paper (vanilla-only builds)

1. Java 21; the latest Paper for the target 1.21.x.
2. Two server folders: `server-fawe/` (FastAsyncWorldEdit) and `server-we/` (WorldEdit 7.3+).
3. `online-mode=false` for local testing if wanted; `op <name>`.
4. Copy the `.schem` files to `plugins/WorldEdit/schematics/` (or FAWE's folder) and run the B1 checklist.

## B3. Results

### Phase 0

| Check | Modded SP | Paper + FAWE | Paper + WE |
|---|---|---|---|
| Versions (MC / loader / WorldEdit) | | | |
| `img2schem_cube` orientation + offset | | | |
| `img2schem_house` pastes cleanly | | | |
| `img2schem_modded` pastes cleanly | | n/a | n/a |
| Partial states accepted (D-002) | | | |
| `inspect` on a WorldEdit-saved file | | | |
| Previews match the paste | | | |
