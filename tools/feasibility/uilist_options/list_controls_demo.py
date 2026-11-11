"""Demo of the list's filter flags: what `filter_items` can work out for each row, and hand to `draw_item`.

    Blender --python tools/feasibility/uilist_options/list_controls_demo.py

Open the 3D View's sidebar (N) and its "UIList Demo" tab. The panel explains `flt_flag`, lets each of six of the
list's own bits be turned on and off, and shows how long `filter_items` takes and how often it runs. The list is a
`DEFAULT` list in the stage's order, with row tooltips and an active row, as the widget's is.

A `UIList`'s `filter_items` runs before the list draws, over every item, and returns one integer of flags per item.
Blender reads the upper 16 bits: `bitflag_filter_item` shows a row, and `bitflag_item_never_show` leaves it out. The
lower 16 bits are the list's own, and `draw_item` gets them back as `flt_flag`. So `filter_items`, which sees every
row at once, can work out what one row's `draw_item` can't: how it relates to the rows around it and to the active
row. The bits here:
- **Has arcs** and **Instance:** read from the row's own prim, to compare with reading it in `draw_item`.
- **Inside a payload:** inherited from an ancestor's row.
- **Ancestor of active:** depends on the active row, so changes as the selection moves.
- **Last sibling:** whether a later row has the same parent, which needs the rows after it; drawn as a guide glyph.
- **Name mark:** a name containing the text box's text is marked, and nothing is hidden.

And one of Blender's bits: **Hide inactive** clears `bitflag_filter_item` on inactive prims' rows.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, override

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_prim_rows  # noqa: E402 (found through the path inserted above)

SETTINGS_PROPERTY = "uilist_demo_list_controls"
VISIBLE_ROW_COUNT = 12
# The list's own bits, in the lower 16 bits of each row's filter flags.
HAS_ARCS_BIT = 1 << 0
INSTANCE_BIT = 1 << 1
INSIDE_PAYLOAD_BIT = 1 << 2
ANCESTOR_OF_ACTIVE_BIT = 1 << 3
LAST_SIBLING_BIT = 1 << 4
NAME_MARK_BIT = 1 << 5
# Each bit's toggle, label, and the icon a row draws for it.
BIT_LEGEND = (
    ("use_has_arcs", "Has arcs", "COLORSET_02_VEC", HAS_ARCS_BIT),
    ("use_instance", "Instance or instance proxy", "COLORSET_04_VEC", INSTANCE_BIT),
    ("use_inside_payload", "Inside a payload (from an ancestor)", "PACKAGE", INSIDE_PAYLOAD_BIT),
    ("use_ancestor_of_active", "Ancestor of the active row", "LAYER_ACTIVE", ANCESTOR_OF_ACTIVE_BIT),
    ("use_name_mark", "Name contains the text below", "VIEWZOOM", NAME_MARK_BIT),
)
EXPLANATION = (
    "Before the list draws, filter_items runs",
    "over every item and returns one integer",
    "of flags per item.",
    "Blender reads the upper 16 bits: one bit",
    "shows the row, another leaves it out.",
    "The lower 16 bits are the list's own:",
    "draw_item gets them back as flt_flag.",
    "filter_items sees every row at once, so",
    "it can mark what one row's draw can't",
    "know: its neighbors, its ancestors, and",
    "the active row.",
)


class FilterCallState:
    """How often filter_items has run, and how long its last run took."""

    call_count = 0
    last_duration_seconds = 0.0
    last_item_count = 0
    last_was_cached = False
    # The last flags computed, and what they were computed from, for returning them again unchanged.
    cached_flags: list[int] = []  # noqa: RUF012 (class-level state)
    cached_inputs: tuple[Any, ...] = ()


def _refill_rows(settings: Any, _context: Any) -> None:
    demo_prim_rows.fill_rows(settings.stage_copies)


class ListControlsSettings(bpy.types.PropertyGroup):
    """Which of the list's bits filter_items sets, and the rows it runs over."""

    use_has_arcs: bpy.props.BoolProperty(default=True)  # ty: ignore[invalid-type-form]
    use_instance: bpy.props.BoolProperty(default=True)  # ty: ignore[invalid-type-form]
    use_inside_payload: bpy.props.BoolProperty(default=True)  # ty: ignore[invalid-type-form]
    use_ancestor_of_active: bpy.props.BoolProperty(default=True)  # ty: ignore[invalid-type-form]
    use_last_sibling: bpy.props.BoolProperty(name="Last sibling: guide glyphs", default=True)  # ty: ignore[invalid-type-form]
    use_name_mark: bpy.props.BoolProperty(default=True)  # ty: ignore[invalid-type-form]
    name_mark_text: bpy.props.StringProperty(name="Mark", default="crate", options={"TEXTEDIT_UPDATE"})  # ty: ignore[invalid-type-form]
    hide_inactive: bpy.props.BoolProperty(name="Hide inactive (clears bitflag_filter_item)")  # ty: ignore[invalid-type-form]
    use_cached_flags: bpy.props.BoolProperty(  # ty: ignore[invalid-type-form]
        name="Reuse Flags",
        description="Return the last flags again while nothing they depend on changed, as a model could keep them",
    )
    stage_copies: bpy.props.IntProperty(  # ty: ignore[invalid-type-form]
        name="Stage Copies",
        description="Repeat the stage's rows, to time filter_items",
        default=1,
        min=1,
        max=20000,
        update=_refill_rows,
    )


