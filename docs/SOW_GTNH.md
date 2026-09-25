# img2schem — Re-scope for GT New Horizons (Minecraft 1.7.10)

**Version:** 2.1-GTNH, 2026-09-23. **Decided by:** the owner (D-009). **Status:** governs over `docs/SOW.md`
wherever they conflict; everything not mentioned here stays as written in the SOW.

## Why

The owner's instance is **GT New Horizons 2.9.0 (Minecraft 1.7.10, Forge 10.13.4.1614, 251 mods,
WorldEdit 6.3.0)**. The SOW assumed Minecraft 1.13+ (block-state strings, Sponge `.schem`, blockstate/model
JSON assets, DataVersion). None of that exists in 1.7.10.

## What changes

| SOW area | Was (v2.0) | Now (GTNH) |
|---|---|---|
| Target | Any modern Java instance; Paper beds for vanilla builds | **GTNH 1.7.10 single-player with its WorldEdit 6.3.0** only. No Paper beds (no 1.7.10 Paper) |
| Output format (§6.10, rule 8, D1, D10) | Sponge `.schem` v2/v3; never legacy `.schematic` | **MCEdit `.schematic`**, the only format WorldEdit 6.3.0 reads, written per its bytecode (D-010) |
| Block identity (C10) | `ns:id[prop=value]` strings | **`modid:name@meta`**: Forge registry name + metadata 0–15 (D-011). No numeric IDs in our artifacts |
| Numeric IDs | n/a | Never stored as world IDs: files carry a `SchematicaMapping` (name → file-local ID) and GTNH's WorldEdit remaps names to the loading world's IDs (D-010) |
| DataVersion (RI.2, R8.4) | From version.json / table | **Dropped** (1.7.10 has none) |
| Palette extraction (§6.1 RP.1–RP.17) | Blockstate/model JSON from jars | **Replaced.** 1.7.10 blocks have no JSON models (rendered in code). Phase 0: the valid block **names** come from a world's `level.dat` (`FML.ItemData`, D-012). Colors, meta meanings and shapes: see open question Q1 |
| Block states in the engine (§6.5 RE.3–RE.5) | Engine writes stair `shape`, pane/fence/wall connections, etc. | Simpler: in 1.7.10 **connections and stair corner shapes are computed by the game**. The engine only writes metadata: stairs direction/upside-down, door halves/facing/hinge, log axis, slab top/bottom |
| Previews (§6.11) | Palette face colors | Phase 0: hash color per `name@meta`; Phase 1 depends on Q1 |
| Validator R10.1b | Validate state against the palette | Name must be registered in the selected world; meta 0–15 |
| CLI (§5.2) | `palette build/show/search/report` | Phase 0: `world list`, `world use` (select the world whose registry validates builds). Palette commands return in Phase 1 once Q1 is settled |

Kept: the pipeline and stage artifacts, `spec.json`/`ops.json`, the coordinate conventions (§4.3), budgets,
the Claude designer/critique design, the web UI plan, caching, `DECISIONS.md`, and the phase gates.

## Phase 0 (redone for GTNH)

Tasks
1. Detect the GTNH instance, its mods from `mcmod.info`, WorldEdit and its `schematic-save-dir`. ✅
2. `.schematic` writer/reader matching WorldEdit 6.3.0, with `SchematicaMapping`. ✅ Cross-checked against the
   jar's own serializers in both directions (D-010).
3. World selection and block-name registry from `level.dat`. ✅
4. Previews and structural validation. ✅
5. Test grids with 1.7.10 names/metadata. ✅

Definition of Done (owner) — **all passed 2026-09-23; Phase 0 closed** (docs/TEST_BED.md)
- [x] `img2schem instance list` shows GTNH with WorldEdit = yes
- [x] `img2schem world use img2schem-test` lists the registered blocks per mod
- [x] `img2schem_cube`, `img2schem_house` and `img2schem_modded` paste with the right orientation and offset;
      stairs, door and panes look right (D-014)
- [x] `img2schem inspect` reads a `.schematic` saved by WorldEdit in GTNH (`//copy`, `//schem save`) with
      names resolved
- [x] Previews match the in-game paste orientation

## Owner requirements added during Phase 1 (2026-09-25)

**G1 — Builds are usable in the world**, not only good to look at: every floor is reachable (stairs between
levels, doors onto terraces and balconies), interiors are lit so mobs don't spawn inside, and drops have
railings. Engine support so far: `spiral_stair`, loft `lights` (D-027). The validator's door-reachability check
(R10.11) and a dark-interior check are follow-ups.

**G2 — The Phase 3 UI** (adds to SOW §6.9; everything there still applies):
- G2.1 Start a build from a **prompt, a photo, or both**. The designer is not limited to the house template:
  a prompt like "a futuristic crescent tower" is built directly in ops (loft, sweep, …).
- G2.2 **Continuously refine** a project: prompt-based revisions ("make the blades taller", "add a terrace at
  level 40") change the current ops. Every revision is saved as a new ops version on disk, with undo/redo across
  versions.
- G2.3 A **plain-text editor for `ops.json`** in the GUI, checked against the ops schema, that recompiles on
  save. Chat revisions and hand edits work on the same document.
- G2.4 A **preview** of every version: the 3D viewport of §6.9 plus the PNG previews.

## Open questions

- **Q1 — Where do colors, metadata meanings and shapes come from?** *Decided for Phase 1: (a) NEI dumps,
  `img2schem palette import` (D-016); (b) stays the upgrade path for the `unknown` shapes.* 1.7.10 blocks have no model files, and
  GTNH has thousands of blocks (many GregTech blocks are machines drawn by code). Options, to decide after
  Phase 0 with real files from the owner:
  - (a) **NEI data dumps** already in GTNH (block list, item panel with damage values and names, optionally
    icon PNGs), read by img2schem. No new mod needed; coverage depends on what NEI exports.
  - (b) A small **Forge 1.7.10 helper mod** (the SOW's O2, promoted to core) that dumps every block, its
    sub-blocks/metadata, render type, opacity and average face colors from the loaded textures.
  - (c) A curated vanilla table (like `tiers.yaml`) plus name/texture heuristics for modded blocks.
- **Q2 — Block entities.** Chests, GregTech machines and many modded blocks need tile-entity NBT. The
  default stays: exclude them (R8.11).
