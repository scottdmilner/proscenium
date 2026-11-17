"""The import rules between units: tiers, and public modules (packages/README.md#import-rules).

The code is in packages: the extension, proscenium, and the workspace's packages in packages/. A package imports only
the packages its pyproject.toml depends on. Within a package, each unit imports only from itself and from units in
lower tiers, and the lowest tier's units import only themselves; a unit may import any unit of a package its package
depends on, unless it is bpy-free. Between units, a public module (a package unit's exported module, or a
module unit) is imported from its package, or names are imported from it; a package unit that exports names is
imported from its parent, or those names from it.

Imports are read from each module's source with ast, without importing it, so type-only imports count too.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

import proscenium
import proscenium_sync
import proscenium_ui

from .bpy_blocker import is_blender_origin


class PackageRules(NamedTuple):
    """A package's units, in tiers, and the packages that group units."""

    directory: Path
    # The units, each a package or a module, by name under the package, lowest tier first. The package's __init__.py
    # and the grouping packages' __init__.py files, which group their units, are no unit's.
    tiers: tuple[tuple[str, ...], ...]
    # The packages that group units, by name under the package, and are none themselves; their __init__.py imports
    # none of their units.
    grouping_packages: tuple[str, ...]
    bpy_free_tier_count: int  # how many of the lowest tiers import no bpy


PACKAGES = {
    "proscenium": PackageRules(Path(proscenium.__file__).parent, (("interface",), ("addon",)), (), 0),
    "proscenium_sync": PackageRules(
        Path(proscenium_sync.__file__).parent,
        (
            ("core", "source_access", "results"),  # bpy-free, each importing only itself
            ("binding_persistence",),
            ("binding_runtime",),
            ("synchronization", "interaction"),
            ("api",),
            ("registration",),
        ),
        (),
        1,
    ),
    "proscenium_ui": PackageRules(
        Path(proscenium_ui.__file__).parent,
        (
            ("widget_model",),  # bpy-free, importing only itself
            ("scene_graph_widget.prim_tree", "property_viewer_widget.property_list"),  # bpy-free
            ("columned_list", "widget_updates"),
            ("widget_resources", "search_box", "text_wrapping"),
            ("scene_graph_widget.display", "property_viewer_widget.display"),
        ),
        ("scene_graph_widget", "property_viewer_widget"),
        2,
    ),
}
# Each unit by its full name, with its package and tier.
TIER_OF = {
    f"{package}.{unit}": (package, tier)
    for package, rules in PACKAGES.items()
    for tier, units in enumerate(rules.tiers)
    for unit in units
}
BPY_FREE = {
    f"{package}.{unit}"
    for package, rules in PACKAGES.items()
    for units in rules.tiers[: rules.bpy_free_tier_count]
    for unit in units
}
GROUPING_INITS = tuple(
    rules.directory.joinpath(*grouping.split("."), "__init__.py")
    for rules in PACKAGES.values()
    for grouping in rules.grouping_packages
)
PACKAGE_INITS = tuple(rules.directory / "__init__.py" for rules in PACKAGES.values())


@functools.cache
def _dependencies(package: str) -> frozenset[str]:
    """The packages of PACKAGES that package's pyproject.toml depends on."""
    pyproject = PACKAGES[package].directory.parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    return frozenset(name for name in declared if name in PACKAGES)


def _allowed(unit: str) -> set[str]:
    """The units unit may import: itself, lower tiers' units, and unless it's bpy-free, its dependencies' units."""
    package, tier = TIER_OF[unit]
    lower = {u for u, (p, t) in TIER_OF.items() if p == package and t < tier}
    dependencies = set() if unit in BPY_FREE else {u for u, (p, _) in TIER_OF.items() if p in _dependencies(package)}
    return lower | dependencies | {unit}


def _unit(parts: list[str] | tuple[str, ...]) -> str:
    """The unit a module belongs to, by its full name, from its name's parts, its package's first."""
    # The unit is the first package under the package that groups nothing, or the module itself.
    package, *rest = parts
    grouping = PACKAGES[package].grouping_packages
    depth = 1
    while depth < len(rest) and ".".join(rest[:depth]) in grouping:
        depth += 1
    return ".".join([package, *rest[:depth]])


