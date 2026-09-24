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
