"""The opt-in verification mode: each capture from a kept chain checked against a full re-read (incremental.md).

Set by the PROSCENIUM_VERIFY_CAPTURE environment variable, read at each evaluation. Evaluation then captures through a
new chain too, and where the two plans differ, uses the new one's and reports each drawn copy that differs with a
verification diagnostic (pipeline.md#diagnostics), the first ten by source path and one counting the rest. It costs a
full re-read per evaluation, about 0.4 s on ALab, and nothing when off.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ..binding.results import Diagnostic, DiagnosticCode

if TYPE_CHECKING:
    from collections.abc import Buffer, Sequence

    from pxr import Usd

    from ..binding.source_access import BindingId
    from ..core import _core

VERIFY_CAPTURE_VARIABLE = "PROSCENIUM_VERIFY_CAPTURE"
LISTED = 10  # the copies named one by one before one diagnostic counts the rest (pipeline.md#diagnostics)

type CopyIdentity = tuple[str, tuple[str, ...]]  # a drawn copy's source entity and instance context


def enabled() -> bool:
    """Whether the verification mode is on: the variable set to anything but empty or 0."""
    return os.environ.get(VERIFY_CAPTURE_VARIABLE, "") not in ("", "0")


def mismatch_diagnostics(
    binding_id: BindingId,
    time_codes: Sequence[Usd.TimeCode],
    kept_plans: Sequence[_core.Plan],
    full_plans: Sequence[_core.Plan],
) -> tuple[Diagnostic, ...]:
    """A verification diagnostic for each drawn copy whose plan from the kept chain differs from the full re-read's.

    Copies are compared by identity, so one in only one plan differs; so does every copy at a time code whose plans'
    diagnostics differ, which names none.
    """
    differing: list[tuple[str, str]] = []  # (source path, at what) in time-code order, then by path
    for time_code, kept, full in zip(time_codes, kept_plans, full_plans, strict=True):
        at = "" if len(time_codes) == 1 else f" at time code {time_code.GetValue()}"
        kept_copies, full_copies = _copies(kept), _copies(full)
        identities = sorted(
            identity
            for identity in kept_copies.keys() | full_copies.keys()
            if kept_copies.get(identity) != full_copies.get(identity)
        )
        differing += [(source_path, at) for source_path, _ in identities]
        if not identities and _diagnostics(kept) != _diagnostics(full):
            differing.append(("", at))
    found = [
        Diagnostic(DiagnosticCode.CAPTURE_MISMATCH, binding_id, _message(source_path, at), source_path=source_path)
        for source_path, at in differing[:LISTED]
    ]
    if (rest := len(differing) - LISTED) > 0:
        message = f"An incremental capture differed from a full re-read at {rest} more drawn copies"
        found.append(Diagnostic(DiagnosticCode.CAPTURE_MISMATCH, binding_id, message))
    return tuple(found)


def _copies(plan: _core.Plan) -> dict[CopyIdentity, tuple[object, ...]]:
    """Each drawn copy's displayed values, by identity: its world matrix, participation, bounds, geometry, and shear."""
    matrices = _values(plan.copy_world_matrices)
    viewport, render = _values(plan.copy_visible_in_viewport), _values(plan.copy_visible_in_render)
    bounds_indices, bounds = _values(plan.copy_placeholder_bounds_indices), _values(plan.placeholder_bounds)
    geometry_indices = _values(plan.copy_geometry_indices)
    geometries = [(g.content_key, tuple(_values(g.extent))) for g in plan.geometries]
    shear_indices = _values(plan.copy_shear_split_indices)
    parents, bases = _values(plan.shear_parent_world_matrices), _values(plan.shear_object_basis_matrices)
    copies: dict[CopyIdentity, tuple[object, ...]] = {}
    for index, entry in enumerate(plan.correspondence):
        bound, geometry, shear = bounds_indices[index], geometry_indices[index], shear_indices[index]
        copies[(entry.source_path, tuple(entry.instance_context))] = (
            _matrix(matrices, index),
            viewport[index],
            render[index],
            None if bound < 0 else tuple(bounds[6 * bound : 6 * bound + 6]),
            None if geometry < 0 else geometries[geometry],
            None if shear < 0 else (_matrix(parents, shear), _matrix(bases, shear)),
        )
    return copies


def _message(source_path: str, at: str) -> str:
    what = "An incremental capture" if source_path else "An incremental capture's diagnostics"
    return f"{what} differed from a full re-read{at}; the full re-read is displayed"


def _matrix(matrices: list, index: int) -> tuple[float, ...]:
    return tuple(matrices[16 * index : 16 * index + 16])


def _values(buffer: Buffer) -> list:
    """A buffer's elements, its view released before returning (SNAP-13)."""
    with memoryview(buffer) as view:
        return view.tolist()


def _diagnostics(plan: _core.Plan) -> list[tuple[str, ...]]:
    return [(d.code, d.source_path, d.message, d.property_path, d.asset_identifier) for d in plan.diagnostics]
