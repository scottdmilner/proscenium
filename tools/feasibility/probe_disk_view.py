"""Probe 7: can a private disk view be built without touching shared layers?

See spec/source-access.md#file-backed-refresh. Each candidate must compose the
on-disk values (all 1.0) while the shared registry layers hold unsaved edits,
leave those shared layers untouched, and keep texture paths resolving to disk.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from _common import Probe
from _scenes import VALUES, build_layered, dirty_edit, layer_path, read_values

LAYER_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")
DISK = {name: (-1.0 if name == "var_a" else 1.0) for name in VALUES}


def run() -> dict[str, Any]:
    from pxr import Sdf

    p = Probe("disk_view")
    scene_dir, abs_dir = build_layered(p.tmp / "src")
    root = scene_dir / "root.usda"
    shared = [Sdf.Layer.FindOrOpen(str(layer_path(scene_dir, abs_dir, n))) for n in VALUES]
    for name in ("sub", "ref", "nested", "abs"):
        dirty_edit(Sdf.Layer.Find(str(layer_path(scene_dir, abs_dir, name))), name)
    snapshot = {lyr.identifier: (lyr.dirty, lyr.ExportToString()) for lyr in shared}

    candidates = {
        "copied scene dir": lambda: _relocated(root, p.tmp / "copy", symlink=False),
        "symlinked scene dir": lambda: _relocated(root, p.tmp / "link", symlink=True),
        "anonymous copies with remapped asset paths": lambda: _anonymous_view(root),
    }
    for label, build in candidates.items():
        built: dict[str, Any] = {}
        p.fact(f"{label}: opened", lambda b=build, d=built: d.setdefault("stage", b()) is not None)
        stage = built.get("stage")
        if not stage:
            continue
        p.fact(f"{label}: composed values", lambda s=stage: read_values(s))
        p.fact(f"{label}: matches disk", lambda s=stage: read_values(s) == DISK)
        p.fact(f"{label}: texture resolves to", lambda s=stage: _texture_target(s, scene_dir))
        p.check(
            f"{label}: shared layers untouched",
            lambda: {lyr.identifier: (lyr.dirty, lyr.ExportToString()) for lyr in shared} == snapshot,
        )
    if alab := os.environ.get("PROSCENIUM_ALAB_ROOT"):
        p.fact("alab: anonymous view vs normal open", lambda: _compare_alab(Path(alab) / "entry.usda", p.tmp))
    return p.result()


def _compare_alab(entry: Path, tmp: Path, rounds: int = 2) -> dict[str, Any]:
    """Production-scale check of the anonymous-copy candidate (clean layers).

    Each open runs in a fresh process, alternating normal and view, so neither
    benefits from the other's in-process layers. The OS file cache is not purged.
    """
    import json
    import subprocess
    import sys

    runs: dict[str, list[dict[str, Any]]] = {"normal": [], "view": []}
    for i in range(rounds):
        for mode in ("normal", "view"):
            out = tmp / f"alab-{mode}-{i}.json"
            subprocess.run(
                [sys.executable, str(Path(__file__).parent / "alab_open.py"), mode, str(entry), str(out)],
                check=True,
                capture_output=True,
            )
            runs[mode].append(json.loads(out.read_text()))
    normal, view = runs["normal"][0], runs["view"][0]
    a, b = view["inventory"], normal["inventory"]
    return {
        "layers_copied": view["layers"],
        "normal_used_layers": normal["layers"],
        "prims_view": len(a),
        "prims_normal": len(b),
        "identical_prim_paths_and_types": a == b,
        "first_differences": sorted(set(a.items()) ^ set(b.items()))[:10],
        "normal_open_seconds": [round(r["seconds"], 2) for r in runs["normal"]],
        "view_open_seconds": [round(r["seconds"], 2) for r in runs["view"]],
        "unresolved_assets": view["unresolved"][:20],
        "unresolved_count": len(view["unresolved"]),
    }


_UNRESOLVED: set[str] = set()


def _open(layer_or_path: Any) -> Any:
    from pxr import Usd

    with Usd.StageCacheContext(Usd.BlockStageCaches):
        return Usd.Stage.Open(layer_or_path, Usd.Stage.LoadAll)


def _relocated(root: Path, dest: Path, symlink: bool) -> Any:
    """Expose the scene dir under a new path so relative layers get new identities."""
    if symlink:
        os.symlink(root.parent, dest, target_is_directory=True)
    else:
        shutil.copytree(root.parent, dest)
    return _open(str(dest / root.name))


def _anonymous_view(root: Path) -> Any:
    """Re-read every layer from disk as an anonymous layer, rewiring layer asset
    paths to the anonymous copies and other asset paths to absolute disk paths."""
    from pxr import Ar, Sdf, UsdUtils

    resolver = Ar.GetResolver()
    copies: dict[str, Any] = {}

    def copy(path: str) -> Any:
        if path in copies:
            return copies[path]
        anon = Sdf.Layer.OpenAsAnonymous(path)
        copies[path] = anon
        anchor = Ar.ResolvedPath(path)

        def remap(asset: str) -> str:
            if not asset:
                return asset
            target = str(resolver.Resolve(resolver.CreateIdentifier(asset, anchor)))
            if not target:
                _UNRESOLVED.add(asset)  # leave as-is; reported by the ALab comparison
                return asset
            if target.lower().endswith(LAYER_EXTENSIONS):
                return copy(target).identifier
            return target

        UsdUtils.ModifyAssetPaths(anon, remap)
        return anon

    view_root = copy(str(root.resolve()))
    stage = _open(view_root)
    stage._proscenium_copies = copies  # noqa: SLF001 - keep anonymous layers alive
    return stage


def _texture_target(stage: Any, scene_dir: Path) -> str:
    """Where the relative texture asset path resolves: the source file, another existing file, or nothing."""
    value = stage.GetPrimAtPath("/World/Ref").GetAttribute("tex").Get()
    if not value or not value.resolvedPath:
        return "unresolved"
    resolved = Path(value.resolvedPath).resolve()
    if resolved == (scene_dir / "textures" / "tex.png").resolve():
        return "source file"
    return f"other existing file: {resolved}" if resolved.exists() else f"missing file: {resolved}"
