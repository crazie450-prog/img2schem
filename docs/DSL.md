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
| `window` | `footprint`, `face`, `u0`, `u1`, `y0`, `y1`, `recess` (0/1), `mat` (`$glass`) | one window; `u` runs along the face (x on front/back, z on sides); `recess: 1` sets the glass one block in |
| `roof` | `footprint`, `y0`, `type`, `pitch`, `ridge`, `rise`, `overhang`, `mat` (`$roof`), `gable_fill` (`$wall`), `parapet` | see below |
| `column` | `pos` (x, z), `y0`, `height`, `mat` | vertical run; logs stand upright |
| `beam` | `from`, `to` (one axis), `mat` | horizontal or vertical run; logs lie along it |
| `trim_band` | `footprint`, `y`, `mat` (`$trim`), `outset` | 1-block ring (belt course, cornice) |
| `carve` | `from`, `to` | sets a box to air |
| `set` | `cells`, `block` | escape hatch: ≤ 64 cells per op, ≤ 256 per build |
| `loft` | `profile`, `keys`, `pivot`, `interp`, `fill`, `thickness`, `mat`, `floor_every`, `floor_mat`, `caps`, `smooth`, `mullions`, `lights` | a curved horizontal profile carried up through keys; see below |
| `sweep` | `points` (x, y, z), `radius`, `interp`, `mat` | a round tube along a curve (ribs, arches) |
| `spiral_stair` | `center` (x, z), `y0`, `y1`, `radius` (1–3), `turn` (cw/ccw), `mat` (stairs), `column` | one stair per level around a central column; clears its shaft through the floors; see below |
| `railing` | `path` ([x, z] points), `y`, `mat`, `closed` | a 1-block line stepped so each block touches the next on a face (panes, fences and walls only connect sideways) |
| `vary` | `target` (op id), `mat`, `ratio` (0.15), `seed` | swaps about `ratio` of the blocks `target` placed with its own `mat` (not its stairs etc.) for `mat`; the same seed gives the same result |
| `define` | `name`, `ops` | a reusable component in its own coordinates; places nothing by itself |
| `place` | `name`, `pos`, `rotate` (0/90/180/270), `mirror` (x/z) | a copy of a component; see below |
| `array` | `name`, `pos`, `count`, `step` [dx, dy, dz], `rotate`, `mirror` | `count` copies, each moved by `step` |
| `mirror` | `ops` (op ids or group names), `axis` (x/z), `plane` | copies what those earlier ops placed across a plane |

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

### Curves: `loft` and `sweep`

A `profile` is a horizontal shape in the XZ plane: `outer` minus each shape in `minus`. Shapes are
`{"shape": "ellipse", "center": [x, z], "rx": 9, "rz": 5, "rotate": 0}` or
`{"shape": "polygon", "points": [[x, z], ...]}`. A crescent is an ellipse minus an offset ellipse.

`keys` (strictly increasing `y`) place the profile at heights: each key scales it (`scale`, and per axis `sx`,
`sz`), rotates it by `rotate` degrees about `pivot`, then shifts it by (`dx`, `dz`). Between keys the transform
is interpolated `smooth` (Catmull-Rom, default) or `linear`; the loft runs from the first key's y to the last.
One pair of equal keys is a straight extrusion; shrinking `scale` tapers, changing `dx`/`dz` leans, changing
`rotate` twists.

- `fill: "solid"` fills the profile; `"shell"` keeps walls `thickness` blocks thick (watertight at any lean).
- `floor_every: N` puts a full layer of `floor_mat` (default `mat`) every N levels from the first key;
  `caps: true` also closes the top and bottom.

```json
{"op": "loft", "id": "core", "profile": {"outer": {"shape": "ellipse", "rx": 13, "rz": 9}},
 "keys": [{"y": 0}, {"y": 50, "scale": 0.85, "rotate": 10}, {"y": 96, "scale": 0.6, "rotate": 25}],
 "fill": "shell", "mat": "$glass", "floor_every": 4, "floor_mat": "$floor", "caps": true}
```

Detail options:

- `smooth: true` turns every step of the outer surface (where it moves in or out by a block between levels)
  into a stair of `<mat>.stairs` rising toward the wall, upside-down under an overhang. Tapers and leans then
  read as slopes, and mobs can't spawn on the ledges. `mat` must be a slot (`$blade`) whose block has stairs
  (from the palette family or `style["blade.stairs"]`); glass has none, so leave glass unsmoothed.
- `mullions: {"count": 12, "mat": "$metal"}`: vertical ribs at equal angles around the pivot, one block wide,
  twisting with the keys' `rotate`. They converge as a loft tapers, so pick the count for the narrowest level.
- `lights: {"every": 4, "mat": "$light"}`: light blocks set into every floor layer (a solid loft: its top
  layer) where x and z are multiples of `every`, never in the outermost ring. `every` 4 keeps a 3-high storey
  lit above light 7 (no mob spawns); 5 or 6 suits open plazas.

`sweep` places balls of `radius` along a curve through `points`; the curve passes through every point.

### Spiral stairs

`spiral_stair` climbs one level per block around the ring of a (2 × `radius` + 1) square centered on
`center`, around a `column` filling the inside: radius 1 is the classic 3 × 3 with 7 blocks of headroom. The
first stair sits at `y0` (on the floor below it) and the last at `y1`; set `y1` to a floor level to step off
there. Every other ring cell from `y0` to `y1 + 2` is cleared, which opens the floors it passes through, so
place it after the floors. On each floor, step on where the stair reaches the floor's level.

Builds may be up to 256 tall (the top of a 1.7.10 world); larger footprints only warn. Full example:
`examples/tower.ops.json`.

### Components, arrays and mirrors

`define` builds a component from its `ops` in its own coordinates (put its origin at a useful corner or at its
center). `place` and `array` copy it: first mirrored (`x` flips east and west, `z` north and south), then turned
`rotate` degrees clockwise seen from above ((x, z) → (−z, x) per quarter turn), then moved to `pos`. Stairs,
doors (facing and hinge) and logs are re-oriented to match. Only the component's final blocks are copied; a
carve inside a component doesn't cut into the build, so carve where you place it.

`mirror` copies what the named earlier ops placed (as they placed it, before later ops) across the plane
`axis = plane`. `plane` is a block coordinate: `6.5` is the middle of block 6 (block 6 maps to itself: a
13-wide build 0..12 is symmetric about it), `6` the face between blocks 5 and 6. Example:
`examples/courtyard.ops.json` places one kiosk four ways (three `place`s and a `mirror`), all doors facing the
center.

## Not implemented yet

Polygon footprints for the rectangular ops (use `loft` for curved or polygonal plans). `facade_from_spec` is
replaced by the template generator writing one `window` op per measured window (D-021), so `ops.json` never
depends on `spec.json`.
