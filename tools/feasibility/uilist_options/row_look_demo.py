"""Demo of a row's look: the layout attributes that change how a row's text, icons, and buttons draw.

    Blender --python tools/feasibility/uilist_options/row_look_demo.py

Open the 3D View's sidebar (N) and its "UIList Demo" tab. The list shows the test stage's prims, each row an indented
name, a type button, and a payload button where the prim has one. Below it, each attribute is tied to a prim fact,
so the list shows what each would say about a stage:
- **Layout states:** `active = False` (dim), `enabled = False` (dim, and its buttons stop taking clicks), and
  `alert = True` (red), each set when a chosen fact holds, on the whole row, the name, or the buttons.
- **Buttons:** the type and payload buttons' `emboss` style, and `depress` when a chosen fact holds.
- **Size and alignment:** the row's `scale_y`, the buttons' `scale_x`, a fixed `ui_units_x` for the type column,
  and its `alignment`.

Each row's state comes from its prim, read in `draw_item`, as the widget's does. **Unload Payloads** opens the stage
with its payloads unloaded, so the unloaded fact has rows to mark.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy
from pxr import Sdf

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_prim_rows  # noqa: E402 (found through the path inserted above)

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

SETTINGS_PROPERTY = "uilist_demo_row_look"
VISIBLE_ROW_COUNT = 14
# The prim facts an attribute can be tied to.
PRIM_FACTS = [
    ("NONE", "Never", "The attribute is never set"),
    ("NOT_DEFINED", "Not a def", "Inactive, an over, or a class: the widget's dim rule"),
    ("INACTIVE", "Inactive", "The prim is deactivated"),
    ("OVER_OR_CLASS", "Over or class", "The prim's specifier is over or class"),
    ("UNLOADED", "Unloaded payload", "The prim's payload is unloaded"),
    ("INSTANCE", "Instance", "The prim is an instance"),
    ("INSTANCE_PROXY", "Instance proxy", "The prim is inside an instance"),
    ("HAS_ARCS", "Has arcs", "The prim has a payload, references, inherits, specializes, or variants"),
    ("ANCESTOR_OF_ACTIVE", "Ancestor of active", "The prim is an ancestor of the active row's prim"),
    ("NOT_MARKED", "Name not marked", "The prim's name doesn't contain the mark text, as unmatched search ancestors"),
]
SCOPES = [
    ("ROW", "Row", "The whole row"),
    ("NAME", "Name", "The indented name and its icon"),
    ("BUTTONS", "Buttons", "The type and payload buttons"),
]
EMBOSS_STYLES = [
    ("NONE", "None", "Bare text and icons, as the widget's badges"),
    ("NORMAL", "Normal", "A button's usual box"),
    ("PULLDOWN_MENU", "Pulldown", "A menu item's look"),
    ("PIE_MENU", "Pie", "A pie menu item's dark background"),
    ("NONE_OR_STATUS", "None or Status", "Bare, but colored by a property's animated, keyed, or driven state"),
]
ALIGNMENTS = [("EXPAND", "Expand", ""), ("LEFT", "Left", ""), ("CENTER", "Center", ""), ("RIGHT", "Right", "")]
# Each layout state's attribute, the value it takes when its fact holds, and its settings' prefix.
LAYOUT_STATES = (
    ("active", False, "dim", "Dim (active = False)"),
    ("enabled", False, "disabled", "Disabled (enabled = False)"),
    ("alert", True, "alert", "Alert (alert = True)"),
)


def _reopen_stage(settings: Any, _context: Any) -> None:
    demo_prim_rows.open_demo_stage(load_payloads=not settings.unload_payloads)


def _fact_property(name: str, default: str) -> Any:
    return bpy.props.EnumProperty(name=name, items=PRIM_FACTS, default=default)


def _scope_property() -> Any:
    return bpy.props.EnumProperty(name="On", items=SCOPES)


class RowLookSettings(bpy.types.PropertyGroup):
    """Which prim fact sets each attribute, and where; the buttons' style; and the row's sizes."""

    dim_fact: _fact_property("Dim", "NOT_DEFINED")  # ty: ignore[invalid-type-form]
    dim_scope: _scope_property()  # ty: ignore[invalid-type-form]
    disabled_fact: _fact_property("Disabled", "NONE")  # ty: ignore[invalid-type-form]
    disabled_scope: _scope_property()  # ty: ignore[invalid-type-form]
    alert_fact: _fact_property("Alert", "NONE")  # ty: ignore[invalid-type-form]
    alert_scope: _scope_property()  # ty: ignore[invalid-type-form]
    mark_text: bpy.props.StringProperty(name="Mark", default="crate", options={"TEXTEDIT_UPDATE"})  # ty: ignore[invalid-type-form]
    button_emboss: bpy.props.EnumProperty(name="Emboss", items=EMBOSS_STYLES)  # ty: ignore[invalid-type-form]
    depress_fact: _fact_property("Depress", "ANCESTOR_OF_ACTIVE")  # ty: ignore[invalid-type-form]
    row_scale_y: bpy.props.FloatProperty(name="Row scale_y", default=1.0, min=0.5, max=2.0)  # ty: ignore[invalid-type-form]
    button_scale_x: bpy.props.FloatProperty(name="Buttons scale_x", default=1.0, min=0.5, max=2.0)  # ty: ignore[invalid-type-form]
    use_type_width: bpy.props.BoolProperty(name="Fixed Type Width", default=False)  # ty: ignore[invalid-type-form]
    type_width_units: bpy.props.FloatProperty(name="ui_units_x", default=4.0, min=1.0, max=10.0)  # ty: ignore[invalid-type-form]
    type_alignment: bpy.props.EnumProperty(name="Alignment", items=ALIGNMENTS, default="RIGHT")  # ty: ignore[invalid-type-form]
    unload_payloads: bpy.props.BoolProperty(name="Unload Payloads", update=_reopen_stage)  # ty: ignore[invalid-type-form]


def _settings(context: Any) -> Any:
    return getattr(context.window_manager, SETTINGS_PROPERTY)


def _active_path(context: Any) -> Sdf.Path | None:
    properties = demo_prim_rows.rows_properties(context)
    row_index = properties.active_row_index
    if not 0 <= row_index < len(properties.rows):
        return None
    prim = demo_prim_rows.demo_prim(properties.rows[row_index])
    return prim.path if prim is not None else None


def _fact_holds(fact: str, prim: demo_prim_rows.DemoPrim, active_path: Sdf.Path | None, mark_text: str) -> bool:
    is_over_or_class = prim.specifier in (Sdf.SpecifierOver, Sdf.SpecifierClass)
    holds_by_fact = {
        "NONE": False,
        "NOT_DEFINED": not prim.is_active or is_over_or_class,
        "INACTIVE": not prim.is_active,
        "OVER_OR_CLASS": is_over_or_class,
        "UNLOADED": prim.has_payload and not prim.is_loaded,
        "INSTANCE": prim.is_instance,
        "INSTANCE_PROXY": prim.is_instance_proxy,
        "HAS_ARCS": prim.has_arcs,
        "ANCESTOR_OF_ACTIVE": active_path is not None and active_path != prim.path and active_path.HasPrefix(prim.path),
        "NOT_MARKED": bool(mark_text) and mark_text.lower() not in prim.name.lower(),
    }
    return holds_by_fact[fact]


class RowButton(bpy.types.Operator):
    """A row's type or payload button: it does nothing, and its tooltip names what it shows."""

    bl_idname = "uilist_demo.row_button"
    bl_label = "Row Button"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    button_name: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]

    @classmethod
    @override
    def description(cls, context: Any, properties: Any) -> str:
        prims = demo_prim_rows.DemoRowsState.prims
        if not 0 <= properties.prim_index < len(prims):
            return ""
        prim = prims[properties.prim_index]
        if properties.button_name == "payload":
            return f"Payload ({'loaded' if prim.is_loaded else 'unloaded'}) on {prim.path}"
        return f"{prim.type_name or 'No type'}: {prim.path}"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        return {"FINISHED"}


