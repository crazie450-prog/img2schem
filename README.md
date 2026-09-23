# img2schem

Photo (or text description) of a building → a designed Minecraft build → a WorldEdit `.schem`
(Java Edition), using only the blocks in **your installed instance, including mods**.

The full spec and plan is [docs/SOW.md](docs/SOW.md). **Status: Phase 0** (output end: instance discovery,
a minimal palette, the Sponge `.schem` writer/reader, previews, structural validation). Photo analysis,
the build engine and the Claude designer come in later phases.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

img2schem instance list                  # instances from the vanilla launcher, CurseForge, Modrinth App, Prism
img2schem instance use "Fabric 1.21.4"   # or launcher:name, or a path to the instance folder
img2schem doctor                         # client jar, DataVersion, WorldEdit, schematics folder
img2schem palette build                  # blocks, properties, shapes -> ~/.cache/img2schem/palettes/<hash>/

python examples/make_test_grids.py       # Phase 0 test grids -> out/testgrids/ (+ your WorldEdit folder)
img2schem inspect  some.schem            # dims, palette, counts, DataVersion, mods required
img2schem preview  some.schem --out out/prev
img2schem validate some.schem [--strict]
```

In game: `//schem load <name>`, stand where the build should go **facing south**, `//paste -a`.
See [docs/TEST_BED.md](docs/TEST_BED.md).

Development: `pytest -q`, `ruff check .`, `mypy img2schem`.

## Legal notice

For personal, non-commercial use. Buildings can be protected by copyright and freedom-of-panorama rules
differ between countries; only convert photos you have the right to use. Minecraft and mod textures belong
to their rights holders: this tool reads them from your own installed files, keeps anything it extracts in a
local cache, and never commits or redistributes them. Not affiliated with Mojang, Microsoft or any mod author.
