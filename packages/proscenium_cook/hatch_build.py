"""The package's build hook: builds the cook's module for this platform, for a wheel or an editable install."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, override

from hatchling.builders.config import BuilderConfig
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

HERE = Path(__file__).resolve().parent


class CookBuildHook(BuildHookInterface[BuilderConfig]):
    """Builds _cook into tree_cook/ unless it's current (tools/build/native_build.py), and adds it to a wheel."""

    @override
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return
        # Both uv sync (no-build-isolation-package) and tools/build/build_extension.py build without isolation, in the
        # uv environment, with the dev group's CMake, Ninja, filelock, and bpy wheel.
        sys.path.insert(0, str(HERE.parents[1] / "tools" / "build"))
        from native_build import COOK, SKIP_NATIVE_BUILD, sync_module, wheel_tag

        if version == "editable":
            # The editable install imports the module from tree_cook/, where sync_module builds it. CI skips it there,
            # and builds the module with tools/build/build_extension.py.
            if os.environ.get(SKIP_NATIVE_BUILD) != "1":
                sync_module(COOK)
            return
        module = sync_module(COOK)
        build_data["pure_python"] = False
        build_data["tag"] = wheel_tag()
        # The module is ignored by Git, which hatchling's file selection follows.
        build_data["force_include"][str(module)] = module.relative_to(HERE / "src").as_posix()