class RowLookList(bpy.types.UIList):
    """Draws each row with the attributes the settings tie to its prim's facts."""

    bl_idname = "UILIST_DEMO_UL_row_look"

    @override
    def draw_item(
        self,
        context: bpy.types.Context | None,
        layout: Any,
        data: Any,
        item: Any,
        icon: int | None,
        active_data: Any,
        active_property: str | None,
        index: int | None,
        flt_flag: int | None,
    ) -> None:
        prim = demo_prim_rows.demo_prim(item)
        if prim is None:
            return
        settings = _settings(context)
        active_path = _active_path(context)
        row = layout.row()
        row.scale_y = settings.row_scale_y
        split = row.split(factor=0.65)
        name_row = split.row(align=True)
        buttons = split.row(align=True)
        layouts_by_scope = {"ROW": row, "NAME": name_row, "BUTTONS": buttons}
        for attribute, value, prefix, _label in LAYOUT_STATES:
            if _fact_holds(getattr(settings, f"{prefix}_fact"), prim, active_path, settings.mark_text):
                setattr(layouts_by_scope[getattr(settings, f"{prefix}_scope")], attribute, value)
        demo_prim_rows.indent(name_row, prim)
        name_row.label(text=prim.name, icon="OUTLINER_DATA_EMPTY" if not prim.type_name else "OBJECT_DATA")
        buttons.alignment = settings.type_alignment
        buttons.scale_x = settings.button_scale_x
        buttons.emboss = settings.button_emboss
        is_depressed = _fact_holds(settings.depress_fact, prim, active_path, settings.mark_text)
        type_column = buttons.row(align=True)
        if settings.use_type_width:
            type_column.ui_units_x = settings.type_width_units
        type_button = type_column.operator(RowButton.bl_idname, text=prim.type_name or "—", depress=is_depressed)
        type_button.prim_index = item.prim_index
        type_button.button_name = "type"
        payload_column = buttons.row(align=True)
        payload_column.ui_units_x = 1.0
        if prim.has_payload:
            payload_icon = "PACKAGE" if prim.is_loaded else "UGLYPACKAGE"
            payload_button = payload_column.operator(
                RowButton.bl_idname, text="", icon=payload_icon, depress=is_depressed
            )
            payload_button.prim_index = item.prim_index
            payload_button.button_name = "payload"
        else:
            payload_column.label(text="", icon="BLANK1")


