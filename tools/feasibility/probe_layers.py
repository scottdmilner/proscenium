"""Probe 6: dirty contributing layers, fresh (uncached) stages, and reloads.

See spec/source-access.md#file-backed-refresh.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from _common import Probe
from _scenes import build_layered, dirty_edit, layer_path, read_values, rewrite_on_disk


def run() -> dict[str, Any]:
    p = Probe("layers")
    _dirty_detection(p, p.tmp / "dirty")
    _fresh_stage(p, p.tmp / "fresh")
    _reload(p, p.tmp / "reload")
    return p.result()


def _open(root: Path, load_all: bool = True) -> Any:
    from pxr import Usd

    load = Usd.Stage.LoadAll if load_all else Usd.Stage.LoadNone
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        return Usd.Stage.Open(str(root), load)


def _names(layers: Any, scene_dir: Path, abs_dir: Path) -> list[str]:
    by_path = {
        str(layer_path(scene_dir, abs_dir, n).resolve()): n
        for n in ("root", "sub", "ref", "pay", "nested", "var_a", "var_b", "abs")
    }
    return sorted(by_path.get(str(Path(lyr.realPath).resolve()), lyr.identifier) for lyr in layers if lyr.realPath)


def _dirty_detection(p: Probe, dest: Path) -> None:
    from pxr import Sdf

    scene_dir, abs_dir = build_layered(dest)
    root = scene_dir / "root.usda"
    stage = _open(root)
    p.check(
        "used layers include layer-stack and arc-introduced layers",
        lambda: _names(stage.GetUsedLayers(), scene_dir, abs_dir),
        expect=["abs", "nested", "pay", "ref", "root", "sub", "var_b"],
    )
    for name in ("sub", "ref", "nested"):
        dirty_edit(Sdf.Layer.Find(str(layer_path(scene_dir, abs_dir, name))), name)

    def dirty(s: Any) -> list[str]:
        return _names([lyr for lyr in s.GetUsedLayers() if lyr.dirty and not lyr.anonymous], scene_dir, abs_dir)

    p.check("dirty contributing layers detected (load all)", lambda: dirty(stage), expect=["nested", "ref", "sub"])
    p.fact("dirty layers detected under load none", lambda: dirty(_open(root, load_all=False)))
    p.fact("session layer is anonymous and dirty", lambda: [stage.GetSessionLayer().anonymous, stage.GetSessionLayer().dirty])
    p.fact(
        "fresh stage over dirty registry layers composes in-process values",
        lambda: read_values(_open(root)),
    )


def _fresh_stage(p: Probe, dest: Path) -> None:
    from pxr import Usd, UsdUtils

    scene_dir, _ = build_layered(dest)
    root = str(scene_dir / "root.usda")
    global_cache = UsdUtils.StageCache.Get()
    with Usd.StageCacheContext(global_cache):
        cached = Usd.Stage.Open(root)
    try:
        p.check("Open outside any cache context returns a new stage", lambda: Usd.Stage.Open(root) != cached)
        with Usd.StageCacheContext(global_cache):
            p.fact("Open inside the global cache context reuses the cached stage", lambda: Usd.Stage.Open(root) == cached)
            with Usd.StageCacheContext(Usd.BlockStageCaches):
                p.check("BlockStageCaches inside a cache context gives a new stage", lambda: Usd.Stage.Open(root) != cached)
        p.check("fresh stages share the root layer object", lambda: _open(Path(root)).GetRootLayer() == cached.GetRootLayer())
    finally:
        global_cache.Erase(cached)


def _reload(p: Probe, dest: Path) -> None:
    from pxr import Sdf

    scene_dir, abs_dir = build_layered(dest)
    root = scene_dir / "root.usda"
    other = _open(root)  # another tool's stage over the same layers
    refresh = _open(root)
    sub_path = layer_path(scene_dir, abs_dir, "sub")
    rewrite_on_disk(sub_path, "sub", 2.0)
    clean = [lyr for lyr in refresh.GetUsedLayers() if not lyr.dirty and not lyr.anonymous]
    p.check(
        "non-forced Reload of all clean layers reloads only the changed one",
        lambda: _names([lyr for lyr in clean if lyr.Reload()], scene_dir, abs_dir),
        expect=["sub"],
    )
    p.check("refresh stage sees disk change after reload", lambda: read_values(refresh)["sub"], expect=2.0)
    p.check("other stage sharing the layer also sees it", lambda: read_values(other)["sub"], expect=2.0)

    # Immediate second rewrite: does a non-forced Reload notice it (mtime granularity)?
    rewrite_on_disk(sub_path, "sub", 3.0)
    sub = Sdf.Layer.Find(str(sub_path))
    sub.Reload()
    p.fact("non-forced Reload sees an immediate second rewrite", lambda: read_values(refresh)["sub"] == 3.0)

    # Rewrite but restore the old mtime, so only a forced Reload should notice.
    # Pin the mtime to whole seconds first: Blender's bundled Python truncates
    # os.utime to microseconds, so an arbitrary ns mtime cannot be restored exactly.
    pinned = (sub_path.stat().st_mtime_ns // 1_000_000_000 - 10) * 1_000_000_000
    os.utime(sub_path, ns=(pinned, pinned))
    sub.Reload(force=True)
    rewrite_on_disk(sub_path, "sub", 4.0)
    os.utime(sub_path, ns=(pinned, pinned))
    sub.Reload()
    p.check(
        "non-forced Reload skips a rewrite with unchanged mtime",
        lambda: read_values(refresh)["sub"],
        expect=3.0,
    )
    sub.Reload(force=True)
    p.check("forced Reload rereads despite unchanged mtime", lambda: read_values(refresh)["sub"], expect=4.0)

    ref = Sdf.Layer.Find(str(layer_path(scene_dir, abs_dir, "ref")))
    dirty_edit(ref, "ref")
    ref.Reload()
    p.fact("Reload on a dirty layer discards unsaved edits", lambda: read_values(other)["ref"] == 1.0)