def _package_of(path: Path) -> str:
    return next(name for name, rules in PACKAGES.items() if rules.directory in path.parents)


def _shown(path: Path) -> Path:
    """Path as a failure names it: from its package's directory's parent."""
    return path.relative_to(PACKAGES[_package_of(path)].directory.parent)


def _module_name(path: Path) -> list[str]:
    package = _package_of(path)
    parts = [package, *path.relative_to(PACKAGES[package].directory).with_suffix("").parts]
    return parts[:-1] if parts[-1] == "__init__" else parts


def _python_files() -> list[Path]:
    return sorted(p for rules in PACKAGES.values() for p in rules.directory.rglob("*.py"))


def _imported(path: Path) -> list[ModuleImport]:
    """The packages' modules path imports, with their line numbers, relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module[:-1]
    return _imports_in(ast.parse(path.read_text(), str(path)), package)


def _submodule(target: str, name: str) -> str:
    """target.name if that is a module of one of the packages, else target.

    Compared with the directory's entries, since a case-insensitive file system finds records.py for a name Records.
    A compiled module, such as core's _core, is found by its type stub.
    """
    directory = PACKAGES[target.split(".")[0]].directory.parent.joinpath(*target.split("."))
    entries = {p.name for p in directory.iterdir()} if directory.is_dir() else set()
    module = bool({f"{name}.py", f"{name}.pyi"} & entries) or (
        name in entries and (directory / name / "__init__.py").is_file()
    )
    return f"{target}.{name}" if module else target


class ModuleImport(NamedTuple):
    """A module of one of the packages that an import reaches."""

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
            if target.split(".")[0] not in PACKAGES:
                continue
            # "from package import x" imports the module x when there is one, and else a name from package
            for alias in node.names:
                name = _submodule(target, alias.name)
                if name != target:
                    found.append(ModuleImport(node.lineno, name, target))
                else:
                    found.append(ModuleImport(node.lineno, name, "", alias.name))
    return [i for i in found if i.name.split(".")[0] in PACKAGES]


def _own_unit(path: Path) -> str | None:
    """The unit path belongs to, or None for a package's __init__.py that is no unit's."""
    parts = _module_name(path)
    return unit if len(parts) > 1 and (unit := _unit(parts)) in TIER_OF else None


def _wrong_way(path: Path, unit: str) -> list[str]:
    """Of path's imports, read as unit's, those of units unit may not import."""
    return [
        f"{_shown(path)}:{line} imports {name}"
        for line, name, *_ in _imported(path)
        if len(parts := name.split(".")) > 1 and _unit(parts) not in _allowed(unit)
    ]


def test_units_import_only_lower_tiers() -> None:
    found = [v for path in _python_files() if (unit := _own_unit(path)) for v in _wrong_way(path, unit)]
    assert not found, "\n".join(found)


def test_the_interface_imports_only_the_api_and_widgets() -> None:
    # M7 plan, settled 3 and Phase F: the temporary UI reaches the product only through api/, and may host
    # proscenium_ui's widgets, which only read a stage their host gives them, so M12 can replace it alone.
    found = [
        f"{_shown(path)}:{line} imports {name}"
        for path in sorted((PACKAGES["proscenium"].directory / "interface").rglob("*.py"))
        for line, name, *_ in _imported(path)
        if (unit := _unit(name.split("."))) not in {"proscenium.interface", "proscenium_sync.api"}
        and not unit.startswith("proscenium_ui.")
    ]
    assert not found, "\n".join(found)


def test_every_module_is_a_units() -> None:
    # A new unit gets a row in its package's tiers, so the tests check it; only the packages' and the grouping
    # packages' __init__.py files are no unit's.
    stray = [p for p in _python_files() if _own_unit(p) is None]
    assert sorted(stray) == sorted([*PACKAGE_INITS, *GROUPING_INITS])
    for init in GROUPING_INITS:
        assert not _imported(init)  # so importing a bpy-free unit never imports bpy


def test_each_package_imports_only_its_dependencies() -> None:
    # The packages a package imports are those its pyproject.toml depends on, so a wheel installs with what it needs.
    found = [
        f"{_shown(path)}:{line} imports {name}"
        for path in _python_files()
        for line, name, *_ in _imported(path)
        if (imported := name.split(".")[0]) != (package := _package_of(path)) and imported not in _dependencies(package)
    ]
    assert not found, "\n".join(found)


@functools.cache
def _exports(package: str) -> frozenset[str]:
    """The names a package exports: its __init__.py's __all__."""
    init = PACKAGES[package.split(".")[0]].directory.parent.joinpath(*package.split("."), "__init__.py")
    for node in ast.parse(init.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return frozenset(ast.literal_eval(node.value))
    return frozenset()


@functools.cache
def _exported_names(package: str) -> frozenset[str]:
    """The names other than modules a package exports."""
    return frozenset(n for n in _exports(package) if _submodule(package, n) == package)


def _in_form(imported: ModuleImport) -> bool:
    """Whether an import of another unit's module reaches it through a public module or a package's exported names.

    A package unit's public modules are those its package exports, and a module unit is public itself. One is imported
    from its package, or names are imported from it. A package unit that exports names is imported from its parent, or
    those names are imported from it.
    """
    name, via = imported.name, imported.via
    unit = _unit(name.split("."))
    package, _, module = name.rpartition(".")
    if not PACKAGES[unit.split(".")[0]].directory.parent.joinpath(*unit.split(".")).is_dir():
        return name == unit and via in (package, "")
    if name == unit:
        names = _exported_names(unit)
        return imported.imported_name in names if imported.imported_name else bool(names) and via in (package, "")
    return package == unit and module in _exports(unit) and via in (package, "")


def _out_of_form(path: Path, imports: list[ModuleImport]) -> list[str]:
    """Of path's imports of other units, those that don't take the one form."""
    own = _own_unit(path)
    return [
        f"{_shown(path)}:{imported.line} imports {imported.name}"
        for imported in imports
        if len(parts := imported.name.split(".")) > 1
        and (unit := _unit(parts)) in TIER_OF
        and unit != own
        and not _in_form(imported)
    ]


def test_units_import_each_other_in_one_form() -> None:
    found = [v for path in _python_files() for v in _out_of_form(path, _imported(path))]
    assert not found, "\n".join(found)


def test_an_import_out_of_form_is_found() -> None:
    # Guards the test above, from a runtime module: a public module from its package, names from a public module, and a
    # package that exports names, or those names from it, take the form; a name a package doesn't export, a package
    # that exports only modules, and an unexported module or a name from one, don't.
    module = PACKAGES["proscenium_sync"].directory / "binding_runtime" / "copy_detection.py"
    runtime = ["proscenium_sync", "binding_runtime"]

    def out_of_form(code: str) -> int:
        return len(_out_of_form(module, _imports_in(ast.parse(code), runtime)))

    assert out_of_form("from proscenium_sync.binding_persistence import manifests, id_property_records") == 0
    assert out_of_form("from proscenium_sync import results") == 0
    assert out_of_form("from proscenium_sync import core") == 0
    assert out_of_form("from proscenium_sync.core import Plan, plan") == 0
    assert out_of_form("from .ownership import Claim") == 0  # inside its own unit
    assert out_of_form("from proscenium_sync.binding_persistence.manifests import Manifest, RepresentationRole") == 0
    assert out_of_form("from proscenium_sync.results import Diagnostic, Result") == 0
    assert out_of_form("from proscenium_sync import synchronization") == 0
    assert out_of_form("from proscenium_sync.synchronization import synchronize, cache") == 0
    assert out_of_form("from proscenium_sync.binding_persistence import Manifest") == 1
    assert out_of_form("from proscenium_sync.synchronization import prepare") == 1
    assert out_of_form("from proscenium_sync.synchronization import application") == 1
    assert out_of_form("from proscenium_sync.synchronization.application import prepare") == 1
    assert out_of_form("from proscenium_sync.core import _core") == 1  # the compiled module is the core's own
    # Another package's units take the same form.
    assert out_of_form("from proscenium_ui.scene_graph_widget import display") == 0
    assert out_of_form("from proscenium_ui import widget_updates") == 0
    assert out_of_form("from proscenium_ui.widget_model import Unexported") == 1


def _own_module_imports(path: Path) -> set[str]:
    """The modules of path's own unit that path imports, by name, type-only imports included."""
    unit = _own_unit(path)
    module = ".".join(_module_name(path))
    return {
        i.name
        for i in _imported(path)
        if len(parts := i.name.split(".")) > 1 and _unit(parts) == unit and i.name not in (module, unit)
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
        for path in _python_files()
        if path.name != "__init__.py" and _own_unit(path)
    }
    cycles = _cycles(imports_by_module)
    assert not cycles, "\n".join(" -> ".join(cycle) for cycle in cycles)


def test_an_import_cycle_is_found() -> None:
    # Guards the test above.
    assert _cycles({"a": {"b"}, "b": {"c"}, "c": {"a"}}) == [["a", "b", "c", "a"]]
    assert _cycles({"a": {"b", "c"}, "b": {"c"}, "c": set()}) == []


def test_a_wrong_way_import_is_found() -> None:
    # Guards the tests above: the API module, read as if it were persistence's, imports above that tier; the lowest
    # tier's units import only themselves; a package imports only the packages it depends on, and its bpy-free units
    # none.
    api = PACKAGES["proscenium_sync"].directory / "api" / "bindings.py"
    persistence = "proscenium_sync.binding_persistence"
    assert any("imports proscenium_sync.binding_runtime" in v for v in _wrong_way(api, persistence))
    assert _allowed("proscenium_sync.results") == {"proscenium_sync.results"}
    assert {"proscenium_sync.api", "proscenium_ui.scene_graph_widget.display"} <= _allowed("proscenium.interface")
    assert "proscenium_sync.api" not in _allowed("proscenium_ui.scene_graph_widget.display")
    assert "proscenium.interface" not in _allowed("proscenium_sync.registration")
    assert not _allowed("proscenium_sync.core") & {u for u in TIER_OF if u.startswith("proscenium_ui.")}


def test_an_absolute_import_of_a_unit_is_found() -> None:
    # Guards the tests above: "from proscenium_sync import x" names the unit it imports.
    imports = _imports_in(ast.parse("from proscenium_sync import binding_runtime"), ["proscenium_sync", "core"])
    assert [i.name for i in imports] == ["proscenium_sync.binding_runtime"]
    assert "proscenium_sync.binding_runtime" not in _allowed("proscenium_sync.core")


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
    """Whether path must import without bpy: each package's lowest tiers' units, and the packages that hold them."""
    return _own_unit(path) in BPY_FREE or path in (*PACKAGE_INITS, *GROUPING_INITS)


def test_bpy_free_code_never_imports_blender() -> None:
    found = [
        f"{_shown(path)}:{line} imports {name}"
        for path in _python_files()
        if _bpy_free(path)
        for line, name in _blender_imports_in(ast.parse(path.read_text(), str(path)))
    ]
    assert not found, "\n".join(found)


def test_a_blender_import_is_found() -> None:
    # Guards the test above: bpy loads from the wheel, and mathutils exists only once bpy made it; pxr, from the wheel's
    # bundled packages, and the standard library are allowed. The bpy-free code is the units and their packages.
    code = "import os\nimport pxr.Usd\ndef f() -> None:\n    import bpy\n    from mathutils import Vector\n"
    assert [name for _, name in _blender_imports_in(ast.parse(code))] == ["bpy", "mathutils"]
    sync, ui = PACKAGES["proscenium_sync"].directory, PACKAGES["proscenium_ui"].directory
    assert _bpy_free(sync / "source_access" / "source_entity_ids.py")
    assert not _bpy_free(sync / "binding_persistence" / "id_property_records.py")
    assert _bpy_free(ui / "scene_graph_widget" / "prim_tree" / "prim_tree.py")
    assert not _bpy_free(ui / "scene_graph_widget" / "display" / "scene_graph_views.py")
    assert _bpy_free(ui / "widget_model" / "text_matching.py")
    assert not _bpy_free(ui / "widget_resources" / "theme_colors.py")
