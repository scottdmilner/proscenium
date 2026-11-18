"""The synchronizer: the bindings, their synchronization and interaction, the API, and the planner.

Its public API is its own names: what bindings exports, and registration's register and unregister. Other packages
import nothing below it (README.md#import-rules). It imports without bpy, so the planner and the other bpy-free
units load without Blender: the API's units load on first use of a name, through the module __getattr__ (PEP 562).
"""

from __future__ import annotations

import importlib
import importlib.util

# The API's units, whose __all__ lists are its names. __init__.pyi star-imports the same units for type checkers
# (tests/bpy_free/test_sync_api.py).
_API_UNITS = ("bindings", "registration")


def __getattr__(name: str) -> object:
    """An API name, or __all__, loading the API's units; Python calls this only for a name the module doesn't hold."""
    # A dunder a tool probes for (__wrapped__, __path__), and a unit a from-import tries as an attribute before it
    # imports the unit, load nothing: neither may import bpy.
    if (name.startswith("__") and name != "__all__") or importlib.util.find_spec(f"{__name__}.{name}") is not None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    unit_modules = [importlib.import_module(f"{__name__}.{unit}") for unit in _API_UNITS]
    if name == "__all__":
        value: object = [unit_name for unit_module in unit_modules for unit_name in unit_module.__all__]
    else:
        unit_module = next((unit_module for unit_module in unit_modules if name in unit_module.__all__), None)
        if unit_module is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(unit_module, name)
    globals()[name] = value  # so later uses don't call this again
    return value
