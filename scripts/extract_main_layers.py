#!/usr/bin/env python3
"""Extract Unity-ready transparent layers from assets/main.png.

The source is preserved byte-for-byte. This script only creates cropped RGBA
derivatives and a layout manifest describing their placement on the 1672x941
canvas. UI silhouettes use conservative polygon masks so rounded cards and
decorative tabs are retained while the surrounding scene becomes transparent.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "main.png"
OUT = ROOT / "assets" / "main"
CANVAS = (1672, 941)


def polygon_mask(size: tuple[int, int], points: list[tuple[int, int]]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def rounded_mask(size: tuple[int, int], radius: int = 24) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def save_layer(src: Image.Image, name: str, bbox: tuple[int, int, int, int], mask_kind: str = "rounded", points=None, radius=24):
    x0, y0, x1, y1 = bbox
    crop = src.crop(bbox).convert("RGBA")
    if mask_kind == "rounded":
        mask = rounded_mask(crop.size, radius)
    elif mask_kind == "polygon":
        mask = polygon_mask(crop.size, points)
    elif mask_kind == "full":
        mask = Image.new("L", crop.size, 255)
    else:
        raise ValueError(mask_kind)
    crop.putalpha(mask)
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(path)
    return {"file": str(path.relative_to(ROOT)), "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0, "pivot": [0.5, 0.5]}


def clear_rects(canvas: Image.Image, rects: list[tuple[int, int, int, int]]) -> Image.Image:
    layer = canvas.convert("RGBA")
    alpha = Image.new("L", layer.size, 255)
    draw = ImageDraw.Draw(alpha)
    for rect in rects:
        draw.rectangle(rect, fill=0)
    layer.putalpha(alpha)
    return layer


def main() -> None:
    src = Image.open(SOURCE).convert("RGB")
    if src.size != CANVAS:
        raise SystemExit(f"expected {CANVAS}, got {src.size}")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "source": "assets/main.png",
        "canvas": {"width": CANVAS[0], "height": CANVAS[1], "units": "pixels"},
        "coordinate_system": "top-left origin; x right; y down",
        "unity_import": {"texture_type": "Sprite (2D and UI)", "sprite_mode": "Single", "pixels_per_unit": 100, "filter_mode": "Point", "compression": "None", "mip_maps": False},
        "layers": {},
        "references": {},
    }

    # The visible world is retained at native resolution with UI occluders made transparent.
    # Occluders are intentionally slightly generous so no UI pixels leak into the scene layer.
    occluders = [
        (0, 0, 490, 270), (0, 245, 325, 690), (850, 0, 1440, 110),
        (1410, 0, 1672, 260), (1450, 235, 1672, 930), (220, 665, 1460, 941),
        (0, 700, 260, 941),
    ]
    world = clear_rects(src, occluders)
    world_path = OUT / "background" / "scene-visible.png"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world.save(world_path)
    manifest["layers"]["background_scene"] = {"file": str(world_path.relative_to(ROOT)), "x": 0, "y": 0, "width": CANVAS[0], "height": CANVAS[1], "pivot": [0.5, 0.5], "notes": "Visible scene pixels only; source UI occlusion is transparent because hidden pixels cannot be reconstructed from a flattened PNG."}

    # A clean central scene crop for Unity placement when the full-canvas layer is not needed.
    # Use the occluded world layer here as well; this prevents status/calendar
    # fragments at the crop edges from being mistaken for scene art.
    scene = save_layer(world, "background/house-and-garden.png", (306, 78, 1460, 688), "full")
    manifest["layers"]["background_house_garden"] = scene

    # Source identity crops used as references for the generated modular base sprites.
    refs = {
        "father": (274, 681, 445, 865),
        "mother": (568, 682, 742, 868),
        "older_daughter": (861, 683, 1035, 867),
        "younger_son": (1165, 682, 1344, 870),
        "corgi": (14, 730, 231, 906),
    }
    for key, bbox in refs.items():
        ref = save_layer(src, f"references/{key}-portrait-source.png", bbox, "full")
        manifest["references"][key] = ref

    # High-level UI cards and navigational controls.
    cards = {
        "ui/status-panel.png": ((0, 14, 480, 270), "polygon", [(20, 0), (450, 0), (480, 24), (480, 244), (443, 256), (18, 256), (0, 236), (0, 22)]),
        "ui/resources-bar.png": ((868, 7, 1426, 102), "rounded", None),
        "ui/tasks-card.png": ((15, 259, 319, 681), "polygon", [(42, 0), (279, 0), (304, 24), (304, 386), (274, 421), (42, 421), (0, 389), (0, 30)]),
        "ui/calendar-card.png": ((1421, 35, 1665, 244), "rounded", None),
        "ui/nav-backpack.png": ((1480, 255, 1666, 410), "rounded", None),
        "ui/nav-shop.png": ((1475, 416, 1668, 562), "rounded", None),
        "ui/nav-journal.png": ((1478, 579, 1668, 718), "rounded", None),
        "ui/nav-settings.png": ((1480, 735, 1669, 912), "rounded", None),
        "ui/family-card-father.png": ((254, 676, 549, 928), "rounded", 28),
        "ui/family-card-mother.png": ((551, 676, 841, 929), "rounded", 28),
        "ui/family-card-older-daughter.png": ((846, 676, 1142, 929), "rounded", 28),
        "ui/family-card-younger-son.png": ((1147, 676, 1448, 929), "rounded", 28),
        "ui/pet-mascot.png": ((10, 728, 235, 908), "rounded", 30),
        "ui/family-ribbon.png": ((0, 844, 244, 941), "polygon", [(0, 20), (219, 20), (244, 48), (225, 95), (0, 95)]),
    }
    for name, spec in cards.items():
        bbox, kind, extra = spec
        if kind == "polygon":
            layer = save_layer(src, name, bbox, kind, extra)
        elif name.startswith("ui/family-card"):
            layer = save_layer(src, name, bbox, kind, radius=extra)
        else:
            layer = save_layer(src, name, bbox, kind)
        manifest["layers"][Path(name).stem] = layer

    # Retain the flattened source as an explicitly named reference for any later re-cutting.
    source_copy = OUT / "source-main.png"
    src.save(source_copy)
    manifest["source_copy"] = str(source_copy.relative_to(ROOT))

    (OUT / "main-layers.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
