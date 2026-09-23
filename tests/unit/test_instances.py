from pathlib import Path

from img2schem.instance.detect import loader_from_version_id
from img2schem.instance.discover import (
    detect_path,
    discover_all,
    discover_curseforge,
    discover_modrinth,
    discover_prism,
    discover_vanilla,
    resolve_instance,
)


def test_vanilla_launcher(launchers):
    found = {i.name: i for i in discover_vanilla(launchers["vanilla"][0])}
    assert set(found) == {"Fabric 1.21.4", "1.21.4"}  # latest-release resolved; snapshot skipped
    fab = found["Fabric 1.21.4"]
    assert (fab.mc_version, fab.loader, fab.loader_version) == ("1.21.4", "fabric", "0.16.9")
    assert (fab.data_version, fab.data_version_source) == (4189, "jar")
    assert [m.id for m in fab.mods] == ["fabdeco", "worldedit"]
    assert fab.mods[0].version == "2.1.0" and fab.mods[0].name == "Fab Deco"
    assert fab.worldedit
    assert fab.schematics_dir and fab.schematics_dir.endswith(str(Path("config/worldedit/schematics")))
    assert found["1.21.4"].loader == "vanilla" and not found["1.21.4"].worldedit


def test_curseforge_neoforge(launchers):
    (inst,) = discover_curseforge(launchers["curseforge"][0])
    assert (inst.name, inst.mc_version) == ("Neo Pack", "1.21.1")
    assert (inst.loader, inst.loader_version) == ("neoforge", "21.1.77")
    assert inst.data_version == 3955 and inst.data_version_source == "jar"
    (mod,) = inst.mods
    assert (mod.id, mod.name, mod.version) == ("neomasonry", "Neo Masonry", "3.4.5")  # ${file.jarVersion} -> manifest


def test_modrinth_without_jar_uses_table(launchers):
    (inst,) = discover_modrinth(launchers["modrinth"][0])
    assert (inst.name, inst.mc_version, inst.loader, inst.loader_version) == ("Fab Pack", "1.20.1", "fabric", "0.15.11")
    assert inst.client_jar is None
    assert (inst.data_version, inst.data_version_source) == (3465, "table")
    assert any("client jar" in w for w in inst.warnings)


def test_prism(launchers):
    (inst,) = discover_prism(launchers["prism"][0])
    assert (inst.name, inst.mc_version, inst.loader) == ("Plain 1.21.4", "1.21.4", "vanilla")
    assert inst.client_jar and inst.data_version == 4189
    assert inst.game_dir.endswith(".minecraft")


def test_discover_all_and_resolve(launchers):
    assert len(discover_all(launchers)) == 5
    assert resolve_instance("curseforge:Neo Pack", launchers).loader == "neoforge"
    assert resolve_instance("Plain 1.21.4", launchers).launcher == "prism"


def test_detect_user_path(launchers):
    inst_dir = launchers["curseforge"][0] / "Instances" / "Neo Pack"
    assert detect_path(inst_dir).loader == "neoforge"
    prism_game = launchers["prism"][0] / "instances" / "Plain" / ".minecraft"
    assert detect_path(prism_game).name == "Plain 1.21.4"


def test_loader_from_version_id():
    assert loader_from_version_id("fabric-loader-0.16.9-1.21.4") == ("fabric", "0.16.9")
    assert loader_from_version_id("neoforge-21.1.77") == ("neoforge", "21.1.77")
    assert loader_from_version_id("1.21.4-forge-54.0.12")[0] == "forge"
    assert loader_from_version_id("1.21.4") == ("vanilla", None)
