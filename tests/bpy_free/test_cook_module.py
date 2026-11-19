"""The cook's compiled module loads, built against this process's USD (proscenium_cook's tree_cook/)."""

from __future__ import annotations

from pxr import Usd

import proscenium_cook


def test_cook_module_built_against_host_usd() -> None:
    assert proscenium_cook.usd_version() == Usd.GetVersion()
