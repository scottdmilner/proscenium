"""Set up the USD situations that source access must handle (docs/spec/source-access.md).

A binding reads its source from a file or from a caller's stage, in a process
where other tools hold stages and layers too. These generators reproduce the
hazards the spec names, so tests can check a binding reads the right content
and leaves everyone else's state alone:

- dirty_layer (F-DIRTY-LAYER): contributing layers with unsaved in-process edits,
  a dirty layer that does not contribute, and a layer changed on disk.
  File-Backed Refresh.
- private_stage (F-PRIVATE-STAGE): a caller's stage whose load set, mask, muting,
  edit target, interpolation, and variant selection all differ from the
  defaults. In-Memory Sources.
- cached_stage (F-CACHED-STAGE): a stage for the same file sitting in a stage
  cache with an active cache context. File-Backed Refresh.

Each returns the values a correct binding would read, derived from how the scene
is built. M1 provides the generators; M3, which owns these fixtures, adds the
synchronization cases that run against them. All three copy Scene.SOURCE_ACCESS
(see its root.usda) into the given directory.

Each generator is a context manager: entering builds the fixture, and leaving
releases the stages and cache entries it created, so the edited layers are
freed and later tests start clean.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Sdf, Usd, UsdUtils

from support.usd import open_fresh

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# Value name -> (composed prim path, attribute). Every authored value is 1 on disk.
VALUES: dict[str, tuple[str, str]] = {
    "root": ("/World", "rootValue"),
    "sub": ("/World", "subValue"),
    "extra": ("/World", "extraValue"),
    "ref": ("/World/Ref", "refValue"),
    "payA": ("/World/PayA", "payValue"),
    "payB": ("/World/PayB", "payValue"),
    "outside": ("/World/Outside", "outsideValue"),
    "varA": ("/World/Var", "varAValue"),  # present while variant "a" is selected
    "varB": ("/World/Var", "varBValue"),  # present while variant "b" is selected
    "unsaved": ("/World", "unsavedValue"),  # authored only in memory, by F-PRIVATE-STAGE
}

# What a load-all stage composes from the files as copied, with no edits anywhere.
# The file selects variant "a", so variant "b"'s value is absent.
DISK: dict[str, float | None] = {name: 1.0 for name in VALUES} | {"varB": None, "unsaved": None}

# Layer file -> the prim path and attribute its value is authored on, inside that layer.
_LAYER_PRIM = {"root": "/World", "sub": "/World", "extra": "/World"} | dict.fromkeys(
    ("ref", "pay", "var_a", "var_b"), "/Asset"
)
_LAYER_ATTR = {
    "root": "rootValue",
    "sub": "subValue",
    "extra": "extraValue",
    "ref": "refValue",
    "pay": "payValue",
    "var_a": "varAValue",
    "var_b": "varBValue",
}


DEFAULT_TIME = Usd.TimeCode.Default()


def read_values(stage: Usd.Stage, time: float | Usd.TimeCode = DEFAULT_TIME) -> dict[str, float | None]:
    """The composed value of each entry in VALUES; None where the prim or opinion is absent."""
    out: dict[str, float | None] = {}
    for name, (prim_path, attr) in VALUES.items():
        prim = stage.GetPrimAtPath(prim_path)
        out[name] = prim.GetAttribute(attr).Get(time) if prim and prim.HasAttribute(attr) else None
    return out


def _layer_file(scene: Path, layer: str) -> Path:
    return scene / f"{layer}.usda"


def _set_layer_value(layer: Sdf.Layer, name: str, value: float) -> None:
    path = Sdf.Path(_LAYER_PRIM[name]).AppendProperty(_LAYER_ATTR[name])
    layer.GetAttributeAtPath(path).default = value


def rewrite_on_disk(scene: Path, layer: str, value: float) -> None:
    """Change a layer file's value without touching the opened (shared) layer.

    The modification time moves forward by 2 s, so a non-forced Reload(), which
    goes by modification time (runtime-record.md#dirty-layers-and-fresh-stages),
    sees the change on any filesystem.
    """
    path = _layer_file(scene, layer)
    mtime_ns = path.stat().st_mtime_ns
    copy = Sdf.Layer.OpenAsAnonymous(str(path))
    _set_layer_value(copy, layer, value)
    copy.Export(str(path))
    os.utime(path, ns=(mtime_ns + 2_000_000_000, mtime_ns + 2_000_000_000))


@dataclass
class DirtyLayerScene:
    root: Path
    caller: Usd.Stage  # another tool's stage; it keeps the edited layers open
    dirty_contributing: dict[str, Path]  # contributing layers (load-all) with unsaved in-process edits
    dirty_not_contributing: dict[str, Path]  # layers with unsaved edits that the stage does not compose
    changed_on_disk: dict[str, Path]  # clean layers whose file changed after they were opened
    disk_values: dict[str, float | None]  # composed from the files on disk, load-all
    in_process_values: dict[str, float | None]  # what `caller` composes, before any reload


@contextmanager
def dirty_layer(dest: Path) -> Generator[DirtyLayerScene]:
    """F-DIRTY-LAYER: unsaved edits in contributing and non-contributing layers; a sublayer changed on disk.

    The contributing dirty layers arrive through a reference, a payload (which
    contributes only when loaded), and the selected variant. The layer of the
    unselected variant is also dirty, but does not contribute.
    """
    scene = copy_scene(Scene.SOURCE_ACCESS, dest)
    caller = open_fresh(scene / "root.usda")
    contributing = {name: _layer_file(scene, name) for name in ("ref", "pay", "var_a")}
    # Opened directly, as another tool might: the caller's stage never loads it.
    not_contributing = {"var_b": _layer_file(scene, "var_b")}
    held = [Sdf.Layer.FindOrOpen(str(path)) for path in not_contributing.values()]
    for name, path in (contributing | not_contributing).items():
        _set_layer_value(Sdf.Layer.Find(str(path)), name, 99.0)
    rewrite_on_disk(scene, "sub", 2.0)
    yield DirtyLayerScene(
        root=scene / "root.usda",
        caller=caller,
        dirty_contributing=contributing,
        dirty_not_contributing=not_contributing,
        changed_on_disk={"sub": _layer_file(scene, "sub")},
        disk_values=DISK | {"sub": 2.0},
        in_process_values=DISK | {"ref": 99.0, "payA": 99.0, "payB": 99.0, "varA": 99.0},
    )
    del held  # released with the caller's stage when the fixture exits


@dataclass
class PrivateStageScene:
    root: Path
    caller: Usd.Stage  # the caller's in-memory stage, with non-default settings
    settings: dict[str, object]  # caller_settings(caller) at build time; a binding must not change it
    layers: dict[str, str]  # layer_contents(caller) at build time; a binding must not author to them
    caller_values: dict[str, float | None]  # what the caller's stage composes
    caller_anim_at_5: float  # animValue at time 5 under the caller's held interpolation


def caller_settings(stage: Usd.Stage) -> dict[str, object]:
    """Stage-level state that In-Memory Sources forbids a binding to change."""
    return {
        "load_set": sorted(str(p) for p in stage.GetLoadSet()),
        "population_mask": str(stage.GetPopulationMask()),
        "muted_layers": sorted(stage.GetMutedLayers()),
        "edit_target": stage.GetEditTarget().GetLayer().identifier,
        "interpolation": str(stage.GetInterpolationType()),
        "session_layer": stage.GetSessionLayer().ExportToString(),
    }


def layer_contents(stage: Usd.Stage) -> dict[str, str]:
    """Current contents of every layer the stage uses, saved or not, by identifier."""
    return {layer.identifier: layer.ExportToString() for layer in stage.GetUsedLayers()}


@contextmanager
def private_stage(dest: Path) -> Generator[PrivateStageScene]:
    """F-PRIVATE-STAGE: a caller stage whose settings all differ from Usd.Stage.Open's defaults.

    Only /World/PayA's payload is loaded; /World/Outside is outside the
    population mask; extra.usda is muted; the edit target is sub.usda;
    interpolation is held; the session layer overrides rootValue and selects
    variant "b"; and the root layer has an unsaved edit.
    """
    scene = copy_scene(Scene.SOURCE_ACCESS, dest)
    root = scene / "root.usda"
    mask = Usd.StagePopulationMask(["/World/Ref", "/World/PayA", "/World/PayB", "/World/Var"])
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        caller = Usd.Stage.OpenMasked(str(root), mask, Usd.Stage.LoadNone)
    caller.Load("/World/PayA")
    caller.MuteLayer(str(_layer_file(scene, "extra")))
    caller.SetInterpolationType(Usd.InterpolationTypeHeld)
    with Usd.EditContext(caller, caller.GetSessionLayer()):
        caller.GetPrimAtPath("/World").GetAttribute("rootValue").Set(5.0)
        caller.GetPrimAtPath("/World/Var").GetVariantSet("option").SetVariantSelection("b")
    world = caller.GetRootLayer().GetPrimAtPath("/World")
    Sdf.AttributeSpec(world, "unsavedValue", Sdf.ValueTypeNames.Double).default = 7.0
    caller.SetEditTarget(Usd.EditTarget(Sdf.Layer.Find(str(_layer_file(scene, "sub")))))
    yield PrivateStageScene(
        root=root,
        caller=caller,
        settings=caller_settings(caller),
        layers=layer_contents(caller),
        caller_values=DISK
        | {"root": 5.0, "extra": None, "payB": None, "outside": None, "varA": None, "varB": 1.0, "unsaved": 7.0},
        caller_anim_at_5=0.0,
    )


@dataclass
class CachedStageScene:
    root: Path
    ambient: Usd.Stage  # cached stage for the same root, with non-default state
    cache_id: Usd.StageCache.Id  # its UsdUtils.StageCache id
    ambient_values: dict[str, float | None]  # what the ambient stage composes
    disk_values: dict[str, float | None]  # what an uncontaminated load-all stage composes


@contextmanager
def cached_stage(dest: Path) -> Generator[CachedStageScene]:
    """F-CACHED-STAGE: a stage for the same root sits in UsdUtils.StageCache, and its context is active.

    The ambient stage has payloads unloaded, extra.usda muted, and session
    opinions overriding rootValue and selecting variant "b". While the fixture
    is active, a plain Usd.Stage.Open(root) returns the ambient stage.
    """
    scene = copy_scene(Scene.SOURCE_ACCESS, dest)
    root = scene / "root.usda"
    ambient = open_fresh(root, Usd.Stage.LoadNone)
    ambient.MuteLayer(str(_layer_file(scene, "extra")))
    with Usd.EditContext(ambient, ambient.GetSessionLayer()):
        ambient.GetPrimAtPath("/World").GetAttribute("rootValue").Set(5.0)
        ambient.GetPrimAtPath("/World/Var").GetVariantSet("option").SetVariantSelection("b")
    cache = UsdUtils.StageCache.Get()
    cache_id = cache.Insert(ambient)
    try:
        with Usd.StageCacheContext(cache):
            yield CachedStageScene(
                root=root,
                ambient=ambient,
                cache_id=cache_id,
                ambient_values=DISK
                | {"root": 5.0, "extra": None, "payA": None, "payB": None, "varA": None, "varB": 1.0},
                disk_values=dict(DISK),
            )
    finally:
        cache.Erase(cache_id)
