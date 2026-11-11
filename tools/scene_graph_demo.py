"""Try the scene graph widget by hand in the Blender binary, hosted the way the add-on will host it.

    Blender --python tools/scene_graph_demo.py [-- path/to/stage.usda]

It registers `proscenium.ui.scene_graph_widget.display` from `src/` and places two views of one stage: one in the
3D View's sidebar and one in the node editor's, each on a "Scene Graph" tab. Press N in either editor to open the
sidebar. The panel's buttons open the test stage (`tests/fixtures/scenes/scene_graph/prim_kinds.usda`), any USD
file, or a generated stage for trying the tree at scale, and add or remove prims to show the tree following stage
edits. Selections from the tree are printed to the console. Nothing is saved: the stage is opened, and edited,
in memory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy
from pxr import Sdf, Usd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proscenium.ui.scene_graph_widget import display  # noqa: E402 (found through the path inserted above)

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

TEST_STAGE = ROOT / "tests" / "fixtures" / "scenes" / "scene_graph" / "prim_kinds.usda"
CATEGORY = "Scene Graph"
# Each view's name, by the editor whose sidebar shows it.
VIEW_NAMES_BY_EDITOR = {"VIEW_3D": "demo_viewport", "NODE_EDITOR": "demo_node_editor"}


class _DemoState:
    """The stage both views show; the host holds it, since the views never do."""

    stage: Usd.Stage | None = None


def _shows_view(editor_type: str) -> Any:
    def shows_in_region(area: Any, region: Any) -> bool:
        return area.type == editor_type and region.type == "UI" and region.active_panel_category == CATEGORY

    return shows_in_region


def _print_selection(view_name: str) -> Any:
    def on_selection_changed(path: Sdf.Path | None) -> None:
        print(f"[{view_name}] selected {path}")

    return on_selection_changed


def _show(stage: Usd.Stage) -> None:
    _DemoState.stage = stage
    for view_name in VIEW_NAMES_BY_EDITOR.values():
        display.set_stage(view_name, stage)


def synthetic_stage(fanout: int, depth: int, wide_leaf_count: int) -> Usd.Stage:
    """An in-memory stage of nested Xforms, fanout children per level, plus one group of wide leaf prims."""
    stage = Usd.Stage.CreateInMemory()
    layer = stage.GetRootLayer()
    with Sdf.ChangeBlock():
        root = Sdf.CreatePrimInLayer(layer, "/World")
        root.specifier = Sdf.SpecifierDef
        root.typeName = "Xform"
        frontier = [root.path]
        for level in range(depth):
            next_frontier = []
            for parent_path in frontier:
                for child_index in range(fanout):
                    spec = Sdf.CreatePrimInLayer(layer, parent_path.AppendChild(f"g{level}_{child_index}"))
                    spec.specifier = Sdf.SpecifierDef
                    spec.typeName = "Xform" if level < depth - 1 else "Mesh"
                    next_frontier.append(spec.path)
            frontier = next_frontier
        if wide_leaf_count:
            group = Sdf.CreatePrimInLayer(layer, "/World/Wide")
            group.specifier = Sdf.SpecifierDef
            group.typeName = "Scope"
            for leaf_index in range(wide_leaf_count):
                spec = Sdf.CreatePrimInLayer(layer, group.path.AppendChild(f"leaf_{leaf_index}"))
                spec.specifier = Sdf.SpecifierDef
                spec.typeName = "Mesh"
    return stage


def _selected_path(context: Any) -> Sdf.Path | None:
    view_name = VIEW_NAMES_BY_EDITOR.get(context.area.type) if context.area else None
    return display.selected_path(view_name) if view_name else None


class DemoOpenTestStage(bpy.types.Operator):
    """Open the scene graph's test stage, which has one prim of each kind a row marks."""

    bl_idname = "scene_graph_demo.open_test_stage"
    bl_label = "Open Test Stage"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        _show(Usd.Stage.Open(str(TEST_STAGE)))
        return {"FINISHED"}


class DemoOpenStage(bpy.types.Operator):
    """Open a USD file in both views."""

    bl_idname = "scene_graph_demo.open_stage"
    bl_label = "Open Stage"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # ty: ignore[invalid-type-form]
    filter_glob: bpy.props.StringProperty(default="*.usd;*.usda;*.usdc;*.usdz", options={"HIDDEN"})  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        stage = Usd.Stage.Open(self.filepath)
        if stage is None:
            self.report({"ERROR"}, f"Could not open {self.filepath}")
            return {"CANCELLED"}
        _show(stage)
        return {"FINISHED"}


class DemoGenerateStage(bpy.types.Operator):
    """Generate an in-memory stage for trying the tree at scale."""

    bl_idname = "scene_graph_demo.generate_stage"
    bl_label = "Generate Stage"

    fanout: bpy.props.IntProperty(name="Fanout", default=8, min=1, max=64)  # ty: ignore[invalid-type-form]
    depth: bpy.props.IntProperty(name="Depth", default=4, min=1, max=8)  # ty: ignore[invalid-type-form]
    wide_leaf_count: bpy.props.IntProperty(name="Wide Group Leaves", default=50_000, min=0, max=1_000_000)  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        return context.window_manager.invoke_props_dialog(self)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        _show(synthetic_stage(self.fanout, self.depth, self.wide_leaf_count))
        return {"FINISHED"}