class RowLookPanel(bpy.types.Panel):
    """The list, then each attribute's settings."""

    bl_idname = "VIEW3D_PT_uilist_demo_row_look"
    bl_label = "2. A Row's Look"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = demo_prim_rows.CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        settings = _settings(context)
        properties = demo_prim_rows.rows_properties(context)
        layout.template_list(
            RowLookList.bl_idname,
            "",
            properties,
            "rows",
            properties,
            "active_row_index",
            item_dyntip_propname="tooltip",
            rows=VISIBLE_ROW_COUNT,
            maxrows=VISIBLE_ROW_COUNT,
        )
        layout.prop(settings, "unload_payloads")
        states = layout.box().column()
        states.label(text="Layout states, each set when its fact holds")
        for _attribute, _value, prefix, label in LAYOUT_STATES:
            states.label(text=label)
            row = states.row(align=True)
            row.prop(settings, f"{prefix}_fact", text="")
            row.prop(settings, f"{prefix}_scope", text="")
        states.prop(settings, "mark_text")
        buttons = layout.box().column()
        buttons.label(text="The type and payload buttons")
        buttons.prop(settings, "button_emboss", text="")
        buttons.prop(settings, "depress_fact")
        sizes = layout.box().column()
        sizes.label(text="Size and alignment")
        sizes.prop(settings, "row_scale_y")
        sizes.prop(settings, "button_scale_x")
        row = sizes.row(align=True)
        row.prop(settings, "use_type_width")
        sub = row.row(align=True)
        sub.active = settings.use_type_width
        sub.prop(settings, "type_width_units")
        sizes.prop(settings, "type_alignment", expand=True)


CLASSES = (RowLookSettings, RowButton, RowLookList, RowLookPanel)


def main() -> None:
    """Register the demo and fill its rows."""
    demo_prim_rows.register_rows()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.WindowManager, SETTINGS_PROPERTY, bpy.props.PointerProperty(type=RowLookSettings))


if __name__ == "__main__":
    main()
