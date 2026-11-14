"""Try the scene graph and property viewer widgets by hand in the Blender binary, hosted as the add-on will host them.

    Blender --python tools/scene_graph_demo.py [-- path/to/stage.usda]

It registers `proscenium.ui.scene_graph_widget.display` and `proscenium.ui.property_viewer_widget.display`
from `src/` and places two views of one stage: one in the 3D View's sidebar and one in the node editor's, each on a
"Scene Graph" tab, with a scene graph panel, a property viewer panel below it showing the properties of the prim the
scene graph selects, and a property metadata panel summarizing the selected property. A target's jump button
selects the target's prim in the scene graph. Press N in either editor to open
the sidebar. The scene graph panel's buttons open the scene graph's test stage
(`tests/fixtures/scenes/scene_graph/prim_kinds.usda`), the property viewer's
(`tests/fixtures/scenes/property_viewer/property_kinds.usda`), any USD file, or a generated stage for trying the tree
at scale, and add prims, toggle them active, and add attributes, to show the widgets following stage edits. The
property viewer shows values at the scene's current frame. Selections are printed to the console. Nothing is saved:
the stage is opened, and edited, in memory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy
from bpy.app.handlers import persistent
from pxr import Sdf, Usd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Found through the path inserted above.
from proscenium.ui.property_viewer_widget import display as property_display  # noqa: E402
from proscenium.ui.scene_graph_widget import display  # noqa: E402

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

TEST_STAGE = ROOT / "tests" / "fixtures" / "scenes" / "scene_graph" / "prim_kinds.usda"
PROPERTIES_TEST_STAGE = ROOT / "tests" / "fixtures" / "scenes" / "property_viewer" / "property_kinds.usda"
UNLOADED_PRIM_PATH = Sdf.Path("/World/Geometry/Prop_Unloaded")  # the test stage's payload the demo leaves unloaded
CATEGORY = "Scene Graph"
# Each view's name, by the editor whose sidebar shows it: its scene graph view's, and its property viewer view's.
VIEW_NAMES_BY_EDITOR = {"VIEW_3D": "demo_viewport", "NODE_EDITOR": "demo_node_editor"}
PROPERTY_VIEW_NAMES_BY_EDITOR = {"VIEW_3D": "demo_viewport_properties", "NODE_EDITOR": "demo_node_editor_properties"}


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


def _show_selected_prim(view_name: str, property_view_name: str) -> Any:
    """A scene graph view's selection callback that shows the selected prim's properties in its property viewer."""

    def on_selection_changed(path: Sdf.Path | None) -> None:
        print(f"[{view_name}] selected {path}")
        property_display.show_prim(property_view_name, path)

    return on_selection_changed


def _jump_to_target(view_name: str, property_view_name: str) -> Any:
    """A property viewer's jump callback that selects a target's prim in its scene graph, and shows its properties.

    A target that's a property, as a connection's source is, is selected in the property viewer too.
    """

    def on_jump_to_target(target_path: Sdf.Path) -> None:
        print(f"[{property_view_name}] jumped to {target_path}")
        prim_path = target_path.GetPrimPath()
        display.select_prim(view_name, prim_path)  # not reported back, so the property viewer is shown it here
        property_display.show_prim(property_view_name, prim_path)
        if target_path.IsPropertyPath():
            property_display.select_property(property_view_name, target_path.name)

    return on_jump_to_target


def _show(stage: Usd.Stage) -> None:
    _DemoState.stage = stage
    for view_name in VIEW_NAMES_BY_EDITOR.values():
        display.set_stage(view_name, stage)  # selects nothing, which shows no prim's properties
    for property_view_name in PROPERTY_VIEW_NAMES_BY_EDITOR.values():
        property_display.set_stage(property_view_name, stage)


@persistent
def _frame_changed(scene: Any, *_args: object) -> None:
    # USD time code t is Blender frame t.
    for property_view_name in PROPERTY_VIEW_NAMES_BY_EDITOR.values():
        property_display.set_time_code(property_view_name, Usd.TimeCode(scene.frame_current))


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
        _show(open_test_stage())
        return {"FINISHED"}


class DemoOpenPropertiesTestStage(bpy.types.Operator):
    """Open the property viewer's test stage, which has one property of each kind a row marks."""

    bl_idname = "scene_graph_demo.open_properties_test_stage"
    bl_label = "Open Properties Test Stage"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        _show(Usd.Stage.Open(str(PROPERTIES_TEST_STAGE)))
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


class DemoAddAttribute(bpy.types.Operator):
    """Add a custom float attribute to the selected prim, in the stage's session layer."""

    bl_idname = "scene_graph_demo.add_attribute"
    bl_label = "Add Attribute"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        stage = _DemoState.stage
        path = _selected_path(context)
        prim = stage.GetPrimAtPath(path) if stage is not None and path is not None else None
        if stage is None or not prim or prim.IsInstanceProxy():
            self.report({"WARNING"}, "Select a prim that isn't inside an instance")
            return {"CANCELLED"}
        attribute_index = 0
        while prim.HasProperty(f"added_{attribute_index}"):
            attribute_index += 1
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            prim.CreateAttribute(f"added_{attribute_index}", Sdf.ValueTypeNames.Float, custom=True).Set(1.0)
        return {"FINISHED"}  # the property viewers see the change through their notices


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
        row.operator(DemoOpenPropertiesTestStage.bl_idname, icon="PROPERTIES", text="Properties")
        row.operator(DemoOpenStage.bl_idname, icon="FILE_FOLDER", text="Open")
        row.operator(DemoGenerateStage.bl_idname, icon="ADD", text="Generate")
        row = layout.row(align=True)
        row.enabled = _DemoState.stage is not None
        row.operator(DemoAddChildPrim.bl_idname, icon="PLUS", text="Add Child")
        row.operator(DemoToggleActive.bl_idname, icon="HIDE_OFF", text="Toggle Active")
        row.operator(DemoAddAttribute.bl_idname, icon="ADD", text="Add Attribute")
        display.draw_tree(layout, context, VIEW_NAMES_BY_EDITOR[self.bl_space_type])


