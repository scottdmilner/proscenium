"""The cook: evaluates a node tree, given as a USD stage (docs/plans/cook-module.md).

Other packages use only the names this module exports.
"""

from .tree_cook import usd_version

__all__ = ["usd_version"]
