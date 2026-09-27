# img2schem

Photo (or text description) of a building → a designed Minecraft build → a WorldEdit `.schematic` for
**GT New Horizons (Minecraft 1.7.10, WorldEdit 6.3.0)**, using the blocks registered in your world,
including mods.

The spec is [docs/SOW.md](docs/SOW.md), re-scoped for GTNH by [docs/SOW_GTNH.md](docs/SOW_GTNH.md).
**Status: Phase 3 in progress** (the local web UI). Phase 2 is done: Claude designs builds from a description
or photos, with critique passes, and edits them with a version history (undo/redo).

## Quick start

Windows PowerShell (5.1 has no `&&`, so one command per line):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev,vlm,server]"   # vlm: the Anthropic SDK (designer); server: the web UI
```

Linux/macOS:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,vlm,server]"
```

Then:

```bash
img2schem instance list                  # instances from Prism, CurseForge, Modrinth App, vanilla launcher
img2schem instance use "<name>"          # or launcher:name, or a path to the instance folder
img2schem world list                     # worlds of that instance
img2schem world use img2schem-test       # its level.dat lists the valid block names
img2schem palette import <.minecraft\dumps>  # colors + shapes from NEI data dumps (see below)
img2schem palette search "stone brick" --shape stairs
img2schem palette review chisel:marble@3 minecraft:stonebrick  # PNG sheet: icon, measured color, family
img2schem doctor                         # WorldEdit, schematics folder, world, palette

img2schem materials my.spec.json photo.jpg --corners "x,y x,y x,y x,y" [--roof-box "x0,y0,x1,y1"]
                                          # photo colors -> blocks for wall/roof/trim/base/window/door in the spec
img2schem plan examples/brick_house.spec.json  # spec.json (measured description) -> brick_house.ops.json (build program)
img2schem compile examples/brick_house.ops.json # ops.json -> .schematic + previews + report.json (+ WorldEdit folder)
img2schem compile examples/tower.ops.json      # a 109-tall curved tower (loft/sweep ops, docs/DSL.md)
img2schem compile examples/courtyard.ops.json  # one component placed four ways (define/place/mirror)
img2schem design "a stone watchtower" --name watchtower  # Claude designs it (costs API credit), then compiles
img2schem design "..." --budget large                    # $5 warning / $10 hard stop instead of $1 / $5
img2schem design --photo house.jpg --name villa "notes"  # from a photo (repeat --photo for more views), 2 critique passes
img2schem edit watchtower "make the roof steeper"        # Claude changes builds/watchtower.ops.json: a new version
img2schem history watchtower                             # versions, instructions, cost
img2schem undo watchtower                                # back one version (redo: forward), recompiled
python examples/make_test_grids.py       # Phase 0 test grids -> out/testgrids/ (+ your WorldEdit folder)
img2schem serve --open                   # the web UI (local): design, revise, preview in 3D, edit ops.json
img2schem inspect  some.schematic        # size, blocks, counts, mods required
img2schem preview  some.schematic --out out/prev
img2schem validate some.schematic [--strict]
```

In game: `//schem load <name>`, stand where the build should go **facing south**, `//paste -a`.
See [docs/TEST_BED.md](docs/TEST_BED.md).

Claude API key (Phase 2): copy `.env.example` to `.env` in the repo folder and put your key after
`ANTHROPIC_API_KEY=`. `.env` is git-ignored. `img2schem doctor` shows whether the key was found (never its
value) and the per-build budgets: a warning at US$1 and a hard stop at US$5, or US$5 / US$10 with
`--budget large`.

NEI dumps: in GTNH open the inventory, click NEI's wrench button, Tools → Data Dumps, and run the Block dump
and the Item Panel dump as **CSV** and as **PNG**. They land in `.minecraft\dumps\`.

Development: `pytest -q`, `ruff check .`, `mypy img2schem`. Web UI source: `web/` (`npm install`, `npm run dev`
with `img2schem serve` running; `npm run build` updates the bundle in `img2schem/server/static`, which is
committed so running the UI needs no Node).

## Legal notice

For personal, non-commercial use. Buildings can be protected by copyright and freedom-of-panorama rules
differ between countries; only convert photos you have the right to use. Minecraft and mod textures belong
to their rights holders: this tool reads them from your own installed files, keeps anything it extracts in a
local cache, and never commits or redistributes them. Not affiliated with Mojang, Microsoft or any mod author.
