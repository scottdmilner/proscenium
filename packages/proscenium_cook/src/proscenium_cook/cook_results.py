"""What a cook returns: its stages, each node's report, and the tree's own diagnostics (docs/plans/cook-module.md).

These are the cook's own types, not proscenium_sync.results': the cook's reports are per node, not a binding's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pxr import Usd


class Severity(StrEnum):
    """How bad a diagnostic's problem is."""

    ERROR = "error"
    WARNING = "warning"


class DiagnosticCode(StrEnum):
    """The stable code naming a diagnostic's problem, which callers and tests identify it by.

    The cook's module reports the same list (_cook.diagnostic_codes()), which importing cook_api checks.
    """

    # The tree's own, which belong to no node:
    MISSING_TREE = "missing-tree"  # the tree's layer has no /Tree prim
    NOT_A_NODE_TREE = "not-a-node-tree"  # /Tree isn't a NodeTree
    UNKNOWN_TREE_FORMAT = "unknown-tree-format"  # tree:format missing, not an int, or a format the cook doesn't read
    COMPOSITION_IN_TREE = "composition-in-tree"  # a sublayer or composition arc in the tree's layer
    INVALID_NODE_NAME = "invalid-node-name"  # a node prim's name doesn't decode to a node ID
    # A node's:
    UNKNOWN_NODE_TYPE = "unknown-node-type"  # a type the definitions don't hold
    MISSING_NODE_VERSION = "missing-node-version"  # no node:version authored
    NEWER_NODE_VERSION = "newer-node-version"  # a node:version newer than the cook's definition
    UNKNOWN_ATTRIBUTE = "unknown-attribute"  # a property the definition doesn't have
    WRONG_ATTRIBUTE_TYPE = "wrong-attribute-type"  # an attribute authored with another type than its definition's
    INVALID_TOKEN = "invalid-token"  # a token outside its menu's allowedTokens
    INVALID_PRIM_PATH = "invalid-prim-path"  # a Prim that isn't an absolute prim path
    INVALID_PRIMS_EXPRESSION = "invalid-prims-expression"  # a Prims that doesn't parse as a path expression
    UNRESOLVED_CONNECTION = "unresolved-connection"  # a connection to no other node's output
    INCOMPATIBLE_LINK = "incompatible-link"  # a link between incompatible socket kinds or value types
    TOO_MANY_LINKS = "too-many-links"  # several links into an input that takes one
    CYCLE = "cycle"  # a node on a cycle of links


@dataclass(frozen=True)
class NodeDiagnostic:
    """One problem: its severity, its code, what it says, and the path in the authored layer it concerns."""

    severity: Severity
    code: DiagnosticCode
    message: str
    source_path: str | None = None  # None when the problem concerns no path


@dataclass(frozen=True)
class NodeReport:
    """One node's diagnostics, in the order the cook found them, and its report data."""

    diagnostics: tuple[NodeDiagnostic, ...]
    report_data: dict[str, Any] = field(default_factory=dict)  # empty until a node type reports data


@dataclass(frozen=True)
class CookResult:
    """One cook's stages and reports, each keyed by node ID."""

    stage_outputs: dict[str, Usd.Stage]  # one per Stage Output that has a stage
    viewer_stages: dict[str, Usd.Stage]  # one per Viewer the tree holds
    node_reports: dict[str, NodeReport]  # one per node with diagnostics or report data
    tree_diagnostics: tuple[NodeDiagnostic, ...]  # problems that belong to no node
