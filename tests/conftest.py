from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixtures.jars.make import fabric_game_dir, neoforge_mod, vanilla_jar


@pytest.fixture
def launchers(tmp_path: Path) -> dict[str, list[Path]]:
    """Fake roots for all four launchers, each with one instance."""
    # Vanilla launcher: a Fabric profile with its own game dir, sharing the root's versions/.
    mc = tmp_path / "dotminecraft"
    vanilla_jar(mc / "versions" / "1.21.4" / "1.21.4.jar")
    fab_id = "fabric-loader-0.16.9-1.21.4"
    (mc / "versions" / fab_id).mkdir(parents=True)
    (mc / "versions" / fab_id / f"{fab_id}.json").write_text(json.dumps({"id": fab_id, "inheritsFrom": "1.21.4"}))
    fab_dir = fabric_game_dir(tmp_path / "fabric-profile")
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
    vanilla_jar(cf / "Install" / "versions" / "1.21.1" / "1.21.1.jar", "1.21.1", 3955)
    inst = cf / "Instances" / "Neo Pack"
    neoforge_mod(inst / "mods" / "neomasonry.jar")
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "minecraftinstance.json").write_text(
        json.dumps(
            {
                "name": "Neo Pack",
                "gameVersion": "1.21.1",
                "baseModLoader": {"name": "neoforge-21.1.77", "type": 6, "minecraftVersion": "1.21.1"},
            }
        )
    )

    # Modrinth App (legacy profile.json), no client jar -> DataVersion from the table.
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

    # Prism: vanilla-only instance.
    pr = tmp_path / "PrismLauncher"
    vanilla_jar(pr / "libraries" / "com" / "mojang" / "minecraft" / "1.21.4" / "minecraft-1.21.4-client.jar")
    pinst = pr / "instances" / "Plain"
    (pinst / ".minecraft").mkdir(parents=True)
    (pinst / "instance.cfg").write_text("[General]\nname=Plain 1.21.4\n")
    (pinst / "mmc-pack.json").write_text(
        json.dumps(
            {"components": [{"uid": "org.lwjgl3", "version": "3.3.3"}, {"uid": "net.minecraft", "version": "1.21.4"}]}
        )
    )

    return {"vanilla": [mc], "curseforge": [cf], "modrinth": [mr], "prism": [pr]}
