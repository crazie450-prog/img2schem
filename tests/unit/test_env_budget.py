import pytest
from fixtures.jars.make import nei_dumps

from img2schem.config import BudgetUSD, Settings
from img2schem.designer.budget import BudgetExceeded, BudgetGuard
from img2schem.util.env import load_dotenv


def test_dotenv_sets_only_missing_variables(tmp_path, monkeypatch):
    monkeypatch.delenv("IMG2SCHEM_T1", raising=False)
    monkeypatch.delenv("IMG2SCHEM_T2", raising=False)
    monkeypatch.delenv("IMG2SCHEM_T4", raising=False)
    monkeypatch.setenv("IMG2SCHEM_T3", "from-shell")
    env = tmp_path / ".env"
    env.write_text('# comment\nIMG2SCHEM_T1=abc  # trailing\nexport IMG2SCHEM_T2="q v"\nIMG2SCHEM_T3=file\n'
                   "IMG2SCHEM_T4=\n", encoding="utf-8")  # fmt: skip
    assert load_dotenv(env) == ["IMG2SCHEM_T1", "IMG2SCHEM_T2"]
    import os

    assert os.environ["IMG2SCHEM_T1"] == "abc" and os.environ["IMG2SCHEM_T2"] == "q v"
    assert os.environ["IMG2SCHEM_T3"] == "from-shell" and "IMG2SCHEM_T4" not in os.environ  # empty = unset
    assert load_dotenv(tmp_path / "missing.env") == []


def test_owner_budgets():
    c = Settings().claude
    assert (c.budget().warn, c.budget().stop) == (1.0, 5.0)
    assert (c.budget("large").warn, c.budget("large").stop) == (5.0, 10.0)
    with pytest.raises(ValueError, match="no budget"):
        c.budget("huge")
    with pytest.raises(ValueError, match="below warn"):
        BudgetUSD(warn=5, stop=1)


def test_guard_warns_once_and_stops_before_passing_the_limit():
    g = BudgetGuard(BudgetUSD(warn=1.0, stop=5.0))
    assert g.add(0.6) is None
    assert "past" in (g.add(0.6) or "")
    assert g.add(0.5) is None  # warned once
    g.check(2.8)  # 1.7 + 2.8 = 4.5: still fits
    with pytest.raises(BudgetExceeded, match="--budget large"):
        g.check(3.5)  # could reach 5.2
    with pytest.raises(BudgetExceeded) as e:
        BudgetGuard(BudgetUSD(warn=5, stop=10), "large").check(11)
    assert "--budget large" not in str(e.value)


def test_review_sheet(tmp_path):
    from img2schem.palette.nei import import_nei
    from img2schem.palette.query import PaletteIndex
    from img2schem.palette.review import review_sheet

    idx = PaletteIndex(import_nei(nei_dumps(tmp_path / "dumps")))
    img = review_sheet(idx, ["minecraft:stonebrick", "minecraft:quartz_block"])
    assert img.size == (6 * 150, 2 * 150)
    assert img.getpixel((6 + 64 + 10, 40)) != (246, 246, 244)  # the color swatch of the first block
