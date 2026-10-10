"""Make importing Blender modules fail, to prove code is bpy-free.

Used two ways:
- tests/bpy_free/conftest.py wraps every test in that layer in `blender_modules_blocked()`.
- As a script, it imports modules in a fresh interpreter with Blender modules
  blocked; tests/bpy_free/test_no_blender_imports.py uses this for proscenium itself:

      python tests/bpy_free/bpy_blocker.py proscenium --walk proscenium.core

Blender modules are recognized by where they come from, not by name:
- Modules loaded from the bpy wheel's package dir: bpy itself (bpy/__init__.so)
  and Blender's Python modules under bpy/<version>/scripts/ (bpy_extras,
  addon_utils, bl_ui, add-ons, ...). The wheel's bundled site-packages, which
  holds pxr and other third-party packages, is excluded.
- Modules that bpy's C code creates when it is imported (mathutils, bmesh, gpu,
  _bpy, bpy.types, ...). They have no import spec and are not interpreter
  built-ins; outside Blender, nothing in this environment creates such modules.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.abc
import importlib.util
import os
import pkgutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType


def _bpy_dirs() -> tuple[str, tuple[str, ...]] | None:
    """The bpy wheel's package dir and its bundled site-packages dirs, found without importing bpy."""
    spec = importlib.util.find_spec("bpy")
    if spec is None or spec.origin is None:
        return None
    root = Path(spec.origin).parent
    dirs = []
    if os.name == "posix":  # macOS/Linux
        dirs = root.glob("*/python/lib/python*/site-packages")
    elif os.name == "nt":  # Windows
        dirs = root.glob("*/python/lib/site-packages")
    # Trailing separators, so prefixes match whole directory names.
    bundled = tuple(os.path.join(p, "") for p in dirs)
    return os.path.join(root, ""), bundled


_BPY = _bpy_dirs()


def is_blender_origin(origin: str | None) -> bool:
    """Whether a module loaded from `origin` is Blender's: inside the bpy wheel, outside its bundled packages."""
    if _BPY is None or not origin:
        return False
    root, bundled = _BPY
    return origin.startswith(root) and not origin.startswith(bundled)


def is_blender_module(name: str, module: object) -> bool:
    """Whether the sys.modules entry `name` is one of Blender's.

    Entries are not always modules: Blender registers objects such as bpy.app directly.
    """
    spec: ModuleSpec | None = getattr(module, "__spec__", None)
    if spec is None:
        # Created directly by C code rather than imported. Apart from the interpreter's
        # built-ins and __main__ (which multiprocessing also registers as __mp_main__),
        # only bpy does that here; with bpy loaded, __mp_main__ is Blender's own module.
        return name not in sys.builtin_module_names and module is not sys.modules.get("__main__")
    return is_blender_origin(spec.origin)


class _BlockBlender(importlib.abc.MetaPathFinder):
    """Import hook that raises for modules that would load from Blender, and ignores everything else."""

    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        # Ask the other finders where the module would come from.
        for finder in sys.meta_path:
            if isinstance(finder, _BlockBlender) or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                if is_blender_origin(spec.origin):
                    raise ImportError(
                        f"{fullname} is a Blender module; tests/bpy_free and proscenium.core must not import it"
                    )
                break
        # Modules created by bpy's C code (mathutils, ...) have no finder; once hidden
        # from sys.modules, importing them fails with ModuleNotFoundError on its own.
        return None  # let the normal finders import it


@contextmanager
def blender_modules_blocked() -> Generator[None]:
    """Inside the block, `import bpy` (and other Blender modules) raises ImportError.

    Blender modules already imported by earlier tests in the same run are
    hidden from sys.modules for the duration, so the import is blocked rather
    than served from the module cache. They are restored afterwards.
    """
    hidden = {name: module for name, module in sys.modules.items() if is_blender_module(name, module)}
    for name in hidden:
        del sys.modules[name]
    blocker = _BlockBlender()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(hidden)


def import_without_blender(modules: Sequence[str], walk: Sequence[str] = ()) -> None:
    """Import `modules`, and `walk` packages with all their submodules, with Blender blocked."""
    with blender_modules_blocked():
        for name in modules:
            importlib.import_module(name)
        for name in walk:
            package = importlib.import_module(name)
            for info in pkgutil.walk_packages(package.__path__, prefix=f"{name}."):
                importlib.import_module(info.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import modules with Blender modules blocked.")
    parser.add_argument("modules", nargs="*", help="modules to import")
    parser.add_argument("--walk", action="append", default=[], help="package to import with all submodules")
    args = parser.parse_args()
    import_without_blender(args.modules, args.walk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
