"""Nested native instances with differing inherited appearance, compared copy by copy with UsdGeom and UsdShade."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy
from pxr import UsdShade

from . import oracle
from .harness import Case, normalized

TIME = 1.0
# How the scene is built (see the purpose comment): leaf meshes x Leaf instances per Branch x Branch instances.
DRAWN = 9 * 4 * 10
# Namespace parts that make every copy below them invisible: invisible groups above instance roots, at
# one and two levels, and an invisible Xform inside Branch.
HIDING_GROUPS = ("/World/HiddenGroup/", "/World/Hidden2/", "/Shroud/")
# Named primvars authored as arrays, and as scalars (BranchD).
ARRAY_PRIMVARS = ("label", "flag", "cell", "tint", "weights")
SCALAR_PRIMVARS = ("note", "rough")
# What UsdShade binds a few LeafB copies to, from how the scene is built. Guards the oracle and the scene.
LEAF_B_BINDINGS = {
    "/World/BranchA/LeafB/Tuft/Picked": "/World/BranchA/LeafB/Looks/Lichen",  # in the collection
    "/World/BranchA/LeafB/Tuft/Unpicked": "/World/BranchA/Looks/Moss",  # not in it: the instance root's
    "/World/BranchA/LeafB/Unbound": "/World/BranchA/Looks/Moss",  # an empty binding binds nothing itself
    "/World/BranchA/LeafB/NotMaterial": None,  # the binding wins, but its target isn't a Material
    "/World/BranchA/LeafB/NoApi": "/World/BranchA/LeafB/Looks/Lichen",  # UsdShade honors it without the API
    "/World/BranchE/LeafB/Blade": "/World/BranchE/Looks/Moss",  # strong inner root beats Blade's own
    "/World/BranchF/LeafB/NotMaterial": "/World/Looks/Copper",  # strong outer root beats everything inside
    "/World/Grove/BranchP/LeafB/Tuft/Picked": "/World/Grove/Looks/Pine",  # strong root two prototypes up
    "/World/Grove/BranchQ/LeafB/Stem": "/World/Grove/BranchQ/Looks/Moss",  # third level, inner root's
}


def run(case: Case) -> None:
    stage = case.open("instances.usda")
    snapshot = case.native.Bridge(stage).capture(TIME)
    plan = case.native.build_plan(snapshot)
    objects = plan.objects
    by_source = {o["source"]: o for o in objects}
    expected = oracle.drawn_gprims(stage)

    def usd_binding(source: str) -> str | None:
        return oracle.face_materials(stage, source, TIME)[0]

    case.check(
        "USD resolves the scene as it is built",
        len(expected) == DRAWN
        and {s: usd_binding(s) for s in LEAF_B_BINDINGS} == LEAF_B_BINDINGS
        and all(not oracle.visible(stage, s, TIME) for s in expected if any(g in s for g in HIDING_GROUPS)),
        (len(expected), {s: usd_binding(s) for s in LEAF_B_BINDINGS}),
    )
    case.check("one object per source", len(by_source) == len(objects), Counter(o["source"] for o in objects))
    case.check(
        "one object per drawn gprim, with each level's instance root as its context",
        {s: o["instance_context"] for s, o in by_source.items()} == expected,
        (sorted(set(by_source) ^ set(expected))),
    )
    sources = sorted(expected)

    def mismatches(planned: Any, usd: Any) -> dict[str, Any]:
        return {s: (planned(s), usd(s)) for s in sources if planned(s) != usd(s)}

    wrong = [s for s in sources if not oracle.close(by_source[s]["matrix"], oracle.world(stage, s, TIME))]
    case.check("world transforms match UsdGeom at every level", not wrong, wrong)
    wrong = mismatches(lambda s: by_source[s]["visible"], lambda s: oracle.visible(stage, s, TIME))
    case.check(
        "visibility matches UsdGeom: instance roots, their ancestors, inner roots, and the prototype's own",
        not wrong,
        wrong,
    )
    hidden = [s for s in sources if any(g in s for g in HIDING_GROUPS)]
    shown = [s for s in hidden if by_source[s]["viewport"] or by_source[s]["render"]]
    case.check(
        "copies under an invisible ancestor of an instance root display in neither destination",
        len(hidden) == 9 * 4 * 2 + 9 * 8 and not shown,
        (len(hidden), shown),
    )
    wrong = mismatches(lambda s: by_source[s]["purpose"], lambda s: oracle.purpose(stage, s))
    case.check("purpose matches UsdGeom's inherited purpose", not wrong, wrong)
    wrong = mismatches(
        lambda s: normalized(by_source[s]["primvars"].get("displayColor")),
        lambda s: normalized(oracle.display_color(stage, s, TIME)),
    )
    case.check("displayColor matches USD primvar inheritance: prim, inner root, then outer root", not wrong, wrong)

    def check_primvars(names: tuple[str, ...], what: str) -> None:
        wrong = {}
        for source in sources:
            planned = {n: normalized(by_source[source]["primvars"].get(n)) for n in names}
            usd = {n: normalized(oracle.inherited_primvar(stage, source, n, TIME)) for n in names}
            if planned != usd:
                wrong[source] = (planned, usd)
        authored = sum(1 for s in sources for n in names if oracle.inherited_primvar(stage, s, n, TIME) is not None)
        case.check(
            f"{what} match USD inheritance, value and shape", authored > 0 and not wrong, dict(list(wrong.items())[:4])
        )

    check_primvars(
        ARRAY_PRIMVARS,
        "named array primvars on instance roots (string, bool, int2, float3, a 3-element float) keep every element",
    )

    wrong = {}
    for source in sources:
        usd = oracle.face_materials(stage, source, TIME)
        planned = oracle.plan_face_materials(plan, by_source[source])
        if not oracle.materials_match(usd, planned):
            wrong[source] = (usd, planned)
    case.check(
        "every copy's material is the one UsdShade binds, through every instancing level: strong roots, "
        "collections, empty and non-Material bindings, and bindings without the API inside the prototype",
        not wrong,
        dict(list(wrong.items())[:6]),
    )
    check_hydra_gaps(case, snapshot)

    bound = {m for s in sources for m in oracle.face_materials(stage, s, TIME) if m is not None}
    material_sources = [path for material in plan.materials for path in material["sources"]]
    not_material = [p for p in material_sources if not stage.GetPrimAtPath(p).IsA(UsdShade.Material)]  # ty: ignore[no-matching-overload]
    case.check(
        "instanced materials list each USD source once, every source is a Material, and every bound material is one",
        len(material_sources) == len(set(material_sources)) and not not_material and bound <= set(material_sources),
        (not_material, sorted(bound - set(material_sources))),
    )

    # Evidence for sharing (M4/M8): how Hydra's instancers split the leaf meshes into plan meshes.
    users = Counter(o["mesh"] for o in objects if o["mesh"] is not None)
    case.findings["plan meshes"] = len(plan.meshes)
    case.findings["most objects sharing one plan mesh"] = max(users.values())
    case.findings["instancers"] = sum(1 for p in snapshot.paths() if snapshot.prim(p)["type"] == "instancer")
    # Whether the copies' point arrays share storage, which would make deduplicating them by identity cheap.
    buffers: dict[str, set[int]] = {}
    for mesh in plan.meshes:
        address = numpy.frombuffer(memoryview(mesh["positions"]), dtype=numpy.float32).__array_interface__["data"][0]
        buffers.setdefault(mesh["name"], set()).add(address)
    case.findings["distinct point buffers per leaf mesh"] = {name: len(a) for name, a in sorted(buffers.items())}

    created = case.apply_plan(plan)
    names: dict[int, set[str]] = {}
    for o in objects:
        if o["mesh"] is not None:
            blender_mesh: Any = created[o["source"]].data
            names.setdefault(o["mesh"], set()).add(blender_mesh.name)
    case.check("objects sharing a plan mesh share Blender mesh data", all(len(n) == 1 for n in names.values()))
    case.check("every copy reaches Blender with its source", all(created[s]["proscenium_source"] == s for s in sources))
    wrong = {}
    for source in sources:
        obj: Any = created[source]
        faces = []
        for polygon in obj.data.polygons:
            material = obj.material_slots[polygon.material_index].material
            faces.append(None if material is None else set(material["proscenium_sources"]))
        usd = oracle.face_materials(stage, source, TIME)
        if not oracle.materials_match(usd, faces):
            wrong[source] = (usd, faces)
    case.check(
        "in Blender, each copy's faces show UsdShade's material through its object-linked slots",
        not wrong,
        dict(list(wrong.items())[:6]),
    )
    # Last, so a failure here doesn't hide the checks above.
    check_primvars(SCALAR_PRIMVARS, "named scalar (non-array) primvars on an instance root (string, float)")


def check_hydra_gaps(case: Case, snapshot: Any) -> None:
    """What Hydra itself binds, before the core's correction: the re-rooting bug, asserted to still reproduce."""
    paths = set(snapshot.paths())

    def hydra_binding(path: str) -> str:
        return snapshot.prim(path)["material_bindings"].get("") or ""

    # Only StrongBranch's LeafB binds Moss strongly enough to beat Blade's own binding.
    strong_blades = [hydra_binding(p) for p in paths if p.endswith("/Blade") and hydra_binding(p).endswith("/Moss")]
    case.findings["Hydra's own bindings for Blades under a strong Moss binding (bound prim exists)"] = [
        b in paths for b in strong_blades
    ]
    case.known_gap(
        "with strongerThanDescendants on an inner root, Hydra applies the strength but keeps the re-rooted path",
        len(strong_blades) == 1 and strong_blades[0] not in paths,
        strong_blades,
    )
    raw = {}
    for path in paths:
        if path.endswith("/Stem"):
            bound = hydra_binding(path)
            if bound.endswith(("/Looks/Moss", "/Looks/Bark")):
                inner_root = path.rsplit("/", 1)[0]
                raw.setdefault(bound.rsplit("/", 1)[-1], set()).add(
                    (bound.startswith(inner_root + "/"), bound in paths)
                )
    case.findings["Hydra's own Stem bindings (inside the inner prototype, bound prim exists)"] = {
        k: sorted(v) for k, v in raw.items()
    }
    case.known_gap(
        "Hydra re-roots an inner instance root's binding into the inner prototype: Moss names a missing prim, "
        "and Bark silently names the inner prototype's own Bark (the core corrects both)",
        (True, False) in raw.get("Moss", set()) and (True, True) in raw.get("Bark", set()),
        raw,
    )
