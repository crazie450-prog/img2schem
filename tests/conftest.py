from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixtures.jars.make import (
    GTNH_BLOCKS,
    client_jar,
    fabric_mod,
    legacy_forge_mod,
    level_dat,
    neoforge_mod,
    write_jar,
)


@pytest.fixture
def launchers(tmp_path: Path) -> dict[str, list[Path]]:
    """Fake roots for all four launchers. Prism holds a GTNH-like Forge 1.7.10 instance with a world."""
    # Vanilla launcher: a Fabric profile with its own game dir, sharing the root's versions/.
    mc = tmp_path / "dotminecraft"
    client_jar(mc / "versions" / "1.21.4" / "1.21.4.jar", "1.21.4")
    fab_id = "fabric-loader-0.16.9-1.21.4"
    (mc / "versions" / fab_id).mkdir(parents=True)
    (mc / "versions" / fab_id / f"{fab_id}.json").write_text(json.dumps({"id": fab_id, "inheritsFrom": "1.21.4"}))
    fab_dir = tmp_path / "fabric-profile"
    fabric_mod(fab_dir / "mods" / "fabdeco-2.1.0.jar")
    (mc / "launcher_profiles.json").write_text(
        json.dumps(
            {
                "profiles": {
                    "a": {"name": "Fabric 1.21.4", "type": "custom", "lastVersionId": fab_id, "gameDir": str(fab_dir)},
                    "b": {"name": "", "type": "latest-release", "lastVersionId": "latest-release"},
                    "c": {"name": "", "type": "latest-snapshot", "lastVersionId": "latest-snapshot"},
                }
            }
        )
    )

    # CurseForge: NeoForge instance.
    cf = tmp_path / "curseforge" / "minecraft"
    client_jar(cf / "Install" / "versions" / "1.21.1" / "1.21.1.jar", "1.21.1")
    inst = cf / "Instances" / "Neo Pack"
    neoforge_mod(inst / "mods" / "neomasonry.jar")
    (inst / "minecraftinstance.json").write_text(
        json.dumps(
            {
                "name": "Neo Pack",
                "gameVersion": "1.21.1",
                "baseModLoader": {"name": "neoforge-21.1.77", "type": 6, "minecraftVersion": "1.21.1"},
            }
        )
    )

    # Modrinth App (legacy profile.json), no client jar.
    mr = tmp_path / "ModrinthApp"
    prof = mr / "profiles" / "fab-pack"
    prof.mkdir(parents=True)
    (prof / "profile.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "name": "Fab Pack",
                    "game_version": "1.20.1",
                    "loader": "fabric",
                    "loader_version": {"id": "0.15.11"},
                }
            }
        )
    )

    # Prism: GTNH-like Forge 1.7.10 instance with WorldEdit and a world.
    pr = tmp_path / "PrismLauncher"
    client_jar(pr / "libraries" / "com" / "mojang" / "minecraft" / "1.7.10" / "minecraft-1.7.10-client.jar", "1.7.10")
    gt = pr / "instances" / "GTNH"
    game = gt / ".minecraft"
    (gt / "instance.cfg").parent.mkdir(parents=True)
    (gt / "instance.cfg").write_text("[General]\nname=GT_New_Horizons_2.9.0\n")
    (gt / "mmc-pack.json").write_text(
        json.dumps(
            {
                "components": [
                    {"uid": "net.minecraft", "version": "1.7.10"},
                    {"uid": "net.minecraftforge", "version": "10.13.4.1614"},
                ]
            }
        )
    )
    legacy_forge_mod(game / "mods" / "worldedit-mc1.7.10-6.3.0.jar", "worldedit", "WorldEdit", "6.3.0")
    legacy_forge_mod(game / "mods" / "gregtech.jar", "gregtech", "GregTech", "5.09.51", mod_list_v2=True)
    write_jar(game / "mods" / "no-metadata-coremod.jar", {"a.class": b"\xca\xfe"})
    level_dat(game / "saves" / "img2schem-test" / "level.dat", GTNH_BLOCKS, {"minecraft:stick": 280})

    return {"vanilla": [mc], "curseforge": [cf], "modrinth": [mr], "prism": [pr]}


@pytest.fixture
def gtnh(launchers):
    from img2schem.instance.discover import discover_prism

    (inst,) = discover_prism(launchers["prism"][0])
    return inst
