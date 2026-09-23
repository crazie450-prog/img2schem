# Decisions log

One entry per deviation from, or interpretation of, docs/SOW.md: context → decision → consequences.
Entries marked **verify** need a check on the owner's machine or test bed.

## 2026-09-23 · Phase 0

### D-001 Sponge Offset and WEOffset (verify)
- **Context:** §4.3 wants the bottom-center of the front facade 2 blocks south of the player. From WorldEdit's
  Sponge readers as we understand them: v2 uses `Metadata.WEOffsetX/Y/Z` (when present) as the region's
  min corner relative to the player, and v3 uses `Offset` for the same thing.
- **Decision:** write `Offset = WEOffset = [-(W//2), 0, 2]` in v2, and `Offset` with that value in v3
  (`stages/export_schem.py:front_center_offset`, the single place to change it).
- **Consequences:** needs checking on the modded single-player bed and on Paper + FAWE / Paper + WE (TEST_BED.md).
  If a bed disagrees, flip the constant there and record the result here.

### D-002 Partial block states (verify)
- **Context:** RE.4: only properties the block has are written; others take in-game defaults. Phase 0 must
  confirm that WorldEdit accepts partial states.
- **Decision:** `PaletteBlock.default_state` is the bare id; the test grids use partial states on purpose
  (e.g. stairs without `waterlogged`, panes with only connection properties).
- **Consequences:** if a bed rejects them, add a defaults-inference step (RE.4) and record it here.

### D-003 Launcher paths and metadata (verify)
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

### D-005 validate_state accepts asset-invisible properties
- **Context:** RP.17 says every property/value must be in `properties`, but some real properties
  (`waterlogged`, `powered`, `persistent`, `distance`) never appear in blockstate files because they don't
  change the model, so the extractor can't see them.
- **Decision:** those four are accepted on any block; any other unknown property is an error.
- **Consequences:** a wrong `waterlogged` on a block that lacks it would pass validation. The Phase 5 helper
  mod (O2) removes the guesswork.

### D-006 Resource packs override, never add, blocks
- **Context:** RP.3 treats every blockstate file as a block, but a resource pack can ship blockstates for
  blocks that aren't registered.
- **Decision:** candidate blocks come only from the vanilla jar and mod jars; resource packs only override
  their blockstates, models and textures.

### D-007 Byte-identical schematics
- **Context:** S5 requires identical bytes for identical input, but gzip headers carry a timestamp and file
  name, and R8.9 metadata carries a `Date`.
- **Decision:** gzip with `mtime=0` and no file name; `SchemMeta.date_ms` pins `Date` (defaults to now).
- **Consequences:** golden tests must pass a fixed `date_ms`.

### D-008 Module layout additions
- **Decision:** `palette/build.py` orchestrates extraction and caching (not listed in §5.1);
  `Palette.validate_state` lives on the model until `palette/query.py` arrives in Phase 1;
  `util/blockstate.py` parses state strings. Phase 0 previews use a flat per-block hash color (§7 Phase 0 task 4).
