"""The synchronizer: the bindings, their synchronization and interaction, the API, and the planner.

Its public API is its own names: what bindings exports, and registration's register and unregister. Other packages
import nothing below it (README.md#import-rules). It imports without bpy, so the planner and the other bpy-free
units load without Blender: each name lazy loads its unit on first use, through the module __getattr__ (PEP 562).
"""

from __future__ import annotations

import importlib

# Each unit of the API and the names it gives: bindings' __all__, and registration's two functions. __init__.pyi gives
# type checkers the same names (tests/bpy_free/test_sync_api.py).
_NAMES_BY_UNIT = {
    "bindings": (
        "BINDINGS",
        "BindingHandle",
        "BindingNotFoundError",
        "BindingStatus",
        "Bindings",
        "PersistentSelection",
        "PickedEntity",
        "ReentrantCallError",
        "RequestedSettings",
        "Result",
        "ResultState",
        "SelectionEntry",
        "SelectionMode",
        "SelectionResolution",
        "SourceUnavailableError",
        "TargetSelection",
    ),
    "registration": ("register", "unregister"),
}
_UNIT_BY_NAME = {name: unit for unit, names in _NAMES_BY_UNIT.items() for name in names}

__all__ = list(_UNIT_BY_NAME)


def __getattr__(name: str) -> object:
    """An API name, loading its unit; Python calls this only for a name the module doesn't hold yet."""
    unit = _UNIT_BY_NAME.get(name)
    if unit is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{unit}"), name)
    globals()[name] = value  # so later uses don't call this again
    return value
