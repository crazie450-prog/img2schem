# img2schem — Statement of Work & Development Plan

**Project:** Photo of a building (or a text description) → Claude-designed build → WorldEdit `.schem` (Minecraft Java Edition), using the owner's **actual installed block palette, including mods**
**Document version:** 2.0 — 2026-09-23 (supersedes v1.0 of 2026-09-04)
**Prepared for:** Execution by Claude Code (autonomous coding agent), owned and reviewed by Clayton
**Companion docs:** *Photo-to-Minecraft: Feasibility and Build Path* (Sept 2026). v1.0 of this SOW is kept for reference; wherever it conflicts with v2.0, **v2.0 governs**.

---

## 0. How to use this document (read first)

This is the build brief for an autonomous coding agent. Place it in the repo at `docs/SOW.md`, place v1.0 at `docs/archive/SOW_v1.0.md` (several kept requirements and the vanilla tier lists are cited from it by R-ID), create `CLAUDE.md` from **Appendix A**, and work the phases in **§7** in order.

Rules of engagement for the agent:

1. **Phase gates are hard.** Do not start Phase N+1 until every item in Phase N's *Definition of Done* checklist passes and the owner has seen that phase's preview images.
2. **Every pipeline stage writes an artifact to disk** (§5.3) and can be re-run in isolation from the previous stage's artifact. The web UI (Phase 3) calls the same stage functions; it never gets its own copy of the logic.
3. **When this spec conflicts with reality** (a library API changed, a model is unavailable, an endpoint moved), pick the closest working alternative, record it in `docs/DECISIONS.md` (one entry per decision: context → decision → consequences), and continue. Do not stall on the spec.
4. **Verify library APIs against the installed versions before use** (`python -c "import x; help(x.fn)"`, the installed package's README). The snippets in §11 were written against September 2026 docs and *will* drift. **Verify Claude model IDs at https://docs.claude.com before hard-coding any default.**
5. **Self-review visually.** After any change to geometry, the engine, the palette or the materials code, regenerate the preview PNGs (§6.11) and look at them before declaring a task done.
6. **Owner inputs** are listed in §1.5 with defaults. Use the default when there is one; ask only when there isn't.
7. **Headless core first.** Phases 0–2 are CLI-only. The local web UI starts in Phase 3 and wraps the same stages. Do not start UI work early.
8. **Do not** write the legacy MCEdit `.schematic` format, target Bedrock Edition, or hard-code block IDs outside the extracted palette (§6.1) and `tiers.yaml`. Modded block IDs come **only** from the palette extracted from the owner's instance.
9. **Never let Claude place blocks one at a time** except through the capped `set` escape hatch. Claude writes **ops** (§6.5) and the engine owns the geometry.

---

## 0.1 What changed from v1.0 and why

**Why:** v1's core risk (C2) was that image-to-3D meshes produce blurry facades, drifting window grids and invented backs on buildings. v1 worked around that by re-stamping the front facade and falling back to procedural massing. Anthropic's Opus 5.5 brick-builder demo (Sept 2026) shows a better pattern: **the model designs the structure as a structured parts list, a deterministic engine builds and checks it, and the UI shows it live.** Applied here, Claude writes a build program of architectural operations, which fits the fidelity target ("accurate, not exact") and Minecraft build conventions (stair roofs, trim, depth) better than voxelizing a mesh.

| Area | v1.0 | v2.0 |
|---|---|---|
| Geometry source | Hybrid: image-to-3D massing (Tripo) plus a stamped front, with procedural fallback | **Ops** (§6.5): a deterministic **template generator** turns `spec.json` into baseline ops (v1's procedural massing, re-expressed), then **Claude refines and details** them. Image-to-3D becomes an optional *massing hint* (Phase 5) |
| Human-editable heart | `spec.json` | `spec.json` **and** `ops.json` (the build program) |
| Palette | Vanilla client jar only, curated `tiers.yaml` | **The owner's instance:** vanilla jar + mod jars (incl. jar-in-jar) + resource packs. Shape classification, material families, auto-tags. `tiers.yaml` still curates vanilla and seeds the auto-tagging |
| Material choice | Nearest color per region (ΔE) | The same ΔE ranking, exposed as a tool (`match_materials`); **Claude chooses** among the top candidates, preferring blocks with a full stair/slab/wall family |
| Stairs, slabs, panes, doors | Deferred to Phase 3 (v1 D7) | **In the engine from Phase 1.** The engine computes stair `facing`/`half`/`shape`, pane connections and door halves, so correctness doesn't depend on the model |
| Depth stage (Depth Anything) | Core | **Dropped.** Recesses and projections are design decisions made in ops |
| Local detector (Grounding DINO) | Fallback layout backend | Optional offline fallback (Phase 5). The no-API path is the template generator plus a hand-edited `spec.json` |
| UI | Streamlit/Gradio in Phase 4 | **Local web app** (FastAPI + React + three.js) in Phase 3: streaming build, chat edits, material slots, layer slider, validator panel |
| Output | Sponge v2 default, v3 by flag | **Unchanged** (v2 default for the widest reader support) |
| Test bed | Paper + FAWE + WorldEdit | **The owner's modded instance in single-player with the WorldEdit mod** is the primary bed (Paper/FAWE cannot load modded blocks). Paper + FAWE/WE remains the compatibility bed for vanilla-only builds |
| DataVersion | Hand-seeded table | Read from the client jar's `version.json` (`world_version`); the table is kept as a fallback |

**Kept unchanged from v1:** §0 rules 1–6, stage artifacts, `report.json`, content-hash caching, `DECISIONS.md`, coordinate conventions (§4.3), 1 block = 1 m, budgets, rectification, `FacadeSpec` (extended), window regularization, the scale and door sanity rules, the region-level (not per-voxel) materials philosophy, the contrast guard, the Sponge writer/reader, PIL previews, the validator rules, the synthetic fixture generator, golden tests, the Windows + Linux CI and the legal notices.

---

## 1. Project summary

### 1.1 Objective

Build `img2schem`, a Python tool with a CLI and a local web UI. It takes **one photograph of a building** (optionally up to four, or a text description) and produces a **Sponge-format `.schem`** that loads in WorldEdit and pastes as a recognizable Minecraft build. The target is correct proportions, storey count, window/door layout, roof form and appropriate materials, with **plausible designed** sides, back and roof for whatever the photo doesn't show. The build uses **only blocks present in the owner's selected Minecraft instance, including modded blocks.**

Fidelity target (owner's words): *"accurate to the image but does not need to be exact."*

UX target: the clean, fluid feel of Anthropic's brick-builder demo. The build streams in live, edits are conversational, and nothing clutters the screen.

### 1.2 In scope

| # | Item |
|---|------|
| I1 | Input: a single photo (JPEG/PNG/WEBP/HEIC→converted) of a building exterior, **or** a text description; optionally up to 4 tagged views |
| I2 | **Instance discovery** (vanilla launcher, CurseForge, Modrinth App, Prism) with MC version, loader and DataVersion detection |
| I3 | **Palette extraction** from the instance: vanilla + mods + resource packs → block list, shapes, properties, face colors, material families, tags, texture atlas |
| I4 | Facade analysis via Claude vision → `spec.json` (storeys, elements, roof, materials, scale), with rectification and regularization |
| I5 | **Build DSL + engine**: ops → block grid, with correct block states for stairs, slabs, panes, doors, logs and fences |
| I6 | **Template generator** (deterministic, no API): `spec.json` → baseline `ops.json` |
| I7 | **Designer** (Claude via tool use): refines and details the ops; conversational edits; render-and-critique loop |
| I8 | Validator + auto-fixes (the Minecraft analogue of the demo's connection checker) |
| I9 | Export: Sponge v2 (default) / v3 `.schem`, PNG previews, `report.json`, layer-by-layer build guide, materials list |
| I10 | Local web UI (Phase 3) |
| I11 | Content-hash caching of API results and palettes |
| I12 | *(Optional, Phase 5)* image-to-3D massing hint (Tripo API V3 / TripoSR), palette helper mod, local detector fallback, `.litematic` export |

### 1.3 Out of scope (v2.0)

- Bedrock Edition / `.mcstructure`.
- Furnished interiors (v2.0 builds hollow shells with floors and stair openings).
- Pixel-exact or survey-accurate geometry.
- In-game generation, server plugins, hosting or multi-user use.
- Landscaping, terrain, vehicles, people, signage text.
- Training or fine-tuning any ML model.
- Redistributing Minecraft or mod textures.

### 1.4 Project-level success criteria

| # | Criterion | How measured |
|---|-----------|--------------|
| S1 | Output loads and pastes with **zero console errors** in the owner's modded instance (single-player, WorldEdit mod) **and**, for vanilla-only builds, on Paper 1.21.x with WorldEdit 7.3+ and FAWE | Manual runbook (Appendix B), every phase |
| S2 | On the owner's 10-photo test set, ≥ 8 pastes are judged "recognizable" (the owner can match paste to photo without labels) | Owner review at the end of Phase 2 |
| S3 | Template-only build (`--designer template`) runs end-to-end in < 1 min CPU-only; a Claude-designed build finishes in < 5 min, including the critique loop | `report.json` timings |
| S4 | Default output ≤ 250,000 non-air blocks and ≤ 128 blocks in any dimension unless `--allow-large` | `validate` stage |
| S5 | Deterministic from `ops.json` onward: the same ops + palette give byte-identical `.schem` files | Golden-file tests |
| S6 | Every stage re-runnable from its predecessor's artifact | Integration tests |
| S7 | Every block in the output exists in the selected instance's palette with valid properties | Validator (hard error) |
| S8 | Palette extraction covers every blockstate file in the instance; a re-run on an unchanged instance is a cache hit in < 2 s | Palette report |
| S9 | UI (Phase 3): ≥ 45 fps orbiting a 50k-block build on the owner's laptop; op toggle/edit recompile + redraw < 200 ms for ≤ 100 ops | Built-in perf overlay |
| S10 | Claude-designed builds report API cost per build; the default settings stay within the owner-set budget (§1.5) | `report.json` `usage` section |

### 1.5 Inputs needed from the owner (defaults in brackets)

| Input | Default if not provided |
|-------|-------------------------|
| Minecraft instance to target | **Auto-detect** the installed instances; the owner picks one. The vanilla test fallback is 1.21.4 |
| Server flavor for vanilla compatibility checks | Paper + FAWE, plus plain WorldEdit 7.3+ |
| Machine: OS / GPU | Windows 11 laptop; **assume no usable GPU**. Nothing in Phases 0–4 needs one |
| `ANTHROPIC_API_KEY` | If absent: `analyze` errors with a clear message, `plan` uses `--designer template`, and the owner can hand-write `spec.json` |
| Design and edit model IDs | Design: the strongest current Claude model; edit: a cheaper current model. **Verify IDs at docs.claude.com** and put them in `config.yaml` |
| Per-build API budget | Soft warning at US$1.00 per build and a hard stop at US$3.00 (configurable). Critique loop max 2 passes |
| Style preference | `realistic-muted` (no wool, no glazed terracotta, ores excluded) |
| Mods to exclude from the palette | None; the owner can toggle mods in `palette.yaml` or the UI |
| 10 test photos (owner-supplied, ideally his own photos of local buildings) | The agent generates synthetic test facades (§8.2) until they're provided |
| Max build size | 128³ bounding box, 250k non-air blocks |
| `TRIPO_API_KEY` (Phase 5 massing hint only) | Feature disabled |

---

## 2. Constraints that shape the design

| # | Constraint | Design response |
|---|------------|-----------------|
| C1 | Sponge `.schem` is fully documented (v2/v3): gzip NBT, palette plus varint block data | Own ~150-line writer on `nbtlib` (§6.10). `mcschematic` is used only as a test cross-check |
| C2 | Single-image-to-3D models are object-centric and produce blurry facades, drifting window grids and invented backs on buildings (feasibility study) | Not in the core path. **Claude designs from a measured spec**; image-to-3D is an optional proportion hint only (Phase 5) |
| C3 | A single photo has no metric scale | 1 block = 1 m. Scale comes from storey count × storey height, cross-checked against a door height of ~2 blocks; override with `--height-blocks` (v1 R2.10 kept) |
| C4 | Photo texture (shadows, noise, vignetting) doesn't translate to blocks; per-pixel color mapping gives speckled junk | **Region-level materials**: one role per region (wall/roof/trim/base…) mapped to one block family, with optional subtle 2-block variation. Per-voxel dithering stays out |
| C5 | Schematics store the full bounding cuboid including air; big pastes lag | Budgets (§6.12); `//paste -a`; 1 block/m default |
| C6 | WorldEdit and `.schem` are Java-only | Java only |
| C7 | Perspective distortion hurts window-grid measurement | Rectify via homography before measuring elements (§6.2) |
| C8 | Tripo API V2 retires 2026-11-01 | Only relevant to the optional Phase 5 massing hint. Target V3 if built |
| C9 | Architectural copyright and freedom of panorama vary by jurisdiction | Personal, non-commercial use. README notice; no sharing features |
| C10 | Block IDs vs block states (post-1.13 flattening) | Modern block-state strings only; no numeric IDs |
| **C11** | **Modded blocks exist only where the mod is installed.** Paper/FAWE cannot load them | Primary test bed is the owner's modded instance (single-player + WorldEdit for Fabric/NeoForge). `.schem` metadata records the source instance and mod list; the validator warns when a build uses modded blocks and names the mods required to paste it |
| **C12** | **Modded asset quirks:** some blocks are code-rendered (connected textures, Framed/Chisel-style blocks, machines) and have no usable JSON model; blockstate file names *usually*, but not always, match registry IDs | Fallback color + `code_rendered` flag, excluded by default; optional helper mod (Phase 5) for exact registry coverage |
| **C13** | **LLM spatial reasoning is imperfect:** off-by-one errors, misaligned roofs, inconsistent symmetry | High-level ops own the geometry; window positions are rasterized from **measured** spec bboxes, not guessed; validator + auto-fixes; render-and-critique loop |
| **C14** | **Large modpacks** can have 10k+ block states, which would overflow a prompt | Claude sees a compact tag summary and queries the palette through tools (`search_palette`, `match_materials`); the full palette never goes in the prompt |
| **C15** | **API cost and latency** | Prompt caching of the system prompt + palette summary, a cheaper edit model, a critique cap, a budget guard, content-hash caching of analysis results |
| **C16** | **Textures are the rights holders' assets** | Extracted textures stay in a local cache directory, are never committed and are never uploaded except inside rendered preview images sent to the Claude API during critique. Committed palette files contain only names and numbers |

---

## 3. Target environment & assumptions

- **Language:** Python ≥ 3.11 (the owner is a strong Python developer, working solo). Type hints and `pydantic` v2 models everywhere.
- **Frontend (Phase 3+):** TypeScript, React, Vite, three.js via `@react-three/fiber` + `@react-three/drei`. Node ≥ 20 is needed only to build the UI. The built static files are served by the Python server, so end users run one command.
- **Packaging:** `pyproject.toml`, `pip install -e .`, console entry point `img2schem`. Extras: `[vlm]` (anthropic), `[server]` (fastapi, uvicorn), `[assist]` (trimesh, tripo3d, rembg), `[local]` (torch, transformers), `[dev]`.
- **OS:** Windows (primary, the owner's laptop) and Linux (CI). `pathlib` everywhere; no shell-specific code.
- **Compute:** everything through Phase 4 runs CPU-only. Optional local image-to-3D (Phase 5) needs an NVIDIA GPU.
- **Minecraft test beds:**
  - **(a) Primary:** the owner's modded instance in single-player with the WorldEdit mod for its loader.
  - **(b) Vanilla compatibility:** local Paper 1.21.x with FAWE, plus a second profile with plain WorldEdit 7.3+.
- **Network:** Anthropic API over HTTPS. Nothing else is required through Phase 4.
- **Secrets:** environment variables or `.env` (never committed): `ANTHROPIC_API_KEY`, and optionally `TRIPO_API_KEY` and `HF_TOKEN`.

---

## 4. Architecture

### 4.1 Pipeline (stages → artifacts)

```
 [P palette]  instance dir ──► palette/<instance-hash>/palette.json + atlas.png + atlas.json + palette_report.json
              (separate command; cached; required by S3–S9)

 photo.jpg (+ optional views)   or   --describe "text"
     │
     ▼
[S0 ingest] ────────────► image.png + image_meta.json
     │
     ▼
[S1 rectify] ───────────► rectified.png + rect.json          (corners from Claude pass A, or --corners)
     │
     ▼
[S2 analyze] ───────────► spec.json (BuildSpec)               ◄── human may edit and re-run from here
     │                     + debug_layout.png
     ▼
[S3 plan]  template ────► ops.json (baseline, deterministic)  ◄── human may edit and re-run from here
           claude   ────► ops.json (refined + detailed; streamed op by op)
     │
     ▼
[S4 compile] ───────────► blocks.npz + palette_used.json (BlockGrid)
     │
     ▼
[S5 validate+fix] ──────► blocks.npz (auto-fixed) + issues.json
     │
     ▼
[S6 critique] (claude designer only; ≤ N passes)
     │   render views ─► Claude compares with photo ─► op edits ─► back to S4
     ▼
[S7 export] ────────────► building.schem + preview_*.png + guide/ + report.json
```

- Every stage is a pure function `artifact_in → artifact_out` behind a small class with `run(ctx)`. The CLI orchestrates them and skips stages whose outputs already exist unless `--force`.
- The web server (Phase 3) calls the same stage classes. The only additions are streaming callbacks: S3 emits each op as it completes, and S4 supports incremental recompiles by dirty region.

### 4.2 Plan modes (`--designer`)

| Mode | What produces `ops.json` | Needs |
|------|--------------------------|-------|
| `template` | Deterministic generator from `spec.json`: v1's procedural massing (box footprint, walls, floors, parametric roof, side-window policy) plus `facade_from_spec` (rasterized measured openings). **This is the no-API path and the regression baseline** | CPU only |
| `claude` (**default**) | Starts from the template ops, then Claude refines and details them via tool use (trims, depth, roof detail, chimneys, dormers, material variation), then runs the critique loop | `ANTHROPIC_API_KEY` |
| `describe` | No photo. Claude writes a `BuildSpec` from text, then proceeds as `claude` | `ANTHROPIC_API_KEY` |

Front-facade fidelity rule (replaces v1 "always re-stamp"): **the front openings come from `facade_from_spec`, which rasterizes the measured, regularized element bboxes.** Claude may add detail around openings (frames, sills, shutters). It may move or resize openings only if the critique step justifies it in the op's `note` field, and every such change is logged in `report.json`.

### 4.3 Coordinate conventions (fixed; document in code) — unchanged from v1

- Internal arrays are `[X, Y, Z]` with **Y up**, matching Minecraft. `X` is the building width (east +), `Z` the depth (south +).
- The **front facade lies in the plane `z = 0` and faces north (−Z)**. The building extends toward +Z. The ground floor is `y = 0`.
- The schematic `Offset` is set so that `//paste` puts the **bottom-center of the front facade 2 blocks south of the player**: `Offset = [-(W//2), 0, 2]`. **Verify empirically in Phase 0 on both the modded-WE and Paper beds** and adjust if the installed WorldEdit interprets Offset differently.
- Image coordinates: the rectified facade image is `(u, v)` with `u→X` and `v` downward, so `y = H - 1 - row`.
- The ops DSL uses the same frame; Claude's system prompt states it explicitly, with a diagram.

### 4.4 Key decisions (ADR summary; full entries go in `docs/DECISIONS.md`)

| ID | Decision | Why | Revisit when |
|----|----------|-----|--------------|
| D1 | Own Sponge writer on `nbtlib` (kept) | Full control of DataVersion, Offset and palette order | `mcschematic` confirmed to cover the target version with Offset |
| D2 | **Claude designs via ops; the engine owns geometry** (replaces v1 D2) | C2, C13; the brick-builder demo pattern | An image-to-3D model handles facades well |
| D3 | Region-level materials (kept); **Claude picks from ΔE-ranked candidates** | C4; builds look architectural | The owner wants map-art style |
| D4 | `spec.json` **and** `ops.json` are first-class human-editable artifacts | The cheapest fix for AI mistakes is a human edit + rebuild | Never; keep |
| D5 | Headless core, CLI-first; web UI in Phase 3 wraps the stages | Testability, agent self-review | — |
| D6 | 1 block = 1 m default, `--detail-scale` multiplier (kept) | Builder convention; sane block counts | The owner wants bigger builds |
| D7 | **Stairs, slabs, panes, doors and logs from Phase 1**, with states computed by the engine (replaces v1 D7) | The engine computes the states deterministically, so the risk v1 worried about goes away | — |
| D8 | Image-to-3D only as an optional Phase 5 massing hint; Tripo V3 via official SDK if built | C2, C8 | — |
| **D9** | **Palette extracted from the owner's instance** (vanilla + mods + resource packs); `tiers.yaml` curates vanilla and seeds auto-tags | Owner requirement; C11, C12 | Helper mod (Phase 5) for code-rendered blocks |
| **D10** | Sponge **v2 default**, v3 via `--schem-version 3` (kept from v1) | Widest reader support | WorldEdit drops v2 reading |
| **D11** | Primary test bed = the owner's modded instance in single-player | C11 | — |
| **D12** | Claude never sees the full palette; it queries through tools | C14 | — |
| **D13** | Analysis runs in two Claude calls: **pass A** (original image → facade corners + coarse spec), then rectify, then **pass B** (original + rectified → element bboxes, materials, roof) | Fixes a circular dependency in v1 (R1.1b needed corners from the same call that needed the rectified image) | One call proves as accurate |
| **D14** | UI stack: FastAPI + WebSocket backend, React + three.js frontend, served locally | Streaming, 3D performance, the owner's Python strength stays in the core | — |

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
│   ├── DSL.md                    # ops reference (also embedded in Claude's system prompt)
│   ├── archive/SOW_v1.0.md       # previous plan; cited by R-ID
│   └── TEST_BED.md               # Appendix B expanded
├── img2schem/
│   ├── cli.py                    # typer app (§5.2)
│   ├── config.py                 # pydantic Settings + config.yaml loader
│   ├── context.py                # RunContext: run_dir, cache, logger, timers, usage meter
│   ├── models.py                 # pydantic data contracts (§5.3)
│   ├── instance/
│   │   ├── discover.py           # launcher-specific instance discovery
│   │   └── detect.py             # MC version, loader, DataVersion, mod list
│   ├── palette/
│   │   ├── sources.py            # vanilla jar, mod jars (+ nested), resource packs, precedence
│   │   ├── models_resolve.py     # blockstate → model → parent chain → textures/elements
│   │   ├── classify.py           # shape classification + families
│   │   ├── colors.py             # face colors, Lab, variance, alpha, tint
│   │   ├── tags.py               # auto-tags, flags, tiers.yaml merge
│   │   ├── atlas.py              # texture atlas for the UI and textured previews
│   │   ├── query.py              # search, ΔE kd-trees per tag/tier, family lookup
│   │   └── data/
│   │       ├── tiers.yaml        # vanilla role tiers + deny list (from v1 R7.3, extended)
│   │       └── dataversions.yaml # fallback mc_version → DataVersion
│   ├── stages/
│   │   ├── ingest.py             # S0
│   │   ├── rectify.py            # S1
│   │   ├── analyze.py            # S2 (Claude pass A/B; regularize; scale)
│   │   ├── plan_template.py      # S3 template generator
│   │   ├── plan_claude.py        # S3 designer + S6 critique driver
│   │   ├── compile.py            # S4 → engine
│   │   ├── validate.py           # S5
│   │   ├── export_schem.py       # S7 writer + reader
│   │   ├── preview.py            # S7 renders (also used by critique)
│   │   └── guide.py              # S7 build guide + materials list
│   ├── engine/
│   │   ├── ops.py                # op pydantic models (discriminated union)
│   │   ├── compiler.py           # ops → grid; dirty-region recompiles
│   │   ├── roof.py               # flat/gable/hip/shed/mansard/dome_approx with stair/slab states
│   │   ├── states.py             # stairs facing/half/shape, panes/fences/walls connections, doors, logs axis
│   │   └── grid.py               # array helpers, flood fill, components
│   ├── designer/
│   │   ├── client.py             # Anthropic client wrapper: streaming, caching, retries, usage/budget
│   │   ├── tools.py              # tool JSON schemas generated from engine/ops.py + palette tools
│   │   └── prompts/              # system prompt, build-craft guide, analysis prompts (versioned)
│   ├── server/                   # Phase 3
│   │   ├── app.py                # FastAPI: REST + WebSocket
│   │   └── sessions.py           # per-project state, undo/redo stack
│   └── util/ (cache.py, color.py, imaging.py, varint.py)
├── web/                          # Phase 3: React + Vite + r3f (built into img2schem/server/static)
├── data/palettes/                # committed: vanilla palette JSON for CI (names + numbers only)
├── tests/
│   ├── unit/  golden/  fixtures/synthetic/  fixtures/photos/
│   ├── fixtures/jars/            # tiny fake jars: vanilla-like, Fabric, NeoForge, jar-in-jar, resource pack, malformed
│   └── fixtures/claude/          # recorded Claude sessions for replay (no API in CI)
└── examples/
```

**Cache (not in the repo):** `~/.cache/img2schem/` holds `palettes/<instance-hash>/` (including extracted textures), `api/` and `renders/`.

### 5.2 CLI contract

```
img2schem instance list                               # discovered instances: name, launcher, MC version, loader, mod count
img2schem instance use NAME|PATH                      # set active instance in config

img2schem palette build [--instance NAME|PATH] [--force]
img2schem palette show   [--mod create] [--tag roof] [--shape stairs] [--flags]
img2schem palette search "dark weathered stone" [--tier wall] [--n 10]
img2schem palette report                              # per-mod counts, code-rendered list, filters in effect

img2schem analyze PHOTO [--views left=... back=... right=...] [--corners ...] [--out spec.json]
img2schem analyze --describe "two-storey brick colonial with a hip roof" [--out spec.json]
img2schem plan SPEC.json [--designer template|claude] [--critique N] [--out ops.json]
img2schem compile OPS.json [--out out/]               # S4, S5 and S7 (no API)
img2schem edit OPS.json "make the roof steeper and add a chimney on the east side"   # Claude edit → new ops.json
img2schem convert PHOTO [all analyze/plan flags] [--mc-schem-version 2|3] [--allow-large] [--name building] [--out out/]

img2schem inspect FILE.schem                          # dims, palette, counts, DataVersion, mods required
img2schem preview FILE.schem|OPS.json [--out preview.png] [--textured]
img2schem validate FILE.schem|OPS.json [--strict]
img2schem serve [--port 8765] [--open]                # Phase 3 web UI
img2schem doctor                                      # checks API key, instance, WorldEdit presence, schematics folder
img2schem cache clear [--palettes|--api|--renders]
```

- **Exit codes:** `0` success, `2` validation failed, `3` external backend failed with no fallback, `4` bad input, `5` budget exceeded.
- All commands accept `-v/-vv` and `--json` (a machine-readable summary to stdout).
- `convert`, `plan` and `compile` write to `out/<name>_<yyyymmdd-hhmmss>/`, or to `--out` exactly when it's given.

### 5.3 Artifacts & data contracts (pydantic models in `models.py`)

| Artifact | Format | Contents |
|----------|--------|----------|
| `image.png`, `image_meta.json` | PNG + JSON | As v1 R0.1–R0.2 |
| `rect.json` + `rectified.png` + `debug_rectify.png` | JSON + PNG | As v1 R1.3 |
| `spec.json` (`BuildSpec`) | JSON | v1 `FacadeSpec` **extended** (below) |
| `debug_layout.png` | PNG | Rectified image with bboxes, storey lines, roof band |
| `ops.json` (`OpsDoc`) | JSON | `{version, instance_hash, palette_hash, style: {slot → block state}, ops: [Op…], history: [...]}` |
| `blocks.npz` + `palette_used.json` (`BlockGrid`) | npz + JSON | `idx: int32[X,Y,Z]` (0 = air), `palette: list[str]` of full block-state strings |
| `issues.json` | JSON | Validator output: `[{rule, severity, pos, message, autofix_applied}]` |
| `building.schem` | gzip NBT | Sponge v2 (default) or v3; `Metadata` includes `img2schem: {version, mods_required[], instance_name}` |
| `preview_front/side/top/iso.png` | PNG | As v1 R9.1; `--textured` uses the atlas |
| `guide/` | HTML + PNG | Per-layer top-down grids, legend, materials list (stacks/shulkers) |
| `report.json` | JSON | Timings, counts, budgets, warnings, fallbacks, validation, **usage** (tokens in/out/cached, est. cost per stage), effective config |
| `palette.json` (`Palette`) | JSON | Per block: `id, mod, shape, family, properties{name: [values]}, default_state, faces{top,bottom,side: {hex, lab}}, alpha, variance, tinted, tags[], flags[], textures{face: atlas_key}` |

**`BuildSpec` = v1 `FacadeSpec` plus:**
```jsonc
{
  "version": 2,
  "...": "all v1 FacadeSpec fields unchanged (scale, facade, footprint, roof, elements, materials, regularize, notes, provenance)",
  "input_mode": "photo | multiview | describe",
  "style": { "era": "colonial", "descriptors": ["symmetrical", "brick", "white trim"] },
  "materials": {                         // v1 keys kept; each gains palette candidates + chosen block
    "wall": { "hint": "red brick", "rgb": [142,74,58],
              "candidates": ["minecraft:bricks", "minecraft:red_terracotta", "..."],   // ΔE-ranked from active palette
              "chosen": "minecraft:bricks" }
  },
  "features": [                          // things template ops don't cover; Claude designs them
    { "kind": "chimney", "where": "east gable", "note": "brick, ~1.5 m wide" },
    { "kind": "porch", "where": "front center", "note": "4 white columns, flat roof" }
  ],
  "unseen": { "strategy": "infer", "notes": "back likely mirrors front with fewer windows" }
}
```

**`Op` (discriminated union on `op`; full reference in `docs/DSL.md`, §6.5):** every op has `id` (stable string), `label` (human text), `group` (optional), `note` (optional rationale), and `mode` (`overwrite` | `keep`, default `overwrite`).

**Semantic labels** (kept from v1, carried on each compiled cell for the validator, previews and guide): `0 air, 1 wall, 2 window, 3 door, 4 roof, 5 trim, 6 floor, 7 base, 8 other`.

### 5.4 `config.yaml` (defaults; CLI flags override)

```yaml
instance: null                         # set by `instance use`; else prompt
schem_version: 2
scale: { blocks_per_m: 1.0, storey_height_blocks: 4, detail_scale: 1.0 }
budgets: { max_dim: 128, max_nonair: 250000, hard_max_total: 2000000 }
claude:
  design_model: "<verify at docs.claude.com — strongest current model>"
  edit_model:   "<verify — cheaper current model>"
  analyze_model: "<same as design_model by default>"
  max_tokens: 16000
  critique_passes: 2
  budget_usd: { warn: 1.00, stop: 3.00 }
  prompt_cache: true
  pricing_file: "pricing.yaml"         # $/MTok per model; owner updates; never hard-coded in code
palette:
  include_mods: all                    # or list
  exclude_mods: []
  exclude_flags: [utility, gravity, block_entity, code_rendered]
  style: realistic-muted               # vibrant allows ores, glazed terracotta, wool
  allow_wool: false
  blacklist: []
materials: { texture_mode: clean, contrast_min_de: 8, variation_ratio: 0.15 }
massing: { side_windows: sparse, hollow: true, floors: true, roof: auto }
export: { offset_mode: front-center, include_we_metadata: true, write_to_instance: true }
server: { port: 8765, open_browser: true }
cache_dir: "~/.cache/img2schem"
```

---

## 6. Module specifications (functional requirements + acceptance criteria)

Each module lists **Responsibility**, **Requirements (R)** and **Acceptance (A)**. Requirement IDs are stable; reference them in commit messages and tests. IDs kept from v1 keep their v1 numbers.

### 6.1 Instance discovery & palette extraction (`instance/*`, `palette/*`)

**Responsibility:** Know exactly which blocks the owner's game has, what they look like and which states they accept.

**Instance discovery**
- RI.1 Discover instances from:
  - the vanilla launcher: `%APPDATA%\.minecraft`, with `launcher_profiles.json` for game directories;
  - CurseForge: `%USERPROFILE%\curseforge\minecraft\Instances\*`, with `minecraftinstance.json`;
  - Modrinth App: its profiles directory, with `profile.json`;
  - Prism Launcher: `%APPDATA%\PrismLauncher\instances\*`, with `mmc-pack.json`;
  - any user-supplied path.

  **Verify each launcher's current paths and metadata files on the owner's machine** and record them in `DECISIONS.md`.
- RI.2 Detect the **MC version** (launcher metadata, falling back to the `versions/` folder name), the **loader + version** (launcher metadata; confirm via `fabric.mod.json` / `META-INF/mods.toml` / `META-INF/neoforge.mods.toml` in the mod jars), the **mod list** (id, name, version, jar), and the **DataVersion** from `version.json` → `world_version` inside the vanilla client jar. Fall back to `dataversions.yaml`.
- RI.3 Locate the vanilla client jar. Launchers that don't keep one inside the instance share it through the launcher's `versions/` or `libraries/` directory. If none is found, instruct the owner to launch that version once.
- RI.4 Detect WorldEdit: record whether it's installed and where its schematics folder is (expected `<instance>/config/worldedit/schematics/`; **verify in Phase 0**).

**Asset sources & precedence**
- RP.1 Asset sources, lowest to highest precedence: the vanilla client jar, then mod jars (sorted by mod id for determinism), then the resource packs enabled in `<instance>/options.txt` (`resourcePacks:[...]`, where the last entry has the highest priority; folder and zip packs; skip `vanilla`, `fabric` and other built-in entries). Read nested jars under `META-INF/jars/` (Fabric jar-in-jar) and `META-INF/jarjar/` (Forge/NeoForge JarJar) recursively.
- RP.2 Build a virtual file system `ns:path → bytes` honoring that precedence. Never extract whole jars to disk; read with `zipfile`.

**Blocks, models, shapes**
- RP.3 Every `assets/<ns>/blockstates/<name>.json` is a candidate block `<ns>:<name>`. Record which source it came from.
- RP.4 Resolve blockstate → model(s):
  - `variants`: keys are property assignments, and the value is a model or a list of weighted models (use the first).
  - `multipart`: `apply` models with `when` conditions (including `OR`/`AND`).
  - Resolve the `parent` chain to a final `elements` list and a `textures` map (resolve `#ref` indirection up to 10 levels). Handle `builtin/generated`, `builtin/entity` and missing models by setting flag `code_rendered`.
- RP.5 **Properties:** collect property names and all values seen in `variants` keys and `multipart` `when` clauses → `properties{name: sorted(values)}`.
- RP.6 **Shape classification:** use the parent model chain first:
  - `block/cube*` → `full_cube`; `cube_column*` → `column`
  - `stairs|inner_stairs|outer_stairs` → `stairs`; `slab*` → `slab`
  - `template_wall_*` → `wall`; `fence_*` → `fence`; `template_fence_gate*` → `fence_gate`
  - `template_glass_pane_*` → `pane`
  - `door_*` → `door`; `template_*trapdoor*` → `trapdoor`

  Otherwise fall back to element geometry (a single element `[0,0,0]→[16,16,16]` with 6 faces → `full_cube`), else `other`.
- RP.7 **Families:** group blocks that share the same primary texture and a common name stem (strip `_stairs|_slab|_wall|_fence|_fence_gate|_pane|_door|_trapdoor`; normalize `bricks→brick`, `planks→<wood>`, `tiles→tile`). Each family records `{base (full_cube), stairs, slab, wall, fence, fence_gate, pane, door, trapdoor}`, with members possibly null. The designer and materials tools use families to find the matching stairs and slabs for a wall or roof block.

**Colors**
- RP.8 Per block, for faces `top`, `bottom` and `side` (from the model's element faces; for `column` shapes, `side` is the bark/side texture and `top` the end):
  - Average color over opaque pixels in linear RGB → sRGB hex + CIELAB.
  - `alpha` = fraction of transparent pixels.
  - `variance` = mean ΔE of pixels from the average (flat vs busy).
  - Animated textures (`.png.mcmeta` present): use frame 0.
- RP.9 **Tint:** faces with `tintindex` (grass, leaves, vines, some modded blocks) are multiplied by the plains default (grass `#91BD59`, foliage `#77AB2F`; **verify against the installed colormap PNGs**, sampling `colormap/grass.png` and `foliage.png` at plains temperature/downfall). Set `tinted: true`.

**Tags, tiers, flags**
- RP.10 **Tags:**
  - Material family from name tokens + color: stone, brick, planks, log, glass, terracotta, concrete, wool, metal, copper, quartz, sandstone, deepslate, tile, plaster (modded), roof (modded names containing `shingle|roof|tile`)…
  - `mod:<id>` and `shape:<shape>`.
- RP.11 **Role tiers** (`wall`, `roof`, `trim`, `glass`, `door`, `floor`, `base`):
  - Vanilla entries come from `tiers.yaml`, seeded **verbatim from v1 R7.3** and extended with stairs/slab-aware roof entries.
  - Modded blocks join tiers by rule: `glass` if `alpha > 0.3` and the name contains `glass`; `roof` if they have a stairs + slab family or roof-ish names; `wall` and `trim` for full cubes whose material tags fit; `floor` for planks/tiles/stone.
  - The owner can override any block in `palette.yaml`.
- RP.12 **Flags** (blocks with these flags are excluded by default):
  - `utility`: command/structure/jigsaw/barrier/light blocks, spawners, infested blocks, ores, `bedrock`
  - `gravity`: sand, red sand, gravel, `*_concrete_powder`, anvils, `suspicious_*`, `pointed_dripstone`, plus modded names containing `sand|gravel|powder`
  - `block_entity`: chests, barrels, signs, banners, beds, shulker boxes, furnaces, hoppers, heads, and anything with a `builtin/entity` model
  - `code_rendered` (RP.4)
  - `light_emitting`: name heuristics; excluded only for wall/roof roles
  - `directional_texture`: glazed terracotta
  - `transparent_leafy`: leaves, ice
- RP.13 **Optional Claude tagging pass:** `palette tag --claude` sends ambiguous modded blocks (no tier assigned, or conflicting tags) in batches of ~200 (id + colors + shape + mod name) to the edit model, which returns role tags. The results are cached by palette hash, so the pass runs once per modpack. Off by default.
- RP.14 **Atlas:** pack every used face texture into `atlas.png` (16×16 tiles; larger resource-pack textures are downscaled to 16) plus `atlas.json` UV lookups. **Stored in the cache only; never committed.**
- RP.15 **Cache key:** sha256 over (vanilla jar path + size + mtime, each mod jar's name + size + mtime, the resource pack list + their mtimes, extractor version). A re-run with the same key loads from cache.
- RP.16 `palette_report.json`: counts per mod and per shape, the `code_rendered` list, the excluded counts per flag, and parse errors (file + message). **Malformed JSON never crashes the extractor.**

**Query API (`palette/query.py`)**
- RP.17 `search(text, tier?, shape?, mod?, n)`: fuzzy search on id, tags and mod name. `nearest(lab, tier, n, face="side")`: ΔE ranking with a cKDTree per tier. `family(block_id)`. `validate_state(state_str)`: checks the id exists and every property/value is in `properties`.

**A-P:**
- On a vanilla instance, ≥ 95% of a 40-block spot list (committed in `tests/fixtures/vanilla_spot.yaml`) gets the correct shape, family and a plausible side color (ΔE < 10 from reference values).
- Every fixture jar is handled: nested jars, resource pack override, malformed JSON.
- On the owner's modded instance, the report lists every mod with a nonzero block count (or an explanation) and the owner eyeballs the palette browser.
- A cached re-run completes in < 2 s.

### 6.2 S0 Ingest & S1 Rectify (`stages/ingest.py`, `stages/rectify.py`) — kept from v1

- R0.1–R0.3 **unchanged** from v1: formats, EXIF, sRGB, ≤ 2048 px, `image_meta.json` with SHA-256, reject < 400 px on the short edge.
- R0.4 `--describe` mode skips S0 and S1; `image.png` is absent, and downstream stages must handle that.
- R1.1 Corner sources, in priority order: (a) `--corners`, (b) Claude analysis **pass A** corners with confidence ≥ 0.5 (D13), (c) `auto` estimator (Phase 4, v1 R1.1c), (d) the full image with a warning.
- R1.2–R1.4 **unchanged** from v1: homography, aspect estimation, 1024-px output, debug overlay, and per-view rectification for multiview.

**A1:** As v1: ≤ 2 px RMS on synthetic fixtures with known homography; overlays visually correct on the owner's photos.

### 6.3 S2 Analyze (`stages/analyze.py`) → `BuildSpec`

**Responsibility:** Turn the photo(s) or a description into a measured, regularized `BuildSpec`.

- R2.1 **Pass A** (original image): Claude returns JSON with facade corner points (normalized), building type, storeys, estimated width/height in metres, roof type/ridge/pitch, depth-ratio guess, style descriptors and occlusion notes. Use the JSON schema generated by pydantic via tool use with a single forced tool (`tool_choice` set to that tool) so the output is schema-shaped.
- R2.1b **Pass B** (original + rectified): element bboxes on the rectified image (window/door/garage/balcony/porch/bay/chimney), a per-region material hint + representative hex, symmetry, the `features[]` list and `unseen` notes.
- R2.2 Validate with pydantic. On failure, retry once with the validation error appended; on a second failure, exit 3, printing the partial JSON so the owner can hand-fix `spec.json`.
- R2.3 Cache each pass by (image hash, prompt version, model id). Never call the API twice for the same input unless `--force`.
- R2.4 Material `rgb` values from Claude are *hints*. Recompute the dominant colors from pixels inside each region (§6.4); use Claude's color only when the pixel sample is unreliable (region < 50 px² or heavily shadowed, i.e., median L* < 20).
- R2.5 **Multiview:** pass B also receives the tagged side/back images. Side/back elements go into `elements` with a `face` field (`front|left|right|back`; default `front`).
- R2.6 **Describe mode:** a single call produces a `BuildSpec` from text, with `elements` as a designed layout rather than measurements, and `provenance.layout_backend = "describe"`.
- R2.9 (**kept**) Window regularization: rows by y-overlap, median sizes, snapping to uniform spacing when CV < 0.15; keep `elements_raw`.
- R2.10 (**kept**) Scale and door sanity rules.
- R2.11 (**kept**) Write `spec.json` + `debug_layout.png`.
- R2.12 **Palette-aware materials:** after the pixel recompute, fill `materials.<role>.candidates` (top 8) and `chosen` (top 1) via `match_materials` (§6.4). The designer may change `chosen` later.

**A2:** On synthetic fixtures (recorded Claude responses committed to `tests/fixtures/claude/`, so replay costs nothing):
- storey count exact in ≥ 95%;
- window bbox IoU ≥ 0.5 for ≥ 80% of windows;
- door detected in ≥ 90%.

On owner photos: reviewed via `debug_layout.png`.

### 6.4 Materials matching (`palette/query.py`, `util/color.py`)

**Responsibility:** Turn photo regions into ranked, palette-valid block choices that look architectural.

- RM.1 **Region color:** for each role region (wall mask = facade minus element bboxes; roof band; trim band; each element interior), compute the median Lab. With `texture_mode: clean`, apply v1 R6.2 luminance normalization first (shadows and vignetting vanish; hue survives).
- RM.2 `match_materials(role, lab, n=8)`: ΔE ranking within the role tier of the **active, filtered palette** (CIE76 for speed, re-ranking the top 20 by CIEDE2000). Score = ΔE + **family penalty**: for roof/trim roles, +6 if the family lacks stairs, +3 if it lacks a slab; for walls, +2 if `variance` is very high (busy textures read as noise at distance). Return `{id, de, score, family_members, mod}`.
- RM.3 **Contrast guard** (v1 R7.9 kept): if the chosen trim block is within ΔE < `contrast_min_de` (8) of the wall block, flag it and propose the next candidate with ΔE ≥ 8. The designer sees this as a validator warning.
- RM.4 **Variation** (`varied` mode, v1 R7.6 kept) is exposed as the `vary` op (§6.5) rather than a global mode. Seeded, 85/15 by default, with no checkerboards.
- RM.5 Per-voxel dithering (v1 R7.7) is **dropped**.

**A-M:** On synthetic facades with known colors, `match_materials` returns the expected block in the top 3 for ≥ 90% of regions, and no denied/flagged blocks appear.

### 6.5 Build DSL & engine (`engine/*`, `docs/DSL.md`)

**Responsibility:** A small architectural language that Claude, the template generator and the owner can all write, compiled deterministically into correct block states. This is the equivalent of the demo's "engine turns the design into parts".

**Materials in ops:** a block reference is either a **slot** (`"$wall"`, `"$roof"`, `"$trim"`, `"$glass"`, `"$door"`, `"$floor"`, `"$base"`, `"$accent1".."$accent4"`), resolved through `OpsDoc.style`, or a literal state (`"minecraft:stone_bricks"`, `"create:andesite_casing"`). A **family reference** like `"$roof.stairs"` or `"$trim.slab"` resolves through `palette.family()`. Changing a slot re-skins the whole build.

**Op set:**

| Op | Parameters | Engine responsibilities |
|---|---|---|
| `box` | `from, to, mat, hollow?, label?` | Solid/hollow volumes |
| `walls` | `footprint (rect or polygon [[x,z]…]), y0, height, mat, thickness=1, label=wall` | Closed wall loop; corners handled |
| `floors` | `footprint, ys[] or every_storey, mat, stair_opening?` | Floor slabs at storey boundaries; optional stairwell hole |
| `facade_from_spec` | `face (front/left/right/back), spec_ref, recess=1, frame_mat?, sill_mat?, lintel_mat?` | Rasterizes the measured `BuildSpec.elements` for that face onto the wall plane (v1 R6.1/R6.5 rules: min sizes, sill/lintel clearance); windows filled with `$glass` (panes if a pane family exists, else full glass), doors with real two-block doors |
| `openings` | `face, pattern {kind: window/door, w, h, sill, spacing, count or fill, offset}, frame_mat?, recess?` | Procedural window grids on faces with no measured elements (v1 R4a.4 `side_windows` policy) |
| `door` | `pos, facing, mat ($door or door block), hinge?` | Emits `half=lower/upper`, `facing`, `hinge`, `open=false`, `powered=false` |
| `roof` | `footprint, type (flat/gable/hip/shed/mansard/dome_approx), pitch (1:2, 1:1, 2:1), ridge (x or z), overhang, mat (family ref), gable_fill_mat?, parapet?` | Stair `facing/half/shape` including inner/outer corners; slabs at half-steps and ridges (`type=bottom/top`); gable-end fill; parapet ring for flat roofs |
| `column` | `pos, y0, height, mat, base_mat?, cap_mat?` | Sets `axis=y` for column-shaped blocks |
| `beam` | `from, to, mat` | Axis-aligned runs; sets `axis` for logs |
| `trim_band` | `y, footprint, mat, outset=0` | Belt courses, cornices; stairs/slabs allowed (upside-down stairs for cornices) |
| `railing` | `path, y, mat (fence/wall/pane family)` | Connection properties computed from neighbors |
| `vary` | `target (op id or label), secondary mat, ratio=0.15, seed` | Seeded variation without checkerboards (v1 R7.6) |
| `define` / `place` | `name, ops[]` / `name, pos, rotate (0/90/180/270), mirror (x/z)?` | Reusable components; the engine rotates block states (facing, axis, shape) correctly |
| `array` | `name, count, step [dx,dy,dz]` | Repetition |
| `mirror` | `ops[] or group, axis, plane` | Symmetry, including state mirroring |
| `carve` | `from, to` | Set air |
| `set` | `pos, block` | **Escape hatch, ≤ 64 cells per op, ≤ 256 total per build** |

**Engine requirements**
- RE.1 Ops are a pydantic discriminated union. JSON schemas for Claude's tools are **generated** from these models, never hand-written, so they can't drift.
- RE.2 Compilation is deterministic and ordered: later ops overwrite earlier ones unless `mode: keep`. Output: `idx` grid + a per-cell `label` grid + a per-cell `op_index` grid (for UI picking, "which op made this block", and dirty tracking).
- RE.3 **State computation** (`engine/states.py`) runs as a final pass over the grid, so neighbors are known:
  - panes, fences and bars: `north/south/east/west` true when the neighbor is the same kind, a solid full cube or a matching gate;
  - walls: side values `none/low/tall` and `up` per vanilla rules (**verify against the installed version's blockstates**);
  - stairs: `shape` from neighboring stairs (inner/outer corners);
  - logs and pillars: `axis`;
  - `waterlogged=false` wherever the property exists.
- RE.4 **Only properties that exist on the block** (per `palette.properties`) are written. The remaining properties come from a conventional-defaults table (`waterlogged=false, powered=false, open=false, lit=false, persistent=true` for leaves, `snowy=false`…); anything else is left unspecified. **Phase 0 must confirm empirically that partial state strings load correctly in both WorldEdit beds.** If they don't, add a defaults inference step and record it in `DECISIONS.md`.
- RE.5 Rotation/mirroring of components rotates `facing`, `axis`, `rotation`, `hinge` and stair `shape` correctly (table-driven, unit-tested for every shape class).
- RE.6 Bounds: the compiled bounding box is normalized so the front facade's plane is `z = 0` and the minimum x/y are 0 (§4.3). Ops may use negative coordinates while designing.
- RE.7 Budgets (v1 R5.5 kept) are checked **before** allocation: `X*Y*Z > hard_max_total` is an error unless `--allow-large`.
- RE.8 Performance: a full compile of ≤ 100 ops at ≤ 128³ takes < 200 ms. **Incremental recompile:** when one op changes, recompute from the first affected op within the union of the old and new bounding boxes, plus a 1-block margin for state recomputation.
- RE.9 Every compiled op returns a **compile summary** for the designer: bounds, block count by state, cells overwritten from earlier ops, and any validator issues touching those bounds.

**A-E:**
- Golden grids for every op and every roof type × pitch × ridge (symmetry, ridge height, correct stair states at corners, no floating overhangs).
- Rotation tests for every shape class.
- Pane/fence/wall connection tests.
- Two-block doors correct in all 4 facings.
- Determinism: the same ops produce the same bytes.

### 6.6 S3 Template generator (`stages/plan_template.py`)

**Responsibility:** Deterministic `BuildSpec` → baseline `ops.json`. This is v1's procedural massing (R4a.1–R4a.7) re-expressed as ops.

- RT.1 Footprint: `W × L` per v1 R4a.1. `walls` + `floors` per R4a.2 (hollow by default).
- RT.2 Front: `facade_from_spec(face=front)`. Other faces: `facade_from_spec` if multiview elements exist for that face, else `openings` per the `side_windows` policy (R4a.4).
- RT.3 Roof: `roof` from the spec's type/ridge/pitch/overhang with `mat="$roof.stairs"`. If the chosen roof block has no stairs family, fall back to the nearest roof-tier block that does and log a warning.
- RT.4 Trim and base: `trim_band` under the eaves if `materials.trim` exists; a base band per R4a.6.
- RT.5 Style slots are filled from `materials.*.chosen`.
- RT.6 Every op gets a readable `label` ("Front facade — measured openings", "Main roof — gable, 1:1").

**A-T:** A 2-storey 12×8 house fixture compiles to the golden grid. Editing `spec.json` (storeys 2→3, roof gable→hip) and re-running `plan --designer template` gives the expected change with no API calls (this is the v1 Phase 1 DoD item, kept).

### 6.7 S3 Claude designer (`stages/plan_claude.py`, `designer/*`)

**Responsibility:** Refine the template into a build a good Minecraft builder would be proud of, streaming op by op, and apply conversational edits.

**Tools exposed to Claude**
- Every DSL op as a tool (`add_<op>`), plus `replace_op(id, op)`, `delete_op(id)`, `set_style(slots)`.
- Palette: `search_palette(query, tier?, shape?, mod?, n)`, `match_materials(role, rgb|lab, n)`, `get_family(block)`.
- Inspection: `get_state_summary()` (ops list with ids/labels/bounds, style, block counts, open issues), `validate()`.
- `render_views(views[], textured?)`: returns PNGs via §6.11. Only offered during critique.
- `finish(summary)`: the model signals it's done.

**System prompt** (versioned in `designer/prompts/`; the version is included in the cache keys):
- Role, and the coordinate frame from §4.3 with an ASCII diagram.
- The full `docs/DSL.md`.
- **Build-craft guide:**
  - depth and layering: recess walls behind frames, overhang roofs, add trims and base courses; no flat single-material walls over ~6×6 without relief;
  - roofs are stairs + slabs, not stepped full blocks;
  - use 2–3 related materials per role at most;
  - honor the measured openings;
  - scale conventions: storey 4–5 blocks, doors 2 tall, windows ≥ 1×2 on 4-block storeys.
- Palette rules: use only ids returned by palette tools; prefer the chosen slots; modded blocks welcome when they fit.
- A compact **palette summary**: per role tier, the top families with ids, plus the list of mods and what they contribute.

The system prompt + palette summary are marked for **prompt caching**.

**Flow**
- RD.1 **Initial design:**
  - input: `BuildSpec`, the template `ops.json` (already compiled; summary attached), the photo(s) and the rectified image;
  - Claude refines by adding and replacing ops;
  - turn cap 30; budget guard (below).
- RD.2 **Streaming:** use the Messages API with streaming. Apply each tool call as soon as its `tool_use` block completes: validate → compile incrementally → push to the UI/CLI progress → return the compile summary (RE.9) as the `tool_result`. Allow parallel tool calls in a turn.
- RD.3 **Errors:** an invalid op (schema error, unknown block, out of budget) becomes a `tool_result` with `is_error: true` and a precise message. After 3 consecutive errors on the same op id, skip it and log.
- RD.4 **Edits:**
  - `edit(ops.json, instruction)` sends the edit model the instruction + `get_state_summary()` (not the full grid) + open issues, with the same tools minus `render_views`;
  - each edit is one history entry (undo/redo);
  - edits that fail validation are rolled back and reported.
- RD.5 **Budget guard:**
  - track usage from API responses and price it from `pricing.yaml`;
  - warn at `budget_usd.warn` and stop at `budget_usd.stop`: stop cleanly, keep the ops produced so far, and exit 5 with a clear message;
  - record usage per stage in `report.json`.
- RD.6 **Caching:** the initial design is cached by (spec hash, template ops hash, palette hash, prompt version, model). Re-running is free unless `--force`.
- RD.7 **Model IDs** come from config only. Verify at docs.claude.com.

**A-D:**
- Replay tests with recorded sessions (no API) reproduce the same `ops.json`.
- A live run on 3 synthetic fixtures produces builds with no validator errors.
- Cost per build is recorded.
- A 20-instruction edit script (committed in `tests/fixtures/edits.yaml`: "steeper roof", "swap walls to deepslate bricks", "add a chimney on the east gable", "remove the porch", …) applies ≥ 80% correctly on the first try, as judged by the owner from before/after previews.

### 6.8 S6 Critique loop (`stages/plan_claude.py`)

- RC.1 After the initial design: render `preview_front` from the photo's approximate viewpoint (front elevation, or iso if the photo is oblique) and compose a side-by-side PNG of the photo and the render. Send it to Claude with: "List the top discrepancies in massing, roof, openings and materials, ranked. Fix the ones that matter using ops. Call `finish` when the remaining differences are cosmetic."
- RC.2 Max `critique_passes` (default 2). Each pass is logged with its discrepancy list in `report.json`.
- RC.3 Critique never moves the measured front openings unless it writes a justification in the op's `note` (§4.2).

**A-C:** On the owner's 10 photos, critique passes reduce owner-flagged discrepancies (owner A/B on 5 photos: with vs without critique).

### 6.9 Web UI (`server/*`, `web/*`) — Phase 3

**Responsibility:** The clean, fluid experience from the demo, wrapped around the same stages.

**Layout**
- **Left panel:** project header (name, instance badge with MC version + loader); photo drop zone (plus a text-describe box); the **design brief card** (editable key fields of `spec.json`: storeys, footprint, roof, style, material slots, with Approve/Rebuild); the chat thread; the op history tree (grouped by `group`/label; toggle visibility, rename, delete, drag to reorder; clicking an op highlights its blocks).
- **Center:** the 3D viewport.
- **Right panel tabs:**
  - **Materials:** each slot shows the block with its real texture; clicking opens the palette browser; dropping a block onto a slot re-skins live.
  - **Blocks:** counts, stacks of 64, shulker boxes, grouped by mod.
  - **Issues:** validator list; clicking an issue flies the camera there; "Fix auto-fixable" button.
  - **Export:** `.schem` (writes to the instance's WorldEdit folder when present), build guide, project save, paste instructions.
- **Footer:** live status ("Designing roof…"), the token/cost meter and a stop button.

**Viewport**
- RU.1 react-three-fiber. Use chunked (16³) meshing with face culling and greedy merging for full cubes, and simple shape geometry for stairs, slabs, panes, fences, walls and doors. Texture everything from `atlas.png` served by the backend (local only). Tinted faces are multiplied by the tint.
- RU.2 **Streaming:** the WebSocket sends `op_applied{op, label}` followed by `grid_diff{chunks: [{cx,cy,cz, palette_idx: base64 uint16}]}`, plus `issues`, `usage`, `status` and `done`. Only dirty chunks rebuild.
- RU.3 **Motion:** blocks from a newly applied op drop in or scale in with a short stagger (≤ 400 ms per op, ease-out), and the camera gently frames new work unless the user is dragging. Honor `prefers-reduced-motion`.
- RU.4 **Controls:** orbit/pan/zoom, `F` fit, `L` layer mode, `Ctrl+Z`/`Ctrl+Y` undo/redo, `Space` pause/resume streaming. Clicking a block shows its state, mod and producing op.
- RU.5 **Layer slider:** show layers 0..y with the layers above ghosted at 10% opacity. This doubles as build-guide mode.
- RU.6 **Reference overlay:** the photo in a floating panel with adjustable opacity; optional camera-match mode that aligns the view to the front elevation.
- RU.7 **Palette browser:** search, filter by mod/tier/shape, texture thumbnails, and a family strip (base/stairs/slab/wall).
- RU.8 **Visual style:**
  - clean and uncluttered, with a dark default and a light theme;
  - one accent color, 8-px spacing rhythm, system font stack;
  - no modal dialogs in the main flow;
  - every long action shows progress and can be cancelled.
- RU.9 **Performance:** S9 targets, with an FPS/perf overlay toggle (`Shift+P`).
- RU.10 **Security:** bind to `127.0.0.1` only; no auth needed; never expose the API key to the browser (all Claude calls are server-side).

**A-U:** The S9 targets are met; a full flow (photo → brief approve → streamed build → 3 chat edits → material swap → export) works without touching the CLI; the owner signs off on the look and feel against the reference video.

### 6.10 S7 Schematic export (`stages/export_schem.py`) — kept from v1, with additions

- R8.1–R8.3, R8.5–R8.8 **unchanged** from v1: v2 layout (root named `Schematic`, `PaletteMax`, `BlockData`), v3 layout (`Schematic` inside an unnamed root, `Blocks{Palette, Data, BlockEntities}`), index `x + z*Width + y*Width*Length`, LEB128 varints, signed NBT bytes, gzip, dims ≤ 32767, a reader for v1/v2/v3, and the `mcschematic` cross-check in tests only.
- R8.4 (**changed**) `DataVersion` comes from the instance (RI.2). `dataversions.yaml` is the fallback, seeded from v1 (`1.20.1: 3465`, `1.20.4: 3700`, `1.21: 3953`, `1.21.1: 3955`, `1.21.4: 4189`; **verify against the Minecraft Wiki "Data version" page**).
- R8.9 **Metadata:** v2 `Metadata{WEOffsetX/Y/Z, Name, Author, Date}`, v3 `Metadata{Name, Author, Date}`, plus in both an `img2schem` compound: `{Version, Instance, MinecraftVersion, Loader, ModsRequired: [modid…]}`. `ModsRequired` = the set of non-`minecraft` namespaces in the palette.
- R8.10 **Write to the instance:** when `export.write_to_instance` is set and WorldEdit is detected (RI.4), also copy the `.schem` into the instance's WorldEdit schematics folder, never overwriting an existing file (append `_2`, `_3`…). Print the paste commands (§11.4).
- R8.11 `BlockEntities` stays empty in v2.0 (block-entity blocks are excluded by default). If the owner enables them, write minimal entries (`Pos`, `Id`) and verify in the test bed first.

**A8:** As v1: the round-trip property test (random palettes up to 300 entries) plus correct paste orientation and Offset. **Also:** a build containing at least 3 modded blocks from the owner's mods (including one stairs block with computed states) pastes correctly in the modded instance.

### 6.11 S7 Previews & build guide (`stages/preview.py`, `stages/guide.py`)

- R9.1 (**kept**) Orthographic front/side/top plus isometric PNGs from `BlockGrid`, rendered with PIL only, with face shading (top 1.0, front 0.85, side 0.7), ≥ 8 px per block. Colors come from palette face averages; non-cube shapes are drawn as partial cells (slabs as half-height, stairs as an L-profile, panes as thin lines).
- R9.2 `--textured`: paint faces with atlas textures (nearest-neighbor, 16 px per block) for critique and the guide.
- R9.3 (**kept**) `--export-obj`.
- R9.4 `debug_ops.png`: iso view with each op's cells tinted by op, plus a legend. Useful for agent self-review and for Claude's critique.
- R9.5 **Build guide** (`guide/index.html` + PNGs):
  - a per-layer top-down grid at 16 px per block with atlas icons, the previous layer ghosted and coordinates on the edges;
  - a legend (block → icon → count);
  - a materials list in stacks of 64 and shulker boxes, grouped by mod;
  - print CSS so it can be printed to PDF.

**A9:** Previews of the synthetic fixtures match golden PNGs (perceptual hash within tolerance). The guide for the 12×8 house has the correct layer count and materials total.

### 6.12 S5 Validate (`stages/validate.py`) — v1 rules + Minecraft checks

| Rule | Severity | Auto-fix |
|---|---|---|
| R10.1 (**kept**) The file parses; `Data` decodes to exactly `W*H*L`; indices < palette size; states parse | Error | — |
| R10.1b Every state passes `palette.validate_state` for the **active instance**, and no flagged or denied block appears unless explicitly allowed | Error | Replace with the nearest allowed block of the same shape (ΔE) and log it |
| R10.2 (**kept**) Budgets: dims ≤ `max_dim`, non-air ≤ `max_nonair` (warning), total ≤ `hard_max_total` (failure) | Warning / Error | — |
| R10.3 (**kept**) No floating fragments: every occupied cell is 6-connected to the ground-connected component, except overhangs ≤ 1 block attached by adjacency | Warning | Remove fragments < 4 cells |
| R10.3b Front facade has ≥ 1 door at ground level; windows don't touch the roof line | Warning | — |
| R10.5 Multi-block consistency: door lower/upper halves, bed head/foot, tall plants | Error | Complete or remove the pair |
| R10.6 Support-requiring blocks (torches, lanterns, buttons, carpets, rails, doors, pressure plates) have their attachment face | Error | Remove, or move to the nearest supported cell |
| R10.7 Gravity blocks (only if allowed) have support beneath | Warning | — |
| R10.8 Roof sanity: no stairs facing into a ridge; stair `shape` matches its neighbors; roof surface has no single-cell holes | Warning | Recompute states; fill holes |
| R10.9 Contrast guard (RM.3) | Warning | Propose the next candidate |
| R10.10 Modded blocks present: list `ModsRequired` | Info | — |
| R10.11 Doors open onto a reachable interior air region (flood fill) | Info | — |

- R10.4 (**kept**) Output goes into the `report.json` `validation` section and `issues.json`. `--strict` turns warnings into failures.

**A10:** Unit tests for every rule with crafted grids; auto-fixes are idempotent.

### 6.13 Cross-cutting (kept from v1 R11.1–R11.5, with additions)

- R11.1 Layered settings (defaults → `config.yaml` → env `IMG2SCHEM_*` → CLI flags). The effective config is dumped into `report.json` with secrets redacted.
- R11.2 Content-addressed cache: Claude responses (analysis + design sessions), palettes, renders. `--force` bypasses; `cache clear` purges.
- R11.3 Logging to a run log in the run dir; `-vv` prints timings per stage **and usage per Claude call**.
- R11.4 Seeded RNG for every stochastic step (`vary`, `openings` jitter).
- R11.5 No global state; each stage takes a `RunContext`.
- R11.6 **Prompt versions:** each prompt file carries a version string that is part of every cache key and is recorded in `provenance`.

### 6.14 Optional modules (Phase 5; build only if the owner asks)

- **O1 Massing hint (`assist/`):**
  - backends: Tripo API V3 via the official SDK, local TripoSR (GPU recommended), or a user-supplied `file`;
  - preprocessing, orientation, voxelization and the quality gate as in v1 R4b.1–R4b.6 / R5.1–R5.3 (see `docs/archive/SOW_v1.0.md` §6.6–6.7, §11.4–11.5);
  - output is **not** blocks: a massing summary (per-layer footprint polygons, roof silhouette, wing/volume list) fed into the designer's initial prompt as a proportions reference.
- **O2 Palette helper mod:**
  - a tiny Fabric or NeoForge client mod for the owner's loader/version;
  - `/img2schem dump` writes the full block registry, every block state with defaults, and baked-model face colors to JSON;
  - the palette extractor merges it (it wins on registry and defaults) to cover code-rendered blocks exactly.
- **O3 Local detector fallback:** Grounding DINO analysis backend per v1 R2.5–R2.8 for offline use.
- **O4 Litematica export:** `.litematic` writer (format per Litematica's repo), validated in the owner's instance.
- **O5 Simple interiors:** floor-plan partition walls, a stair run between floors, and optional furniture-like blocks from a curated list.

---

## 7. Phased development plan

Effort figures are **estimates for a solo developer working with Claude Code**, not commitments. Each phase ends with a demo to the owner: preview PNGs plus a paste in the test bed.

### Phase 0 — Prove the output end on the real test bed (est. 2–4 days)

**Goal:** retire the riskiest unknowns first. That means the format, the Offset, partial block states, the WorldEdit folder on the modded loader, and a modded block round-trip.

**Tasks**
1. Repo scaffold: `pyproject.toml`, `CLAUDE.md` (Appendix A), `docs/` (including `archive/SOW_v1.0.md`), `tests/`, CI (GitHub Actions: `ruff` + `mypy` + unit tests on Linux and Windows).
2. `instance/discover.py` + `detect.py` (RI.1–RI.4); `img2schem instance list/use`; `doctor`.
3. **Minimal** palette pass: block ids + properties + shapes from blockstates and models (RP.1–RP.6). Colors come in Phase 1.
4. `models.py`, `util/varint.py`, `export_schem.py` writer + reader (v2, then v3); `preview.py` using a flat per-block color.
5. `validate.py` structural rules (R10.1, R10.1b, R10.2).
6. `docs/TEST_BED.md` (Appendix B). Hand-made grids: a 5×5×5 test cube, a 20×12×8 "house", and a **modded test**: a 7×5×7 grid mixing vanilla stairs (explicit states), one modded full block and one modded stairs block from the owner's mods.

**Definition of Done**
- [ ] `pytest` green, including the varint property test and the round-trip test
- [ ] `instance list` shows the owner's instances with the correct MC version, loader, DataVersion and mod count
- [ ] `inspect` on a WorldEdit-saved `.schem` from the owner's modded instance (`//copy` + `//schem save`) prints the correct dims/palette, **including modded states**. This proves the reader on real files
- [ ] The hand-made grids paste in the **modded single-player instance** and on **Paper + FAWE / Paper + WE** (vanilla-only grids), with the correct orientation (the front faces the player) and origin behavior. Adjustments are recorded in `DECISIONS.md`
- [ ] Partial state strings (RE.4): confirmed to load, or a defaults step added. Result recorded in `DECISIONS.md`
- [ ] The WorldEdit schematics folder path for the owner's loader is confirmed and `R8.10` writes there
- [ ] Previews match the in-game paste orientation

### Phase 1 — Palette + engine + template (no API) (est. 2–3 weeks)

**Goal:** a hand-written or edited `spec.json` becomes a good-looking, correct build from the owner's real palette, with no AI at all.

**Tasks**
1. The full palette extractor (RP.1–RP.17): colors, tint, families, tags, tiers, flags, atlas, cache, report, `palette show/search/report`.
2. `tiers.yaml` seeded from v1 R7.3; modded tier rules (RP.11).
3. The engine: every op in §6.5, states (RE.3–RE.5), incremental compile (RE.8), `docs/DSL.md` with examples.
4. S0 ingest, S1 rectify (manual corners), `util/color.py`, materials matching (§6.4) on a user-supplied spec + photo.
5. Template generator (§6.6); `plan --designer template`; `compile`; `report.json`.
6. Synthetic fixture generator (§8.2) + golden tests; `debug_ops.png`.
7. The full validator (§6.12) with auto-fixes.

**Definition of Done**
- [ ] All A-criteria for §6.1, §6.2, §6.4, §6.5, §6.6, §6.10–6.12 met
- [ ] The palette report on the owner's modded instance has been reviewed by the owner; his three favorite modded building blocks appear with the correct family and colors
- [ ] Three owner buildings with **hand-written** `spec.json` produce builds with stair/slab roofs, framed windows and two-block doors that paste cleanly
- [ ] Editing `spec.json` (storeys, roof type, a material slot) and re-running gives the expected change with no API calls
- [ ] Zero console errors on paste in both beds (vanilla builds) and in the modded bed (modded builds)

### Phase 2 — Claude analysis + designer + critique (est. 2–3 weeks)

**Goal:** photo → recognizable, well-crafted build, with conversational edits, from the CLI.

**Tasks**
1. `designer/client.py`: streaming, prompt caching, retries, usage metering, budget guard, `pricing.yaml`.
2. S2 analyze (pass A/B, D13), palette-aware materials (R2.12), caching; `describe` mode.
3. `designer/tools.py` (schemas generated from the op models), the system prompt + build-craft guide + palette summary.
4. `plan --designer claude` with streaming CLI progress (a `rich` live view: current op label, block count, cost).
5. The critique loop (§6.8) with side-by-side renders.
6. `img2schem edit` (RD.4) with undo history in `ops.json`.
7. Recording/replay harness for Claude sessions; recorded fixtures for CI.

**Definition of Done**
- [ ] A-criteria for §6.3, §6.7, §6.8 met
- [ ] **Owner blind test on the 10 photos: ≥ 8/10 recognizable** (S2). A/B previews of the template vs Claude-designed build are written side by side
- [ ] The 20-instruction edit script is ≥ 80% correct on the first try
- [ ] Median cost per build and per edit recorded; the defaults stay within the §1.5 budget
- [ ] No duplicate paid API calls for unchanged inputs (verified via cache-hit logs)
- [ ] End-to-end < 5 min per photo, including critique

### Phase 3 — Local web UI (est. 2–3 weeks)

**Goal:** the demo's feel: live streaming build, chat edits, material slots, layer slider, validator panel.

**Tasks**
1. `server/app.py` (FastAPI, REST + WebSocket, RU.2 protocol, RU.10 security), `sessions.py` (project state, undo/redo, autosave to `project.img2schem.json`).
2. `web/`: the layout (§6.9), chunk mesher (Web Worker), atlas texturing, streaming animation, op history, materials slots + palette browser, issues panel, export panel, cost meter, themes.
3. `img2schem serve --open`; the built UI is bundled into the Python package.
4. A Playwright smoke test of the full flow against recorded Claude sessions.

**Definition of Done**
- [ ] A-U met, including the S9 performance targets on the owner's laptop
- [ ] The owner completes the full flow without the CLI and signs off on the look and feel against the reference video
- [ ] Every UI action maps to an artifact on disk (the project reloads identically after a restart)

### Phase 4 — Fidelity & polish (incremental; each item ships independently)

In owner-priority order:
1. **Build guide** (R9.5) and textured previews (R9.2).
2. **Auto rectification** (v1 R1.1c).
3. **Multiview** (`--views`), with side/back elements feeding `facade_from_spec` on those faces.
4. **Per-storey materials** (e.g., a stone ground floor under brick upper floors) and **ground plate** (`--ground-plate`, v1 P3.7).
5. **Claude palette tagging pass** (RP.13) for large modpacks.
6. **Packaging:** `pipx`-installable, a Windows `.bat` launcher that runs `img2schem serve --open`, a README quick start, `doctor` checks.
7. Docs pass; `DECISIONS.md` review; tag **v1.0.0**.

### Phase 5 — Optional modules (owner decides)

O1–O5 from §6.14.

---

## 8. Testing strategy

### 8.1 Layers

| Layer | What | Tooling |
|-------|------|---------|
| Unit | Varint, NBT writer/reader, palette resolution (fixture jars), shape/family classification, color math, every op, state computation, rotation/mirroring, validator rules, budget rules, tiers/deny lists | `pytest`, `hypothesis` (varint, round-trip, rotation properties) |
| Golden | Synthetic fixtures → `spec.json` (from recorded Claude responses), template `ops.json`, `blocks.npz`, `.schem` and previews compared to committed goldens (grids exactly; PNGs by perceptual hash) | `pytest` + `imagehash` |
| Replay | Recorded Claude sessions (analysis, design, critique, edits) replayed through the real tool-handling code; must reproduce the same `ops.json` | `pytest -m replay` (runs in CI; no network) |
| Integration | `convert --designer template` end-to-end on fixtures; stage re-runs from artifacts; cache hit/miss; palette build on fixture instances | `pytest -m integration` |
| External (opt-in) | Live Claude calls; palette build on the owner's real instance. Skipped unless `IMG2SCHEM_RUN_EXTERNAL=1`; new recordings saved to `tests/fixtures/claude/` | `pytest -m external` |
| Frontend | Mesher correctness (face counts for known grids), WebSocket protocol handling; a full-flow smoke test | `vitest`, Playwright |
| Manual | Paste in the modded bed + the Paper beds; owner blind recognizability test; owner UI sign-off | Appendix B checklist |

### 8.2 Synthetic fixture generator (**kept** from v1 §8.2)

Renders simple buildings with PIL from a ground-truth spec: flat-colored wall, dark windows in a grid, a door, a roof band/triangle. It then applies a random perspective warp (known homography) and mild noise/vignetting, which gives exact ground truth for rectification error, storey count, window IoU and facade-cell agreement. Generate ≥ 30 fixtures across 1–6 storeys, 3 roof types and 4 wall colors, with and without occluders (a green "tree" blob covering ≤ 15%).

### 8.3 Fixture instances

`tests/fixtures/jars/` builds tiny fake instances at test time:
- a vanilla-like jar (~40 blocks with real-format blockstates/models and 16×16 PNGs generated by the test);
- a Fabric mod jar with a nested jar-in-jar;
- a NeoForge mod jar with `META-INF/jarjar/`;
- a resource pack overriding one texture;
- a mod with a malformed blockstate;
- a mod with a `builtin/entity` block.

### 8.4 Quality metrics recorded in `report.json`

`storeys_ok`, `window_iou_mean`, `facade_cell_agreement`, `nonair_count`, `palette_size`, `mods_required`, `ops_count`, `set_cells_used`, `critique_passes`, `validation`, `time_per_stage`, `usage{tokens_in, tokens_out, cache_read, cache_write, est_cost_usd}` per stage, `fallbacks[]`.

---

## 9. Risks & mitigations

| # | Risk | Likelihood | Impact | Mitigation / trigger |
|---|------|-----------|--------|----------------------|
| R1 | Claude makes spatial mistakes (off-by-one, misaligned roofs, broken symmetry) | Medium | Medium | High-level ops own the geometry; measured openings rasterized deterministically; validator + auto-fixes; critique loop; `ops.json` is human-editable |
| R2 | Offset/orientation semantics differ between WorldEdit builds or loaders | Medium | High | Phase 0 empirical test on every bed; a single constant to flip; `DECISIONS.md` |
| R3 | Claude returns malformed or inconsistent JSON / wrong storeys | Medium | Medium | Forced tool schemas; pydantic validation with retry; human-editable `spec.json` |
| R4 | Modded asset quirks (code-rendered blocks, odd blockstate names, CTM) | High | Medium | Flags + fallbacks + palette report; helper mod (O2) |
| R5 | Large modpack makes palette extraction slow or the prompt huge | Medium | Medium | Cache by hash; tool-based palette access (D12); tag summary only in the prompt |
| R6 | API cost creeps up | Medium | Medium | Prompt caching, cheaper edit model, critique cap, budget guard with a hard stop, content-hash caching |
| R7 | A modded build is pasted where the mods are missing | Medium | Medium | `ModsRequired` in metadata; validator info message; `inspect` shows the mods required |
| R8 | Partial block-state strings rejected by some WorldEdit build | Low–Med | High | Phase 0 test; defaults inference fallback (RE.4) |
| R9 | Photo has heavy occlusion (trees, cars) | High | Medium | Occlusion notes in pass A; regularization; the designer infers from style; human spec edits |
| R10 | Perspective/rectification fails on wide-angle shots | Medium | Medium | Manual `--corners`; the debug overlay makes failure obvious |
| R11 | Viewer is slow on a laptop GPU | Medium | Medium | Chunked greedy meshing in a Web Worker; dirty-chunk rebuilds; perf overlay; LOD for > 100k blocks |
| R12 | Block names/properties change between MC versions | Low–Med | Medium | Everything comes from the instance's own assets; `validate_state` against the active palette |
| R13 | Copyright of buildings, photos or textures | Low (personal use) | Legal | README notice; textures never committed or distributed; no sharing features |
| R14 | Windows path/encoding issues | Medium | Low | `pathlib` everywhere; CI on Windows |
| R15 | The UI balloons in scope | Medium | Medium | Phase 3 scope is fixed by §6.9; extras go to Phase 4 by owner priority |

---

## 10. Dependencies & licenses (verify versions at install time)

| Package | Purpose | License | Notes |
|---------|---------|---------|-------|
| `numpy`, `scipy`, `scikit-image` | Arrays, kd-trees, flood fill, Lab/ΔE | BSD | Core |
| `opencv-python-headless` | Homography, resizing | Apache-2.0 | Core |
| `Pillow` (+ `pillow-heif` optional) | Image I/O, previews, atlas | HPND / LGPL (heif) | Core |
| `pydantic` v2, `pyyaml`, `typer`, `rich` | Models, config, CLI, live progress | MIT | Core |
| `nbtlib` (≥ 2.0) | NBT read/write | MIT | Core |
| `anthropic` | Claude API (analysis, design, critique, edits) | MIT | `[vlm]`; paid per token |
| `fastapi`, `uvicorn` | Local server + WebSocket | MIT / BSD | `[server]` |
| React, Vite, three.js, `@react-three/fiber`, `@react-three/drei`, `zustand` | Web UI | MIT | `web/` |
| `mcschematic` (11.4.x) | Cross-check only | MIT | `[dev]` |
| `hypothesis`, `pytest`, `imagehash`, `ruff`, `mypy`, `vitest`, Playwright | Tests/lint | MIT / MPL / Apache-2.0 | `[dev]` |
| `trimesh`, `rembg`, `tripo3d`, TripoSR | Massing hint | MIT / check repo | `[assist]`, Phase 5 only |
| `torch`, `transformers` | Local detector fallback | BSD / Apache-2.0 | `[local]`, Phase 5 only |

**Data:** Minecraft and mod textures are read from the owner's own installed files. Committed palette files contain block names, properties and numbers only; textures and atlases live in the local cache.

---

## 11. Reference implementations (re-verify against the installed versions)

### 11.1 Sponge v2 writer/reader — **kept verbatim from v1 §11.1**

See `docs/archive/SOW_v1.0.md` §11.1 (`encode_varints`, `write_schem_v2`, `decode_varints`, reader notes). For v3, wrap the fields in `{"Schematic": {...}}` under an unnamed root, move `Palette` and `Data` into `Blocks`, and drop `PaletteMax`.

### 11.2 Blockstate → model → textures resolution (sketch)

```python
import json, zipfile
from pathlib import PurePosixPath

class AssetFS:
    """Virtual FS over jars/packs; later sources override earlier ones."""
    def __init__(self, sources: list[zipfile.ZipFile]):
        self.index: dict[str, tuple[zipfile.ZipFile, str]] = {}
        for z in sources:                                  # lowest → highest precedence
            for name in z.namelist():
                if name.startswith("assets/"):
                    self.index[name] = (z, name)
    def read_json(self, path: str) -> dict | None:
        hit = self.index.get(path)
        if not hit: return None
        try: return json.loads(hit[0].read(hit[1]))
        except Exception: return None                      # log + skip (RP.16)

def model_path(ref: str) -> str:                          # "minecraft:block/stone_bricks" → assets path
    ns, _, p = ref.partition(":") if ":" in ref else ("minecraft", "", ref)
    return f"assets/{ns}/models/{p}.json"

def resolve_model(fs: AssetFS, ref: str, depth=0) -> dict:
    m = fs.read_json(model_path(ref)) or {}
    parent = m.get("parent")
    if parent and depth < 16 and not parent.startswith("builtin/"):
        base = resolve_model(fs, parent, depth + 1)
        merged = {**base, **m}
        merged["textures"] = {**base.get("textures", {}), **m.get("textures", {})}
        merged["elements"] = m.get("elements", base.get("elements"))
        merged["_parents"] = base.get("_parents", []) + [parent]
        return merged
    m.setdefault("_parents", [parent] if parent else [])
    return m

def resolve_texture(textures: dict, key: str, depth=0) -> str | None:
    v = textures.get(key.lstrip("#"))
    while isinstance(v, str) and v.startswith("#") and depth < 10:
        v = textures.get(v[1:]); depth += 1
    return v                                               # e.g. "minecraft:block/stone_bricks"
```
Nested jars: open `META-INF/jars/*.jar` / `META-INF/jarjar/*.jar` members with `zipfile.ZipFile(io.BytesIO(z.read(name)))` and add them to `sources` right after their parent.

### 11.3 Claude streaming tool loop (sketch — verify SDK event names and model IDs)

```python
import anthropic
client = anthropic.Anthropic()                             # reads ANTHROPIC_API_KEY

system = [{"type": "text", "text": SYSTEM_PROMPT + PALETTE_SUMMARY,
           "cache_control": {"type": "ephemeral"}}]        # prompt caching
messages = [{"role": "user", "content": initial_content}]  # text + images (base64) + template summary

while True:
    with client.messages.stream(model=cfg.claude.design_model, max_tokens=cfg.claude.max_tokens,
                                system=system, tools=TOOLS, messages=messages) as stream:
        for event in stream:
            if event.type == "content_block_stop" and getattr(event, "content_block", None) \
               and event.content_block.type == "tool_use":
                ui.preview_pending(event.content_block)    # optional early UI feedback
        final = stream.get_final_message()
    meter.add(final.usage); meter.check_budget()           # RD.5
    messages.append({"role": "assistant", "content": final.content})
    results = []
    for block in final.content:
        if block.type == "tool_use":
            ok, payload = tools.dispatch(block.name, block.input)   # validate → compile → summary
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": payload, "is_error": not ok})
    if final.stop_reason != "tool_use" or tools.finished:
        break
    messages.append({"role": "user", "content": results})
```
Apply ops at `content_block_stop` if the SDK exposes the completed input there; otherwise apply them after `get_final_message()`. The UI still animates op by op. Record the choice in `DECISIONS.md`.

### 11.4 WorldEdit paste commands (manual verification)

```
//schem list
//schem load building          # modded single-player: <instance>/config/worldedit/schematics (verify)
                               # Paper: plugins/WorldEdit/schematics (or FAWE's folder)
//paste -a                     # -a = skip air, keeps terrain
//undo
```

---

## 12. References

- **Anthropic, "Claude Opus 5.5 builds daydreams that hold together"** (YouTube, Sept 2026): the reference for the design-by-model + deterministic engine + live UI pattern. https://www.youtube.com/watch?v=lCR9epzSNGc
- Sponge Schematic Specification v2 / v3 (`SpongePowered/Schematic-Specification`, GitHub): gzip NBT, palette, varint data, index `x + z*Width + y*Width*Length`, v3 nesting under `Schematic`.
- WorldEdit 7.x clipboard/schematic docs (enginehub.org): `//schem load/save`, `//paste -a`, schematics folders per platform.
- Minecraft Wiki: *Tutorials/Models* and *Model* (blockstates `variants`/`multipart`, model `parent`/`textures`/`elements`, `tintindex`), *Data version*, *Java Edition data values*.
- Fabric documentation: jar-in-jar (`META-INF/jars`), `fabric.mod.json`. NeoForge documentation: `neoforge.mods.toml`, JarJar (`META-INF/jarjar`).
- Anthropic API docs (docs.claude.com): Messages API, tool use (including forced `tool_choice` and parallel tool calls), streaming, prompt caching, vision, model IDs and pricing.
- three.js, `@react-three/fiber` docs: `InstancedMesh`/`BufferGeometry`, texture atlases, Web Workers.
- `nbtlib` (≥ 2.0), `mcschematic` 11.4.x, `trimesh`, Tripo platform docs (API V2 retirement 2026-11-01), TripoSR — as cited in v1 §12.
- Feasibility study (Sept 2026): object-centric limits of image-to-3D on buildings; prior art (ObjToSchematic, Bloxelizer, PicCraft).
- Claude Code memory docs: `CLAUDE.md` is read from the working directory upward at session start.

---

## Appendix A — `CLAUDE.md` template (place at repo root)

```markdown
# img2schem

Photo/description → Claude-designed build (ops) → deterministic engine → WorldEdit `.schem` (Minecraft Java),
using the owner's real installed palette including mods. Python 3.11+ core, CLI-first; local web UI from Phase 3.

## Read first
- docs/SOW.md — full spec and phased plan. Follow §0 rules and §7 phase gates.
- docs/DSL.md — the ops language (also Claude's system-prompt reference). Change ops only via engine/ops.py.
- docs/DECISIONS.md — log every deviation from the SOW (context → decision → consequences).
- docs/archive/SOW_v1.0.md — earlier plan; referenced for kept requirements (R-IDs) and tiers.

## Conventions
- Arrays are [X, Y, Z], Y up; front facade at z=0 facing −Z (north). SOW §4.3.
- Every stage writes an artifact to the run dir and can be re-run from the previous artifact. The UI calls the same stages.
- Block states are modern strings. Never numeric IDs. Never legacy `.schematic`.
- Block IDs come only from the extracted palette (active instance) or palette/data/tiers.yaml. Never hard-code others.
- Claude writes ops, not blocks (`set` capped). Tool schemas are generated from engine/ops.py.
- Model IDs and prices live in config.yaml / pricing.yaml only.
- Secrets only via env vars. Never commit .env, extracted textures, atlases, or owner photos > 1 MB.

## Commands
- `pip install -e ".[dev,vlm,server]"`; `pytest -q`; `pytest -m replay`; `ruff check .`; `mypy img2schem`
- `img2schem instance list` · `img2schem palette build` · `img2schem palette report`
- `img2schem convert tests/fixtures/photos/example.jpg --designer template --out out/dev`
- `img2schem serve --open` (Phase 3+) · web: `cd web && npm i && npm run dev`
- External tests: `IMG2SCHEM_RUN_EXTERNAL=1 pytest -m external`

## Definition of done for any task
1. Tests added/updated and green (including replay).
2. Previews regenerated and visually checked (out/**/preview_*.png, debug_ops.png).
3. report.json shows no new warnings; usage/cost within budget for Claude stages.
4. DECISIONS.md updated if the SOW was deviated from.
```

## Appendix B — Test-bed runbook (expand into `docs/TEST_BED.md`)

**B1. Primary: the owner's modded instance (single-player)**
1. Confirm the instance's loader and MC version (`img2schem instance list`). Install the WorldEdit build for that loader and version from the official distribution if it isn't already installed.
2. Create a dedicated **creative, superflat test world** named `img2schem-test`. Never test in a survival world you care about.
3. Launch once so `config/worldedit/` is created. Confirm the schematics folder (create it if missing) and record the path.
4. Copy the `.schem` there (or let `R8.10` do it) → in game: `//schem list`, `//schem load <name>`, stand where the building should appear facing **south**, `//paste -a`. Expected: the front facade 2 blocks in front of you, centered on you. Use `//undo` to remove it.
5. Check each build:
   - loads with no errors in chat or `logs/latest.log`;
   - orientation is correct;
   - stairs, slabs, panes, fences, walls and doors look right (no disconnected panes, no stair corners that should be inner/outer);
   - modded blocks render;
   - nothing falls;
   - counts match `report.json`.

   Then `//copy` + `//schem save` a re-copy and `img2schem inspect` it to compare palettes.

**B2. Vanilla compatibility: Paper (vanilla-only builds)** — as v1 Appendix B.
1. Java 21; latest Paper for the target 1.21.x.
2. Two profiles: `server-fawe/` and `server-we/` (WorldEdit 7.3+).
3. `online-mode=false` for local testing if desired; `op <name>`.
4. Same paste checklist as B1.

**B3.** Record the WorldEdit/FAWE versions, the loader version and the results in `docs/TEST_BED.md` at the end of every phase.

## Appendix C — Glossary

- **Ops / build program:** the ordered list of architectural operations in `ops.json` that the engine compiles into blocks.
- **Engine:** the deterministic compiler from ops to a block grid, including block-state computation.
- **Template generator:** the deterministic `spec.json` → baseline ops path (no API); v1's procedural massing in ops form.
- **Designer:** Claude, via tool use, refining the ops and applying edits.
- **Critique loop:** render → compare with the photo → fix, capped at N passes.
- **Slot:** a named material role (`$wall`, `$roof`…) mapped to a block in `OpsDoc.style`; changing it re-skins the build.
- **Family:** related shapes of one material (base block, stairs, slab, wall, fence, …) detected from shared textures and names.
- **Tier:** the subset of palette blocks allowed for a role (wall/roof/trim/glass/door/floor/base).
- **Facade grid / measured openings:** the rectified front photo's elements, rasterized to block cells by `facade_from_spec`.
- **Massing:** the building's overall 3D volume (footprint × height × roof form) without detail.
- **Sponge schematic:** the `.schem` format WorldEdit/FAWE use (v2 default here, v3 optional).
- **DataVersion:** Minecraft's integer world-data version stored in the schematic so WorldEdit can upgrade block states.
- **ModsRequired:** the non-vanilla namespaces a schematic needs installed in order to paste.
