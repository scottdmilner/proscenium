"""Every part of a plan as plain values, and a script that prints a scene's plan that way from a fresh process.

test_core_determinism.py compares plans built in separate processes (PLAN-08, ROLE-02):

    python tests/bpy_free/plan_process.py <root layer> <time code>

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
    "copy_worlds",
    "copy_objects",
    "copy_geometries",
    "copy_placeholders",
    "placeholder_bounds",
    "copy_viewport",
    "copy_render",
    "copy_shears",
    "shear_parent_worlds",
    "shear_object_bases",
)


def contents(plan: _core.Plan) -> dict[str, Any]:
    """Every part of the plan, in its order, as JSON values: what equal plans share."""
    groups, single = plan.batch_groups(1)
    return {
        "partitions": [list(p.resources) for p in plan.partitions],
        "resources": [[r.role, r.entity, r.place, list(r.covers), list(r.uses)] for r in plan.resources],
        "correspondence": [[c.element, c.source, list(c.instance_context)] for c in plan.correspondence],
        "buffers": {name: memoryview(getattr(plan, name)).tolist() for name in BUFFERS},
        "geometries": [[g.source, memoryview(g.extent).tolist(), g.content_key] for g in plan.geometries],
        "diagnostics": [
            [d.code, d.source_path, d.message, d.property_path, d.asset, d.fallback] for d in plan.diagnostics
        ],
        "batch groups": [[g.geometry, g.viewport, g.render, g.repeat, memoryview(g.members).tolist()] for g in groups]
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
