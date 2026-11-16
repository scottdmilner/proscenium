"""Incremental fixtures: the scenes M7's incremental refresh is checked on, from scenes/incremental/.

- no_op_refresh (F-NO-OP-REFRESH): one drawn copy of each kind M7's application makes, for refreshes that
  change nothing: a mesh, a sheared mesh, a placeholder box, an empty marker, an invisible mesh, a render-only
  mesh, a guide-only mesh that isn't drawn, and a prototype's mesh drawn through two native instances.
- same_values (F-SAME-VALUES): a translate and a visibility sampled with equal values at different time codes,
  and a mesh nothing varies on.
- unmanaged_user (F-UNMANAGED-USER): drawn copies a test gives unmanaged users in Blender (a user of a bounds
  mesh, an unmanaged parent, and an unmanaged object beside them in the destination), and an edit to them.

Each copies its layers from Scene.INCREMENTAL, opens them as the caller's live stage, and yields what the scene
is built to display, written out from the layer by hand. tests/bpy_free/test_incremental_fixtures.py checks these
against USD's own APIs.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Gf, Vt

from support.time_codes import TimeVariation
from support.usd import open_stage_without_cache

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pxr import Usd


@dataclass(frozen=True)
class DrawnCopy:
    """What a drawn copy is built to be: its source prim, and how the display shows it."""

    source_path: str  # its source entity: an instance-proxy path for a copy inside instance contents
    instance_context: tuple[str, ...]  # the native-instance roots it's drawn through, outermost first
    sheared: bool  # its world matrix shears it, so its copy has a shear parent
    placeholder: bool  # an untranslated type, shown as a box of its bounds, or a marker without them
    has_bounds: bool  # a marker when a placeholder has none
    visible_in_viewport: bool
    visible_in_render: bool


@dataclass
class NoOpRefreshScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    copies: tuple[DrawnCopy, ...]  # every drawn copy, in source order
    not_drawn: frozenset[str]  # prims with geometry that neither destination's purposes include
    placeholder_paths: frozenset[str]  # each with an untranslated-type diagnostic; a marker also warns


@contextmanager
def no_op_refresh(dest: Path) -> Generator[NoOpRefreshScene]:
    """F-NO-OP-REFRESH: see scenes/incremental/no_op_refresh.usda."""
    root = copy_scene(Scene.INCREMENTAL, dest) / "no_op_refresh.usda"

    def mesh(path: str, *, sheared: bool = False, viewport: bool = True, render: bool = True) -> DrawnCopy:
        return DrawnCopy(path, (), sheared, False, True, viewport, render)

    def crate(instance: str) -> DrawnCopy:
        return DrawnCopy(f"{instance}/Box", (instance,), False, False, True, True, True)

    yield NoOpRefreshScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        copies=(
            mesh("/World/Plain"),
            mesh("/World/Sheared", sheared=True),
            DrawnCopy("/World/Curves", (), False, True, True, True, True),
            DrawnCopy("/World/Fog", (), False, True, False, True, True),
            mesh("/World/Hidden", viewport=False, render=False),
            mesh("/World/RenderOnly", viewport=False),
            crate("/World/Instances/Left"),
            crate("/World/Instances/Right"),
        ),
        not_drawn=frozenset({"/World/GuideOnly"}),
        placeholder_paths=frozenset({"/World/Curves", "/World/Fog"}),
    )


# --- F-SAME-VALUES -------------------------------------------------------------------------------------------

HELD, BLINK, STILL = "/World/Held", "/World/Blink", "/World/Still"


@dataclass
class SameValuesScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    variation: TimeVariation
    # Pairs of time codes at which every drawn copy evaluates the same: a synchronization at one, then the other,
    # writes nothing.
    equal_time_codes: tuple[tuple[float | None, float | None], ...]  # None: the default time code

    def held_x(self, time_code: float | None) -> float:
        """Held's x translation: 0 at the default time code, linear between its samples (0, 5, 5, 0 at 0 to 30)."""
        if time_code is None or time_code <= 0.0 or time_code >= 30.0:
            return 0.0
        if time_code <= 10.0:
            return 0.5 * time_code
        if time_code <= 20.0:
            return 5.0
        return 0.5 * (30.0 - time_code)

    def blink_visible(self, time_code: float | None) -> bool:
        """Blink is invisible from 10 until 20; visible at the default time code."""
        return time_code is None or not 10.0 <= time_code < 20.0

    def changed_copies(self, first: float | None, second: float | None) -> frozenset[str]:
        """The drawn copies whose content differs between two time codes: never Still."""
        changed = set()
        if self.held_x(first) != self.held_x(second):
            changed.add(HELD)
        if self.blink_visible(first) != self.blink_visible(second):
            changed.add(BLINK)
        return frozenset(changed)


@contextmanager
def same_values(dest: Path) -> Generator[SameValuesScene]:
    """F-SAME-VALUES: see scenes/incremental/same_values.usda."""
    root = copy_scene(Scene.INCREMENTAL, dest) / "same_values.usda"
    yield SameValuesScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        variation=TimeVariation(
            start=0.0, end=30.0, authored_sample_time_codes=(0.0, 10.0, 20.0, 30.0), transitions=(10.0, 20.0)
        ),
        equal_time_codes=((10.0, 15.0), (12.5, 17.5), (0.0, None)),
    )


# --- F-UNMANAGED-USER ----------------------------------------------------------------------------------------

USED, CHILD = "/World/Used", "/World/Child"


@dataclass
class UnmanagedUserScene:
    """What a test builds the unmanaged users from, and what the edit changes.

    A test synchronizes, then gives Used's bounds mesh to an unmanaged object, parents Child's managed object
    to an unmanaged empty, and links an unmanaged object into the destination, before refreshing or removing.
    """

    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    copies: tuple[str, ...]  # every drawn copy's source path, in source order
    used_extent: tuple[Gf.Vec3f, Gf.Vec3f]  # Used's local bounds before the edit
    edited_used_extent: tuple[Gf.Vec3f, Gf.Vec3f]  # and after
    child_translation: Gf.Vec3d  # Child's world translation before the edit
    edited_child_translation: Gf.Vec3d  # and after

    def edit(self) -> None:
        """Grow Used's extent and move Child, in the root layer in memory, as a caller editing it would."""
        layer = self.stage.GetRootLayer()
        layer.GetAttributeAtPath(f"{USED}.extent").default = Vt.Vec3fArray(self.edited_used_extent)
        layer.GetAttributeAtPath(f"{CHILD}.xformOp:translate").default = self.edited_child_translation


@contextmanager
def unmanaged_user(dest: Path) -> Generator[UnmanagedUserScene]:
    """F-UNMANAGED-USER: see scenes/incremental/unmanaged_user.usda."""
    root = copy_scene(Scene.INCREMENTAL, dest) / "unmanaged_user.usda"
    yield UnmanagedUserScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        copies=(USED, CHILD, "/World/Still"),
        used_extent=(Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 1, 1)),
        edited_used_extent=(Gf.Vec3f(0, 0, 0), Gf.Vec3f(2, 2, 2)),
        child_translation=Gf.Vec3d(3, 0, 0),
        edited_child_translation=Gf.Vec3d(3, 3, 0),
    )
