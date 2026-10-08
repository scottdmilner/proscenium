"""Isolated body: open the production-like CI fixture with Blender's pxr and take its inventory.

Runs in a fresh Blender process (isolated/harness.py); see tests/isolated/test_ci_fixture.py.
"""

from __future__ import annotations

from typing import Any

from pxr import Usd

from fixtures import production_like


def inventory(root: str, load_all: bool) -> dict[str, Any]:
    stage = Usd.Stage.Open(root, Usd.Stage.LoadAll if load_all else Usd.Stage.LoadNone)
    return production_like.inventory(stage)