class DemoPropertiesPanel:
    """The properties of the prim the tree selects, from the property viewer."""

    bl_label = "Property Viewer"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_space_type: str
    layout: Any

    def draw(self, context: Any) -> None:
        """Draw the editor's property viewer view."""
        layout: Any = self.layout  # never None while drawing
        property_display.draw_properties(layout, context, PROPERTY_VIEW_NAMES_BY_EDITOR[self.bl_space_type])


class DemoPropertyMetadataPanel:
    """A summary of the property the property viewer selects."""

    bl_label = "Property Metadata"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_space_type: str
    layout: Any

    def draw(self, context: Any) -> None:
        """Draw the editor's property viewer view's metadata."""
        layout: Any = self.layout  # never None while drawing
        property_display.draw_metadata(layout, context, PROPERTY_VIEW_NAMES_BY_EDITOR[self.bl_space_type])


class DemoViewportTreePanel(DemoTreePanel, bpy.types.Panel):
    """The tree in the 3D View's sidebar."""

    bl_idname = "VIEW3D_PT_scene_graph_demo_tree"
    bl_space_type = "VIEW_3D"


class DemoViewportPropertiesPanel(DemoPropertiesPanel, bpy.types.Panel):
    """The property viewer in the 3D View's sidebar."""

    bl_idname = "VIEW3D_PT_scene_graph_demo_properties"
    bl_space_type = "VIEW_3D"


class DemoViewportPropertyMetadataPanel(DemoPropertyMetadataPanel, bpy.types.Panel):
    """The property metadata in the 3D View's sidebar."""

    bl_idname = "VIEW3D_PT_scene_graph_demo_property_metadata"
    bl_space_type = "VIEW_3D"


class DemoNodeEditorTreePanel(DemoTreePanel, bpy.types.Panel):
    """The tree in the node editor's sidebar."""

    bl_idname = "NODE_PT_scene_graph_demo_tree"
    bl_space_type = "NODE_EDITOR"


class DemoNodeEditorPropertiesPanel(DemoPropertiesPanel, bpy.types.Panel):
    """The property viewer in the node editor's sidebar."""

    bl_idname = "NODE_PT_scene_graph_demo_properties"
    bl_space_type = "NODE_EDITOR"


class DemoNodeEditorPropertyMetadataPanel(DemoPropertyMetadataPanel, bpy.types.Panel):
    """The property metadata in the node editor's sidebar."""

    bl_idname = "NODE_PT_scene_graph_demo_property_metadata"
    bl_space_type = "NODE_EDITOR"


CLASSES = (
    DemoOpenTestStage,
    DemoOpenPropertiesTestStage,
    DemoOpenStage,
    DemoGenerateStage,
    DemoAddChildPrim,
    DemoToggleActive,
    DemoAddAttribute,
    # Each editor's panels, in the order they show.
    DemoViewportTreePanel,
    DemoViewportPropertiesPanel,
    DemoViewportPropertyMetadataPanel,
    DemoNodeEditorTreePanel,
    DemoNodeEditorPropertiesPanel,
    DemoNodeEditorPropertyMetadataPanel,
)


def register() -> None:
    """Register the widgets, create each editor's views, and register the host's panels and frame handler."""
    display.register()
    property_display.register()
    for editor_type, view_name in VIEW_NAMES_BY_EDITOR.items():
        property_view_name = PROPERTY_VIEW_NAMES_BY_EDITOR[editor_type]
        display.create_view(view_name, _shows_view(editor_type), _show_selected_prim(view_name, property_view_name))
        property_display.create_view(
            property_view_name,
            _shows_view(editor_type),
            _print_selection(property_view_name),
            _jump_to_target(view_name, property_view_name),
        )
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.frame_change_post.append(_frame_changed)
    scene = bpy.context.scene
    if scene is not None:
        _frame_changed(scene)


def unregister() -> None:
    """Undo register; the widgets remove their views."""
    bpy.app.handlers.frame_change_post.remove(_frame_changed)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    property_display.unregister()
    display.unregister()
    _DemoState.stage = None


def open_test_stage() -> Usd.Stage:
    """Open the test stage with its Prop_Unloaded payload unloaded, as a file can't leave it."""
    stage = Usd.Stage.Open(str(TEST_STAGE))
    stage.Unload(UNLOADED_PRIM_PATH)
    return stage


def main() -> None:
    """Register, then show the stage named after `--`, or the test stage."""
    register()
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if not arguments:
        _show(open_test_stage())
        return
    stage = Usd.Stage.Open(arguments[0])
    if stage is None:
        raise SystemExit(f"could not open {arguments[0]}")
    _show(stage)


if __name__ == "__main__":
    main()
