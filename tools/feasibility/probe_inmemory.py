"""Probe 5: in-memory source candidates (spec/source-access.md#in-memory-sources).

Candidate: a private stage per binding over the caller's root and session
layers, opened with the binding's payload policy, reproducing the caller's
population mask, muted layers, and interpolation.
"""

from __future__ import annotations

from typing import Any

from _common import Probe
from _scenes import build_layered, dirty_edit, layer_path, read_values


def run() -> dict[str, Any]:
    from pxr import Sdf, Usd

    p = Probe("inmemory")
    scene_dir, abs_dir = build_layered(p.tmp)
    caller = _caller_stage(scene_dir, abs_dir)
    before = _caller_state(caller)
    before_layers = {layer.identifier: layer.ExportToString() for layer in caller.GetUsedLayers()}

    private = {policy: _private_stage(caller, policy) for policy in ("load_none", "load_all")}
    none_vals = read_values(private["load_none"])
    all_vals = read_values(private["load_all"])
    p.check("private stage is a distinct stage", lambda: private["load_none"] != caller)
    p.check("private stage sees caller's unsaved layer edit", lambda: all_vals["ref"], expect=99.0)
    p.check("private stage sees caller's session-layer opinion", lambda: all_vals["root"], expect=5.0)
    p.check("load_none private stage leaves payload unloaded", lambda: none_vals["pay"], expect=None)
    p.check("load_all private stage loads payload", lambda: all_vals["pay"], expect=1.0)
    p.check("population mask reproduced", lambda: none_vals["abs"], expect=None)
    p.check("muted layer reproduced", lambda: all_vals["sub"], expect=None)
    p.check(
        "interpolation reproduced",
        lambda: private["load_all"].GetInterpolationType() == Usd.InterpolationTypeHeld,
    )
    p.check("caller stage settings unchanged", lambda: _caller_state(caller) == before)
    p.check(
        "caller layers not authored",
        lambda: {lyr.identifier: lyr.ExportToString() for lyr in caller.GetUsedLayers()} == before_layers,
    )
    p.fact("resolver context type", lambda: type(caller.GetPathResolverContext()).__name__)

    # Private stages share layers, so later caller edits are visible live.
    dirty_edit(Sdf.Layer.Find(str(layer_path(scene_dir, abs_dir, "ref"))), "ref", 7.0)
    p.fact("caller edit after open visible in private stage", lambda: read_values(private["load_all"])["ref"])

    # An active StageCacheContext could hand back the caller's own stage.
    cache = Usd.StageCache()
    cache.Insert(caller)
    with Usd.StageCacheContext(cache):
        p.fact("Open(root, session) inside a cache context returns caller stage", lambda: _open_like(caller) == caller)
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        p.check("Open inside BlockStageCaches returns a new stage", lambda: _open_like(caller) != caller)
    settings = {k: v for k, v in before.items() if k != "values"}
    p.check(
        "caller settings unchanged after cache-context opens",
        lambda: {k: v for k, v in _caller_state(caller).items() if k != "values"} == settings,
    )
    return p.result()


def _caller_stage(scene_dir: Any, abs_dir: Any) -> Any:
    """Caller stage with non-default settings and unsaved edits."""
    from pxr import Sdf, Usd

    mask = Usd.StagePopulationMask(["/World/Ref", "/World/Pay", "/World/Var"])
    stage = Usd.Stage.OpenMasked(str(scene_dir / "root.usda"), mask, Usd.Stage.LoadAll)
    dirty_edit(Sdf.Layer.Find(str(layer_path(scene_dir, abs_dir, "ref"))), "ref")
    stage.MuteLayer(Sdf.Layer.Find(str(layer_path(scene_dir, abs_dir, "sub"))).identifier)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.OverridePrim("/World").CreateAttribute("rootValue", Sdf.ValueTypeNames.Double).Set(5.0)
    stage.SetEditTarget(stage.GetSessionLayer())
    stage.SetInterpolationType(Usd.InterpolationTypeHeld)
    return stage


def _caller_state(stage: Any) -> dict[str, Any]:
    return {
        "load_set": sorted(str(x) for x in stage.GetLoadSet()),
        "mask": str(stage.GetPopulationMask()),
        "muted": sorted(stage.GetMutedLayers()),
        "edit_target": stage.GetEditTarget().GetLayer().identifier,
        "interpolation": str(stage.GetInterpolationType()),
        "values": read_values(stage),
    }


def _private_stage(caller: Any, policy: str) -> Any:
    from pxr import Usd

    load = Usd.Stage.LoadAll if policy == "load_all" else Usd.Stage.LoadNone
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        stage = Usd.Stage.OpenMasked(
            caller.GetRootLayer(),
            caller.GetSessionLayer(),
            caller.GetPathResolverContext(),
            caller.GetPopulationMask(),
            load,
        )
    stage.MuteAndUnmuteLayers(caller.GetMutedLayers(), [])
    stage.SetInterpolationType(caller.GetInterpolationType())
    return stage


def _open_like(caller: Any) -> Any:
    from pxr import Usd

    return Usd.Stage.Open(caller.GetRootLayer(), caller.GetSessionLayer(), Usd.Stage.LoadNone)