def _settings(context: Any) -> Any:
    return getattr(context.window_manager, SETTINGS_PROPERTY)


def _last_sibling_flags(depths: list[int]) -> list[bool]:
    """For each row, whether no later row shares its parent: a reverse pass, one pending flag per depth."""
    has_later_sibling_at_depth: dict[int, bool] = {}
    is_last = [True] * len(depths)
    for row_index in range(len(depths) - 1, -1, -1):
        depth = depths[row_index]
        is_last[row_index] = not has_later_sibling_at_depth.get(depth, False)
        has_later_sibling_at_depth[depth] = True
        for deeper in [d for d in has_later_sibling_at_depth if d > depth]:
            del has_later_sibling_at_depth[deeper]  # rows above this one at those depths have another parent
    return is_last


class FilterFlagsList(bpy.types.UIList):
    """Sets the list's own bits in filter_items, and draws each row from them."""

    bl_idname = "UILIST_DEMO_UL_filter_flags"

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
        flags = flt_flag or 0
        split = layout.split(factor=0.6)
        name_row = split.row(align=True)
        if settings.use_last_sibling and prim.depth > 0:
            for _ in range(prim.depth - 1):
                name_row.separator(factor=2.0)
            glyph = name_row.row(align=True)
            glyph.ui_units_x = 1.0  # a label in an aligned row otherwise takes an equal share of its width
            glyph.label(text="└" if flags & LAST_SIBLING_BIT else "├")
        else:
            demo_prim_rows.indent(name_row, prim)
        name_row.label(text=prim.name)
        marks = split.row(align=True)
        marks.alignment = "RIGHT"
        # Every enabled bit keeps its column, blank when unset, so marks line up down the list.
        for property_name, _label, mark_icon, bit in BIT_LEGEND:
            if getattr(settings, property_name):
                marks.label(text="", icon=mark_icon if flags & bit else "BLANK1")

    @override
    def filter_items(self, context: bpy.types.Context | None, data: Any, property: str) -> tuple[Any, Any]:  # noqa: A002 (Blender's name)
        started = time.perf_counter()
        settings = _settings(context)
        items = getattr(data, property)
        inputs = (
            *(getattr(settings, name) for name in ListControlsSettings.__annotations__ if name != "use_cached_flags"),
            data.active_row_index,
            len(items),
        )
        is_cached = settings.use_cached_flags and inputs == FilterCallState.cached_inputs
        if is_cached:
            filter_flags = FilterCallState.cached_flags
        else:
            filter_flags = self._compute_filter_flags(settings, data, items)
            FilterCallState.cached_flags, FilterCallState.cached_inputs = filter_flags, inputs
        FilterCallState.call_count += 1
        FilterCallState.last_duration_seconds = time.perf_counter() - started
        FilterCallState.last_item_count = len(items)
        FilterCallState.last_was_cached = is_cached
        return filter_flags, []  # no reordering: rows keep the stage's order

    def _compute_filter_flags(self, settings: Any, data: Any, items: Any) -> list[int]:
        prims = [demo_prim_rows.demo_prim(item) for item in items]
        payload_paths = {prim.path for prim in demo_prim_rows.DemoRowsState.prims if prim.has_payload}
        active_row_index = data.active_row_index
        active_prim = prims[active_row_index] if 0 <= active_row_index < len(prims) else None
        ancestor_paths = set(active_prim.path.GetPrefixes()[:-1]) if active_prim is not None else set()
        is_last_sibling = _last_sibling_flags([prim.depth if prim else 0 for prim in prims])
        mark_text = settings.name_mark_text.lower()
        filter_flags = []
        for row_index, prim in enumerate(prims):
            flags = self.bitflag_filter_item
            if prim is None:
                filter_flags.append(flags)
                continue
            if settings.hide_inactive and not prim.is_active:
                flags &= ~self.bitflag_filter_item
            if settings.use_has_arcs and prim.has_arcs:
                flags |= HAS_ARCS_BIT
            if settings.use_instance and (prim.is_instance or prim.is_instance_proxy):
                flags |= INSTANCE_BIT
            if settings.use_inside_payload and any(path in payload_paths for path in prim.path.GetPrefixes()[:-1]):
                flags |= INSIDE_PAYLOAD_BIT
            if settings.use_ancestor_of_active and prim.path in ancestor_paths:
                flags |= ANCESTOR_OF_ACTIVE_BIT
            if is_last_sibling[row_index]:
                flags |= LAST_SIBLING_BIT
            if settings.use_name_mark and mark_text and mark_text in prim.name.lower():
                flags |= NAME_MARK_BIT
            filter_flags.append(flags)
        return filter_flags


