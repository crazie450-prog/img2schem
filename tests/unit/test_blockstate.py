import pytest

from img2schem.util.blockstate import format_state, parse_state


def test_parse_and_format():
    s = "minecraft:oak_stairs[facing=north,half=bottom,shape=straight]"
    bid, props = parse_state(s)
    assert bid == "minecraft:oak_stairs"
    assert props == {"facing": "north", "half": "bottom", "shape": "straight"}
    assert format_state(bid, props) == s
    assert parse_state("create:andesite_casing") == ("create:andesite_casing", {})


@pytest.mark.parametrize("bad", ["stone", "minecraft:Stone", "minecraft:stone[", "minecraft:stone[a=b,a=c]", "1"])
def test_malformed(bad):
    with pytest.raises(ValueError):
        parse_state(bad)
