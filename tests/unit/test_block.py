import pytest

from img2schem.util.block import format_block, namespace, parse_block


def test_parse_and_format():
    assert parse_block("minecraft:wool@14") == ("minecraft:wool", 14)
    assert parse_block("minecraft:stone") == ("minecraft:stone", 0)
    assert parse_block("IC2:blockMachine@3") == ("IC2:blockMachine", 3)
    assert parse_block("gregtech:gt.blockcasings@15") == ("gregtech:gt.blockcasings", 15)
    assert parse_block("chisel:marble_stairs.0") == ("chisel:marble_stairs.0", 0)
    assert format_block("minecraft:wool", 14) == "minecraft:wool@14"
    assert format_block("minecraft:stone", 0) == "minecraft:stone"
    assert namespace("IC2:blockMachine@3") == "IC2"


@pytest.mark.parametrize("bad", ["stone", "1", "minecraft:wool@16", "minecraft:wool@x", "minecraft:a b", "minecraft:"])
def test_malformed(bad):
    with pytest.raises(ValueError):
        parse_block(bad)
