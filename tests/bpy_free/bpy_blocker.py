"""Import modules in a fresh interpreter with Blender's modules blocked, to prove code is bpy-free.

tests/bpy_free/test_no_blender_imports.py runs it as a script for proscenium's bpy-free code:

    python tests/bpy_free/bpy_blocker.py proscenium proscenium.binding proscenium.binding.results \
        --walk proscenium.core --walk proscenium.binding.source_access

A fresh interpreter has no Blender module cached, so every import of one goes through the block. Blender modules are
recognized by where they come from, not by name: bpy itself (bpy/__init__.so) and Blender's Python modules under
bpy/<version>/scripts/ (bpy_extras, addon_utils, bl_ui, add-ons, ...) load from the bpy wheel's package dir. The wheel's
bundled site-packages, which holds pxr and other third-party packages, is excluded. The modules bpy's C code creates
when it is imported (mathutils, bmesh, gpu, ...) don't exist without it. tests/bpy_free/test_import_tiers.py uses
is_blender_origin to forbid Blender imports in the bpy-free code's source.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.abc
import importlib.util
import os
import pkgutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from collections.abc import Sequence
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


class _BlockBlender(importlib.abc.MetaPathFinder):
    """Import hook that raises for modules that would load from Blender, and ignores everything else."""

    @override
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
                        f"{fullname} is a Blender module; tests/bpy_free and bpy-free code must not import it"
                    )
                break
        # Modules created by bpy's C code (mathutils, ...) have no finder: without bpy, importing them fails
        # with ModuleNotFoundError on its own.
        return None  # let the normal finders import it


def import_without_blender(modules: Sequence[str], walk: Sequence[str] = ()) -> None:
    """Import `modules`, and `walk` packages with all their submodules, with Blender blocked."""
    sys.meta_path.insert(0, _BlockBlender())
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
