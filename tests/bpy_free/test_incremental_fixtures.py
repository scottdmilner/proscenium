"""The incremental fixture generators produce the scenes their docstrings claim, by USD's own APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Tf, Usd, UsdGeom

from fixtures import incremental
from support.time_codes import sampled

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

MESH, GPRIM = Tf.Type.Find(UsdGeom.Mesh), Tf.Type.Find(UsdGeom.Gprim)
VIEWPORT_PURPOSES = {UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy}  # the spec's defaults
RENDER_PURPOSES = {UsdGeom.Tokens.default_, UsdGeom.Tokens.render}


def _sheared(matrix: Gf.Matrix4d) -> bool:
    rows = [matrix.GetRow3(i) for i in range(3)]
    return any(abs(Gf.Dot(rows[i], rows[j])) > 1e-9 for i in range(3) for j in range(i + 1, 3))


@pytest.fixture
def no_op_refresh(tmp_path: Path) -> Iterator[incremental.NoOpRefreshScene]:
    with incremental.no_op_refresh(tmp_path) as scene:
        yield scene


def test_no_op_refresh_draws_every_gprim_but_the_guide(no_op_refresh: incremental.NoOpRefreshScene) -> None:
    gprims = {
        str(prim.GetPath())
        for prim in Usd.PrimRange(no_op_refresh.stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
        if prim.IsA(GPRIM)
    }
    drawn = {copy.source_path for copy in no_op_refresh.copies}
    assert gprims == drawn | no_op_refresh.not_drawn
    assert not drawn & no_op_refresh.not_drawn


def test_no_op_refresh_copies(no_op_refresh: incremental.NoOpRefreshScene) -> None:
    stage, cache = no_op_refresh.stage, UsdGeom.XformCache()
    for copy in no_op_refresh.copies:
        prim = stage.GetPrimAtPath(copy.source_path)
        imageable = UsdGeom.Imageable(prim)
        visible = imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
        purpose = imageable.ComputePurpose()
        assert copy.visible_in_viewport == (visible and purpose in VIEWPORT_PURPOSES), copy.source_path
        assert copy.visible_in_render == (visible and purpose in RENDER_PURPOSES), copy.source_path
        assert copy.sheared == _sheared(cache.GetLocalToWorldTransform(prim)), copy.source_path
        assert copy.placeholder == (not prim.IsA(MESH)), copy.source_path
        assert copy.placeholder == (copy.source_path in no_op_refresh.placeholder_paths)
        assert copy.has_bounds == UsdGeom.Boundable(prim).GetExtentAttr().HasAuthoredValue(), copy.source_path
        roots = [str(p.GetPath()) for p in _ancestors(prim) if p.IsInstance()]
        assert tuple(roots) == copy.instance_context, copy.source_path
        assert prim.IsInstanceProxy() == bool(copy.instance_context), copy.source_path


def test_no_op_refresh_guide_is_in_neither_destination(no_op_refresh: incremental.NoOpRefreshScene) -> None:
    for path in no_op_refresh.not_drawn:
        purpose = UsdGeom.Imageable(no_op_refresh.stage.GetPrimAtPath(path)).ComputePurpose()
        assert purpose not in VIEWPORT_PURPOSES | RENDER_PURPOSES


def _ancestors(prim: Usd.Prim) -> list[Usd.Prim]:
    """Prim's ancestors, outermost first, without the pseudo-root."""
    chain = []
    while (prim := prim.GetParent()) and not prim.IsPseudoRoot():
        chain.append(prim)
    return chain[::-1]


# --- F-SAME-VALUES -------------------------------------------------------------------------------------------


@pytest.fixture
def same_values(tmp_path: Path) -> Iterator[incremental.SameValuesScene]:
    with incremental.same_values(tmp_path) as scene:
        yield scene


def _usd_time(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _evaluated(stage: Usd.Stage, time_code: float | None) -> dict[str, tuple[Gf.Matrix4d, bool]]:
    """Each drawn mesh's world matrix and visibility at the time code, by USD."""
    cache = UsdGeom.XformCache(_usd_time(time_code))
    return {
        path: (
            cache.GetLocalToWorldTransform(prim := stage.GetPrimAtPath(path)),
            UsdGeom.Imageable(prim).ComputeVisibility(_usd_time(time_code)) != UsdGeom.Tokens.invisible,
        )
        for path in (incremental.HELD, incremental.BLINK, incremental.STILL)
    }


def _sampled(scene: incremental.SameValuesScene) -> tuple[float | None, ...]:
    return sampled("F-SAME-VALUES", scene.variation).time_codes


def test_same_values_held_and_blink(same_values: incremental.SameValuesScene) -> None:
    for time_code in _sampled(same_values):
        evaluated = _evaluated(same_values.stage, time_code)
        assert evaluated[incremental.HELD][0].ExtractTranslation()[0] == same_values.held_x(time_code), time_code
        assert evaluated[incremental.BLINK][1] == same_values.blink_visible(time_code), time_code
        assert evaluated[incremental.STILL] == _evaluated(same_values.stage, None)[incremental.STILL], time_code


def test_same_values_equal_time_codes(same_values: incremental.SameValuesScene) -> None:
    for first, second in same_values.equal_time_codes:
        assert _evaluated(same_values.stage, first) == _evaluated(same_values.stage, second), (first, second)
        assert not same_values.changed_copies(first, second)


def test_same_values_changed_copies(same_values: incremental.SameValuesScene) -> None:
    time_codes = _sampled(same_values)
    for first in time_codes:
        for second in time_codes:
            before, after = _evaluated(same_values.stage, first), _evaluated(same_values.stage, second)
            differing = frozenset(path for path in before if before[path] != after[path])
            assert same_values.changed_copies(first, second) == differing, (first, second)
