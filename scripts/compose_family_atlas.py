#!/usr/bin/env python3
"""Compose the completed family sprite runs into one deterministic atlas.

Each source run is generated/extracted by sprite-gen. This final packer does
not redraw, resize, or infer frames from alpha; it only copies extracted frame
cells into a single atlas and writes the runtime rectangle manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


CELL_W = 64
CELL_H = 96
DEFAULT_FPS = 8


def all_runs(folder: Path) -> list[Path]:
    if (folder / "sprite-request.json").exists():
        return [folder]
    direct_runs = [p for p in folder.iterdir() if p.is_dir() and (p / "sprite-request.json").exists()]
    if direct_runs:
        return sorted(direct_runs, key=lambda p: p.stat().st_mtime)
    runs = [p for p in folder.glob("run-*") if p.is_dir() and (p / "sprite-request.json").exists()]
    if not runs:
        raise FileNotFoundError(f"no sprite-gen run in {folder}")
    return sorted(runs, key=lambda p: p.stat().st_mtime)


def state_frames(run: Path, state: str) -> list[Path]:
    def clean(paths: list[Path]) -> list[Path]:
        return [p for p in paths if p.stem.rsplit("-", 1)[-1].isdigit()]

    direct = run / "frames" / state
    if direct.is_dir():
        frames = clean(sorted(direct.glob("frame-*.png")))
        if frames:
            return frames
    matches = clean(sorted((run / "frames").rglob("frame-*.png")))
    matches = [p for p in matches if state in p.parts]
    if matches:
        return matches
    raise FileNotFoundError(f"no extracted frames for {state} in {run}")


def request(run: Path) -> dict:
    for name in ("sprite-request.json", "request-single.json", "request-input.json", "request-authoring.json", "maid-request.json"):
        p = run / name
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError(f"request missing in {run}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--characters-root", type=Path, default=Path("assets/main/characters"))
    parser.add_argument("--interactions-root", type=Path, default=Path("assets/main/interactions"))
    parser.add_argument("--out-dir", type=Path, default=Path("assets/main/atlas"))
    args = parser.parse_args()

    sources: list[tuple[str, list[Path]]] = []
    for folder in sorted(args.characters_root.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        try:
            sources.append((folder.name, all_runs(folder)))
        except FileNotFoundError:
            continue
    if args.interactions_root.exists():
        try:
            sources.append(("interactions", all_runs(args.interactions_root)))
        except FileNotFoundError:
            pass
    if not sources:
        raise SystemExit("no completed runs found")

    rows: list[tuple[str, str, list[Path], int, bool, str]] = []
    used_runs: dict[str, set[str]] = {}
    for slug, runs in sources:
        # New correction runs may contain only one repaired state. Select the
        # newest available run per state, while retaining the older run's
        # complete set of other states.
        states: dict[str, tuple[Path, dict]] = {}
        for run in runs:
            req = request(run)
            for state, spec in req.get("states", {}).items():
                states[state] = (run, spec)
        for state, (run, spec) in sorted(states.items()):
            frames = state_frames(run, state)
            expected = int(spec.get("frames", len(frames)))
            if len(frames) != expected:
                raise SystemExit(f"{run}: {state}: expected {expected} frames, found {len(frames)}")
            rows.append((slug, state, frames, int(spec.get("fps", DEFAULT_FPS)), bool(spec.get("loop", True)), str(run)))
            used_runs.setdefault(slug, set()).add(str(run))

    cols = max(len(frames) for _, _, frames, *_ in rows)
    atlas_w = cols * CELL_W
    atlas_h = len(rows) * CELL_H
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    manifest = {
        "version": 1,
        "kind": "sprite-gen-family-atlas",
        "engine": "component-row",
        "game_input": "family-sprite-atlas.png",
        "degraded_static_fallback": False,
        "cell": {"width": CELL_W, "height": CELL_H},
        "atlas": {"width": atlas_w, "height": atlas_h, "columns": cols, "rows": len(rows)},
        "coordinate_system": "top-left origin; x right; y down",
        "animation": {"rows": {}},
        "frame_layout": {"rows": {}},
        "source_runs": {},
    }

    for row_index, (slug, state, frames, fps, loop, run) in enumerate(rows):
        name = f"{slug}__{state}"
        rects = []
        for i, frame_path in enumerate(frames):
            frame = Image.open(frame_path).convert("RGBA")
            if frame.size != (CELL_W, CELL_H):
                raise SystemExit(f"{frame_path}: expected {(CELL_W, CELL_H)}, got {frame.size}")
            x, y = i * CELL_W, row_index * CELL_H
            atlas.alpha_composite(frame, (x, y))
            rects.append({"x": x, "y": y, "w": CELL_W, "h": CELL_H, "source_frame": str(frame_path)})
        manifest["animation"]["rows"][name] = {"frames": len(frames), "fps": fps, "durations_ms": [round(1000 / fps)] * len(frames), "loop": loop}
        manifest["frame_layout"]["rows"][name] = rects
        manifest["source_runs"].setdefault(slug, {"run": run, "states": []})["states"].append(state)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    atlas_path = args.out_dir / "family-sprite-atlas.png"
    atlas.save(atlas_path)
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    report = {
        "ok": True,
        "engine": "component-row",
        "atlas": str(atlas_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "frames": sum(len(frames) for _, _, frames, *_ in rows),
        "cell": [CELL_W, CELL_H],
        "resampled": False,
        "source_runs": sorted(path for paths in used_runs.values() for path in paths),
    }
    (args.out_dir / "family-atlas.report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
