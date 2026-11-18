"""proscenium_sync's lazy API is its units' names, which its stub gives type checkers (packages/README.md#public-apis).

Read without importing the units, which import bpy; tests/blender/test_sync_api.py loads them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import proscenium_sync

PACKAGE = Path(proscenium_sync.__file__).parent


def _all(unit: str) -> list[str]:
    """The literal __all__ of a unit, a package or a module, read without importing it."""
    module_path = PACKAGE / unit / "__init__.py"
    if not module_path.exists():
        module_path = PACKAGE / f"{unit}.py"
    for node in ast.parse(module_path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{module_path} has no __all__")


def _stub_star_imports() -> list[str]:
    """The units __init__.pyi star-imports; it imports nothing else."""
    units: list[str] = []
    for node in ast.parse((PACKAGE / "__init__.pyi").read_text()).body:
        if isinstance(node, ast.ImportFrom):
            assert node.level == 1 and node.module is not None
            assert [alias.name for alias in node.names] == ["*"], "the stub star-imports each unit's __all__"
            units.append(node.module)
    return units


def test_the_stub_imports_the_api_units() -> None:
    # The module as it runs: the stub, which type checkers read instead, has no _API_UNITS.
    assert _stub_star_imports() == list(vars(proscenium_sync)["_API_UNITS"])


def test_no_name_is_in_two_units() -> None:
    names = [name for unit in vars(proscenium_sync)["_API_UNITS"] for name in _all(unit)]
    assert len(set(names)) == len(names)


def test_a_unit_still_imports_as_a_submodule() -> None:
    # A from-import tries the name as an attribute first; tests/bpy_free/test_no_blender_imports.py checks that this
    # loads nothing else, in a fresh interpreter.
    from proscenium_sync import planner

    assert planner.__name__ == "proscenium_sync.planner"
