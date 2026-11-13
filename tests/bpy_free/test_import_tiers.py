"""The import rules between proscenium's units: tiers, and public modules (src/proscenium/README.md#import-rules).

Each unit imports only from itself and from units in lower tiers, and the lowest tier's units import only themselves.
Between units, a public module (a package unit's exported module, or a module unit) is imported from its package, or
names are imported from it; a package unit that exports names is imported from its parent, or those names from it.

Imports are read from each module's source with ast, without importing it, so type-only imports count too.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import sys
from pathlib import Path
from typing import NamedTuple

import proscenium

from .bpy_blocker import is_blender_origin

PACKAGE = Path(proscenium.__file__).parent

# The units, each a package or a module, by name under proscenium, lowest tier first. proscenium/__init__.py, the
# extension's entry, and the grouping packages' __init__.py files, which group their units, are no unit's.
TIERS = (
    # bpy-free, each importing only itself
    ("core", "binding.source_access", "binding.results", "ui.widget_model"),
    # bpy-free
    ("ui.scene_graph_widget.prim_tree",),
    ("binding.persistence",),
    ("binding.runtime",),
    ("synchronization",),
    ("api",),
    ("ui.widget_resources", "ui.columned_list", "ui.widget_updates"),
    ("ui.search_box",),
    ("ui.scene_graph_widget.display",),
    ("addon",),
)
TIER_OF = {unit: tier for tier, units in enumerate(TIERS) for unit in units}
BPY_FREE = {*TIERS[0], *TIERS[1]}
# The packages that group units, by name under proscenium, and are none themselves; their __init__.py imports none
# of their units.
GROUPING_PACKAGES = ("binding", "ui", "ui.scene_graph_widget")
GROUPING_INITS = tuple(PACKAGE.joinpath(*package.split("."), "__init__.py") for package in GROUPING_PACKAGES)


def _allowed(unit: str) -> set[str]:
    """The units unit may import: itself, and every unit in a lower tier unless it's in the lowest."""
    tier = TIER_OF[unit]
    return {unit} if tier == 0 else {u for u, t in TIER_OF.items() if t < tier} | {unit}


def _unit(parts: list[str] | tuple[str, ...]) -> str:
    """The unit a module belongs to, from its name's parts under proscenium."""
    # The unit is the first package under proscenium that groups nothing, or the module itself.
    depth = 1
    while depth < len(parts) and ".".join(parts[:depth]) in GROUPING_PACKAGES:
        depth += 1
    return ".".join(parts[:depth])


def _module_name(path: Path) -> list[str]:
    parts = ["proscenium", *path.relative_to(PACKAGE).with_suffix("").parts]
    return parts[:-1] if parts[-1] == "__init__" else parts


