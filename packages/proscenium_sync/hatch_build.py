"""The wheel's build hook: ships the planner, built for this platform, in a wheel tagged for it."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, override

from hatchling.builders.config import BuilderConfig
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

HERE = Path(__file__).resolve().parent


class PlannerBuildHook(BuildHookInterface[BuilderConfig]):
    """Builds the planner into planner/ unless it's current (tools/native_build.py), and adds it to the wheel."""

    @override
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return  # an editable install imports the module from planner/, where tools/build_extension.py builds it
        # The build runs without isolation, in the uv environment, with the dev group's CMake, Ninja, and bpy wheel.
        sys.path.insert(0, str(HERE.parents[1] / "tools"))
        from native_build import PLANNER, sync_module, wheel_tag

        module = sync_module(PLANNER)
        build_data["pure_python"] = False
        build_data["tag"] = wheel_tag()
        # The module is ignored by Git, which hatchling's file selection follows.
        build_data["force_include"][str(module)] = module.relative_to(HERE / "src").as_posix()
