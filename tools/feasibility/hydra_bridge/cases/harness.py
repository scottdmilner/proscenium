"""What each correctness case gets: the compiled module, the application module, a scratch directory, and checks."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy
from pxr import Usd

if TYPE_CHECKING:
    from types import ModuleType

SCENES = Path(__file__).resolve().parent


class CheckFailedError(AssertionError):
    pass


@dataclass
class Case:
    name: str
    native: ModuleType
    apply: ModuleType
    tmp: Path
    checks: list[str] = field(default_factory=list)
    # Observations recorded as evidence, not asserted: counts, timings, and what Hydra reports on its own.
    findings: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, condition: bool, detail: object = None) -> None:
        if not condition:
            raise CheckFailedError(name if detail is None else f"{name}: {detail}")
        self.checks.append(name)

    def known_gap(self, name: str, reproduced: bool, detail: object = None) -> None:
        """A gap the decision weighs. Asserting it still reproduces keeps the recorded evidence honest."""
        self.check(f"known gap: {name}", reproduced, detail)

    def open(self, scene: str) -> Usd.Stage:
        """Open a copy of a scene from this directory, so edits never reach the repository."""
        copy = self.tmp / scene
        shutil.copy(SCENES / scene, copy)
        stage = Usd.Stage.Open(str(copy))
        if not stage:
            raise CheckFailedError(f"could not open {scene}")
        return stage

    def collection(self) -> bpy.types.Collection:
        """A fresh collection in the current scene for this case's objects."""
        collection = bpy.data.collections.new(f"Case_{self.name}")
        scene: Any = bpy.context.scene  # never None in a running Blender
        scene.collection.children.link(collection)
        return collection

    def apply_plan(self, plan: Any) -> dict[str, bpy.types.Object]:
        """Apply the plan, returning its objects by USD source.

        Raises if a source has several objects (a prim shown in both destinations with different materials): use
        apply.apply then.
        """
        objects = self.apply.apply(plan, self.collection()).objects
        sources = [o["source"] for o in plan.objects]
        repeated = sorted({s for s in sources if sources.count(s) > 1})
        if repeated:
            raise CheckFailedError(f"apply_plan needs one object per source; repeated: {repeated}")
        return dict(zip(sources, objects, strict=True))


def codes(plan: Any, source: str) -> set[str]:
    return {d["code"] for d in plan.diagnostics if d["source"] == source}


def normalized(value: Any) -> Any:
    """A plain, comparable form of snapshot and plan values: Vt arrays and Gf types become nested tuples."""
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, str | bool | int | float) or value is None:
        return value
    if hasattr(value, "GetRow"):  # Gf matrices don't iterate
        return tuple(tuple(value.GetRow(row)) for row in range(len(value)))
    try:
        return tuple(normalized(item) for item in value)
    except TypeError:
        return value