def _imported(path: Path) -> list[ModuleImport]:
    """The proscenium modules path imports, with their line numbers, relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module[:-1]
    return _imports_in(ast.parse(path.read_text(), str(path)), package)


def _submodule(target: str, name: str) -> str:
    """target.name if that is a module of proscenium, else target.

    Compared with the directory's entries, since a case-insensitive file system finds records.py for a name Records.
    A compiled module, such as core's _core, is found by its type stub.
    """
    directory = PACKAGE.parent.joinpath(*target.split("."))
    entries = {p.name for p in directory.iterdir()} if directory.is_dir() else set()
    module = bool({f"{name}.py", f"{name}.pyi"} & entries) or (
        name in entries and (directory / name / "__init__.py").is_file()
    )
    return f"{target}.{name}" if module else target


class ModuleImport(NamedTuple):
    """A proscenium module an import reaches."""

    line: int
    name: str
    via: str  # the package it was imported from, for "from package import module"; else empty, as for "from module
    # import names"
    imported_name: str = ""  # the name taken from the module, for "from module import name"; else empty


def _imports_in(tree: ast.Module, package: list[str]) -> list[ModuleImport]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [ModuleImport(node.lineno, alias.name, "") for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            target = ".".join([*base, *([node.module] if node.module else [])])
            # "from package import x" imports the module x when there is one, and else a name from package
            for alias in node.names:
                name = _submodule(target, alias.name)
                if name != target:
                    found.append(ModuleImport(node.lineno, name, target))
                else:
                    found.append(ModuleImport(node.lineno, name, "", alias.name))
    return [i for i in found if i.name.split(".")[0] == "proscenium"]


def _own_unit(path: Path) -> str | None:
    """The unit path belongs to, or None for a package's __init__.py that is no unit's."""
    parts = path.relative_to(PACKAGE).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return unit if parts and (unit := _unit(parts)) in TIER_OF else None


def _wrong_way(path: Path, unit: str) -> list[str]:
    """Of path's imports, read as unit's, those of units unit may not import."""
    return [
        f"{path.relative_to(PACKAGE)}:{line} imports {name}"
        for line, name, *_ in _imported(path)
        if (parts := name.split(".")[1:]) and _unit(parts) not in _allowed(unit)
    ]


def test_units_import_only_lower_tiers() -> None:
    found = [v for path in sorted(PACKAGE.rglob("*.py")) if (unit := _own_unit(path)) for v in _wrong_way(path, unit)]
    assert not found, "\n".join(found)


def test_every_module_is_a_units() -> None:
    # A new unit gets a row in TIERS, so the tests check it; only the entry and the grouping __init__.py files are no
    # unit's.
    stray = [p for p in PACKAGE.rglob("*.py") if _own_unit(p) is None]
    assert sorted(p.relative_to(PACKAGE) for p in stray) == sorted(
        [Path("__init__.py"), *(init.relative_to(PACKAGE) for init in GROUPING_INITS)]
    )
    for init in GROUPING_INITS:
        assert not _imported(init)  # so importing a bpy-free unit never imports bpy


@functools.cache
def _exports(package: str) -> frozenset[str]:
    """The names a package of proscenium exports: its __init__.py's __all__."""
    init = PACKAGE.parent.joinpath(*package.split("."), "__init__.py")
    for node in ast.parse(init.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return frozenset(ast.literal_eval(node.value))
    return frozenset()


@functools.cache
def _exported_names(package: str) -> frozenset[str]:
    """The names other than modules a package of proscenium exports."""
    return frozenset(n for n in _exports(package) if _submodule(package, n) == package)


def _in_form(imported: ModuleImport) -> bool:
    """Whether an import of another unit's module reaches it through a public module or a package's exported names.

    A package unit's public modules are those its package exports, and a module unit is public itself. One is imported
    from its package, or names are imported from it. A package unit that exports names is imported from its parent, or
    those names are imported from it.
    """
    name, via = imported.name, imported.via
    unit = f"proscenium.{_unit(name.split('.')[1:])}"
    package, _, module = name.rpartition(".")
    if not PACKAGE.parent.joinpath(*unit.split(".")).is_dir():
        return name == unit and via in (package, "")
    if name == unit:
        names = _exported_names(unit)
        return imported.imported_name in names if imported.imported_name else bool(names) and via in (package, "")
    return package == unit and module in _exports(unit) and via in (package, "")


def _out_of_form(path: Path, imports: list[ModuleImport]) -> list[str]:
    """Of path's imports of other units, those that don't take the one form."""
    own = _own_unit(path)
    return [
        f"{path.relative_to(PACKAGE)}:{imported.line} imports {imported.name}"
        for imported in imports
        if (parts := imported.name.split(".")[1:])
        and (unit := _unit(parts)) in TIER_OF
        and unit != own
        and not _in_form(imported)
    ]


def test_units_import_each_other_in_one_form() -> None:
    found = [v for path in sorted(PACKAGE.rglob("*.py")) for v in _out_of_form(path, _imported(path))]
    assert not found, "\n".join(found)


def test_an_import_out_of_form_is_found() -> None:
    # Guards the test above, from a runtime module: a public module from its package, names from a public module, and a
    # package that exports names, or those names from it, take the form; a name a package doesn't export, a package
    # that exports only modules, and an unexported module or a name from one, don't.
    module = PACKAGE / "binding" / "runtime" / "copy_detection.py"
    runtime = ["proscenium", "binding", "runtime"]

    def out_of_form(code: str) -> int:
        return len(_out_of_form(module, _imports_in(ast.parse(code), runtime)))

    assert out_of_form("from ..persistence import manifests, id_property_records") == 0
    assert out_of_form("from .. import results") == 0
    assert out_of_form("from ...core import _core") == 0
    assert out_of_form("from .ownership import Claim") == 0  # inside its own unit
    assert out_of_form("from ..persistence.manifests import Manifest, RepresentationRole") == 0
    assert out_of_form("from ..results import Diagnostic, Result") == 0
    assert out_of_form("from ... import synchronization") == 0
    assert out_of_form("from ...synchronization import synchronize, cache") == 0
    assert out_of_form("from ..persistence import Manifest") == 1
    assert out_of_form("from .. import persistence") == 1
    assert out_of_form("from ...synchronization import prepare") == 1
    assert out_of_form("from ...synchronization import application") == 1
    assert out_of_form("from ...synchronization.application import prepare") == 1


def _own_module_imports(path: Path) -> set[str]:
    """The modules of path's own unit that path imports, by name, type-only imports included."""
    unit = _own_unit(path)
    module = ".".join(_module_name(path))
    return {
        i.name
        for i in _imported(path)
        if (parts := i.name.split(".")[1:])
        and _unit(parts) == unit
        and i.name != module
        and i.name != f"proscenium.{unit}"
    }


def _cycles(imports_by_module: dict[str, set[str]]) -> list[list[str]]:
    """The import cycles among modules, each as the modules around it, found by a depth-first walk."""
    found: list[list[str]] = []
    finished: set[str] = set()

    def walk(module: str, trail: list[str]) -> None:
        if module in trail:
            found.append([*trail[trail.index(module) :], module])
            return
        if module in finished:
            return
        for imported in sorted(imports_by_module.get(module, ())):
            walk(imported, [*trail, module])
        finished.add(module)

    for module in sorted(imports_by_module):
        walk(module, [])
    return found


def test_a_units_modules_import_each_other_without_cycles() -> None:
    # Within a unit, modules form layers too: a cycle, even through a type-only import, means two modules each
    # need the other, so neither can be read or changed alone. A package's __init__.py, which exports its
    # modules, is left out.
    imports_by_module = {
        ".".join(_module_name(path)): _own_module_imports(path)
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name != "__init__.py" and _own_unit(path)
    }
    cycles = _cycles(imports_by_module)
    assert not cycles, "\n".join(" -> ".join(cycle) for cycle in cycles)


def test_an_import_cycle_is_found() -> None:
    # Guards the test above.
    assert _cycles({"a": {"b"}, "b": {"c"}, "c": {"a"}}) == [["a", "b", "c", "a"]]
    assert _cycles({"a": {"b", "c"}, "b": {"c"}, "c": set()}) == []


def test_a_wrong_way_import_is_found() -> None:
    # Guards the tests above: the API module, read as if it were persistence's, imports above that tier; and the
    # lowest tier's units import only themselves.
    api = PACKAGE / "api" / "bindings.py"
    assert any("imports proscenium.binding.runtime" in v for v in _wrong_way(api, "binding.persistence"))
    assert _allowed("binding.results") == {"binding.results"}


def test_an_absolute_import_of_a_unit_is_found() -> None:
    # Guards the tests above: "from proscenium.binding import x" names the unit it imports.
    imports = _imports_in(ast.parse("from proscenium.binding import runtime"), ["proscenium", "core"])
    assert [i.name for i in imports] == ["proscenium.binding.runtime"]
    assert "binding.runtime" not in _allowed("core")


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
    """Whether path must import without bpy: the two lowest tiers' units, and the packages that hold them."""
    return _own_unit(path) in BPY_FREE or path in (PACKAGE / "__init__.py", *GROUPING_INITS)


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
    assert _bpy_free(PACKAGE / "binding" / "source_access" / "source_entity_ids.py")
    assert not _bpy_free(PACKAGE / "binding" / "persistence" / "id_property_records.py")
    widget = PACKAGE / "ui" / "scene_graph_widget"
    assert _bpy_free(widget / "prim_tree" / "prim_tree.py")
    assert not _bpy_free(widget / "display" / "scene_graph_views.py")
    assert _bpy_free(PACKAGE / "ui" / "widget_model" / "text_matching.py")
    assert not _bpy_free(PACKAGE / "ui" / "widget_resources" / "theme_colors.py")
