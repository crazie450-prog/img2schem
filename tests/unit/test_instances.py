from pathlib import Path

from img2schem.instance.detect import loader_from_version_id, schematics_dir
from img2schem.instance.discover import (
    detect_path,
    discover_all,
    discover_curseforge,
    discover_modrinth,
    discover_vanilla,
    resolve_instance,
)


def test_gtnh_forge_1_7_10(gtnh):
    assert (gtnh.name, gtnh.mc_version, gtnh.loader, gtnh.loader_version) == (
        "GT_New_Horizons_2.9.0",
        "1.7.10",
        "forge",
        "10.13.4.1614",
    )
    mods = {m.id: m for m in gtnh.mods}
    assert mods["worldedit"].version == "6.3.0" and gtnh.worldedit  # read from mcmod.info
    assert mods["gregtech"].name == "GregTech"  # modListVersion 2 form
    assert "no_metadata_coremod" in mods  # falls back to the file name
    assert gtnh.client_jar and gtnh.warnings == []
    assert gtnh.schematics_dir == str(Path(gtnh.game_dir) / "config" / "worldedit" / "schematics")


def test_schematic_save_dir_from_properties(tmp_path):
    we = tmp_path / "config" / "worldedit"
    we.mkdir(parents=True)
    (we / "worldedit.properties").write_text("#comment\nschematic-save-dir=my_schems\n")
    assert schematics_dir(tmp_path) == we / "my_schems"


def test_vanilla_launcher(launchers):
    found = {i.name: i for i in discover_vanilla(launchers["vanilla"][0])}
    assert set(found) == {"Fabric 1.21.4", "1.21.4"}  # latest-release resolved; snapshot skipped
    fab = found["Fabric 1.21.4"]
    assert (fab.mc_version, fab.loader, fab.loader_version) == ("1.21.4", "fabric", "0.16.9")
    assert [m.id for m in fab.mods] == ["fabdeco"] and not fab.worldedit
    assert found["1.21.4"].loader == "vanilla"


def test_curseforge_neoforge(launchers):
    (inst,) = discover_curseforge(launchers["curseforge"][0])
    assert (inst.name, inst.mc_version) == ("Neo Pack", "1.21.1")
    assert (inst.loader, inst.loader_version) == ("neoforge", "21.1.77")
    (mod,) = inst.mods
    assert (mod.id, mod.name, mod.version) == ("neomasonry", "Neo Masonry", "3.4.5")  # ${file.jarVersion} -> manifest


def test_modrinth_without_jar(launchers):
    (inst,) = discover_modrinth(launchers["modrinth"][0])
    assert (inst.name, inst.mc_version, inst.loader, inst.loader_version) == ("Fab Pack", "1.20.1", "fabric", "0.15.11")
    assert inst.client_jar is None and any("client jar" in w for w in inst.warnings)


def test_discover_all_and_resolve(launchers):
    assert len(discover_all(launchers)) == 5
    assert resolve_instance("curseforge:Neo Pack", launchers).loader == "neoforge"
    assert resolve_instance("GT_New_Horizons_2.9.0", launchers).launcher == "prism"


def test_detect_user_path(launchers):
    assert detect_path(launchers["curseforge"][0] / "Instances" / "Neo Pack").loader == "neoforge"
    gtnh_game = launchers["prism"][0] / "instances" / "GTNH" / ".minecraft"
    assert detect_path(gtnh_game).name == "GT_New_Horizons_2.9.0"
    assert detect_path(gtnh_game.parent).mc_version == "1.7.10"


def test_loader_from_version_id():
    assert loader_from_version_id("fabric-loader-0.16.9-1.21.4") == ("fabric", "0.16.9")
    assert loader_from_version_id("neoforge-21.1.77") == ("neoforge", "21.1.77")
    assert loader_from_version_id("1.7.10-Forge10.13.4.1614-1.7.10")[0] == "forge"
    assert loader_from_version_id("1.21.4") == ("vanilla", None)
