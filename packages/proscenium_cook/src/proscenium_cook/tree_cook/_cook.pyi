# Types of the cook's module, proscenium_cook.tree_cook._cook (python_bindings.cpp), so ty checks callers without a
# build.
from typing import Any

from pxr import Usd

def usd_version() -> tuple[int, int, int]: ...
def diagnostic_codes() -> list[str]: ...

# The tree prim name that stands for a node ID (node_ids.h), which the cook decodes back to the node ID.
def prim_name_from_node_id(node_id: str) -> str: ...

class NodeDefinitions:
    """Every node type's definition, from a node definitions file (node_definitions.h).

    Raises ValueError, naming every problem, for a malformed file or one whose node types differ from the node
    registry's, and pxr.Tf.ErrorException, with USD's own errors, for a file USD can't read.
    """

    def __init__(self, path: str) -> None: ...
    def type_names(self) -> list[str]: ...
    # Why the cook rejects a link from output_type's output_attribute to input_type's input_attribute (full names, such
    # as outputs:layer); "" when it takes it. Raises ValueError for a type or attribute the definitions don't have.
    def link_problem(self, output_type: str, output_attribute: str, input_type: str, input_attribute: str) -> str: ...

class TreeCook:
    """The cook of one tree (tree_cook.h). Raises ValueError for no stage or no definitions."""

    def __init__(self, tree_stage: Usd.Stage, base_directory: str, definitions: NodeDefinitions) -> None: ...
    # viewer is the active Viewer's node ID, "" for none; one that names no Viewer is a tree warning. Returns
    # stage_outputs (node ID to Usd.Stage), viewer_stage (a Usd.Stage or None), node_reports (node ID to (diagnostics,
    # report_data)), and tree_diagnostics; each diagnostic is (severity, code, message, source_path), source_path "" for
    # none.
    def cook(self, viewer: str) -> dict[str, Any]: ...
