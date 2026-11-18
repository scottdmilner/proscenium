"""proscenium_sync's lazy API names what its stub gives type checkers (packages/README.md#public-apis)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import proscenium_sync

PACKAGE = Path(proscenium_sync.__file__).parent


def _all(module_path: Path) -> list[str]:
    """The literal __all__ of a module, read without importing it."""
    for node in ast.parse(module_path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{module_path} has no __all__")


def _stub_names_by_unit() -> dict[str, set[str]]:
    """What __init__.pyi imports, by unit; a star import, the unit's __all__."""
    names_by_unit: dict[str, set[str]] = {}
    for node in ast.parse((PACKAGE / "__init__.pyi").read_text()).body:
        if isinstance(node, ast.ImportFrom):
            assert node.level == 1 and node.module is not None
            if [alias.name for alias in node.names] == ["*"]:
                names = _all(PACKAGE / node.module / "__init__.py")
            else:
                assert all(alias.asname == alias.name for alias in node.names), "a stub re-exports as X as X"
                names = [alias.name for alias in node.names]
            names_by_unit.setdefault(node.module, set()).update(names)
    return names_by_unit


def test_names_match_the_stub() -> None:
    # The module as it runs: the stub, which type checkers read instead, has neither the map nor __all__.
    module_globals = vars(proscenium_sync)
    names_by_unit = module_globals["_NAMES_BY_UNIT"]
    assert {unit: set(names) for unit, names in names_by_unit.items()} == _stub_names_by_unit()
    exported = module_globals["__all__"]
    assert exported == [name for names in names_by_unit.values() for name in names]
    assert len(set(exported)) == len(exported), "a name in two units"


def test_other_names_are_not_attributes() -> None:
    with pytest.raises(AttributeError, match="no attribute 'Missing'"):
        _ = proscenium_sync.Missing  # ty: ignore[unresolved-attribute]
    from proscenium_sync import planner  # a unit still imports as a submodule, past __getattr__

    assert planner.__name__ == "proscenium_sync.planner"
