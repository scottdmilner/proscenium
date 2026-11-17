"""The compiled core. Must not import bpy (enforced by tests/bpy_free).

The compiled module, _core, links Blender's usd_ms without embedding a path to it, so it loads only
into a process that already has that library. Its names are the package's; the module itself is the package's own.
"""

# Importing pxr.Usd loads Blender's usd_ms, which only processes without bpy (such as tests/bpy_free) lack, and
# registers the Python converters for USD types that _core's arguments use, which any process may lack.
from pxr import Usd  # noqa: F401

from ._core import (
    BatchGroup,
    Correspondence,
    CorrespondenceEntry,
    Diagnostic,
    GeometryDescription,
    Partition,
    Plan,
    PlanDiff,
    PlannedResource,
    PlanningContext,
    PlanSettings,
    SceneIndexChain,
    Snapshot,
    SourceEntity,
    SourceSelection,
    SourceUnavailableError,
    StageHandle,
    diagnostic_codes,
    diff_plans,
    plan,
    usd_version,
)

__all__ = [
    "BatchGroup",
    "Correspondence",
    "CorrespondenceEntry",
    "Diagnostic",
    "GeometryDescription",
    "Partition",
    "Plan",
    "PlanDiff",
    "PlanSettings",
    "PlannedResource",
    "PlanningContext",
    "SceneIndexChain",
    "Snapshot",
    "SourceEntity",
    "SourceSelection",
    "SourceUnavailableError",
    "StageHandle",
    "diagnostic_codes",
    "diff_plans",
    "plan",
    "usd_version",
]
