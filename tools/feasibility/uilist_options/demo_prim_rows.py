"""The rows each UIList options demo draws: every prim of the scene graph test stage, fully expanded.

The demos compare ways a UIList can show a prim, so they share one flat list of prims and leave expanding and
collapsing to the widget. Each row item stores its prim's index into `DemoRowsState.prims`; a demo reads the prim
from there. Its tooltip is computed on hover, as the widget's is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy
from pxr import Sdf, Usd

ROOT = Path(__file__).resolve().parents[3]
TEST_STAGE = ROOT / "tests" / "fixtures" / "scenes" / "scene_graph" / "prim_kinds.usda"
CATEGORY = "UIList Demo"  # the sidebar tab every demo's panels are on
ROWS_PROPERTY = "uilist_demo_rows"  # the WindowManager's DemoRowsProperties


@dataclass(frozen=True)
class DemoPrim:
    """What the demos draw of one prim, read once when the stage opens."""

    path: Sdf.Path
    depth: int
    type_name: str
    specifier: Sdf.Specifier
    is_active: bool
    model_kind: str
    has_payload: bool
    is_loaded: bool
    has_references: bool
    has_inherits: bool
    has_specializes: bool
    has_variants: bool
    is_instance: bool
    is_instance_proxy: bool

    @property
    def name(self) -> str:
        """The prim's name."""
        return self.path.name

    @property
    def has_arcs(self) -> bool:
        """Whether the prim has any composition arc: a payload, references, inherits, specializes, or variants."""
        return any((self.has_payload, self.has_references, self.has_inherits, self.has_specializes, self.has_variants))


class DemoRowsState:
    """The stage's prims, in traversal order; row items index into them."""

    stage: Usd.Stage | None = None
    prims: list[DemoPrim] = []  # noqa: RUF012 (class-level state, as the widget's states are)


def read_demo_prims(stage: Usd.Stage) -> list[DemoPrim]:
    """Every prim on the stage, instance proxies included, in depth-first order."""
    predicate = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
    prims = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), predicate):
        if prim.IsPseudoRoot():
            continue
        prims.append(
            DemoPrim(
                path=prim.GetPath(),
                depth=prim.GetPath().pathElementCount - 1,
                type_name=str(prim.GetTypeName()),
                specifier=prim.GetSpecifier(),
                is_active=prim.IsActive(),
                model_kind=str(Usd.ModelAPI(prim).GetKind()),
                has_payload=prim.HasPayload(),
                is_loaded=prim.IsLoaded(),
                has_references=prim.HasAuthoredReferences(),
                has_inherits=prim.HasAuthoredInherits(),
                has_specializes=prim.HasAuthoredSpecializes(),
                has_variants=bool(prim.GetVariantSets().GetNames()),
                is_instance=prim.IsInstance(),
                is_instance_proxy=prim.IsInstanceProxy(),
            )
        )
    return prims


def demo_prim(row_item: Any) -> DemoPrim | None:
    """The prim a row item stands for."""
    prim_index = row_item.prim_index
    return DemoRowsState.prims[prim_index] if 0 <= prim_index < len(DemoRowsState.prims) else None


def prim_tooltip(prim: DemoPrim) -> str:
    """A tooltip naming everything the demos know of a prim."""
    lines = [str(prim.path), f"{prim.type_name or 'No type'}, {prim.specifier.displayName}"]
    facts = [
        ("Inactive", not prim.is_active),
        (f"Kind: {prim.model_kind}", bool(prim.model_kind)),
        (f"Payload ({'loaded' if prim.is_loaded else 'unloaded'})", prim.has_payload),
        ("References", prim.has_references),
        ("Inherits", prim.has_inherits),
        ("Specializes", prim.has_specializes),
        ("Variants", prim.has_variants),
        ("Instance", prim.is_instance),
        ("Instance proxy", prim.is_instance_proxy),
    ]
    lines.extend(text for text, is_shown in facts if is_shown)
    return "\n".join(lines)


def _row_tooltip(row_item: Any) -> str:
    prim = demo_prim(row_item)
    return prim_tooltip(prim) if prim is not None else ""


class DemoRowItem(bpy.types.PropertyGroup):
    """One row: its name, which the built-in name filter reads, and its prim's index."""

    prim_index: bpy.props.IntProperty(default=-1)  # ty: ignore[invalid-type-form]
    tooltip: bpy.props.StringProperty(get=_row_tooltip)  # ty: ignore[invalid-type-form]


class DemoRowsProperties(bpy.types.PropertyGroup):
    """The rows a demo list draws, and its active row."""

    rows: bpy.props.CollectionProperty(type=DemoRowItem)  # ty: ignore[invalid-type-form]
    active_row_index: bpy.props.IntProperty(default=-1)  # ty: ignore[invalid-type-form]


def rows_properties(context: Any) -> Any:
    """The window manager's DemoRowsProperties."""
    return getattr(context.window_manager, ROWS_PROPERTY)


def open_demo_stage(stage_path: Path = TEST_STAGE, load_payloads: bool = True) -> None:
    """Open a stage, with its payloads loaded or not, and make one row item per prim."""
    load_set = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = Usd.Stage.Open(str(stage_path), load_set)
    DemoRowsState.stage = stage
    DemoRowsState.prims = read_demo_prims(stage)
    fill_rows(1)


def fill_rows(stage_copies: int) -> None:
    """Make one row item per prim, repeating the stage's rows to try a list's costs at length."""
    properties = rows_properties(bpy.context)
    properties.rows.clear()
    for _ in range(stage_copies):
        for prim_index, prim in enumerate(DemoRowsState.prims):
            row_item = properties.rows.add()
            row_item.name = prim.name
            row_item.prim_index = prim_index


def indent(layout: Any, prim: DemoPrim) -> None:
    """Indent a row for its prim's depth, as the widget does: one small separator per level."""
    for _ in range(prim.depth):
        layout.separator(factor=2.0)


def register_rows() -> None:
    """Register the row classes and the window manager's rows, and fill them from the test stage."""
    bpy.utils.register_class(DemoRowItem)
    bpy.utils.register_class(DemoRowsProperties)
    setattr(bpy.types.WindowManager, ROWS_PROPERTY, bpy.props.PointerProperty(type=DemoRowsProperties))
    open_demo_stage()


def unregister_rows() -> None:
    """Remove what register_rows added."""
    delattr(bpy.types.WindowManager, ROWS_PROPERTY)
    bpy.utils.unregister_class(DemoRowsProperties)
    bpy.utils.unregister_class(DemoRowItem)
