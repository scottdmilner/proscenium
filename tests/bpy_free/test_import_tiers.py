"""Each package imports only what its row allows; in binding, a tier imports only the tier below it.

See docs/plans/source-tiers-and-names.md#tiers and AGENTS.md#layout.

Imports are read from each module's source with ast, without importing it, so type-only imports count too.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import sys
from pathlib import Path

import proscenium

from .bpy_blocker import is_blender_origin

PACKAGE = Path(proscenium.__file__).parent

# What each package, and each bpy-free package or module, may import from proscenium, keyed by the unit's name under
# proscenium: the bindings' code's units are binding's subpackages and results module. Other modules at the
# package's top level, such as addon, may import any.
BELOW_TIERS = {"core", "binding.source_access", "binding.results"}
ALLOWED = {
    "core": {"core"},
    "binding": set(),  # binding/__init__.py imports none of its units
    "binding.source_access": {"binding.source_access"},
    "binding.results": {"binding.results"},
    "binding.persistence": {"binding.persistence", *BELOW_TIERS},
    "binding.runtime": {"binding.runtime", "binding.persistence", *BELOW_TIERS},
    "api": {"api", "binding.runtime", "binding.persistence", *BELOW_TIERS},
}


def _unit(parts: list[str] | tuple[str, ...]) -> str:
    """The unit a module belongs to, from its name's parts under proscenium."""
    return ".".join(parts[:2]) if parts[0] == "binding" and len(parts) > 1 else parts[0]


def _module_name(path: Path) -> list[str]:
    parts = ["proscenium", *path.relative_to(PACKAGE).with_suffix("").parts]
    return parts[:-1] if parts[-1] == "__init__" else parts


def _imported(path: Path) -> list[tuple[int, str]]:
    """The proscenium modules path imports, with their line numbers, relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module[:-1]
    return _imports_in(ast.parse(path.read_text(), str(path)), package)


def _submodule(target: str, name: str) -> str:
    """target.name if that is a module of proscenium, else target."""
    path = PACKAGE.parent.joinpath(*target.split("."), name)
    return f"{target}.{name}" if path.with_suffix(".py").is_file() or (path / "__init__.py").is_file() else target


def _imports_in(tree: ast.Module, package: list[str]) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            target = ".".join([*base, *([node.module] if node.module else [])])
            # "from package import x" imports the module x when there is one, and else a name from package
            found += [(node.lineno, _submodule(target, alias.name)) for alias in node.names]
    return [(line, name) for line, name in found if name.split(".")[0] == "proscenium"]


def _violations(path: Path, tier: str) -> list[str]:
    return [
        f"{path.relative_to(PACKAGE)}:{line} imports {name}" for line, name in _imported(path) if _crosses(name, tier)
    ]


def _crosses(name: str, tier: str) -> bool:
    parts = name.split(".")[1:]
    return bool(parts) and _unit(parts) not in ALLOWED[tier]


def _tier(path: Path) -> str | None:
    parts = path.relative_to(PACKAGE).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return unit if parts and (unit := _unit(parts)) in ALLOWED else None


def test_tiers_import_only_below() -> None:
    found = [v for path in sorted(PACKAGE.rglob("*.py")) if (tier := _tier(path)) for v in _violations(path, tier)]
    assert not found, "\n".join(found)


def test_every_module_is_in_a_tier_or_at_the_top() -> None:
    # A new subpackage gets a row in ALLOWED, so the test above checks it.
    stray = [p for p in PACKAGE.rglob("*.py") if len(p.relative_to(PACKAGE).parts) > 1 and _tier(p) is None]
    assert not stray, stray


# The tiers in binding; outside its own tier, a tier's modules are reached only through its package.
BINDING_TIERS = {"binding.runtime", "binding.persistence"}
# The modules that may reach a tier's module anyway, and which. The manifests aren't persistence's API until M5 calls
# the ownership index, which reads and writes them, and the state holds them for it (persistence/__init__.py).
REACH_EXCEPTIONS = {
    Path("binding/runtime/ownership_index.py"): {"proscenium.binding.persistence.manifests"},
    Path("binding/runtime/state.py"): {"proscenium.binding.persistence.manifests"},
}


def _reached_inside(path: Path, imports: list[tuple[int, str]]) -> list[str]:
    """Of path's imports, those of the modules inside a unit of binding where only its package may be used.

    Code outside binding uses each unit's package, and code in binding uses a tier's package from outside that tier.
    """
    own = _tier(path)
    outside = path.relative_to(PACKAGE).parts[0] != "binding"
    return [
        f"{path.relative_to(PACKAGE)}:{line} imports {name}"
        for line, name in imports
        if name.startswith("proscenium.binding.")
        and len(name.split(".")) > 3
        and (unit := _unit(name.split(".")[1:])) != own
        and (outside or unit in BINDING_TIERS)
        and name not in REACH_EXCEPTIONS.get(path.relative_to(PACKAGE), set())
    ]


def test_units_are_reached_through_their_packages() -> None:
    found = [v for path in sorted(PACKAGE.rglob("*.py")) for v in _reached_inside(path, _imported(path))]
    assert not found, "\n".join(found)


def test_an_import_inside_a_unit_is_found() -> None:
    # Guards the test above: runtime may not reach persistence's modules, nor api source access's; persistence may.
    module = [(1, "proscenium.binding.persistence.records"), (2, "proscenium.binding.source_access.binding_ids")]
    assert len(_reached_inside(PACKAGE / "binding" / "runtime" / "state.py", module[:1])) == 1
    assert len(_reached_inside(PACKAGE / "api" / "bindings.py", module[1:])) == 1
    assert not _reached_inside(PACKAGE / "binding" / "persistence" / "binding_records.py", module[1:])
    assert not _reached_inside(PACKAGE / "binding" / "persistence" / "binding_records.py", module[:1])
    # "from package import module" reaches the module, and "from package import name" only the package.
    imports = _imports_in(
        ast.parse("from ..persistence import manifests, Loaded"), ["proscenium", "binding", "runtime"]
    )
    assert [name for _, name in imports] == [
        "proscenium.binding.persistence.manifests",
        "proscenium.binding.persistence",
    ]


def test_a_wrong_way_import_is_found() -> None:
    # Guards the tests above: the API module, read as if it were in persistence, imports above that tier.
    api = PACKAGE / "api" / "bindings.py"
    assert any("imports proscenium.binding.runtime" in v for v in _violations(api, "binding.persistence"))


def test_an_absolute_import_of_a_tier_is_found() -> None:
    # Guards the tests above: "from proscenium.binding import x" names the unit it imports.
    imports = _imports_in(ast.parse("from proscenium.binding import runtime"), ["proscenium", "core"])
    assert [(name, _crosses(name, "core")) for _, name in imports] == [("proscenium.binding.runtime", True)]


def _blender_imports_in(tree: ast.Module) -> list[tuple[int, str]]:
    """The absolute imports in tree of Blender's modules, anywhere in it: type-only and in functions too."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names = [node.module]
        else:
            continue
        found += [(node.lineno, name) for name in names if _is_blender(name.split(".")[0])]
    return found