class ListControlsPanel(bpy.types.Panel):
    """The list, then the bit toggles and the explanation."""

    bl_idname = "VIEW3D_PT_uilist_demo_list_controls"
    bl_label = "1. The List: filter flags"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = demo_prim_rows.CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        settings = _settings(context)
        properties = demo_prim_rows.rows_properties(context)
        layout.template_list(
            FilterFlagsList.bl_idname,
            "",
            properties,
            "rows",
            properties,
            "active_row_index",
            item_dyntip_propname="tooltip",
            rows=VISIBLE_ROW_COUNT,
            maxrows=VISIBLE_ROW_COUNT,
        )
        row_index = properties.active_row_index
        prim = demo_prim_rows.demo_prim(properties.rows[row_index]) if 0 <= row_index < len(properties.rows) else None
        layout.label(text=f"Active: {prim.path}" if prim is not None else "No active row")
        bits = layout.box().column(align=True)
        bits.label(text="The list's own bits, and their marks")
        for property_name, label, mark_icon, _bit in BIT_LEGEND:
            row = bits.row(align=True)
            row.label(text="", icon=mark_icon)
            row.prop(settings, property_name, text=label)
        row = bits.row(align=True)
        row.label(text="", icon="BLANK1")
        row.prop(settings, "use_last_sibling")
        bits.prop(settings, "name_mark_text")
        bits.separator()
        bits.label(text="One of Blender's bits")
        bits.prop(settings, "hide_inactive")
        cost = layout.box().column(align=True)
        cost.prop(settings, "stage_copies")
        cost.prop(settings, "use_cached_flags")
        cost.label(
            text=f"filter_items: {FilterCallState.call_count} runs, last "
            f"{FilterCallState.last_duration_seconds * 1000:.2f} ms over {FilterCallState.last_item_count:,} items"
            f"{', reused' if FilterCallState.last_was_cached else ''}"
        )
        explanation = layout.box().column(align=True)
        explanation.scale_y = 0.8
        for line in EXPLANATION:
            explanation.label(text=line)


CLASSES = (ListControlsSettings, FilterFlagsList, ListControlsPanel)


def main() -> None:
    """Register the demo and fill its rows."""
    demo_prim_rows.register_rows()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.WindowManager, SETTINGS_PROPERTY, bpy.props.PointerProperty(type=ListControlsSettings))


if __name__ == "__main__":
    main()
