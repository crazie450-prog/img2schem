# Decisions log

One entry per deviation from, or interpretation of, docs/SOW.md: context → decision → consequences.
Entries marked **verify** need a check on the owner's machine or test bed.

## 2026-09-23 · Phase 0

### D-001 Sponge Offset and WEOffset — superseded by D-010
- **Context:** §4.3 wants the bottom-center of the front facade 2 blocks south of the player. From WorldEdit's
  Sponge readers as we understand them: v2 uses `Metadata.WEOffsetX/Y/Z` (when present) as the region's
  min corner relative to the player, and v3 uses `Offset` for the same thing.
- **Decision:** write `Offset = WEOffset = [-(W//2), 0, 2]` in v2, and `Offset` with that value in v3
  (`stages/export_schem.py:front_center_offset`, the single place to change it).
- **Consequences:** needs checking on the modded single-player bed and on Paper + FAWE / Paper + WE (TEST_BED.md).
  If a bed disagrees, flip the constant there and record the result here.

### D-002 Partial block states — obsolete (1.7.10 has no block states, D-009)
- **Context:** RE.4: only properties the block has are written; others take in-game defaults. Phase 0 must
  confirm that WorldEdit accepts partial states.
- **Decision:** `PaletteBlock.default_state` is the bare id; the test grids use partial states on purpose
  (e.g. stairs without `waterlogged`, panes with only connection properties).
- **Consequences:** if a bed rejects them, add a defaults-inference step (RE.4) and record it here.