@functools.cache
def _is_blender(top: str) -> bool:
    """Whether the top-level module top is Blender's: loaded from the bpy wheel, or not found without bpy."""
    if (module := sys.modules.get(top)) is not None:  # imported already, perhaps by a blender-layer test
        spec = getattr(module, "__spec__", None)
        if spec is None:  # created by C code: by bpy's, unless it is an interpreter built-in
            return top not in sys.builtin_module_names
        return is_blender_origin(spec.origin)
    spec = importlib.util.find_spec(top)
    return spec is None or is_blender_origin(spec.origin)


def _bpy_free(path: Path) -> bool:
    """Whether path must import without bpy: the bpy-free units, and the packages that hold them (AGENTS.md#layout)."""
    return _tier(path) in {*BELOW_TIERS, "binding"} or path == PACKAGE / "__init__.py"


def test_bpy_free_code_never_imports_blender() -> None:
    found = [
        f"{path.relative_to(PACKAGE)}:{line} imports {name}"
        for path in sorted(PACKAGE.rglob("*.py"))
        if _bpy_free(path)
        for line, name in _blender_imports_in(ast.parse(path.read_text(), str(path)))
    ]
    assert not found, "\n".join(found)


def test_a_blender_import_is_found() -> None:
    # Guards the test above: bpy loads from the wheel, and mathutils exists only once bpy made it; pxr, from the wheel's
    # bundled packages, and the standard library are allowed. The bpy-free code is the units and their packages.
    code = "import os\nimport pxr.Usd\ndef f() -> None:\n    import bpy\n    from mathutils import Vector\n"
    assert [name for _, name in _blender_imports_in(ast.parse(code))] == ["bpy", "mathutils"]
    assert _bpy_free(PACKAGE / "binding" / "source_access" / "binding_ids.py")
    assert not _bpy_free(PACKAGE / "binding" / "persistence" / "records.py")
