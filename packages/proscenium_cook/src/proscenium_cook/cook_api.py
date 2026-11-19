"""TreeCook, the cook of one node tree given as a USD stage (docs/plans/cook-module.md "The interface")."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from . import tree_cook
from .cook_results import CookResult, DiagnosticCode, NodeDiagnostic, NodeReport, Severity

if TYPE_CHECKING:
    from pxr import Usd

DEFINITIONS = Path(__file__).with_name("node_definitions.usda")

# Compared as strings, so a code DiagnosticCode lacks fails the import too, rather than raising ValueError.
if frozenset(tree_cook.diagnostic_codes()) != frozenset(code.value for code in DiagnosticCode):
    raise ImportError("The cook's module reports other diagnostic codes than proscenium_cook.DiagnosticCode")


@cache
def _definitions() -> tree_cook.NodeDefinitions:
    """The shipped node definitions, loaded once a process; loading checks them against the node registry."""
    return tree_cook.NodeDefinitions(str(DEFINITIONS))


class TreeCook:
    """The cook of one tree: it holds the tree's stage until it's dropped, and never edits it.

    It reads only the stage's root layer. Problems in the tree are diagnostics in each cook's result; it raises only
    for misuse, such as no stage. Its state, the zones' layers and each node's cache, stays between cooks, so
    returned stages keep composing the same layers.
    """

    _cook: tree_cook.TreeCook

    def __init__(self, tree_stage: Usd.Stage, base_directory: str | Path | None = None) -> None:
        """Hold tree_stage; base_directory is where // paths start, and None means they're errors."""
        if tree_stage is None:
            raise ValueError("TreeCook needs the tree's stage")
        self._cook = tree_cook.TreeCook(
            tree_stage, "" if base_directory is None else str(base_directory), _definitions()
        )

    def cook(self) -> CookResult:
        """Cook the whole tree, and return its stages and reports."""
        raw = self._cook.cook()
        return CookResult(
            stage_outputs=dict(raw["stage_outputs"]),
            viewer_stages=dict(raw["viewer_stages"]),
            node_reports={
                node_id: NodeReport(_diagnostics(diagnostics), dict(report_data))
                for node_id, (diagnostics, report_data) in raw["node_reports"].items()
            },
            tree_diagnostics=_diagnostics(raw["tree_diagnostics"]),
        )


def _diagnostics(raw: list[tuple[str, str, str, str]]) -> tuple[NodeDiagnostic, ...]:
    return tuple(
        NodeDiagnostic(Severity(severity), DiagnosticCode(code), message, source_path or None)
        for severity, code, message, source_path in raw
    )