### D-003 Launcher paths and metadata (verify)
- **Update:** confirmed on the owner's machine for Prism: GTNH found with MC 1.7.10 and Forge 10.13.4.1614.
- **Context:** RI.1 asks to verify each launcher's paths and metadata files on the owner's machine.
- **Decision:** best-known defaults in `instance/discover.py`: vanilla `%APPDATA%\.minecraft` +
  `launcher_profiles.json`; CurseForge `%USERPROFILE%\curseforge\minecraft\Instances\*\minecraftinstance.json`
  with the client jar under `...\minecraft\Install\versions\`; Modrinth App `%APPDATA%\ModrinthApp` (or
  `com.modrinth.theseus`) with `profiles\*\profile.json` **or**, for newer app versions, the `profiles` table in
  `app.db`; Prism `%APPDATA%\PrismLauncher\instances\*` with `mmc-pack.json` + `instance.cfg`, jar under
  `libraries\com\mojang\minecraft\<ver>\minecraft-<ver>-client.jar`. `instance use PATH` works for anything
  not found automatically.
- **Consequences:** update this entry with what `img2schem instance list` shows on the owner's machine.

### D-004 Config file location
- **Context:** §5.4 shows `config.yaml` but not where it lives; `instance use` must persist the choice.
- **Decision:** user config at `%APPDATA%\img2schem\config.yaml` (Windows) / `$XDG_CONFIG_HOME/img2schem/config.yaml`,
  overridden by `./config.yaml`, then `IMG2SCHEM_*` env vars (`IMG2SCHEM_CONFIG` points at another file).
- **Consequences:** a project-local `config.yaml` can pin settings per checkout.

### D-005 validate_state accepts asset-invisible properties — obsolete (D-009)
- **Context:** RP.17 says every property/value must be in `properties`, but some real properties
  (`waterlogged`, `powered`, `persistent`, `distance`) never appear in blockstate files because they don't
  change the model, so the extractor can't see them.
- **Decision:** those four are accepted on any block; any other unknown property is an error.
- **Consequences:** a wrong `waterlogged` on a block that lacks it would pass validation. The Phase 5 helper
  mod (O2) removes the guesswork.

### D-006 Resource packs override, never add, blocks — obsolete (D-009)
- **Context:** RP.3 treats every blockstate file as a block, but a resource pack can ship blockstates for
  blocks that aren't registered.
- **Decision:** candidate blocks come only from the vanilla jar and mod jars; resource packs only override
  their blockstates, models and textures.

### D-007 Byte-identical schematics (still applies; there is no Date field any more)
- **Context:** S5 requires identical bytes for identical input, but gzip headers carry a timestamp and file
  name, and R8.9 metadata carries a `Date`.
- **Decision:** gzip with `mtime=0` and no file name; `SchemMeta.date_ms` pins `Date` (defaults to now).
- **Consequences:** golden tests must pass a fixed `date_ms`.

### D-008 Module layout additions — superseded by D-013
- **Decision:** `palette/build.py` orchestrates extraction and caching (not listed in §5.1);
  `Palette.validate_state` lives on the model until `palette/query.py` arrives in Phase 1;
  `util/blockstate.py` parses state strings. Phase 0 previews use a flat per-block hash color (§7 Phase 0 task 4).

## 2026-09-23 · Re-scope for GT New Horizons

### D-009 Target GTNH 1.7.10 (owner decision)
- **Context:** the owner's instance is GT New Horizons 2.9.0: Minecraft 1.7.10, Forge 10.13.4.1614, 251 mods,
  WorldEdit 6.3.0. The SOW assumed Minecraft 1.13+.
- **Decision:** re-scope the project to GTNH / 1.7.10; `docs/SOW_GTNH.md` governs over `docs/SOW.md`.
- **Consequences:** Sponge `.schem`, DataVersion and blockstate-JSON palette extraction are gone; the palette
  source for colors and shapes is open (SOW_GTNH Q1).

### D-010 `.schematic` layout taken from the WorldEdit 6.3.0 jar, with SchematicaMapping
- **Context:** GTNH's WorldEdit 6.3.0 (the owner's jar, built 2024-07-16) reads only MCEdit `.schematic`. Its
  Forge side registers `RemappingBlockIOFactory` + `ForgeMappingProvider`: on save it writes file-local IDs
  plus a `SchematicaMapping` (name → local ID) and Schematica's AddBlocks nibble order (even cells in the
  high nibble); on load it maps names to the current world's IDs (unknown names → air, with a warning).
  Without a mapping, IDs are used as-is with classic WorldEdit nibble order.
- **Decision:** always write `SchematicaMapping` with local IDs (air 0, then 1..N), `Blocks`/`Data`/`AddBlocks`,
  `WEOrigin = 0` and `WEOffset = [-(W//2), 0, 2]` (y changed to −1 by D-015) (WorldEdit pastes the min corner at player + WEOffset).
- **Verification:** `WeCheck` harness (not committed; it needs the WorldEdit jar) ran the jar's own
  `RemappingBlockIOFactory` serializer/deserializer against our writer/reader in both directions, with
  50–2000 distinct blocks and world IDs different from file IDs: every cell matched.
- **Consequences:** files don't depend on a world's numeric IDs. At most 4095 distinct block names per file.
  **Verified in game 2026-09-23:** orientation, WEOffset placement and name remapping all correct; a
  WorldEdit-saved file reads back with names resolved (TEST_BED.md Phase 0).

### D-011 Blocks are written `modid:name@meta`
- **Decision:** a block is its Forge registry name plus metadata 0–15, written `name@meta` (`@0` omitted),
  e.g. `minecraft:wool@14`, `gregtech:gt.blockcasings@5`. Names may contain upper case and dots.

### D-012 Valid block names come from the world's level.dat
- **Context:** 1.7.10 blocks have no blockstate/model files, so jars can't tell us which blocks exist. Forge
  stores every registered block in `level.dat` → `FML.ItemData` (`\u0001` prefix = block, `\u0002` = item).
- **Decision:** `img2schem world use NAME` selects a world; validation (R10.1b) checks names against its
  registry. Colors/shapes are Q1 in SOW_GTNH.md.
- **Consequences:** the owner must create a world (e.g. `img2schem-test`) before validating builds.
  The exact level.dat layout is from Forge 1.7.10 as documented; confirm with `world use` on the real world.

### D-013 Removed the modern-only code
- **Decision:** deleted the Sponge writer/reader, blockstate/model palette extraction, `dataversions.yaml`
  varints and the `palette build` command (last present in commit fde8606 if a modern target is ever wanted).
  Added `util/block.py`, `instance/world.py`, the MCEdit `stages/export_schem.py`, and `world list/use`.

### D-014 1.7.10 orientation metadata in the test grids (verify)
- **Decision:** stairs `0/1/2/3` ascend east/west/south/north, `+4` upside-down (from `BlockStairs` placement
  logic); `wooden_door` lower half `0–3` = east/south/west/north, upper half `8` (hinge left).
- **Consequences:** the engine (Phase 1) will use the same tables. **Verified in game** for vanilla stairs and
  doors. Modded stairs may use their own metadata scheme (Chisel packs texture variants into metadata), so
  orientation metadata must be known per block, not assumed from vanilla (feeds SOW_GTNH Q1).
  Chisel stairs (`chisel:aluminum_stairs.1`, meta 0–7) were verified in game to follow the vanilla table.

### D-015 Bottom layer replaces the ground under the player (owner decision)
- **Context:** Phase 0 pastes put the build's bottom layer (the floor) at the player's feet level, one block
  above the ground they stand on. SOW §4.3 specified `Offset = [-(W//2), 0, 2]`.
- **Decision:** `WEOffset = [-(W//2), -1, 2]`, so the floor replaces the ground layer and builds sit flush on terrain.
- **Consequences:** stand on the ground where the build goes before `//paste -a`; one block of ground under
  the footprint is replaced by the floor.

## 2026-09-24 · Phase 1 palette

### D-016 Palette from NEI data dumps (resolves SOW_GTNH Q1 for now)
- **Context:** 1.7.10 has no block model files. The owner exported NEI's data dumps from GTNH: `block.csv`
  (4357 blocks with Java class), `itempanel.csv` (58484 stacks: name, ID, meta, display name) and
  `itempanel_icons/` (40987 16x16 PNGs named by display name, with `_2`, `_3`... for repeats).
- **Decision:** `img2schem palette import <dumps>` builds `palette.json` (in the cache, never committed):
  - **variants:** each item-panel row of a block (no NBT, meta 0–15) is a placeable material variant;
  - **colors:** icons are linked to rows by display name + repeat order, **only when a name has exactly as many
    icons as rows** (82% of variants; ~95%+ for chisel, etfuturum, Ztones, BiblioWoods, Botania, vanilla).
    Icon filenames map non-ASCII to `#Uxxxx` and `\/:*?"<>|` to `_` (checked on the dump);
  - **shapes:** regex rules over the class simple name + registry path (not the mod id), plus a curated
    full-cube class list and `palette/data/shape_overrides.yaml` for corrections;
  - **orientation bits:** color lookup strips them per shape (stairs `meta & 8`, slab `meta & 7`, log `meta & 3`).
- **Known limits:**
  - icon colors are shaded 3D renders, ~70% of true texture brightness; consistent between blocks, so
    Phase 1 matching must normalize brightness (clean mode, v1 R6.2);
  - NEI renders some blocks near-black (e.g. Botania metamorphic stone). Icons with L* < 12 are flagged
    `dark_icon` rather than dropped, since real black blocks look the same;
  - 3441 blocks have shape `unknown` (machines, plants, decorative blocks with generic classes). NEI doesn't
    record opacity, render type or tile entities; the SOW's helper mod (O2) would.

### D-017 Which blocks the builder may use (owner decision: "any block with known shape and color")
- **Context:** the SOW's curated `tiers.yaml` (v1 R7.3) lists 1.13+ vanilla names and no modded blocks. The
  owner chose to allow any block whose shape and color are known rather than a list of building mods.
- **Decision:** a variant is **usable** when its block's shape is known, it has a color, and it has no flags
  (`PaletteBlock.usable()`). Two additions make that rule workable on GTNH:
  - **cube outline:** a block with no shape from its class/name whose every icon has NEI's isometric cube
    outline (IoU ≥ 0.95 with the stone icon's outline) is a `full_cube`. Measured on the owner's dump: known
    cubes score 1.0, stairs 0.92, slabs 0.64;
  - **exclude list** `palette/data/exclude.yaml`: regexes over "class + display name" for tile-entity blocks
    (machines, drawers, chests, hatches…), ores, plants and gravity blocks. Matches are flagged `excluded`.
- **Result on the owner's dump:** 4834 usable variants of 1240 blocks (chisel 1903, Ztones 411, etfuturum 264,
  Botania 253, …).
- **Consequences:** heuristic; some machine-like cubes may slip through and some fine blocks may be excluded.
  The owner corrects them by editing `exclude.yaml` / `shape_overrides.yaml` and re-running `palette import`.
  Role tiers (wall/roof/trim/…) are derived from this set by rules in Phase 1 instead of a curated list.

### D-018 Infested blocks and icon file names
- **Infested (owner rule):** never use an infested block when a non-infested variant exists. A variant whose
  display name is "Infested X" is flagged `infested` when any variant is named "X" (case-insensitive);
  otherwise it stays usable (e.g. Twilight Forest "Infested Towerwood", which has no plain counterpart).
- **Icon names fix:** NEI keeps non-ASCII characters in icon file names (`Iszm ①.png`). The earlier `#Uxxxx`
  mapping came from how the dump zip was extracted for development, not from NEI, and cost the owner's Windows
  run all Ztones colors (−546 variants). Only `\/:*?"<>|` are replaced by `_`.

### D-019 Block families, metadata that can't be material, Chisel top slabs, spaces in names
- **Families** (`palette/query.py`, `img2schem palette family BLOCK`): a usable full block's stairs, slab,
  wall, fence and gate are the usable variants with the same display-name stem (drop stairs/slab/wall/fence/
  block/planks/wood/(fireproof), bricks→brick, tiles→tile), nearest color first, at most ΔE 20. On the owner's
  dump: 3808 usable full blocks, 674 with stairs, 745 with a slab, 644 with both (roof-capable).
- **`nbt_variant` flag:** stairs can only carry material in meta 0/8, slabs 0–7, logs 0–3 (the rest is
  orientation). Item variants outside those (Forestry 68, ExtraTrees 34, Railcraft 22) keep their type in
  tile-entity NBT and would paste as the default type, so they're flagged and not used.
- **Chisel slabs** register a separate `<name>_top` block for the top half and use all 16 metas as materials;
  `PaletteBlock.top_block` records the pairing and color lookup uses the full meta for them.
- **Registry names may contain inner spaces** (`Natura:Rare Tree`, 15 blocks); `parse_block` allows them.
- **Known limit:** a display name shared by more rows than icons (e.g. "Marble": 18 rows, 17 icons) gets no
  colors at all, since the missing icon can't be identified. `chisel:marble` is affected.

### D-020 Engine: first op set, 1.7.10 metadata only, paste offset from the compiled origin
- **Scope:** `box, walls, floors, door, openings, roof, column, beam, trim_band, carve, set` (docs/DSL.md).
  Deferred: `facade_from_spec` (with the template generator), `railing, vary, define/place, array, mirror`,
  polygon footprints.
- **States (RE.3–RE.5, re-scoped):** in 1.7.10 the game computes pane/fence/wall connections and stair corner
  shapes, so the engine only writes metadata: stairs direction/upside-down, door halves/facing/hinge, log axis,
  vanilla top slabs (bit 3) or the Chisel `_top` block.
- **Roofs:** gable/hip/shed/flat × pitch 1:1 (stairs), 1:2 (bottom/top slabs), 2:1 (stairs over full blocks).
  Odd-width gables get a full-block ridge; gable fill stops just below the roof; a shed's high-side overhang
  stays level. Checked by eye on previews and by unit tests.
- **Materials:** `$slot`, `$slot.<family member>` (style override first, then the palette family), or a
  literal. Without a palette the engine guesses shapes from vanilla-style names, so hand-written builds and
  tests work offline.
- **Paste offset:** `WEOffset = (-(W//2), -origin_y - 1, -origin_z + 2)`, so the design's z = 0 plane still lands
  2 blocks ahead when a roof overhangs in front (design z < 0).
- **Not yet done from RE.8:** incremental recompiles (only needed for the Phase 3 UI).

### D-021 BuildSpec conventions and the template generator
- **Element boxes** are normalized over the front **wall** (left → right, eaves = 0 → ground = 1), not the whole
  image, so they map straight onto wall rows. The roof is described separately (`roof`).
- **Storey layout:** a foundation at y = 0 (replaces the ground, D-015); walls from y = 1; floor slabs at
  y = 0, g, g + s, …; the roof one block above the walls. Defaults g = s = 4 (SOW); the example uses 5.
- **`window` op instead of `facade_from_spec`:** the template writes one `window` op per measured window
  (recessed one block by default), so `ops.json` is self-contained and editable. Doors 2+ blocks wide become a
  double door (hinges left/right; hinge look not yet checked in game).
- **Rules:** v1 R6.5 (windows ≥ 1×2, never on the ground or eaves row; doors 2 tall at ground), v1 R4a.4 sparse
  side/back windows (one per storey per 6 blocks), RT.3 roof fallback to the nearest-colored usable block that
  has stairs/slab. Element kinds other than window/door are reported as warnings for a designer to handle.
- **Role defaults** for glass/door/floor live in `palette/data/role_defaults.yaml` (vanilla, always present).
- **Golden test:** `tests/golden/house_spec.npz` is the compiled `examples/brick_house.spec.json`; regenerate with
  `UPDATE_GOLDEN=1 pytest tests/unit/test_plan_template.py` after an intentional change.

### D-022 Rebuild workflow fixes (owner feedback)
- **Windows flush:** with 1-block walls, a recessed window leaves a hole in the wall and a pane floating inside
  the room (seen in game). The template now places glass in the wall plane (`recess: 0`); `recess: 1` stays
  available for thicker walls. Supersedes the "recessed by default" part of D-021.
- **`compile` accepts a spec.json** (detected by its `facade` key): it plans with the template designer, writes
  the ops.json next to it, then compiles, so editing a spec and compiling can't silently rebuild stale ops.
- **Overwriting in the WorldEdit folder (R8.10 changed):** a same-name file is replaced when img2schem wrote it
  (its NBT has the `img2schem` compound), so a rebuild keeps its `//schem load` name. Files from anywhere else
  are still never overwritten (the copy gets `_2`, `_3`, …).

### D-023 Doors win over windows in the template
- **Context (owner bug):** at 1 storey the measured upper-floor window boxes compress onto the lower rows; one
  landed on the double door's top halves, and a 1.7.10 door without its upper half pops off.
- **Decision:** the template places door ops after windows and leaves out any window that would cover a door
  cell, with a warning. (The validator's door-pair rule, R10.5, will also catch this class of error.)

### D-024 Validator rules, roof sealing, debug_ops.png
- **Rules** (`stages/validate.py`): R10.3 floating fragments, R10.3b door at ground / window under the roof,
  R10.5 door pairs, R10.6 doors supported, R10.8 single-block roof holes, R10.9 trim/wall contrast (ΔE < 8),
  R10.10 mods required. **Auto-fixes** (applied by `compile` before validating, each reported): add a missing
  upper door half when there is room, otherwise remove the orphan half; remove unsupported doors; remove floating
  fragments under 4 blocks. Not done: R10.7 (gravity blocks are excluded from the palette anyway) and R10.11
  (door reachability, info only).
- **R10.8 is a warning without auto-fix** (deviation): a hole can be an intentional `carve` (skylight), which the
  compiled grid can't tell apart.
- **Connectivity is 18-neighborhood** (faces + edges): stair and slab roofs step diagonally, so consecutive
  courses share only an edge yet form one surface in game; face-only connectivity flagged every hip roof.
- **Roof sealing (bug found by R10.3 on the cottage):** with an overhang, the course above the wall line sat one
  block above the wall top, leaving a slot. The roof op now fills every wall-line column from `y0` up to just
  below its lowest roof block with `gable_fill`; this one rule also produces the gable triangles and a shed's
  tall wall (replacing the separate code). Guarded by a test over every roof type × pitch × overhang 0–2.
- **`debug_ops.png`** (R9.4): iso view with each op's cells in its own color and a legend, written by `compile`.

### D-025 Photo stages: ingest, manual rectify, materials from photo colors
- **True block colors from the icon's top face:** NEI's cube icons light the top face fully and shade the sides
  (~70 % / ~45 %). The palette now stores `face_rgb`/`face_lab` (mean of the top-face diamond, read off the owner's
  quartz icon) and `variance` for cube icons; they match real textures (stone bricks 123, bricks (146,100,87),
  oak planks (157,128,79), quartz 236). Previews and matching use them. This replaces a global brightness factor.
- **Matching (RM.2):** CIEDE2000 (verified on Sharma et al. 2005 reference pairs) + penalties (roof/trim +6 no
  stairs, +3 no slab; wall +2 if variance > 8). Exact search: candidates are visited in color order until the
  color distance alone exceeds the n-th best score (a fixed CIE76 preselection missed roof blocks with stairs).
- **S0/S1:** `stages/ingest.py` (v1 R0.1–R0.3), `stages/rectify.py` (manual corners, any order; aspect from the
  quad; long edge 1024; `rect.json`, `debug_rectify.png`). Auto corners (v1 R1.1c) and Claude corners come later.
- **`img2schem materials SPEC.json PHOTO --corners … [--roof-box …]`:** wall = wall minus padded element boxes,
  windows/doors = inner 60 % of their boxes, base = bottom 6 % (only if the spec has `base`), roof = the owner's
  box on the photo. Median CIELAB per region. R2.4: automatic regions under 50 px or with L* < 20 fall back to the
  spec's `rgb` hint; the owner-marked roof box skips the shadow test (dark roofs are common). RM.3 contrast guard
  for trim. Existing `chosen` blocks are kept unless `--replace`.
- **Windows keep clear glass** unless the photo color is clearly tinted (chroma ≥ 15): windows photograph dark
  because of the room behind them.
- **Doors, trapdoors, fence gates:** only variant 0 is placeable by metadata; other item variants are
  `nbt_variant` (e.g. ExtraTrees doors).
- **Synthetic facades** (`tests/fixtures/synthetic/gen.py`, §8.2): flat-color facade + roof band, known
  homography, noise and vignetting. Tests: rectification ≤ 2 px RMS (A1) over 4 random perspectives; wall color
  recovered and matched to the right block (A-M) through warp/noise/vignette.

### D-026 Grand-scale builds: curve ops (loft, sweep) and raised budgets
- **Context (owner request):** a futuristic tower about 100 blocks tall (curved glass core, crescent blades) "on
  a grand scale". Rectangle-only ops can't express it, and the old budgets (SOW R10.2) were sized for houses.
- **Budgets** (`config.py`): `max_dim` 256 and `max_nonair` 1,000,000 now only warn; `hard_max_total`
  16,000,000 cells stops the compile. New `max_height` 256 is an **error**: a 1.7.10 world ends at y = 256, so a
  taller build can't be pasted. The paste point also needs the build's height of free space below y = 256.
- **`loft`:** a 2D profile (ellipse or polygon, minus cut-out shapes: a crescent = ellipse − offset ellipse)
  carried up through y-keys that scale, stretch, rotate about a pivot and shift. Between keys the transform is
  interpolated linearly or with Catmull-Rom (`smooth`, default). `fill` is solid or a shell `thickness` thick
  (the profile mask minus its erosion, so the shell is watertight); `floor_every` / `caps` add floor layers.
  Replaces SOW §6.5's "polygon footprints" for curved plans.
- **`sweep`:** a round tube along a Catmull-Rom or straight curve (ribs, arches).
- **Rasterization** uses an even-odd point-in-polygon test at cell centers. `cv2.fillPoly` also filled cells
  the outline only touched, so a 12 × 12 square came out 13 × 13 and symmetric shapes weren't symmetric.
- **Not yet:** stair/slab smoothing of curved surfaces; the dict-based compiler is fine at ~30k blocks (tower:
  1 s) but will need vectorizing for builds near 1M blocks.
- **Example:** `examples/tower.ops.json` (80 × 109 × 68, ~26k blocks, vanilla + `etfuturum:smooth_stone`).

### D-027 Detail and in-world usability: smoothing, mullions, lights, spiral stairs
- **Context (owner):** refine the tower for detail and for usability *in the world* (G1 in SOW_GTNH): getting
  between floors, lighting, reaching the terraces.
- **Loft `smooth`:** a wall cell whose top (bottom) face is open while the profile continues one level up
  (down) beside it becomes a stair rising toward that side, upside-down underneath. Exposure is tested against
  the profile, not the shell's cells, so only the outer surface is smoothed. In 1.7.10 stairs don't form
  corners, so a corner cell takes the side with the most solid cells over it. Needs `$slot.stairs`; slabs are
  not used (a slab on a shell leaves a half-block slit).
- **Mullions** are chosen by the perpendicular distance to each rib line (≤ 0.5 block) rather than the arc
  distance: a rib running exactly along a cell boundary matched no cell under the arc test.
- **Lights** skip only cells that share a face with the outside (a plus-shaped erosion). With the 3 × 3
  erosion, small rotated floors lost most of their grid positions. Spacing checked with a block-light
  simulation (light 15 − Manhattan distance through air/glass/panes/doors): on the tower `every` 4 leaves
  3 dark spawnable spots inside the core versus 128 at 5; the remaining dark spots are on the rib and blade
  ledges outside.
- **`spiral_stair`** clears its ring from `y0` to `y1 + 2` except the stairs, so it opens every floor it
  crosses; one op, no separate carve.
- **Preview:** the iso view draws stairs and slabs as their boxes (the front/side/top views stay full cells),
  so smoothing and roofs can be checked in `preview_iso.png`.
- **Tower:** blades are quartz (vanilla quartz stairs) instead of iron, which has no stairs; terraces moved to
  core floor levels (36, 52, 64) with double doors facing east; a spiral stair runs from the lobby to a roof
  deck with a railing.
- **Not verified in game yet:** east-facing doors (only north was checked, D-014) and the smoothing stairs.

### D-028 Array-based compiler (RE.8 performance)
- **Context:** grand-scale builds (D-026). The compiler kept a Python dict entry per cell and the even-odd
  test looped over every outline edge on the whole grid: the tower took 0.65 s, and a million-block build
  would take tens of seconds.
- **Decision:** each op rasterizes to arrays (`Raster`: positions, block ids, labels); box, walls, floors,
  carve, loft and sweep build them with numpy, the small ops still produce lists that are converted. The ops are
  applied in order to dense idx/label/op-index grids sized to the union of all solid cells, then cropped to what
  survives (carves can shrink it). Within one op the last cell at a position wins (`keep`: the first), as
  before. The polygon test is a scanline: per row, the sorted edge crossings and a binary search.
- **Result:** identical grids and op summaries for the house, cottage and tower. Tower 0.65 → 0.17 s (RE.8's
  200 ms target); a 241 × 251 × 241 test build of 535k blocks compiles in 1.8 s. The palette is now ordered
  by first use in op order, so the golden grid was regenerated (same blocks by name).
- **Still to do from RE.8:** incremental recompiles (Phase 3 UI).

### D-029 Components, mirrors, variation and railings (the rest of SOW §6.5)
- **`define` / `place` / `array`:** a component is compiled with the same apply pass as a build, and its final
  non-air blocks become a reusable raster. Carves inside a component only shape the component (it has no build
  underneath yet); a component that needs an opening in the build is placed after a `carve`. `define` can't
  nest, but components can `place` earlier components.
- **`mirror`** copies the rasters of the named earlier ops (what they placed, not what survived later ops):
  "copy the west half" should not depend on what was added on top afterwards. The plane is a whole or half
  block coordinate; cell c maps to 2 × plane − c − 1.
- **State transforms (RE.5)** are a table in `states.py`: stairs and lower door halves turn/mirror their
  direction, an upper door half flips its hinge under a mirror, logs swap the x/z axis on a quarter turn.
  Property-tested (four quarter turns and two mirrors are the identity; x-mirror + 180° = z-mirror) for every
  meta.
- **`vary`** acts on the grid while applying: it only swaps blocks that the target op placed with its own
  `mat` and that are still there, chosen with a seeded RNG (numpy default_rng) over those cells in grid order.
  Random choice doesn't form checkerboards, so no extra rule is needed.
- **`railing`** steps along the longer remaining axis, so consecutive blocks always share a face.
- **In-game check pending:** doors facing east, south and west (`examples/courtyard.ops.json`).

### D-030 API key via .env, owner budgets, palette review sheet
- **API key:** the CLI loads `.env` from the working folder, then from the config folder, at startup; variables
  already in the environment win and empty values are ignored. `.env.example` documents it; `.env` stays
  git-ignored. A few lines of our own instead of python-dotenv (no new dependency).
- **Budgets (owner, replaces SOW §1.5):** `claude.budget_usd` in config: `default` warn US$1 / stop US$5,
  `large` warn US$5 / stop US$10 (selected with `--budget large` once the designer exists). `BudgetGuard.check`
  runs before each API call with its worst-case cost (input + `max_tokens` output at list price), so the stop
  is never overshot; `add` records the actual cost and warns once.
- **Palette review (Phase 1 DoD):** `img2schem palette review BLOCK...` writes a PNG sheet with each block's
  NEI icon, the measured color and its family members, so the owner can check them against the game. It runs
  on the owner's machine because the icons stay in the local dumps (SOW C16).

### D-031 Claude designer, first slice: text prompt -> build
- **Scope:** `img2schem design "PROMPT"` builds from a description with no template (the SOW's `describe`
  mode taken all the way to ops). Photo analysis (S2), the template-plus-photo design (`plan --designer
  claude`), the critique loop and `edit` follow on the same client, tools and loop.
- **Model:** `claude-opus-5` (adaptive thinking, effort `high`, streaming, `max_tokens` 32000 per turn), with
  the server-side fallback to `claude-opus-4-8` (same price, so the budget math holds) when a turn is declined.
  IDs live in `designer/data/defaults.yaml`, prices in `designer/data/pricing.yaml` (CLAUDE.md), both
  overridable from config.yaml.
- **Tools** follow SOW §6.7: one `add_<op>` per op with the input schema generated from engine/ops.py
  (`op` implied by the tool, pydantic titles stripped, define's nested ops as plain objects: 22k → 10k
  tokens), `replace_op`, `delete_op`, `set_style`, `search_palette`, `get_family`, `get_state_summary`,
  `render_views`, `finish`. **Deviation:** `render_views` is offered during the initial design too (the SOW
  offers it only in critique): a prompt-only build has no photo to critique against, and seeing the build is
  how Claude catches proportion mistakes. `match_materials` and `validate` are folded into
  `search_palette` and every tool result (each change returns the validator's issues).
- **Every change is checked:** validated by pydantic, compiled, run through the same `check_build` as
  `compile`; a change that errors is rolled back and returned as `is_error` (RD.3), and an op failing 3 times
  in a row is skipped with a warning.
- **Loop:** a manual loop rather than the SDK's tool runner, because every turn needs the budget check before
  the call, all tool results of a turn go back in one message, and live/recorded/replayed sessions must take
  the same path. Tool inputs stream eagerly and are validated before use; a turn cut off at `max_tokens` runs
  none of its tools; a refusal stops the design.
- **Caching:** the system prompt (role, build-craft guide, docs/DSL.md, a ~5k-token palette summary of the
  owner's full blocks with stairs) and the tool list are a fixed prefix with a cache breakpoint; the
  conversation is cached incrementally. Prompt version `v1` is recorded in `design.json`.
- **Budget (D-030):** before each turn, spend so far + the turn's worst case (all input at the cache-write rate
  + `max_tokens` of output) must fit under the hard stop; a stop keeps and compiles the ops so far and exits 5.
- **Recording and replay:** live runs write `session.jsonl` into the run folder; `--replay` re-runs one with
  no API calls. CI replays a synthetic session (tests/fixtures/designer), and the live SDK path is tested
  against a mock HTTP server; real recordings from the owner's runs can be added as fixtures.

### D-032 Designer on Claude Opus 5.5 (owner)
- **Decision (owner):** the designer runs on `claude-opus-5-5` instead of `claude-opus-5` (D-031): 20 % cheaper per
  token ($4 / $20, cache reads $0.20 per million) and, at `medium` effort, at least as good as Opus 5 at `high`
  with fewer tokens. Effort is set to `medium` explicitly (the API default).
- **Its API changes, handled:** thinking is always on (adaptive); forced tool choice is not used; the loop passes
  every returned block back unchanged and never edits earlier turns, so thinking blocks stay valid (a test checks
  that each request's system, tools and history extend the previous one byte for byte). The request opts into
  `prefix_mismatch_behavior: "drop_block"` (beta `thinking-binding-controls-2026-08-01`): if a block ever failed
  the check the API drops it (reported as a warning) instead of failing a paid build. Notes between tool calls
  arrive as thinking text with `display: "updates"` (beta `thinking-display-updates-2026-08-18`) and are shown
  as progress.
- **Fallback:** `claude-opus-5` re-runs a declined turn (the documented targets are Opus 5 / 4.8). It is dearer
  ($5 / $25), so the budget's worst case is priced at the dearer of the two models, and each turn is priced by
  the model that served it.

### D-033 Edits with version history (RD.4)
- **Builds have a home:** `design --name N` keeps the build as `builds/N.ops.json` (git-ignored, like `out/`),
  with every version in `builds/N.history/` (`v001.ops.json`, ...; `log.json` holds the current version and
  each version's kind, instruction, run folder, cost and summary). **Deviation:** the SOW puts the undo
  history in ops.json; a sidecar keeps ops.json a plain build program that `compile` and hand edits read as
  before.
- **`edit N "instruction"`** starts from the current version and runs the same loop, tools and checks as
  `design`, with the whole ops.json (defaults left out) and the open validator issues in the brief.
  **Deviation:** the SOW sends only `get_state_summary()`; without the ops' fields Claude can't `replace_op`
  reliably, and a build's ops are small next to the cached prompt. `render_views` is left out by default as
  the SOW says (`--render` adds it). An edit that changes nothing adds no version.
- **`undo` / `redo`** move through versions and recompile (so `//schem load` shows it); an edit after an undo
  drops the undone versions. `history` lists them with the total API cost. An ops.json made outside the
  history becomes version 1 before its first edit.
- Each edit is validated change by change like a design (a change that fails is rolled back), so the saved
  version always compiles; a budget stop keeps the changes made so far as the new version (undo reverts it).

### D-034 Design from photos, with the critique pass (RC.1)
- **Photos go to Claude directly:** `design --photo P [--photo P2 ...] ["notes"]` ingests each photo (S0) into
  the run folder and puts the images in the brief, asking Claude to state what it sees (footprint, storeys,
  volumes, roof, front openings, materials per role) before building, with the camera side at z = 0 and
  plausible hidden sides. **Deviation:** the SOW's S2 analysis (pass A/B -> spec.json) and the template as a
  starting point are skipped for now: Opus 5.5 reads images well enough to design from them in one loop, and
  the owner's photos (modern cantilevered houses) are outside what the rectangle-and-gable template covers.
  S2 remains the route for measured, repeatable specs.
- **Critique (RC.1, RC.2):** after `finish`, up to `--critique N` times (default 2 with photos), Claude gets a
  side-by-side sheet (photo | iso from the north-west | front elevation), lists the top discrepancies, fixes
  them and finishes again. The sheet goes in the same user message as the finish tool result (the history
  stays append-only). Each sheet is saved as `critique_N.png` in the run folder; `design.json` records the
  passes.

### D-035 Handedness in photo designs (prompt v2)
- **Context:** the first photo design (the owner's second modern house) came out mirrored before critique
  (garage on the right of the front view instead of the left). Critique pass 1 caught it and rebuilt the house
  the right way round (critique_2 matches the photo and the in-game paste), but that spent a pass. Reading
  "left in the photo = low x" mirrors a build whose front faces north.
- **Decision:** the system prompt (now v2), the photo brief and the critique prompt state the rule outright:
  the viewer of the front looks south, so the photo's left is east (+x); the critique checks for mirroring
  first; the front panel of the critique sheet is labelled "left = east, +x". Aim: right on the first try, so
  the critique passes go to refinements.

### D-036 R10.8 counts only see-through roof holes
- **Context:** house 3 (owner, prompt v2) reported four "single-block holes in the roof" that Claude couldn't
  find. They were a gutter between two roofs (the main roof's flat overhang and the upper room's low hip roof),
  sitting on the hip roof's lower course: nothing to see through.
- **Decision:** R10.8 flags an air cell between roof blocks only when the cell below it is empty too. A false
  warning costs more than noise here: it goes into every tool result and the designer spends turns on it.
