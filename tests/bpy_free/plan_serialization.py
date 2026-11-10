"""Every part of a plan as plain values, and a script that prints a scene's plan that way from a fresh process.

test_core_determinism.py compares plans built in separate processes (PLAN-08, ROLE-02):

    python tests/bpy_free/plan_serialization.py <root layer> <time code>

opens the root layer as a stage of its own, loading everything, captures it at the time code through a chain of its
own, plans it under the default settings and context (plan_checks), and prints contents(plan) as JSON. JSON keeps
floats exactly, so equal contents mean equal plans.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # run as a script: the test tree's modules, as conftest.py puts them on sys.path
    sys.path[:0] = [str(Path(__file__).resolve().parents[1])]

from pxr import Usd

from proscenium.core import _core

BUFFERS = (
    "copy_world_matrices",
    "copy_object_resource_indices",
    "copy_geometry_indices",
    "copy_placeholder_bounds_indices",
    "placeholder_bounds",
    "copy_visible_in_viewport",
    "copy_visible_in_render",
    "copy_shear_split_indices",
    "shear_parent_world_matrices",
    "shear_object_basis_matrices",
)


def contents(plan: _core.Plan) -> dict[str, Any]:
    """Every part of the plan, in its order, as JSON values: what equal plans share."""
    groups, single = plan.batch_groups(1)
    return {
        "partitions": [list(p.resource_indices) for p in plan.partitions],
        "resources": [
            [
                r.role,
                r.source_entity_path,
                r.object_index_in_copy,
                list(r.source_entity_paths),
                list(r.dependency_resource_indices),
            ]
            for r in plan.resources
        ],
        "correspondence": [
            [c.object_resource_index, c.source_path, list(c.instance_context)] for c in plan.correspondence
        ],
        "buffers": {name: memoryview(getattr(plan, name)).tolist() for name in BUFFERS},
        "geometries": [
            [g.representative_source_path, memoryview(g.extent).tolist(), g.content_key] for g in plan.geometries
        ],
        "diagnostics": [
            [d.code, d.source_path, d.message, d.property_path, d.asset_identifier, d.fallback_description]
            for d in plan.diagnostics
        ],
        "batch groups": [
            [
                g.geometry_index,
                g.visible_in_viewport,
                g.visible_in_render,
                g.coincident_copy_index,
                memoryview(g.copy_indices).tolist(),
            ]
            for g in groups
        ]
        + [memoryview(single).tolist()],
    }


def main(root: str, time: float) -> None:
    from bpy_free.plan_checks import CONTEXT, SETTINGS

    stage = Usd.Stage.Open(root, Usd.Stage.LoadAll)
    chain = _core.SceneIndexChain(stage)
    try:
        plan = _core.plan(chain.capture(Usd.TimeCode(time)), SETTINGS, CONTEXT)
    finally:
        chain.release()
    print(json.dumps(contents(plan)))


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]))
