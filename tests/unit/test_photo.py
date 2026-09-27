import json

import cv2
import numpy as np
import pytest
from fixtures.jars.make import nei_dumps
from fixtures.synthetic.gen import photograph, render_facade
from PIL import Image

from img2schem.models import BuildSpec
from img2schem.palette.nei import import_nei
from img2schem.palette.query import PaletteIndex
from img2schem.stages.ingest import IngestError, ingest
from img2schem.stages.materials import apply_materials, lab_to_srgb, region_colors
from img2schem.stages.rectify import order_quad, parse_corners, rectify
from img2schem.util.color import srgb_to_lab

ELEMENTS = [
    {"kind": "window", "bbox": [0.1, 0.15, 0.25, 0.4]},
    {"kind": "window", "bbox": [0.75, 0.15, 0.9, 0.4]},
    {"kind": "door", "bbox": [0.44, 0.55, 0.56, 1.0]},
]


def test_ingest_orientation_resize_hash_and_rejects(tmp_path):
    big = Image.new("RGB", (3000, 1200), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90 degrees clockwise
    big.save(tmp_path / "p.jpg", exif=exif)
    out = ingest(tmp_path / "p.jpg", tmp_path / "run")
    meta = json.loads((tmp_path / "run" / "image_meta.json").read_text())
    assert Image.open(out).size == (819, 2048)  # EXIF-rotated to portrait, long edge clamped to 2048
    assert meta["original_size"] == [1200, 3000] and meta["resize_factor"] == pytest.approx(2048 / 3000, 1e-4)
    again = ingest(tmp_path / "p.jpg", tmp_path / "run2")
    assert json.loads((tmp_path / "run2" / "image_meta.json").read_text())["sha256"] == meta["sha256"]
    assert again.is_file()
    Image.new("RGB", (800, 300)).save(tmp_path / "small.png")
    with pytest.raises(IngestError, match="short edge"):
        ingest(tmp_path / "small.png", tmp_path / "run3")
    (tmp_path / "junk.jpg").write_bytes(b"not an image")
    with pytest.raises(IngestError, match="cannot read"):
        ingest(tmp_path / "junk.jpg", tmp_path / "run4")


def test_corner_parsing_and_ordering():
    pts = parse_corners("900,820 100,90 880,100 120,800")
    assert order_quad(pts) == [(100, 90), (880, 100), (900, 820), (120, 800)]
    with pytest.raises(ValueError):
        parse_corners("1,2 3,4")


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_rectify_error_under_2px(tmp_path, seed):
    """A1: with the true corners, points on the wall land within 2 px RMS of where they belong."""
    facade, _ = render_facade(ELEMENTS)
    roof_px = facade.shape[0] - 400
    photo, corners, h_true = photograph(facade, roof_px, seed=seed)
    Image.fromarray(photo).save(tmp_path / "image.png")
    rect = rectify(tmp_path / "image.png", tmp_path, [corners[i] for i in (2, 0, 3, 1)])  # any order
    out_w, out_h = rect.size
    # Grid of wall points: facade frame -> photo (true H) -> rectified (our H); expected: scaled wall coords.
    u, v = np.meshgrid(np.linspace(0, 599, 7), np.linspace(0, 399, 5))
    wall_pts = np.stack([u.ravel(), v.ravel() + roof_px], axis=1).astype(np.float64)
    in_photo = cv2.perspectiveTransform(wall_pts[None], h_true)[0]
    back = cv2.perspectiveTransform(in_photo[None], rect.homography)[0]
    expected = np.stack([u.ravel() / 599 * (out_w - 1), v.ravel() / 399 * (out_h - 1)], axis=1)
    rms = float(np.sqrt(((back - expected) ** 2).sum(axis=1).mean()))
    assert rms <= 2.0
    assert (tmp_path / "debug_rectify.png").is_file() and json.loads((tmp_path / "rect.json").read_text())[
        "method"
    ] == "manual"


@pytest.fixture
def index(tmp_path):
    return PaletteIndex(import_nei(nei_dumps(tmp_path / "dumps")))


def test_region_colors_and_matching_from_a_photo(tmp_path, index):
    """A-M: known wall/window colors come back through warp + noise + vignette, and match the right blocks."""
    stone = (88, 88, 88)  # the fixture palette's Stone Bricks (cube icon)
    facade, _ = render_facade(ELEMENTS, wall=stone, window=(200, 200, 185), roof=(91, 91, 91))
    photo, corners, _ = photograph(facade, facade.shape[0] - 400, seed=5, noise=3.0)
    Image.fromarray(photo).save(tmp_path / "image.png")
    rect = rectify(tmp_path / "image.png", tmp_path, corners)
    spec = BuildSpec.model_validate({"facade": {"width_m": 12, "storeys": 2}, "elements": ELEMENTS,
                                     "materials": {"wall": {}, "roof": {}}})  # fmt: skip
    regions = region_colors(np.asarray(Image.open(rect.image)), spec)
    wall_rgb = lab_to_srgb(regions["wall"].lab)
    assert max(abs(a - b) for a, b in zip(wall_rgb, stone, strict=True)) <= 10  # vignette darkens edges a bit
    assert regions["window"].reliable and regions["door"].reliable
    notes = apply_materials(spec, regions, index)
    assert spec.materials["wall"].chosen == "minecraft:stonebrick"
    assert "minecraft:monster_egg@2" not in spec.materials["wall"].candidates  # infested: never offered
    assert any("roof" in n and "skipped" in n for n in notes)  # no roof region, no rgb hint


def test_lab_roundtrip():
    for rgb in [(0, 0, 0), (255, 255, 255), (150, 97, 83), (20, 200, 60)]:
        assert lab_to_srgb(tuple(float(v) for v in srgb_to_lab(np.array(rgb)))) == rgb
