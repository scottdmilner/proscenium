"""The incremental fixture generators produce the scenes their docstrings claim, by USD's own APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Tf, Usd, UsdGeom

from fixtures import incremental

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
