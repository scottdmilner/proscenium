"""Prim purposes and material purposes per destination: what each destination shows, with which materials."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from pxr import UsdGeom

from . import oracle

if TYPE_CHECKING:
    from .harness import Case

TIME = 1.0
# spec/support/visibility.md. A guide is in the viewport only when USD makes it explicitly visible (VIS-04);
# effective visibility already says so, because the guide fallback is invisible.
VIEWPORT = {"default", "proxy", "guide"}
RENDER = {"default", "render"}
# The bridge's default material purpose per destination.
MATERIAL_PURPOSE = {"viewport": "preview", "render": "full"}
# How each drawn mesh should be represented, from how the scene is built: destinations and object count.
EXPECTED_LAYOUT = {
    "/World/Both": ({"viewport", "render"}, 2),
    "/World/Same": ({"viewport", "render"}, 1),
    "/World/Split": ({"viewport", "render"}, 2),
    "/World/Proxy": ({"viewport"}, 1),
    "/World/Render": ({"render"}, 1),
    "/World/Guide": (set(), 1),
    "/World/ShownGuide": ({"viewport"}, 1),
    "/World/InheritedGuide": (set(), 1),
    "/World/Muted/HiddenRender": (set(), 1),
    "/World/Kit/Body": ({"viewport", "render"}, 2),
    "/World/Kit/Stand": ({"viewport"}, 1),
    "/World/Kit/Detail": ({"render"}, 1),
}


def run(case: Case) -> None:
    stage = case.open("purposes.usda")
    plan = case.native.build_plan(case.native.Bridge(stage).capture(TIME))
    objects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in plan.objects:
        objects[obj["source"]].append(obj)

    # USD's answer for every drawn mesh: where it displays, and each destination's materials face by face.
    expected: dict[str, dict[str, Any]] = {}
    for source in oracle.drawn_gprims(stage):
        purpose = str(UsdGeom.Imageable(stage.GetPrimAtPath(source)).ComputePurpose())
        visible = oracle.visible(stage, source, TIME)
        destinations = {
            d for d, purposes in (("viewport", VIEWPORT), ("render", RENDER)) if visible and purpose in purposes
        }
        materials = {d: oracle.face_materials(stage, source, TIME, MATERIAL_PURPOSE[d]) for d in ("viewport", "render")}
        expected[source] = {"destinations": destinations, "materials": materials}
    layout = {
        s: (
            e["destinations"],
            2 if len(e["destinations"]) == 2 and e["materials"]["viewport"] != e["materials"]["render"] else 1,
        )
        for s, e in expected.items()
    }
    case.check("USD gives the scene's intended destinations and object counts", layout == EXPECTED_LAYOUT, layout)
    contexts = oracle.drawn_gprims(stage)
    wrong = {
        s: [o["instance_context"] for o in objs]
        for s, objs in objects.items()
        if any(o["instance_context"] != contexts.get(s) for o in objs)
    }
    case.check(
        "every object has its USD source and instance context, both objects of a split instanced prim included",
        set(objects) == set(contexts) and not wrong and contexts["/World/Kit/Body"] == ("/World/Kit",),
        (sorted(set(objects) ^ set(contexts)), wrong),
    )

    wrong = {}
    for source, usd in expected.items():
        for destination in ("viewport", "render"):
            shown = [o for o in objects[source] if o[destination]]
            if len(shown) != (destination in usd["destinations"]):
                wrong[f"{source} {destination}"] = len(shown)
    case.check("each destination displays exactly the prims USD includes for it, once each", not wrong, wrong)

    wrong = {}
    for source, usd in expected.items():
        for obj in objects[source]:
            for destination in ("viewport", "render"):
                planned = oracle.plan_face_materials(plan, obj)
                if obj[destination] and not oracle.materials_match(usd["materials"][destination], planned, exact=True):
                    wrong[f"{source} {destination}"] = (usd["materials"][destination], planned)
    case.check(
        "each destination's object has UsdShade's materials for that destination's material purpose",
        not wrong,
        wrong,
    )

    counts = {s: len(objects[s]) for s in expected}
    case.check(
        "one object when the destinations agree or only one shows the prim; two when they differ",
        counts == {s: n for s, (_, n) in EXPECTED_LAYOUT.items()},
        counts,
    )
    twins = {s: objs for s, objs in objects.items() if len(objs) == 2}
    case.check(
        "the two objects of a prim share one plan mesh and split the destinations",
        all(
            a["mesh"] == b["mesh"]
            and {(a["viewport"], a["render"]), (b["viewport"], b["render"])} == {(True, False), (False, True)}
            for a, b in twins.values()
        ),
        twins,
    )

    created = case.apply.apply(plan, case.collection()).objects
    wrong = {}
    by_mesh: dict[int, set[str]] = defaultdict(set)
    for obj, made in zip(plan.objects, created, strict=True):
        blender: Any = made
        flags = (not blender.hide_viewport, not blender.hide_render)
        # Each plan material's sources identify it: they are unique per material, unlike names.
        slots = [
            (slot.link, None if slot.material is None else list(slot.material["proscenium_sources"]))
            for slot in blender.material_slots
        ]
        planned_slots = [
            ("OBJECT", None if m is None else list(plan.materials[m]["sources"])) for m in obj["material_slots"]
        ]
        if flags != (obj["viewport"], obj["render"]) or slots != planned_slots:
            wrong[obj["source"]] = (flags, slots, planned_slots)
        by_mesh[obj["mesh"]].add(blender.data.name)
    case.check("Blender's hide flags and object-linked material slots match the plan", not wrong, wrong)
    case.check("objects of one plan mesh share Blender mesh data", all(len(names) == 1 for names in by_mesh.values()))
    # Materials are resolved only for the destinations an object displays in (Proxy's full Unseen isn't).
    linked = {m for obj in plan.objects for m in obj["material_slots"] if m is not None}
    unlinked = [plan.materials[i]["sources"] for i in range(len(plan.materials)) if i not in linked]
    case.check("every planned material is linked by an object, so none is created unused", not unlinked, unlinked)
    case.findings["objects"] = len(plan.objects)
    case.findings["meshes"] = len(plan.meshes)
