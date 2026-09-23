# img2schem — Statement of Work & Development Plan

**Project:** Single-photo building → voxel model → WorldEdit `.schem` (Minecraft Java Edition)
**Document version:** 1.0 — 2026-09-04
**Prepared for:** Execution by Claude Code (autonomous coding agent), owned/reviewed by Clayton
**Companion doc:** *Photo-to-Minecraft: Feasibility and Build Path* (feasibility study, Sept 2026) — this SOW assumes its conclusions and does not repeat its research.

---

## 0. How to use this document (read first)

This is the build brief for an autonomous coding agent. Place it in the repo at `docs/SOW.md`, create `CLAUDE.md` from **Appendix A**, and work the phases in **§7** in order.

Rules of engagement for the agent:

1. **Phase gates are hard.** Do not start Phase N+1 until every item in Phase N's *Definition of Done* checklist passes and the owner has been shown the preview images for that phase.
2. **Every pipeline stage writes an artifact to disk** (§5.3) and can be re-run in isolation from the previous stage's artifact. Never build a stage that only works as part of a monolithic run.
3. **When this spec conflicts with reality** (a library API changed, a model is unavailable, an endpoint moved), pick the closest working alternative, record it in `docs/DECISIONS.md` (one entry per decision: context → decision → consequences), and continue. Do not stall on the spec.
4. **Verify library APIs against installed versions before use** (`python -c "import x; help(x.fn)"`, read the installed package's README). Snippets in §11 were verified against docs in September 2026 and *will* drift.
5. **Self-review visually.** After any change to geometry, stamping, or block-mapping code, regenerate the preview PNGs (§6.11) and look at them before declaring a task done.
6. **Owner inputs** are listed in §1.5 with defaults. Use the default when one is given; ask only when no default exists.
7. **Do not** build a GUI, a web service, or a Minecraft plugin before Phase 4. CLI-first.
8. **Do not** write the legacy MCEdit `.schematic` format, target Bedrock Edition, or hard-code block IDs without the version-checked palette in §6.9.

---

## 1. Project summary

### 1.1 Objective

Build `img2schem`, a Python command-line tool that takes **one photograph of a building** (optionally more) and produces a **Sponge-format `.schem` file** that loads in WorldEdit / FastAsyncWorldEdit (FAWE) on Minecraft Java Edition and pastes as a recognizable, blocky reproduction of the building: correct proportions, storey count, window/door layout, roof shape, and approximate materials/colors, with **plausible inferred** sides, back, and roof for the parts the photo does not show.

Fidelity target (owner's words): *"accurate to the image but does not need to be exact."*

### 1.2 In scope

| # | Item |
|---|------|
| I1 | Single-photo input (JPEG/PNG/HEIC→converted), building exterior, any common building type (house, townhome, commercial block, church, etc.) |
| I2 | Facade analysis: rectification, storey/window/door/roof detection, material/color estimation, relative depth |
| I3 | Three geometry modes: **procedural** (no external AI 3D), **ai** (image-to-3D model → mesh), **hybrid** (default: AI massing + photo-accurate front facade) |
| I4 | Optional multi-photo input (front/side/back) routed to a multiview image-to-3D backend |
| I5 | Voxelization to a Minecraft-scale grid with color + semantic label per voxel |
| I6 | Mapping voxels to real Minecraft block states using a version-checked palette, with semantic overrides (windows→glass, doors, roof, trim) |
| I7 | Export to Sponge Schematic v2 (default) / v3 (flag) `.schem`, gzip-compressed NBT, pasteable with `//schem load` + `//paste -a` |
| I8 | Preview renders (front/side/top/isometric PNG) so output can be reviewed without launching Minecraft |
| I9 | Validation: structural checks, round-trip parse, block-budget enforcement |
| I10 | Editable intermediate spec (`spec.json`) so a human can correct storeys/windows/roof and rebuild without re-running AI |
| I11 | Caching of model downloads and API results keyed by input hash |

### 1.3 Out of scope (v1)

- Bedrock Edition / `.mcstructure`
- Interior detailing beyond hollow shell + floor slabs
- Pixel-exact or survey-accurate geometry
- Real-time / in-game generation, server plugin, or GUI (Phase 4 may add a minimal local UI *after* the CLI is complete)
- Landscaping, terrain, vehicles, people, signage text
- Training or fine-tuning any ML model

### 1.4 Project-level success criteria

| # | Criterion | How measured |
|---|-----------|--------------|
| S1 | Output loads and pastes on Paper 1.21.x with WorldEdit 7.3+ **and** with FAWE, with zero console errors | Manual runbook (Appendix B), every phase |
| S2 | On the owner's 10-photo test set, ≥ 8 pastes are judged "recognizable" (owner can match paste to photo without labels) | Owner review at end of Phase 2 and Phase 3 |
| S3 | Procedural mode runs end-to-end in < 2 min on CPU-only laptop; hybrid mode < 10 min including API wait | `report.json` timings |
| S4 | Default output ≤ 250,000 non-air blocks and ≤ 128 blocks in any dimension unless `--allow-large` | `validate` stage |
| S5 | Deterministic for identical inputs + seed (excluding external API nondeterminism) | Golden-file tests |
| S6 | Every stage re-runnable from its predecessor's artifact | Integration tests |

### 1.5 Inputs needed from the owner (defaults in brackets)

| Input | Default if not provided |
|-------|-------------------------|
| Target Minecraft Java version | **1.21.4** (config `mc_version`; DataVersion looked up from table §6.10) |
| Server flavor used for testing | Paper + FAWE (also verify plain WorldEdit) |
| Machine: OS / GPU | Assume Windows 11 or Ubuntu, **no GPU** for procedural mode; GPU optional (CUDA) for local depth/3D models |
| `TRIPO_API_KEY` (for `ai`/`hybrid` modes via Tripo API) | If absent, `hybrid` falls back to procedural with a warning; `ai` mode errors |
| `ANTHROPIC_API_KEY` (for VLM layout analysis) | If absent, use local Grounding DINO backend (§6.3) |
| Style preference: *realistic-muted* vs *vibrant* palette | `realistic-muted` (concrete/terracotta/stone/brick; no wool) |
| 10 test photos (owner-supplied, ideally own photos of local buildings) | Agent generates synthetic test facades (§8.2) until provided |
| Max acceptable build size | 128³ bounding box, 250k non-air blocks |

---

## 2. Constraints that shape the design (from the feasibility study)

| # | Constraint | Design response |
|---|------------|-----------------|
| C1 | Sponge `.schem` is fully documented (v2/v3), gzip NBT, palette + varint block data; trivially writable from Python | Own ~150-line writer on `nbtlib` (§6.10). `mcschematic` used only as a cross-check |
| C2 | Single-image-to-3D models (TripoSR, Hunyuan3D, Tripo, Meshy) are trained on object datasets (Objaverse) and are documented to produce blurry flat facades, drifting window grids, and hallucinated backs on buildings | **Hybrid** architecture: AI mesh supplies *massing only* (bulk, roof silhouette, unseen sides). The **front facade is always re-stamped from the photo** (§6.8). Procedural fallback if AI output fails quality heuristics (§6.6) |
| C3 | A single photo has no metric scale; proportions are ambiguous | Convention 1 block = 1 m. Scale derived from storey count × storey height, cross-checked against door height (~2 blocks); user override `--height-blocks` |
| C4 | Photo texture (shadows, noise, lens vignetting) does not translate to block texture; per-pixel nearest-color mapping produces speckled junk | **Region-level material mapping**: one dominant block per semantic region (wall/roof/trim), optional 2-block subtle variation; per-voxel dithering is opt-in only (§6.9) |
| C5 | Schematics store the full bounding cuboid including air; large pastes lag/crash vanilla WorldEdit | Block budgets enforced (§6.12); recommend FAWE + `//paste -a`; keep 1 block/m default |
| C6 | WorldEdit/`.schem` are Java Edition only | Java only. Bedrock explicitly out of scope |
| C7 | Perspective distortion in photos breaks grid detection | Facade rectification via homography before any layout analysis (§6.2) |
| C8 | Tripo API **V2 retires 2026-11-01** (per platform docs) | Build against Tripo API V3 / official `tripo3d` Python SDK; verify SDK targets V3 |
| C9 | Architectural copyright & freedom-of-panorama vary by jurisdiction | Personal/non-commercial use assumed. README carries a notice; no distribution features in v1 |
| C10 | Pre-1.13 "flattening" boundary: block IDs vs block states | Only modern block-state strings (`minecraft:stone_bricks`, `minecraft:oak_stairs[facing=north,...]`); no numeric IDs |

---

## 3. Target environment & assumptions

- **Language:** Python ≥ 3.11 (owner is a strong Python developer, solo). Type hints + `pydantic` models everywhere.
- **Packaging:** `pyproject.toml` (hatch or setuptools), `pip install -e .`, console entry point `img2schem`. Optional extras: `[ai]` (torch, transformers, rembg), `[tripo]`, `[vlm]` (anthropic), `[dev]`.
- **OS:** Windows and Linux both supported (path handling via `pathlib`; no shell-specific code).
- **Compute:** Procedural mode must run CPU-only. Depth Anything V2 *Small* runs acceptably on CPU (seconds per image). Local image-to-3D (TripoSR) is optional and slow on CPU; Hunyuan3D 2.1 requires a 10–29 GB NVIDIA GPU and is a stretch backend only.
- **Minecraft test bed:** Local Paper server (1.21.x) with FAWE, plus a second profile with plain WorldEdit 7.3+ for compatibility checks. Runbook in Appendix B.
- **Network:** Model weights from Hugging Face on first run (cache under `~/.cache/huggingface`); Tripo API over HTTPS; Anthropic API over HTTPS. All optional in procedural mode except Hugging Face for depth (which is itself optional: `--no-depth`).
- **Secrets:** via environment variables or `.env` (never committed). `TRIPO_API_KEY`, `ANTHROPIC_API_KEY`, `HF_TOKEN` (optional).

---

## 4. Architecture

### 4.1 Pipeline (stages → artifacts)

```
 photo.jpg (+ optional side/back photos)
     │
     ▼
[S0 ingest] ─────────────► image.png (normalized, EXIF-rotated, ≤ 2048 px long edge)
     │
     ▼
[S1 rectify] ────────────► rectified.png + rect.json (facade quad, homography H)
     │
     ▼
[S2 layout] ─────────────► spec.json  (FacadeSpec: storeys, windows, doors, roof, materials, scale)
     │        ▲                       ◄── human may edit and re-run from here
     ▼        │
[S3 depth] ──┘───────────► depth.npy  (relative depth of rectified facade; optional)
     │
     ▼
[S4 massing]  mode=procedural ─► mesh-free box+roof voxels
              mode=ai        ─► model.glb (Tripo API / TripoSR / file) → voxelize
              mode=hybrid    ─► ai massing, procedural fallback on failure
     │
     ▼
[S5 voxelize] ───────────► voxels.npz (occupancy, rgb, label; X,Y,Z; 1 voxel = 1 block)
     │
     ▼
[S6 stamp] ──────────────► voxels.npz (front-face voxels overwritten from rectified photo + spec)
     │
     ▼
[S7 map] ────────────────► blocks.npz (int index grid) + palette.json (index → block state)
     │
     ▼
[S8 export] ─────────────► building.schem (Sponge v2/v3) + preview_*.png + report.json
     │
     ▼
[S9 validate] ───────────► pass/fail + warnings in report.json (round-trip parse, budgets, sanity)
```

Every stage is a pure function `artifact_in → artifact_out` behind a small class with `run(ctx)`; the CLI orchestrates them and skips stages whose outputs already exist unless `--force`.

### 4.2 Geometry modes

| Mode | Massing source | Front facade | Sides/back/roof | Needs |
|------|----------------|--------------|-----------------|-------|
| `procedural` | Box footprint (W from facade, L from spec/ratio) + parametric roof | From rectified photo + spec | Rule-based (mirrored/sparse window pattern, same materials) | CPU only |
| `ai` | Image-to-3D mesh (Tripo API v3 default; `triposr` local; `file` for user GLB/OBJ) | From the mesh's own texture (poor) | From mesh | API key or GPU |
| `hybrid` (**default**) | AI mesh massing, **quality-gated**; falls back to procedural | **Always** re-stamped from photo + spec | From mesh (roof silhouette, side shapes) with procedural window pattern overlay | Same as `ai`, degrades gracefully |
| `multiview` | Tripo `multiview_to_model` from 2–4 tagged photos | Re-stamped from front photo | From mesh | API key; Phase 3 |

### 4.3 Coordinate conventions (fixed; document in code)

- Internal arrays are `[X, Y, Z]` with **Y up**, matching Minecraft. `X` = building width (east +), `Z` = depth (south +).
- The **front facade lies in the plane `z = 0` and faces north (−Z)**. The building extends toward +Z. Ground floor is `y = 0` (bottom voxel layer is the ground-floor floor slab).
- Schematic `Offset` is set so that `//paste` (origin at player position) places the **bottom-center of the front facade 2 blocks south of the player**: `Offset = [-(W//2), 0, 2]` (min-corner = origin + Offset per WorldEdit's Sponge writer semantics). **Verify empirically in Phase 0 and adjust** if WorldEdit interprets Offset differently on the installed version.
- Image coordinates: rectified facade image is `(u, v)` with `u→X`, `v` downward → `y = H - 1 - row`.

### 4.4 Key decisions (ADR summary — full entries go in `docs/DECISIONS.md`)

| ID | Decision | Why | Revisit when |
|----|----------|-----|--------------|
| D1 | Own Sponge writer on `nbtlib`, not `mcschematic` as the primary path | Full control of `DataVersion`, `Offset`, palette order; `mcschematic` Version enum coverage for 1.21.x unverified; fewer surprises | `mcschematic` confirmed to cover target version and exposes Offset |
| D2 | Hybrid as default; AI mesh never authoritative for front face | C2 | An image-to-3D model demonstrably handles building facades |
| D3 | Region-level material mapping, not per-voxel | C4; Minecraft aesthetics | Owner asks for photo-realistic map-art style |
| D4 | Human-editable `spec.json` is a first-class artifact | Cheapest fix for AI mistakes is a human editing storeys/windows and rebuilding | Never; keep |
| D5 | CLI-first, stage artifacts on disk | Testability, re-runs, agent self-review | Phase 4 |
| D6 | 1 block = 1 m default, `--detail-scale` multiplier | Standard builder convention; keeps block counts sane | Owner wants bigger/more detailed builds |
| D7 | Full `minecraft:glass` blocks for windows (not panes) in v1 | Pane connection states must be computed explicitly; full blocks paste cleanly | Phase 3 adds panes with computed `north/south/east/west` states |
| D8 | Tripo API V3 via official `tripo3d` SDK | C8; SDK already wraps upload/poll/download | SDK stalls; call REST directly |

---

## 5. Repository layout, CLI, data contracts, config

### 5.1 Repository layout

```
img2schem/
├── CLAUDE.md                     # Appendix A
├── README.md                     # quick start + legal notice
├── pyproject.toml
├── docs/
│   ├── SOW.md                    # this document
│   ├── DECISIONS.md              # ADR log
│   └── TEST_SERVER.md            # Appendix B expanded
├── img2schem/
│   ├── __init__.py
│   ├── cli.py                    # typer app: convert / analyze / build / palette / inspect / preview / validate
│   ├── config.py                 # pydantic Settings + config.yaml loader
│   ├── context.py                # RunContext: run_dir, cache, logger, timers
│   ├── models.py                 # pydantic data contracts (§5.3)
│   ├── stages/
│   │   ├── ingest.py             # S0
│   │   ├── rectify.py            # S1
│   │   ├── layout.py             # S2 (backends: vlm, local)
│   │   ├── depth.py              # S3
│   │   ├── massing_procedural.py # S4a
│   │   ├── massing_ai.py         # S4b (backends: tripo, triposr, file)
│   │   ├── voxelize.py           # S5
│   │   ├── stamp.py              # S6
│   │   ├── blockmap.py           # S7
│   │   ├── export_schem.py       # S8 writer + reader
│   │   ├── preview.py            # S8 renders
│   │   └── validate.py           # S9
│   ├── blocks/
│   │   ├── palette_build.py      # extract average colors from a Minecraft client jar
│   │   ├── palette.py            # load/query palette (Lab kd-tree), tiers, allow/deny lists
│   │   └── data/
│   │       ├── tiers.yaml        # wall/roof/trim/glass/door/floor tiers + deny list
│   │       └── dataversions.yaml # mc_version → DataVersion (§6.10)
│   ├── geom/
│   │   ├── roof.py               # parametric roofs (flat/gable/hip/shed)
│   │   ├── grid.py               # array helpers, hollowing, floors, flood fill
│   │   └── varint.py
│   └── util/
│       ├── cache.py              # hash-keyed cache for model/API outputs
│       ├── color.py              # sRGB↔Lab, dominant color, luminance normalization
│       └── imaging.py
├── data/
│   └── palettes/                 # built palettes: palette_1.21.4.json (generated, committed)
├── tests/
│   ├── unit/
│   ├── golden/                   # golden .schem + previews for synthetic fixtures
│   ├── fixtures/synthetic/       # rendered facades with ground truth JSON (§8.2)
│   └── fixtures/photos/          # owner photos (small, ≤ 1 MB each)
└── examples/
    └── run_example.sh
```

### 5.2 CLI contract

```
img2schem convert PHOTO [--views left=... back=... right=...]
                  [--mode procedural|ai|hybrid|multiview]   (default hybrid)
                  [--mc-version 1.21.4] [--schem-version 2|3]
                  [--height-blocks N | --storey-height 4] [--detail-scale 1.0]
                  [--depth-blocks N] [--roof flat|gable|hip|shed|auto]
                  [--corners x1,y1,x2,y2,x3,y3,x4,y4]        (manual facade quad, image px)
                  [--layout-backend vlm|local] [--ai-backend tripo|triposr|file:PATH]
                  [--texture-mode clean|varied|dithered]   (default clean)
                  [--side-windows mirror|sparse|none]      (default sparse)
                  [--hollow/--solid] [--floors/--no-floors]
                  [--no-depth] [--allow-large] [--seed 0]
                  [--out out/] [--name building] [--force]

img2schem analyze PHOTO [--out spec.json] ...        # runs S0–S3 only
img2schem build SPEC.json [...]                      # runs S4–S9 from an (edited) spec
img2schem palette build --mc-jar PATH [--mc-version 1.21.4]
img2schem palette show [--tier wall]
img2schem inspect FILE.schem                         # dims, palette, counts, DataVersion
img2schem preview FILE.schem [--out preview.png]
img2schem validate FILE.schem [--strict]
```

- Exit codes: `0` success, `2` validation failed, `3` external backend failed and no fallback, `4` bad input.
- All commands accept `-v/-vv` and `--json` (machine-readable summary to stdout).
- Every `convert`/`build` writes to `out/<name>_<yyyymmdd-hhmmss>/` (or `--out` exactly if given) the artifacts listed in §5.3.

### 5.3 Artifacts & data contracts (pydantic models in `models.py`)

| Artifact | Format | Contents |
|----------|--------|----------|
| `image.png` | PNG | Normalized input (EXIF-rotated, sRGB, long edge ≤ 2048) |
| `rect.json` + `rectified.png` | JSON + PNG | Facade quad in image px, homography `H` (3×3), rectified size, method used (`manual`/`vlm`/`auto`), confidence |
| `spec.json` | JSON (`FacadeSpec`) | See below |
| `depth.npy` | float32 `[h, w]` | Relative depth of rectified facade, 0 = nearest |
| `model.glb` (ai modes) | GLB | Raw mesh from backend, plus `model_meta.json` (backend, task id, timings, quality-gate results) |
| `voxels.npz` (`VoxelModel`) | npz | `occ: bool[X,Y,Z]`, `rgb: uint8[X,Y,Z,3]`, `label: uint8[X,Y,Z]`, `meta.json` string (pitch=1, origin, source mode) |
| `blocks.npz` + `palette.json` (`BlockGrid`) | npz + JSON | `idx: int32[X,Y,Z]` (0 = air), `palette: list[str]` block-state strings |
| `building.schem` | gzip NBT | Sponge v2 (default) or v3 |
| `preview_front.png`, `preview_side.png`, `preview_top.png`, `preview_iso.png` | PNG | Rendered from `BlockGrid` using palette average colors |
| `report.json` | JSON | Timings per stage, counts, budgets, warnings, backend used, fallbacks taken, validation result |

**`FacadeSpec` (the human-editable heart of the system):**

```jsonc
{
  "version": 1,
  "source_image": "image.png",
  "building_type": "townhouse",              // free text hint
  "scale": { "blocks_per_m": 1.0, "storey_height_blocks": 4, "ground_storey_height_blocks": 4 },
  "facade": {
    "width_m": 12.0,                          // estimated; drives W in blocks
    "height_m": 9.5,                          // estimated incl. roof
    "storeys": 2,
    "symmetric": true
  },
  "footprint": { "depth_ratio": 0.6, "depth_m": null },   // depth_m overrides ratio if set
  "roof": { "type": "gable", "ridge": "parallel", "pitch": "medium", "overhang_blocks": 1,
            "height_blocks": null },        // null → derived from pitch & depth
  "elements": [                             // normalized rectified-facade coords, origin top-left
    { "kind": "window", "bbox": [0.08, 0.15, 0.22, 0.32], "storey": 2, "style": "rect" },
    { "kind": "door",   "bbox": [0.44, 0.62, 0.56, 0.97], "storey": 1 },
    { "kind": "balcony","bbox": [...] }, { "kind": "garage", "bbox": [...] }
  ],
  "materials": {
    "wall":  { "hint": "red brick", "rgb": [142, 74, 58] },
    "roof":  { "hint": "dark asphalt shingle", "rgb": [55, 55, 60] },
    "trim":  { "hint": "white painted wood", "rgb": [235, 235, 230] },
    "window":{ "hint": "dark glass", "rgb": [40, 60, 80] },
    "door":  { "hint": "dark wood", "rgb": [60, 40, 30] },
    "base":  { "hint": null, "rgb": null }     // optional foundation band
  },
  "regularize": { "windows": true, "snap_to_grid": true },
  "notes": "free text from analyzer (e.g., 'left third occluded by tree')",
  "provenance": { "layout_backend": "vlm", "model": "...", "confidence": 0.78 }
}
```

Validation rules (pydantic): storeys 1–30; bboxes in [0,1] with x0<x1, y0<y1; roof type enum; `rgb` 0–255; unknown `kind` values are kept but ignored with a warning.

**Semantic labels (`label` in `VoxelModel`):** `0 air/none, 1 wall, 2 window, 3 door, 4 roof, 5 trim, 6 floor, 7 base, 8 balcony/other`.

### 5.4 `config.yaml` (defaults; CLI flags override)

```yaml
mc_version: "1.21.4"
schem_version: 2
scale: { blocks_per_m: 1.0, storey_height_blocks: 4, detail_scale: 1.0 }
budgets: { max_dim: 128, max_nonair: 250000, hard_max_total: 2000000 }
layout: { backend: vlm, vlm_model: "claude-sonnet-5", local_model: "IDEA-Research/grounding-dino-tiny", min_conf: 0.3 }
depth:  { enabled: true, model: "depth-anything/Depth-Anything-V2-Small-hf", relief_blocks: 1 }
ai:     { backend: tripo, tripo_model_version: null, timeout_s: 600, remove_background: true,
          quality_gate: { aspect_tolerance: 0.25, min_watertight_ratio: 0.8 } }
massing:{ side_windows: sparse, hollow: true, floors: true, roof: auto }
blocks: { texture_mode: clean, style: realistic-muted, allow_wool: false, allow_gravity: false,
          windows: glass, doors: planks }        # doors: planks | real (Phase 3)
export: { offset_mode: front-center, include_we_metadata: true }
cache_dir: "~/.cache/img2schem"
```

---

## 6. Module specifications (functional requirements + acceptance criteria)

Each module lists: **Responsibility**, **Requirements (R)**, **Acceptance (A)**. Requirement IDs are stable; reference them in commit messages and tests.

### 6.1 S0 — Ingest (`stages/ingest.py`)

**Responsibility:** Normalize any input photo into a predictable `image.png`.

- R0.1 Accept JPEG/PNG/WEBP/HEIC (HEIC via `pillow-heif` if installed; otherwise error with a clear message). Apply EXIF orientation. Convert to sRGB 8-bit RGB. Resize so long edge ≤ 2048 px (LANCZOS). Preserve aspect ratio.
- R0.2 Record original size, resize factor, EXIF focal length if present (optional use for rectification later), and SHA-256 of original bytes → `image_meta.json`. The hash is the cache key for every downstream external call.
- R0.3 Reject images < 400 px on the short edge with exit code 4.

**A0:** Unit tests for orientation (EXIF 1–8), size clamp, hash stability.

### 6.2 S1 — Rectify (`stages/rectify.py`)

**Responsibility:** Find the main facade quadrilateral and warp it to a fronto-parallel rectangle so that rows of windows become horizontal and storeys become bands.

- R1.1 Corner sources, in priority order: (a) `--corners` manual, (b) corners returned by the layout VLM (§6.3) if confidence ≥ 0.5, (c) `auto` estimator (Phase 3): OpenCV line-segment detection (`cv2.createLineSegmentDetector` or `cv2.ximgproc.createFastLineDetector`) → cluster near-vertical and near-horizontal segments → RANSAC vanishing points → pick the largest quad consistent with the two VPs. If none, fall back to the full image with a warning (`method: none`).
- R1.2 Compute homography `H` (`cv2.getPerspectiveTransform`) to a rectangle whose aspect ratio is **estimated** from the quad using the standard rectangle-aspect-from-perspective trick when the VLM supplies `width_m`/`height_m` (use them), else from the average of opposite side lengths. Output size: long edge 1024 px.
- R1.3 Output `rectified.png`, `rect.json` (quad, `H`, method, confidence, aspect estimate) and a debug overlay PNG (`debug_rectify.png`) drawing the quad on the source image.
- R1.4 Multi-photo: side/back photos are rectified independently with the same code and stored as `rectified_<view>.png`; they are only used by `multiview` massing and by side-window stamping in Phase 3.

**A1:** On synthetic fixtures with known homography (§8.2), rectification error ≤ 2 px RMS with manual corners; overlay PNGs visually correct on 10 owner photos.

### 6.3 S2 — Layout analysis (`stages/layout.py`) → `FacadeSpec`

**Responsibility:** Turn the rectified facade into a structured `FacadeSpec`: storeys, windows, doors, roof, materials, scale estimates.

Two backends behind one interface `LayoutBackend.analyze(image, rectified) -> FacadeSpec`:

**`vlm` backend (default when `ANTHROPIC_API_KEY` is set)**
- R2.1 Send the *original* image and the *rectified* image to a Claude vision model (config `layout.vlm_model`; default `claude-sonnet-5` — **verify the current model ID at https://docs.claude.com before use**) with a system prompt that demands **only JSON** matching the `FacadeSpec` schema (embed the JSON schema generated by pydantic in the prompt). Ask for: building type; facade corner points on the original image (normalized); storeys; estimated width/height in metres with reasoning suppressed (numbers only); roof type/ridge/pitch; depth ratio guess; window and door bboxes on the rectified image; per-region material hint + representative hex color; symmetry; occlusion notes.
- R2.2 Parse → validate with pydantic; on failure retry once with the validation error appended; on second failure fall back to `local` backend and record it in `provenance`.
- R2.3 Cache the response keyed by (image hash, prompt version, model id). Never call the API twice for the same input unless `--force`.
- R2.4 Material `rgb` values from the VLM are *hints*; S6/S7 recompute dominant colors from pixels inside each region and only use the VLM color if the pixel sample is unreliable (e.g., region < 50 px² or heavily shadowed).

**`local` backend (no API key, or offline)**
- R2.5 Zero-shot detection with Grounding DINO (`IDEA-Research/grounding-dino-tiny`, Apache-2.0) via `transformers` `zero-shot-object-detection` pipeline on the rectified image with prompts `["window", "door", "garage door", "balcony", "roof"]` (lowercase; the processor expects period-separated phrases — check the model card for the exact formatting the installed `transformers` version expects). Threshold from config (`min_conf`, default 0.3). Optional SAM masks are **not** required in v1 (bboxes suffice on a rectified facade).
- R2.6 Storeys: cluster window bboxes by vertical center (1-D k-means / gap threshold); storeys = number of clusters, sanity-clamped 1–30; if no windows detected, storeys = round(facade_height_est / 3.2 m) with a warning.
- R2.7 Roof: detect the roof band as the region above the top window row where dominant color differs from the wall; classify `flat` if the top edge of the rectified facade is straight and no roof band, `gable` if a triangular region is present (check the facade quad's top edge vs. detected roof polygon), else `hip` — with `auto` defaulting to `gable` for houses and `flat` for buildings ≥ 4 storeys. This is heuristic; VLM backend does better.
- R2.8 Materials: dominant color per region via k-means (k=3) on Lab pixels of the wall mask (facade minus element bboxes), roof band, and element interiors; `hint` left null.

**Common post-processing (both backends)**
- R2.9 `regularize.windows`: group windows into rows by y-overlap; per row set uniform height = median; per column set uniform width = median; if positions are near-uniformly spaced (CV < 0.15), snap to uniform spacing. Keep an `elements_raw` copy for debugging.
- R2.10 Scale: `W_blocks = round(width_m * blocks_per_m * detail_scale)`; `H_wall_blocks = Σ storey heights`; if `--height-blocks` given, derive `blocks_per_m` from it. Door sanity: if the median door height in blocks would be < 2 or > 3 at the derived scale, warn and (if no explicit override) adjust `blocks_per_m` so doors are 2 tall.
- R2.11 Write `spec.json` and `debug_layout.png` (rectified image with bboxes, storey lines, roof band).

**A2:** On synthetic fixtures: storey count exact in ≥ 95%; window bbox IoU ≥ 0.5 for ≥ 80% of windows; door detected in ≥ 90%. On owner photos: reviewed via `debug_layout.png`.

### 6.4 S3 — Depth (`stages/depth.py`)

**Responsibility:** Relative depth of the rectified facade to recess windows/doors and protrude balconies/bays.

- R3.1 Depth Anything V2 via `transformers` `pipeline("depth-estimation", model=cfg.depth.model)`; default `depth-anything/Depth-Anything-V2-Small-hf` (relative). Optional `depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf` when `--metric-depth`. Requires `transformers >= 4.45`.
- R3.2 Normalize to [0,1] within the facade region, invert so 0 = nearest, median-filter (5×5), store `depth.npy`.
- R3.3 Quantize to `relief_blocks` levels (default 1: binary recess/no-recess). Windows/doors are *always* recessed by 1 regardless of depth (semantic rule beats depth); depth adds relief only for bays/balconies/pilasters with area ≥ 4 block cells.
- R3.4 `--no-depth` skips the stage; downstream treats depth as flat.

**A3:** Runs on CPU in < 20 s for a 1024-px image; recess mask matches window bboxes; no relief noise on flat synthetic walls (< 2% cells).

### 6.5 S4a — Procedural massing (`stages/massing_procedural.py`)

**Responsibility:** Build a full `VoxelModel` from `FacadeSpec` alone.

- R4a.1 Footprint `W × L`: `W = W_blocks`; `L = round(depth_m * scale)` if set, else `round(W * depth_ratio)` clamped to [4, 64].
- R4a.2 Walls: 1-block-thick shell on all four sides, height = wall height. Interior hollow (`hollow: true`), with 1-block floor slab at each storey boundary (`floors: true`, label 6). `--solid` fills everything.
- R4a.3 Front facade (`z = 0` plane): every cell gets label from the spec elements rasterized at block resolution (§6.8 does the color; this stage sets occupancy and labels): windows label 2, doors label 3 (door cells are **air** at `z=0` and the door material at `z=1` when `doors: planks`; real 2-block door states in Phase 3), trim label 5 for a 1-block band under the roof and around the door if `materials.trim` exists.
- R4a.4 Side/back facades: window pattern policy `side_windows`: `mirror` replicates the front row pattern scaled to the side width; `sparse` places one window per storey per 6 blocks of side length, aligned to front storey heights; `none` blank walls. Back wall follows `sparse` unless a back photo exists (Phase 3).
- R4a.5 Roof (`geom/roof.py`): parametric generators returning occupancy + label 4:
  - `flat`: 1-block parapet ring, optional 1-block overhang.
  - `gable`: ridge along X (`ridge: parallel`) or Z (`perpendicular`); pitch `low|medium|steep` = rise/run 1:2, 1:1, 2:1 in block steps; gable end triangles filled with wall material (label 1); 1-block overhang. Uses full blocks in v1; stairs/slabs in Phase 3.
  - `hip`: four slopes meeting at ridge/point, same pitch table.
  - `shed`: single slope front-to-back.
  - `auto`: from spec, else `gable` for ≤ 3 storeys, `flat` otherwise.
- R4a.6 Base band: if `materials.base` present, bottom 1 block layer of all walls gets label 7.
- R4a.7 Output `VoxelModel` with `rgb` prefilled from `materials` per label (S6 overwrites the front).

**A4a:** Deterministic; unit tests for each roof type check symmetry, no floating voxels, ridge height; a 2-storey 12×8 house renders correctly in previews.

### 6.6 S4b — AI massing (`stages/massing_ai.py`)

**Responsibility:** Obtain a textured mesh of the whole building from the photo, for massing/unseen sides.

Backends behind `MeshBackend.generate(image_path, ctx) -> Path(glb)`:

- R4b.1 **Preprocess** (all backends): background removal with `rembg` (`remove_background: true`) to isolate the building; crop to the alpha bbox + 5% margin; place on plain white 1024×1024 canvas preserving aspect; save `ai_input.png`. Rationale: object-centric models expect a single centered object.
- R4b.2 **`tripo`** backend (default): official `tripo3d` Python SDK — `TripoClient()` (reads `TRIPO_API_KEY`), `image_to_model(image=..., texture=True, pbr=False, orientation="align_image" if supported, model_version=cfg)`, `wait_for_task(task_id, timeout=cfg.ai.timeout_s)`, `download_task_models(task, run_dir)`. Confirm the installed SDK targets **API V3** (V2 endpoints stop accepting requests 2026-11-01); if it does not, implement a thin REST client from the V3 docs at https://platform.tripo3d.ai/docs and record the decision. Cache results by image hash. Respect credit cost: never re-generate for an unchanged input.
- R4b.3 **`triposr`** backend (local, MIT): clone/install from the `VAST-AI-Research/TripoSR` repo; run its `run.py` equivalent via subprocess or import; CPU allowed with a warning about runtime. Output `.obj` → convert to GLB with trimesh.
- R4b.4 **`file`** backend: user supplies `.glb/.obj/.ply`; skip generation.
- R4b.5 **Post-process:** `trimesh.load(path, force="mesh")`; bake textures to vertex colors (`mesh.visual = mesh.visual.to_color()`); orient so the facade faces −Z: compute the mesh's OBB; the facade is the largest vertical face closest to the camera-facing side (Tripo's `align_image` orientation makes the image-facing side +Z or −Z — **determine empirically once** and encode as a rotation); scale so bounding-box height = `H_total_blocks`; translate min corner to origin.
- R4b.6 **Quality gate** (hybrid mode): compute (a) width/height aspect of the mesh's front projection vs. the spec's `width_m/height_m`; reject if relative error > `aspect_tolerance`; (b) watertightness (`mesh.is_watertight`) or, failing that, ratio of voxels retained after `fill()` vs. before within sane bounds; (c) no more than 3 disconnected components with > 5% volume each. On rejection: log reasons, write `model_meta.json`, and **fall back to procedural massing**. `ai` mode (not hybrid) does not fall back; it errors with exit 3 unless `--no-quality-gate`.
- R4b.7 **Multiview** (Phase 3): `multiview_to_model(images=[front, left, back, right])` order per SDK docs; missing views are omitted where the API allows.

**A4b:** A Tripo run on the owner's first photo produces `model.glb`, previews, and a `model_meta.json`; quality gate rejects an obviously wrong mesh (test with a deliberately mismatched spec). No duplicate API calls on re-run.

### 6.7 S5 — Voxelize (`stages/voxelize.py`)

**Responsibility:** Convert a mesh into a `VoxelModel` at 1 voxel = 1 block.

- R5.1 `vg = mesh.voxelized(pitch=1.0)` (trimesh, method `subdivide`; try `ray` if the surface is very thin); `vg.fill()` to get solid occupancy; `vg.strip()`; take `vg.matrix` (bool `[X,Y,Z]`) and `vg.origin`.
- R5.2 If `hollow: true`: `occ_shell = occ & ~binary_erosion(occ)` (scipy, 6-connectivity) and then re-add floor slabs at storey heights from the spec inside the footprint (label 6). Ensure the shell is ≥ 1 block thick everywhere (`hollow()` in trimesh gives surface voxels; erosion-based is more predictable).
- R5.3 Colors: for each *surface* voxel, nearest point on the mesh via `trimesh.proximity.ProximityQuery(mesh).on_surface(centers)` → triangle id → barycentric interpolation of vertex colors (`trimesh.triangles.points_to_barycentric`). Interior voxels get the wall material color.
- R5.4 Labels: default 1 (wall); roof label 4 for voxels whose nearest surface normal has `|ny| > 0.5` and `y > wall_height - 1`; everything else resolved by S6 stamping / S7 heuristics.
- R5.5 Enforce budgets *before* allocating dense arrays: if `X*Y*Z > hard_max_total` → error unless `--allow-large`.

**A5:** Cube/house test meshes voxelize to expected counts; color sampling reproduces a two-tone test mesh; runtime < 30 s for a 128³ grid.

### 6.8 S6 — Stamp (`stages/stamp.py`)

**Responsibility:** Make the front facade faithful to the photo regardless of how massing was produced.

- R6.1 Build the **facade grid**: resample the rectified facade image to `W_blocks × H_wall_blocks` cells (area-average). For each cell compute mean Lab color and the majority element label from rasterized spec bboxes (window 2, door 3, trim 5, else wall 1).
- R6.2 Luminance normalization per label region: replace each cell's L* with the region median unless `texture_mode: dithered`; keep a/b* (hue) per cell only in `varied` mode. Result: shadows and vignetting vanish; brick vs. stone hue differences survive.
- R6.3 Locate the front surface in the `VoxelModel`: for procedural massing it is exactly `z = 0`; for AI massing it is, per column `(x, y)`, the smallest `z` with `occ[x,y,z]` **and** surface normal within 45° of −Z (drop voxels that belong to side walls seen edge-on). Cells with no matching voxel (mesh narrower than spec) are **created** at `z = z_front(x)` with label 1 so the facade is always complete.
- R6.4 Write `rgb` and `label` from the facade grid into those voxels. Apply depth relief (§6.4): window/door voxels are moved 1 block inward (`z+1`) with the original position left as air; balcony/bay cells protrude 1 block (`z-1`) where relief says so.
- R6.5 Windows: enforce ≥ 1 wide × ≥ 2 tall when storey height ≥ 4 (else 1×1); doors: 2 tall × ≥ 1 wide at ground level; never let a window touch the roof line or the ground (1-block sill/lintel) unless the spec explicitly places it there and `regularize` is off.
- R6.6 Sides/back (procedural rule overlay, all modes): apply the `side_windows` policy from §6.5 to side-facing surface voxels of the AI mesh too, so hybrid builds don't have blank AI-textured sides.

**A6:** Front-face previews of synthetic fixtures reproduce the ground-truth window/door layout cell-for-cell (≥ 95% cell agreement); real photos show no shadow banding in `clean` mode.

### 6.9 S7 — Palette & block mapping (`blocks/*`, `stages/blockmap.py`)

**Responsibility:** Choose a real block state for every occupied voxel.

**Palette build (`img2schem palette build`)**
- R7.1 Extract average sRGB (and Lab) per block from the **owner's local Minecraft client jar** (`.minecraft/versions/<ver>/<ver>.jar` → `assets/minecraft/textures/block/*.png`), which guarantees version-correct block names and textures. For multi-texture blocks (logs, grass), use the side texture. Also read `assets/minecraft/blockstates/*.json` names to validate that every palette entry exists in that version. Commit the generated `data/palettes/palette_<ver>.json` so the tool works without the jar present.
- R7.2 Fallback if no jar: use an open dataset (e.g., `RandomGamingDev/mc_block_color_mapper` output or map-color tables from `plonck/palette`) with a warning that names must be verified for the target version.
- R7.3 **Tiers** (`blocks/data/tiers.yaml`) restrict candidates per semantic label. Initial lists (agent may extend; every entry must exist in the target version):
  - `wall`: all `*_concrete`, all `*_terracotta` (incl. plain `terracotta`), `bricks`, `stone_bricks`, `mossy_stone_bricks`, `stone`, `smooth_stone`, `andesite`, `polished_andesite`, `diorite`, `polished_diorite`, `granite`, `polished_granite`, `sandstone`, `smooth_sandstone`, `red_sandstone`, `quartz_block`, `smooth_quartz`, `deepslate_bricks`, `deepslate_tiles`, `polished_deepslate`, `tuff`, `polished_tuff`, `mud_bricks`, `nether_bricks`, `end_stone_bricks`, all `*_planks`, `stripped_*_log`/`*_wood` (side textures), `blackstone`, `polished_blackstone_bricks`, `cobblestone`, `stone_bricks`
  - `roof`: `deepslate_tiles`, `deepslate_bricks`, `dark_prismarine`, `nether_bricks`, `red_nether_bricks`, `bricks`, `*_terracotta` (browns/reds/grays), `cobbled_deepslate`, `blackstone`, `polished_blackstone`, `dark_oak_planks`, `spruce_planks`, `*_concrete` (dark tones), `copper_block`/`oxidized_copper` variants
  - `trim`: `quartz_block`, `smooth_quartz`, `white_concrete`, `light_gray_concrete`, `smooth_stone`, `stone_bricks`, `polished_andesite`, `birch_planks`, `bone_block`, `*_terracotta` where close
  - `glass`: `glass`, `light_gray_stained_glass`, `light_blue_stained_glass`, `gray_stained_glass`, `black_stained_glass`, `tinted_glass`, `cyan_stained_glass`
  - `door`: `dark_oak_planks`, `spruce_planks`, `oak_planks`, `iron_block`, `*_concrete` (v1 "planks" mode); Phase 3: real `minecraft:*_door[...]` two-block states
  - `floor`: `oak_planks`, `spruce_planks`, `stone`, `smooth_stone`
  - `deny` (never emitted): gravity blocks (`sand`, `red_sand`, `gravel`, `*_concrete_powder`, `anvil`), `*_wool` unless `allow_wool`, `*_leaves`, `ice`/`packed_ice`/`snow*`, `tnt`, any light-emitting or functional block (`glowstone`, `sea_lantern`, `furnace`, `crafting_table`, `*_shulker_box`, `chest`, `beacon`, `magma_block`, `dried_kelp_block`, `slime_block`, `honey_block`, `sponge`), `bedrock`, `barrier`, `command_block`, ores (unless `style: vibrant`), `*_glazed_terracotta` (directional), non-full blocks (stairs, slabs, fences, walls, panes, doors) in v1.

**Mapping**
- R7.4 Distance metric: CIE76 ΔE in Lab (upgrade to CIEDE2000 if results look off; `skimage.color.deltaE_ciede2000`). Precompute a `scipy.spatial.cKDTree` per tier.
- R7.5 `texture_mode: clean` (default): per **semantic region** (front wall, side walls, roof, trim, base, each window, each door) take the region's median Lab → nearest block in the tier → assign to every voxel in the region. Result is architectural, not photographic.
- R7.6 `varied`: per region pick the two nearest tier blocks; assign the primary to 85% of voxels and the secondary to 15% using seeded blue-noise-ish jitter (avoid checkerboards: reject a secondary if it would be adjacent to > 2 secondaries).
- R7.7 `dithered`: per-voxel nearest block with Floyd–Steinberg error diffusion across the facade grid (only meaningful for large flat facades; off by default).
- R7.8 Semantic overrides: label 2 → `glass` tier by window color; label 3 → `door` tier; label 4 → `roof` tier; label 5 → `trim` tier; label 6 → `floor` tier; label 7 → `wall` tier constrained to darker/stone entries.
- R7.9 Contrast guard: if the chosen trim block ΔE from the wall block < 8, pick the next candidate with ΔE ≥ 8 so details remain visible.
- R7.10 Output `BlockGrid` with a **compact palette** (only used states, index 0 = `minecraft:air`).

**A7:** Given a synthetic facade with known material colors, `clean` mode picks the expected blocks; every emitted block state validates against the version's blockstates list; no denied blocks appear; palette size ≤ 32 on typical inputs.

### 6.10 S8 — Schematic export (`stages/export_schem.py`)

**Responsibility:** Write Sponge Schematic v2 (default) or v3 `.schem`; also read them back.

- R8.1 **v2 layout** (root compound named `Schematic`): `Version:int=2`, `DataVersion:int`, `Width/Height/Length:short`, `Offset:int[3]`, `PaletteMax:int`, `Palette:compound{state→int}`, `BlockData:byte[] (varint per cell)`, `BlockEntities:list<compound>` (empty), optional `Metadata:compound{WEOffsetX,WEOffsetY,WEOffsetZ:int}`. Index order **`x + z*Width + y*Width*Length`** (x fastest, then z, then y).
- R8.2 **v3 layout** (unnamed root containing compound `Schematic`): `Version=3`, `DataVersion`, dims, `Offset`, `Blocks:{Palette, Data, BlockEntities}`; optional `Biomes`, `Entities`, `Metadata`. Same indexing and varint rules. Prefer **v2 by default** for widest reader support (WorldEdit 7.x, FAWE, and many third-party plugins read v2; v3 requires newer WorldEdit builds); v3 behind `--schem-version 3`.
- R8.3 Varint: LEB128-style, 7 bits per byte, continuation bit 0x80, max 5 bytes. Fast path: when `len(palette) ≤ 128`, `Data` is simply `idx.astype(uint8)` flattened in the right order. **NBT byte arrays are signed**: convert via `np.frombuffer(bytes, dtype=np.int8)` before constructing `nbtlib.ByteArray`.
- R8.4 `DataVersion` from `blocks/data/dataversions.yaml`; seed with (verify against the Minecraft Wiki *Data version* page before relying on them): `1.20.1: 3465`, `1.20.4: 3700`, `1.21: 3953`, `1.21.1: 3955`, `1.21.4: 4189`. Unknown version → error asking the user to add the value.
- R8.5 Gzip the NBT (`nbtlib.File(..., gzipped=True).save(path)`), root name `Schematic` for v2 (`File.root_name`).
- R8.6 Dims must be ≤ 32767 (NBT short is signed); assert.
- R8.7 Reader: parse v1/v2/v3 back into a `BlockGrid` (used by `inspect`, `validate`, tests, and golden comparisons). Must decode varints properly (not assume 1 byte).
- R8.8 Optional cross-check in tests only: build the same grid with `mcschematic` and compare decoded grids (not bytes).

**A8:** Round-trip `BlockGrid → .schem → BlockGrid` is identical (property test with random palettes up to 300 entries to exercise multi-byte varints). Loads in WorldEdit and FAWE (Appendix B) with correct orientation and Offset behavior.

### 6.11 S8 — Preview renders (`stages/preview.py`)

- R9.1 Orthographic elevations (front from −Z, side from −X, top from +Y) and one isometric view, rendered from `BlockGrid` using palette average colors; simple painter's algorithm or per-pixel depth test in numpy; face shading (top 1.0, front 0.85, side 0.7) so form reads. PNG, ≥ 8 px per block, PIL only (no OpenGL).
- R9.2 `debug_stamp.png`: facade grid with labels colorized.
- R9.3 Optional `--export-obj`: voxel boxes as OBJ (via `trimesh` `VoxelGrid.as_boxes()`) for viewing in any 3D viewer.

**A9:** Previews of the synthetic fixtures match golden PNGs (perceptual hash within tolerance).

### 6.12 S9 — Validate (`stages/validate.py`)

- R10.1 Structural: file parses; `len(Data)` decodes to exactly `W*H*L` entries; all indices < palette size; all palette states parse as `namespace:id[props]`; every state is in the version's blockstates list (from the built palette file); no denied blocks.
- R10.2 Budgets: dims ≤ `max_dim`, non-air ≤ `max_nonair` (warn), total ≤ `hard_max_total` (fail).
- R10.3 Sanity: no floating voxels (each occupied voxel is 6-connected to the ground-connected component) except intentional overhangs ≤ 1 block; front facade has ≥ 1 door at ground level (warn if not); windows not touching the roof line (warn).
- R10.4 Writes `report.json` section `validation: {ok, errors, warnings}`; `--strict` turns warnings into failure.

**A10:** Unit tests for each rule with crafted grids.

### 6.13 Cross-cutting: config, caching, logging, reproducibility

- R11.1 `config.py`: layered settings (defaults → `config.yaml` → env vars `IMG2SCHEM_*` → CLI flags). Dump the effective config into `report.json`.
- R11.2 `util/cache.py`: content-addressed cache (`sha256(input) + stage + params-hash`) for VLM responses, Tripo results (task id + downloaded GLB), depth maps, and Grounding DINO outputs. `--force` bypasses; `img2schem cache clear`.
- R11.3 Logging via `logging` with a run log file in the run dir; `-vv` prints timings per stage.
- R11.4 Seeded RNG (`numpy.random.default_rng(seed)`) for any stochastic step (varied texture, sparse windows).
- R11.5 No global state; each stage takes `RunContext`.

---

## 7. Phased development plan

Effort figures are **estimates for a solo developer working with Claude Code** and are not commitments. Each phase ends with a demo to the owner (preview PNGs + a paste on the test server).

### Phase 0 — Prove the output end (est. 1–2 days)

Goal: a hand-built grid becomes a `.schem` that pastes correctly, so the riskiest unknown (format + Offset semantics) is retired first.

Tasks
1. Repo scaffold: `pyproject.toml`, `CLAUDE.md`, `docs/`, `tests/`, CI (GitHub Actions: lint + unit tests on Linux and Windows).
2. `models.py` (`FacadeSpec`, `VoxelModel`, `BlockGrid`), `geom/varint.py`, `stages/export_schem.py` writer + reader (v2, then v3).
3. `blocks/palette_build.py` + `img2schem palette build` from the owner's jar; commit `palette_1.21.4.json`; `tiers.yaml` v1.
4. `stages/preview.py` (elevations + iso).
5. `stages/validate.py` structural rules.
6. Test-server runbook (`docs/TEST_SERVER.md`, Appendix B). Paste a hand-made 5×5×5 test grid and a 20×12×8 "house" grid; confirm orientation, Offset, and that `//paste -a` skips air.

Definition of Done
- [ ] `pytest` green incl. varint property test and round-trip test
- [ ] `img2schem inspect` on a WorldEdit-saved `.schem` (owner copies any build with `//copy` + `//schem save`) prints correct dims/palette → proves the reader against real files
- [ ] Hand-made grids paste on **both** FAWE and plain WorldEdit with correct orientation (front faces player) and origin behavior; adjustments recorded in `DECISIONS.md`
- [ ] Previews match the in-game paste orientation

### Phase 1 — Procedural MVP (est. 1–2 weeks)

Goal: photo → recognizable front facade + plausible box massing + roof, CPU-only, no external AI 3D.

Tasks
1. S0 ingest, S1 rectify (manual + VLM corners; `auto` deferred), S2 layout (`vlm` **and** `local` backends), S3 depth.
2. S4a procedural massing incl. `geom/roof.py` (flat/gable/hip/shed), floors, hollow.
3. S6 stamp (facade grid, luminance normalization, relief), S7 mapping (`clean` + `varied`), tiers tuned.
4. `img2schem convert --mode procedural`, `analyze`, `build`; caching; `report.json`.
5. Synthetic fixture generator (§8.2) + golden tests.
6. Run on the owner's 10 photos; iterate on `tiers.yaml` and regularization until the owner signs off on ≥ 6/10.

Definition of Done
- [ ] All A-criteria for §6.1–6.5, §6.8–6.12 met on synthetic fixtures
- [ ] 10 owner photos processed CPU-only in < 2 min each; previews reviewed; ≥ 6/10 recognizable
- [ ] Editing `spec.json` (e.g., change `storeys` 2→3, roof gable→hip) and `img2schem build` produces the expected change without re-running AI stages
- [ ] Zero console errors pasting on FAWE and WorldEdit

### Phase 2 — AI massing + hybrid (est. 1–2 weeks)

Goal: true 3D bulk and roof silhouette from an image-to-3D backend, with the photo-faithful front preserved.

Tasks
1. S4b `tripo` backend via official SDK on API V3 (`rembg` preprocessing, caching, timeouts, credit-safety), `file` backend.
2. S5 voxelize with color sampling; orientation determination (one-time empirical test, then fixed rotation).
3. Quality gate + automatic fallback; `model_meta.json`.
4. S6 stamping onto AI surfaces (front detection via normals; side-window overlay).
5. `--mode hybrid` default; A/B previews (procedural vs hybrid) written side by side for the owner.
6. Optional: `triposr` local backend if the owner has a GPU (else document as available-but-slow).

Definition of Done
- [ ] Hybrid runs on 10 photos; fallback triggers on at least one bad mesh and produces a valid build anyway
- [ ] Owner blind test ≥ 8/10 recognizable (S2) across best-of {procedural, hybrid} per photo
- [ ] No duplicate paid API calls for unchanged inputs (verified via cache hit logs)
- [ ] Hybrid end-to-end < 10 min including API wait

### Phase 3 — Fidelity & polish (est. 2–4 weeks, incremental)

Pick by owner priority; each item is independently shippable.
1. **Real doors and window panes**: two-block `minecraft:*_door[facing=north,half=lower|upper,hinge=left,open=false,powered=false]`; `glass_pane` with computed `north/south/east/west` booleans from neighbors.
2. **Sloped roofs with stairs/slabs**: replace stepped full blocks with `*_stairs[facing=…,half=bottom,shape=straight]` on slope faces and slabs at ridges; `deepslate_tile_stairs`, `dark_oak_stairs`, `brick_stairs`, etc. added to the roof tier as *shape-aware* entries.
3. **Auto rectification** (`auto` corner estimator, R1.1c).
4. **Multiview mode** (`--views`), side/back stamping from additional photos.
5. **Trim & detail**: window sills (1-block `smooth_stone_slab`), lintels, corner quoins, chimney detection (VLM), balcony railings (`*_fence`), foundation band.
6. **Better materials**: CIEDE2000; per-storey wall material changes (e.g., stone ground floor + brick upper); mixed-block "brick" textures (bricks + red terracotta 90/10).
7. **Ground plate** option: 1-block `grass_block`/`stone` slab under the footprint for pasting on uneven terrain (`--ground-plate`).
8. Litematica `.litematic` export (nice-to-have; format documented in Litematica's repo).

### Phase 4 — Delivery & UX (est. 1 week)

1. Minimal local review UI (Streamlit or Gradio): upload photo → shows `debug_layout.png` → edit storeys/roof/material → rebuild → download `.schem` + previews. Wraps the CLI; no new logic.
2. Packaging: `pipx`-installable; Windows batch launcher; README quick start; `--doctor` command that checks Java-side prerequisites (WorldEdit folder path) and API keys.
3. Docs pass; `DECISIONS.md` review; version 1.0 tag.

---

## 8. Testing strategy

### 8.1 Layers

| Layer | What | Tooling |
|-------|------|---------|
| Unit | varint, NBT writer/reader, roof generators, regularization, color math, budget rules, tiers loading, deny list | `pytest`, `hypothesis` (varint & round-trip property tests) |
| Golden | Synthetic fixtures → `spec.json`, `blocks.npz`, `.schem`, previews compared to committed goldens (grids compared exactly; PNGs by perceptual hash) | `pytest` + `imagehash` |
| Integration | `convert --mode procedural` on fixtures end-to-end; stage re-run from artifacts; cache hit/miss | `pytest` marks `integration` |
| External (opt-in) | `vlm`, `tripo`, `depth`, `local` detector — skipped unless env `IMG2SCHEM_RUN_EXTERNAL=1`; results cached in `tests/.cache` and committed as fixtures where license permits | `pytest -m external` |
| Manual | Paste on FAWE + WorldEdit; owner blind recognizability test | Appendix B checklist |

### 8.2 Synthetic fixture generator (`tests/fixtures/synthetic/gen.py`)

Renders simple buildings with PIL from a ground-truth `FacadeSpec`: flat-colored wall, dark windows in a grid, a door, roof band/triangle; then applies a random perspective warp (known homography) and mild noise/vignetting. Provides exact ground truth for rectification error, storey count, window IoU, and facade-cell agreement. Generate ≥ 30 fixtures across 1–6 storeys, 3 roof types, 4 wall colors, with/without occluders (a green "tree" blob covering ≤ 15%).

### 8.3 Quality metrics recorded in `report.json` (for tracking across versions)

`storeys_ok`, `window_iou_mean`, `facade_cell_agreement`, `nonair_count`, `palette_size`, `time_per_stage`, `fallbacks[]`, `validation`.

---

## 9. Risks & mitigations

| # | Risk | Likelihood | Impact | Mitigation / trigger |
|---|------|-----------|--------|----------------------|
| R1 | AI mesh looks wrong on buildings (blurry, hallucinated back) | High | Medium | Hybrid design: front always re-stamped; quality gate + procedural fallback; owner can force `--mode procedural` |
| R2 | Offset/orientation semantics differ from expectation | Medium | High (everything pastes wrong) | Phase 0 empirical test; single constant to flip; recorded in `DECISIONS.md` |
| R3 | VLM returns inconsistent JSON / wrong storeys | Medium | Medium | Schema-validated with retry; `spec.json` human-editable; `local` backend fallback |
| R4 | Tripo API V2 sunset (2026-11-01) breaks SDK | Medium | Medium | Target V3 from day one; thin REST client fallback |
| R5 | Block names change between MC versions | Low–Med | Medium | Palette built from the actual jar; validation against blockstates list; `dataversions.yaml` |
| R6 | Huge grids exhaust memory / lag servers | Medium | Medium | Budgets enforced pre-allocation; default 1 block/m; FAWE + `//paste -a` recommended |
| R7 | Photo has heavy occlusion (trees, cars) | High | Medium | VLM occlusion notes; regularization fills window grid; user edits spec |
| R8 | Perspective/rectification failure on wide-angle shots | Medium | Medium | Manual `--corners` always available; debug overlay makes failure obvious |
| R9 | Model downloads blocked / no GPU | Medium | Low | Procedural mode has no ML dependency beyond optional depth; `--no-depth` |
| R10 | Copyright of buildings/photos for shared output | Low (personal use) | Legal | README notice; no sharing/upload features in v1 |
| R11 | Windows path/encoding issues | Medium | Low | `pathlib` everywhere; CI on Windows |

---

## 10. Dependencies & licenses (verify versions at install time)

| Package | Purpose | License | Notes |
|---------|---------|---------|-------|
| `numpy`, `scipy`, `scikit-image` | arrays, kd-tree/erosion, Lab/ΔE | BSD | core |
| `opencv-python-headless` | homography, line detection, resizing | Apache-2.0 | core |
| `Pillow` (+ `pillow-heif` optional) | image I/O, previews | HPND / LGPL (heif) | core |
| `pydantic` v2, `pyyaml`, `typer`, `rich` | models, config, CLI, logs | MIT | core |
| `nbtlib` (≥ 2.0) | NBT read/write | MIT | core (writer) |
| `mcschematic` (11.4.x) | cross-check only | MIT | dev extra |
| `trimesh` (≥ 4) + `rtree` (optional accel) | mesh load, voxelize, proximity | MIT | `[ai]` |
| `torch`, `transformers` (≥ 4.45) | Depth Anything V2, Grounding DINO | BSD / Apache-2.0 | `[ai]`; model weights: Depth Anything V2 Small is Apache-2.0 (Base/Large are CC-BY-NC-4.0 — **use Small** for any non-personal use); Grounding DINO Apache-2.0 |
| `rembg` (+ `onnxruntime`) | background removal | MIT | `[ai]` |
| `tripo3d` (official SDK, VAST-AI-Research) | Tripo API client | check repo | `[tripo]`; API is paid per credit |
| `anthropic` | VLM layout backend | MIT | `[vlm]`; API is paid per token |
| `TripoSR` (repo) | local image-to-3D | MIT | optional, GPU recommended |
| `hypothesis`, `pytest`, `imagehash`, `ruff`, `mypy` | tests/lint | MIT/MPL | `[dev]` |

Data: Minecraft textures are read from the owner's own client jar for palette *statistics only*; the generated palette JSON contains block names and average colors (numbers), not textures.

---

## 11. Reference implementations (verified against docs Sept 2026 — re-verify against installed versions)

### 11.1 Sponge v2 writer/reader skeleton (`nbtlib`)

```python
import numpy as np
from nbtlib import File, Compound, List, Int, Short, IntArray, ByteArray

def encode_varints(values: np.ndarray) -> bytes:
    if values.max() < 128:                       # fast path, 1 byte per cell
        return values.astype(np.uint8).tobytes()
    out = bytearray()
    for v in values.tolist():
        while v >= 0x80:
            out.append((v & 0x7F) | 0x80); v >>= 7
        out.append(v)
    return bytes(out)

def write_schem_v2(path, idx: np.ndarray, palette: list[str], data_version: int,
                   offset=(0, 0, 0)):
    X, Y, Z = idx.shape                          # Width, Height, Length
    assert max(X, Y, Z) <= 32767 and palette[0] == "minecraft:air"
    flat = np.transpose(idx, (1, 2, 0)).reshape(-1)   # order: x fastest, then z, then y
    data = encode_varints(flat)
    root = Compound({
        "Version": Int(2),
        "DataVersion": Int(data_version),
        "Width": Short(X), "Height": Short(Y), "Length": Short(Z),
        "Offset": IntArray(np.array(offset, dtype=np.int32)),
        "PaletteMax": Int(len(palette)),
        "Palette": Compound({name: Int(i) for i, name in enumerate(palette)}),
        "BlockData": ByteArray(np.frombuffer(data, dtype=np.int8)),   # NBT bytes are signed
        "BlockEntities": List[Compound]([]),
        "Metadata": Compound({"WEOffsetX": Int(offset[0]), "WEOffsetY": Int(offset[1]),
                              "WEOffsetZ": Int(offset[2])}),
    })
    f = File(root, gzipped=True)
    f.root_name = "Schematic"                    # v2: root compound is named "Schematic"
    f.save(str(path))

def decode_varints(buf: bytes, n: int) -> np.ndarray:
    out = np.empty(n, dtype=np.int32); i = 0
    for k in range(n):
        v = 0; shift = 0
        while True:
            b = buf[i]; i += 1
            v |= (b & 0x7F) << shift
            if not (b & 0x80): break
            shift += 7
        out[k] = v
    return out
```
Reader: `f = nbtlib.load(path)`; v2 fields are on `f` directly (root named `Schematic`); v3 fields are under `f["Schematic"]` with `Blocks.Palette` / `Blocks.Data`. Invert the palette compound, decode varints to `W*H*L`, reshape `(Y, Z, X)` then transpose back to `(X, Y, Z)`.

### 11.2 Depth Anything V2 (`transformers >= 4.45`)

```python
from transformers import pipeline
from PIL import Image
pipe = pipeline(task="depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")
depth = pipe(Image.open("rectified.png"))["depth"]     # PIL image; convert to np.float32
```
Metric outdoor variant: `depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf`.

### 11.3 Grounding DINO zero-shot boxes

```python
from transformers import pipeline
det = pipeline("zero-shot-object-detection", model="IDEA-Research/grounding-dino-tiny")
boxes = det(image, candidate_labels=["window", "door", "garage door", "balcony", "roof"], threshold=0.3)
# each: {"score", "label", "box": {"xmin","ymin","xmax","ymax"}}
```
If the pipeline rejects the label format on the installed version, use `AutoProcessor` + `AutoModelForZeroShotObjectDetection` with text `"window. door. garage door. balcony. roof."` and `processor.post_process_grounded_object_detection(...)`.

### 11.4 Mesh → voxels with colors (`trimesh`)

```python
import numpy as np, trimesh
from trimesh.proximity import ProximityQuery
m = trimesh.load("model.glb", force="mesh")
m.visual = m.visual.to_color()                   # bake UV texture → vertex colors
m.apply_scale(target_height_blocks / m.extents[1])
m.apply_translation(-m.bounds[0])                # min corner → origin
vg = m.voxelized(pitch=1.0).fill()
occ = vg.matrix                                  # bool [X, Y, Z]
centers = vg.points                              # filled voxel centers
closest, dist, fid = ProximityQuery(m).on_surface(centers)
bary = trimesh.triangles.points_to_barycentric(m.triangles[fid], closest)
vc = m.visual.vertex_colors[m.faces[fid]][..., :3].astype(np.float32)   # (n, 3, 3)
rgb = (bary[:, :, None] * vc).sum(axis=1).astype(np.uint8)
```

### 11.5 Tripo image-to-model (official `tripo3d` SDK; confirm it targets API V3)

```python
import asyncio
from tripo3d import TripoClient
async def gen(png_path, out_dir):
    async with TripoClient() as client:          # reads TRIPO_API_KEY
        task_id = await client.image_to_model(image=png_path, texture=True, pbr=False)
        task = await client.wait_for_task(task_id, timeout=600, verbose=True)
        if task.status != "success": raise RuntimeError(task.status)
        return await client.download_task_models(task, out_dir)   # {"model": ".../model.glb", ...}
paths = asyncio.run(gen("ai_input.png", "run_dir"))
```

### 11.6 WorldEdit paste commands (manual verification)

```
//schem list
//schem load building          # from plugins/WorldEdit/schematics (or FAWE's schematics folder)
//paste -a                     # -a = skip air, keeps terrain
//undo
```

---

## 12. References (primary sources used to write this SOW)

- Sponge Schematic Specification v2 / v3 — `SpongePowered/Schematic-Specification` (GitHub): gzip NBT, palette, varint `Data`, index `x + z*Width + y*Width*Length`, `.schem` extension.
- WorldEdit 7.x Clipboard docs (enginehub.org): `//schem load`, `//schem save`, schematics folder (`plugins/WorldEdit/schematics`), legacy MCEdit loading; `//paste -a`.
- Madeline Miller, "How to use MCEdit schematics in 1.13+": WorldEdit loads legacy `.schematic` via a compatibility layer; new tools should write Sponge.
- `nbtlib` (PyPI/GitHub, ≥ 2.0): gzipped NBT read/write; `File` root-name handling.
- `mcschematic` 11.4.x (PyPI): `setBlock`, `save(folder, name, Version.JE_x)`, cuboid-includes-air caveat.
- Depth Anything V2 (arXiv 2406.09414) and HF model cards `depth-anything/Depth-Anything-V2-*-hf` (`transformers >= 4.45`).
- Grounding DINO (`IDEA-Research/grounding-dino-tiny`, Apache-2.0) via `transformers` zero-shot-object-detection.
- `trimesh` docs: `Trimesh.voxelized(pitch, method)`, `VoxelGrid.fill/hollow/strip/matrix/points`, `ProximityQuery.on_surface`.
- Tripo platform docs (platform.tripo3d.ai/docs): image_to_model, upload/STS, face_limit/texture/pbr options; **API V2 retirement 2026-11-01**; official Python SDK `VAST-AI-Research/tripo-python-sdk`.
- TripoSR (`VAST-AI-Research/TripoSR`, MIT); Hunyuan3D 2.1 (GPU requirements).
- Feasibility study (Sept 2026) for the object-centric limitation of image-to-3D models (ComboVerse, Extend3D, SynCity) and prior art (ObjToSchematic, Bloxelizer, PicCraft).
- Claude Code memory docs (code.claude.com/docs/en/memory): `CLAUDE.md` is read from the working directory upward at session start; `/init` bootstraps it.

---

## Appendix A — `CLAUDE.md` template (place at repo root)

```markdown
# img2schem

Photo of a building → voxel model → WorldEdit `.schem` (Minecraft Java). Python 3.11+, CLI-first.

## Read first
- docs/SOW.md — the full spec and phased plan. Follow §0 rules and §7 phase gates.
- docs/DECISIONS.md — log every deviation from the SOW here (context → decision → consequences).

## Conventions
- Arrays are [X, Y, Z], Y up; front facade at z=0 facing −Z (north). See SOW §4.3.
- Every stage writes an artifact to the run dir and can be re-run from the previous artifact.
- Block states are modern strings (`minecraft:stone_bricks`, `minecraft:oak_stairs[facing=north,...]`). Never numeric IDs. Never legacy `.schematic`.
- Use the version-checked palette in data/palettes/. Never hard-code block names outside blocks/data/tiers.yaml.
- Secrets only via env vars (TRIPO_API_KEY, ANTHROPIC_API_KEY). Never commit .env.

## Commands
- `pip install -e ".[dev]"`; `pytest -q`; `ruff check .`; `mypy img2schem`
- `img2schem convert tests/fixtures/photos/example.jpg --mode procedural --out out/dev`
- External tests: `IMG2SCHEM_RUN_EXTERNAL=1 pytest -m external`

## Definition of done for any task
1. Tests added/updated and green.
2. Previews regenerated and visually checked (open out/**/preview_*.png).
3. report.json shows no new warnings.
4. DECISIONS.md updated if the SOW was deviated from.
```

## Appendix B — Test-server runbook (expand into `docs/TEST_SERVER.md`)

1. Install Java 21. Download the latest Paper build for the target MC version (1.21.x) and, in separate folders, (a) FAWE and (b) WorldEdit 7.3+ jars into `plugins/`. Two server profiles: `server-fawe/` and `server-we/`.
2. First run: `java -Xmx2G -jar paper.jar --nogui`; accept `eula.txt`; set `online-mode=false` for a local test if desired; `op <yourname>`.
3. Schematics folder: `plugins/WorldEdit/schematics/` (WorldEdit) or FAWE's configured schematics folder. The folder may need to be created manually before the first `//schem save`.
4. Copy `building.schem` there → in game: `//schem list`, `//schem load building`, stand where the building should appear facing **south**, `//paste -a`. Expected: front facade 2 blocks in front of you, centered on you. `//undo` to remove.
5. Checklist per build: loads without console errors; orientation correct; no floating/gravity blocks fall; windows/doors placed as in preview; counts match `report.json`; `//schem save` a re-copy and `img2schem inspect` it to compare palettes.
6. Record the installed WorldEdit/FAWE versions and results in `docs/TEST_SERVER.md`.

## Appendix C — Glossary

- **Facade grid**: the rectified front photo resampled to one cell per Minecraft block.
- **Massing**: the building's overall 3D volume (footprint × height × roof form) without detail.
- **Stamping**: overwriting front-face voxels with colors/labels derived from the photo.
- **Tier**: the subset of palette blocks allowed for a semantic label (wall/roof/trim/glass/door/floor).
- **Sponge schematic**: the `.schem` format WorldEdit/FAWE use (v2 default here, v3 optional).
- **DataVersion**: Minecraft's integer world-data version stored in the schematic so WorldEdit can upgrade block states.
