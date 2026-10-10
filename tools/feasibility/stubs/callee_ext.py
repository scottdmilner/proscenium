"""Stands in for extension code in probe_exchange: a separately loaded module
that imports pxr itself and inspects a stage handed over by caller code."""

from typing import Any

from pxr import Sdf, Usd, UsdUtils


def inspect(stage: Any, root_id: str, cache_id: int) -> dict[str, bool]:
    found = UsdUtils.StageCache.Get().Find(Usd.StageCache.Id.FromLongInt(cache_id))
    return {
        "is_stage": isinstance(stage, Usd.Stage),
        "sees_unsaved_prim": bool(stage.GetPrimAtPath("/Extra")),
        "sees_session_prim": bool(stage.GetPrimAtPath("/SessionOnly")),
        "same_root_layer": Sdf.Layer.Find(root_id) == stage.GetRootLayer(),
        "cache_lookup_is_same_stage": found == stage,
    }
