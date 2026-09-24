# Build DSL (ops)

`ops.json` is the build program: a style (material slots) plus an ordered list of ops. The engine
(`img2schem/engine/`) compiles it deterministically into blocks; `img2schem compile ops.json` turns it into a
`.schematic` with previews. The models in `engine/ops.py` are the source of truth (Claude's tool schemas are
generated from them); this page explains them. Example: `examples/house.ops.json`.

## Coordinates

```
            north (-Z)
               ^
   front facade: the plane z = 0, facing north
   +--------------------------+  z = 0
   |                          |
   |        building          |    X = east (+), Z = south (+), Y = up
   |                          |    ground floor: y = 0
   +--------------------------+  z = depth - 1
  x = 0                  x = width - 1
```

- Boxes and rects are **inclusive**: `{"x0": 0, "z0": 0, "x1": 12, "z1": 8}` is 13 × 9.
- Negative coordinates are fine (e.g. a roof overhang at z = -1); the compiler shifts everything so the grid
  starts at 0 and keeps the paste position: the front facade's bottom center lands 2 blocks south of the
  player and y = 0 replaces the block they stand on.

## Materials

Every `mat` is one of:

| Form | Example | Meaning |
|---|---|---|
| slot | `"$wall"` | the block in `style["wall"]` |
| family member | `"$roof.stairs"` | `style["roof.stairs"]` if set, else the palette family (`img2schem palette family`) of the `$roof` block: `.stairs`, `.slab`, `.wall`, `.fence`, `.fence_gate` |
| literal | `"chisel:marble@3"` | a block: registry name + `@meta` (omit `@0`) |

Changing a slot re-skins the whole build. Orientation metadata (stairs direction, door halves, log axis, top
slabs) is written by the engine, so literals give only the material variant (`minecraft:log@1` = spruce log;
the engine adds the axis). Pane, fence and wall connections and stair corner shapes are computed by the game.

## Common fields

Every op has `id` (unique), `label` (human text), optional `group` and `note` (why it exists), and `mode`:
`overwrite` (default: replaces earlier blocks) or `keep` (only fills cells that are still air). Ops apply in order.

## Ops

| Op | Fields | Notes |
|---|---|---|
| `box` | `from`, `to`, `mat`, `hollow` | solid or hollow cuboid |
| `walls` | `footprint`, `y0`, `height`, `mat` (`$wall`), `thickness` | closed rectangular wall loop |
| `floors` | `footprint`, `ys` (list), `mat` (`$floor`) | full layers at each y |
| `door` | `pos` (lower half), `facing`, `mat` (`$door`), `hinge` | two-block door; `facing` = the wall's outward side (`north` for the front wall). Carve the opening first if a wall is there |
| `openings` | `footprint`, `face` (front/back/left/right), `sills`, `w`, `h`, `spacing`, `count`, `margin`, `mat` (`$glass`) | a centered row of equal windows at each sill height; `count: 0` fits as many as possible |
| `roof` | `footprint`, `y0`, `type`, `pitch`, `ridge`, `rise`, `overhang`, `mat` (`$roof`), `gable_fill` (`$wall`), `parapet` | see below |
| `column` | `pos` (x, z), `y0`, `height`, `mat` | vertical run; logs stand upright |
| `beam` | `from`, `to` (one axis), `mat` | horizontal or vertical run; logs lie along it |
| `trim_band` | `footprint`, `y`, `mat` (`$trim`), `outset` | 1-block ring (belt course, cornice) |
| `carve` | `from`, `to` | sets a box to air |
| `set` | `cells`, `block` | escape hatch: ≤ 64 cells per op, ≤ 256 per build |

### Roofs

`y0` is the height of the lowest course (usually the top of the walls + 1). The roof covers `footprint` plus
`overhang` on every side, and stairs always rise toward the ridge.

| `type` | Shape |
|---|---|
| `gable` | two slopes meeting at a ridge along `ridge` (`x` or `z`); an odd width gets a full-block ridge; the triangular ends above the walls are filled with `gable_fill` |
| `hip` | slopes on all four sides, shrinking ring by ring to a ridge line or peak |
| `shed` | one slope rising toward `rise` (north/south/east/west); the side triangles and the tall wall are filled |
| `flat` | one layer of `mat`; `parapet: true` adds a ring on top of the edge |

| `pitch` | Course | Needs |
|---|---|---|
| `1:1` | one stair per block of depth | `<mat>.stairs` |
| `1:2` | alternating bottom and top slabs (half a block per step) | `<mat>.slab` |
| `2:1` | a full block under a stair (two blocks per step) | `<mat>.stairs` |

## Not implemented yet

From SOW §6.5: `facade_from_spec` (arrives with the template generator), `railing`, `vary`, `define`/`place`,
`array`, `mirror`, and polygon footprints (rectangles only for now).