class DemoAddChildPrim(bpy.types.Operator):
    """Define a new Xform under the selected prim (or the root), in the stage's session layer."""

    bl_idname = "scene_graph_demo.add_child_prim"
    bl_label = "Add Child Prim"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        stage = _DemoState.stage
        if stage is None:
            return {"CANCELLED"}
        parent_path = _selected_path(context) or Sdf.Path.absoluteRootPath
        child_index = 0
        while stage.GetPrimAtPath(parent_path.AppendChild(f"Added_{child_index}")):
            child_index += 1
        with Usd.EditContext(stage, stage.GetSessionLayer()):  # the files on disk stay as they are
            stage.DefinePrim(parent_path.AppendChild(f"Added_{child_index}"), "Xform")
        return {"FINISHED"}  # the views see the change through their notices, and redraw from a timer


class DemoToggleActive(bpy.types.Operator):
    """Toggle whether the selected prim is active, in the stage's session layer."""

    bl_idname = "scene_graph_demo.toggle_active"
    bl_label = "Toggle Active"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        stage = _DemoState.stage
        path = _selected_path(context)
        prim = stage.GetPrimAtPath(path) if stage is not None and path is not None else None
        if stage is None or not prim or prim.IsInstanceProxy():
            self.report({"WARNING"}, "Select a prim that isn't inside an instance")
            return {"CANCELLED"}
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            prim.SetActive(not prim.IsActive())
        return {"FINISHED"}


class DemoTreePanel:
    """The host's panel: its own buttons, then the widget's tree for this editor's view."""

    bl_label = "Scene Graph"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_space_type: str
    layout: Any

    def draw(self, context: Any) -> None:
        """Draw the stage buttons and the view's tree."""
        layout: Any = self.layout  # never None while drawing
        row = layout.row(align=True)
        row.operator(DemoOpenTestStage.bl_idname, icon="FILE_3D", text="Test")
        row.operator(DemoOpenStage.bl_idname, icon="FILE_FOLDER", text="Open")
        row.operator(DemoGenerateStage.bl_idname, icon="ADD", text="Generate")
        row = layout.row(align=True)
        row.enabled = _DemoState.stage is not None
        row.operator(DemoAddChildPrim.bl_idname, icon="PLUS", text="Add Child")
        row.operator(DemoToggleActive.bl_idname, icon="HIDE_OFF", text="Toggle Active")
        display.draw_tree(layout, context, VIEW_NAMES_BY_EDITOR[self.bl_space_type])


class DemoDetailsPanel:
    """The selected prim's details, from the widget."""

    bl_label = "Prim"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_space_type: str
    layout: Any

    def draw(self, context: Any) -> None:
        """Draw the view's details."""
        layout: Any = self.layout  # never None while drawing
        display.draw_details(layout, VIEW_NAMES_BY_EDITOR[self.bl_space_type])


class DemoViewportTreePanel(DemoTreePanel, bpy.types.Panel):
    """The tree in the 3D View's sidebar."""

    bl_idname = "VIEW3D_PT_scene_graph_demo_tree"
    bl_space_type = "VIEW_3D"


class DemoViewportDetailsPanel(DemoDetailsPanel, bpy.types.Panel):
    """The details in the 3D View's sidebar."""

    bl_idname = "VIEW3D_PT_scene_graph_demo_details"
    bl_space_type = "VIEW_3D"


class DemoNodeEditorTreePanel(DemoTreePanel, bpy.types.Panel):
    """The tree in the node editor's sidebar."""

    bl_idname = "NODE_PT_scene_graph_demo_tree"
    bl_space_type = "NODE_EDITOR"


class DemoNodeEditorDetailsPanel(DemoDetailsPanel, bpy.types.Panel):
    """The details in the node editor's sidebar."""

    bl_idname = "NODE_PT_scene_graph_demo_details"
    bl_space_type = "NODE_EDITOR"


CLASSES = (
    DemoOpenTestStage,
    DemoOpenStage,
    DemoGenerateStage,
    DemoAddChildPrim,
    DemoToggleActive,
    DemoViewportTreePanel,
    DemoViewportDetailsPanel,
    DemoNodeEditorTreePanel,
    DemoNodeEditorDetailsPanel,
)


def register() -> None:
    """Register the widget, create a view per editor, and register the host's panels."""
    display.register()
    for editor_type, view_name in VIEW_NAMES_BY_EDITOR.items():
        display.create_view(view_name, _shows_view(editor_type), _print_selection(view_name))
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    """Undo register; the widget removes its views."""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    display.unregister()
    _DemoState.stage = None


def main() -> None:
    """Register, then show the stage named after `--`, or the test stage."""
    register()
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    stage_path = Path(arguments[0]) if arguments else TEST_STAGE
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise SystemExit(f"could not open {stage_path}")
    _show(stage)


if __name__ == "__main__":
    main()
