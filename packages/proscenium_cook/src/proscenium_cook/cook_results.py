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
    NO_UPSTREAM_VALUE = "no-upstream-value"  # a link that brings nothing: its node failed, can't run, or is muted
    USD_ERROR = "usd-error"  # a USD error a node raised while it ran, which it doesn't report as its own
    # A zone's:
    UNPAIRED_ZONE = "unpaired-zone"  # a begin whose zone:end names no end of its zone, or an end no one begin names
    CHAIN_BRANCH = "chain-branch"  # an Editable Layer output linked to more than one input
    BROKEN_CHAIN = "broken-chain"  # an end its begin's chain doesn't reach
    MISMATCHED_ZONE = "mismatched-zone"  # an end another begin's chain reaches
    UNREACHED_ZONE_END = "unreached-zone-end"  # a chain node on a chain that never reaches its end
    NO_CHAIN = "no-chain"  # an authoring node whose Editable Layer doesn't trace back to a begin
    SHARED_FILE = "shared-file"  # two zones that save to one file
    # A Path property's:
    MISSING_BASE_DIRECTORY = "missing-base-directory"  # a // path with no base directory: the .blend isn't saved
    WORKING_DIRECTORY_PATH = "working-directory-path"  # a ./ or ../ path, which resolves against the working directory
    # A node type's own:
    MISSING_PATH = "missing-path"  # Layer from File or Prim: an empty Path
    FILE_NOT_FOUND = "file-not-found"  # Layer from File: no file at Path
    UNREADABLE_FILE = "unreadable-file"  # Layer from File: a file that doesn't parse as a layer
    UNLINKED_INPUT = "unlinked-input"  # Stage Output: nothing linked into its Layer
    MISSING_STAGE_METRICS = "missing-stage-metrics"  # Stage Output: a root layer with no upAxis or metersPerUnit
    INVALID_DEFAULT_PRIM = "invalid-default-prim"  # New Layer Zone: a Default Prim that isn't a prim of its layer
    DEFAULT_PRIM_NOT_DEF = "default-prim-not-def"  # New Layer Zone: a Default Prim whose spec is an over or a class
    INVALID_PRIM_NAME = "invalid-prim-name"  # Create Prim: a Name that isn't a valid identifier
    EXISTING_PRIM_SPEC = "existing-prim-spec"  # Create Prim: a prim the layer already has a spec for
    UNKNOWN_PRIM_TYPE = "unknown-prim-type"  # Create Prim: a Type that names no registered schema
    NON_CONCRETE_PRIM_TYPE = "non-concrete-prim-type"  # Create Prim: a Type that names an abstract or API schema


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
    viewer_stages: dict[str, Usd.Stage]  # one per Viewer that has a stage
    node_reports: dict[str, NodeReport]  # one per node with diagnostics or report data
    tree_diagnostics: tuple[NodeDiagnostic, ...]  # problems that belong to no node
