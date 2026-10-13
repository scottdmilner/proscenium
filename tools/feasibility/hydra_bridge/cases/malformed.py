"""Malformed input: errors and diagnostics, never a crash, and nothing invalid reaches Blender."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from pxr import UsdGeom

from .harness import Case, codes

if TYPE_CHECKING:
    from collections.abc import Callable

TIME = 1.0
# Expected from how each prim is built (see malformed.usda): the reason each mesh is rejected, as a substring
# of its invalid-mesh message. NegativeIndex's wording is PxOsd's.
INVALID_MESHES = {
    "IndexOutOfRange": "Face-vertex index 2 is 7, outside [0, 3)",
    "NegativeIndex": "Face vertex indices element",
    "CountMismatch": "size '3' does not match expected size '4'",
    "TwoCornerFace": "counts must be greater than 2",
    "CornerCountOverflow": "More corners than Blender can index",
    "NegativeCount": "counts must be greater than 2",
    "HoleOutOfRange": "Hole indices must be less than face count '1'",
    "UnknownScheme": "'loopy' is not a valid 'scheme'",
    "UnknownOrientation": "'sideways' is not a valid 'orientation'",
    "WrongPointsType": "No points",
    "MissingPoints": "No float3 points",
}
# Faces Blender's Mesh.validate() deletes, left out with a warning (see malformed.usda): the faces Blender
# should get, as points in USD's order, and the left-out counts in the warning (repeated point, duplicate).
REPAIRED = {
    "RepeatedPoint": ([(0, 1, 2)], "1 face(s) using a point more than once and 0 face(s)"),
    "DuplicateFace": ([(0, 1, 2), (1, 3, 2)], "0 face(s) using a point more than once and 1 face(s)"),
    "ReversedDuplicateFace": ([(0, 1, 2)], "0 face(s) using a point more than once and 1 face(s)"),
}
# Per prim: each broken primvar and a substring of its invalid-primvar message.
SKIPPED = {
    "ShortPrimvar": {"weight": "Value count 2 does not match vertex interpolation's 3"},
    "PrimvarIndexOutOfRange": {"st": "Index 2 is 9, outside [0, 2)"},
    "BadPrimvars": {
        "negativeIndex": "Index 1 is -1, outside [0, 2)",
        "shortIndices": "Index count 2 does not match vertex interpolation's 3",
        "unknownInterpolation": "Unknown interpolation 'sideways'",
        "emptyUniform": "Value count 0 does not match uniform interpolation's 1",
        "longFaceVarying": "Value count 4 does not match faceVarying interpolation's 3",
        "displayColor": "its index is invalid",
    },
}
VALID_PRIMVARS = {"BadPrimvars": "fine"}
BROKEN_SUBSETS = {
    "NegativeSubsetIndex": "Broken: Subset face index 0 is -1, outside [0, 1)",
    "SubsetIndexOutOfRange": "Broken: Subset face index 0 is 4, outside [0, 1)",
}
SPARSE = ["/World/Sparse/Empty", "/World/Sparse/PointsOnly"]


def messages(plan: Any, source: str, code: str) -> list[str]:
    return [d["message"] for d in plan.diagnostics if d["source"] == source and d["code"] == code]


def run(case: Case) -> None:
    stage = case.open("malformed.usda")
    bridge = case.native.Bridge(stage)
    snapshot = bridge.capture(TIME)
    plan = case.native.build_plan(snapshot)
    by_source = {o["source"]: o for o in plan.objects}

    def bad(name: str) -> str:
        return f"/World/Bad/{name}"

    wrong = {}
    for name, reason in INVALID_MESHES.items():
        found = messages(plan, bad(name), "invalid-mesh")
        if by_source[bad(name)]["mesh"] is not None or not any(reason in m for m in found):
            wrong[name] = (by_source[bad(name)]["mesh"], found, reason)
    case.check(
        "each invalid mesh becomes a placeholder with an invalid-mesh error, for its reason, on its USD path",
        not wrong,
        wrong,
    )
    case.findings["invalid-mesh messages"] = {
        d["source"]: d["message"] for d in plan.diagnostics if d["code"] == "invalid-mesh"
    }
    wrong = {}
    for name, broken in SKIPPED.items():
        obj = by_source[bad(name)]
        attributes = [] if obj["mesh"] is None else [a["name"] for a in plan.meshes[obj["mesh"]]["attributes"]]
        found = messages(plan, bad(name), "invalid-primvar")
        for primvar, reason in broken.items():
            transferred = primvar in attributes or primvar in obj["primvars"]
            if obj["mesh"] is None or transferred or not any(f"'{primvar}'" in m and reason in m for m in found):
                wrong[f"{name}.{primvar}"] = (obj["mesh"], found, attributes, list(obj["primvars"]))
        valid = VALID_PRIMVARS.get(name)
        if valid is not None and valid not in attributes:
            wrong[f"{name}.{valid}"] = ("valid primvar missing", attributes)
    case.check(
        "each invalid primvar is skipped with an error for its reason; the mesh and its valid primvars still build",
        not wrong,
        wrong,
    )
    wrong = {}
    for name, reason in BROKEN_SUBSETS.items():
        obj = by_source[bad(name)]
        found = messages(plan, bad(name), "invalid-subset")
        if obj["mesh"] is None or not any(reason in m for m in found):
            wrong[name] = (obj["mesh"], found)
            continue
        mesh = plan.meshes[obj["mesh"]]
        # The broken subset assigns nothing: every face keeps slot 0, the mesh's own binding, the only slot.
        if list(mesh["material_indices"]) != [0] * len(mesh["face_offsets"]) or mesh["slot_count"] != 1:
            wrong[name] = (list(mesh["material_indices"]), mesh["slot_count"])
    case.check("an invalid subset is skipped with an error, and its faces keep the mesh's material", not wrong, wrong)
    wrong = {
        s: (by_source[s]["mesh"], codes(plan, s)) for s in SPARSE if by_source[s]["mesh"] is None or codes(plan, s)
    }
    case.check(
        "an empty mesh and a mesh with points but no faces are valid: planned with no diagnostics", not wrong, wrong
    )
    good_codes = codes(plan, "/World/Good")
    case.check(
        "the valid mesh builds, with no geometry diagnostics",
        by_source["/World/Good"]["mesh"] is not None
        and not good_codes & {"invalid-mesh", "invalid-primvar", "invalid-subset"},
        good_codes,
    )
    case.check(
        "no error diagnostic lacks a source", all(d["source"] for d in plan.diagnostics if d["severity"] == "error")
    )
    repeats = [d for d, n in Counter(tuple(sorted(d.items())) for d in plan.diagnostics).items() if n > 1]
    case.check("diagnostics have no exact duplicates", not repeats, repeats)

    tf = [d for d in plan.diagnostics if d["code"] == "tf-warning" and "timecode" in d["message"].lower()]
    case.check(
        "a Tf warning posted while capturing becomes a diagnostic on the USD source it came from",
        len(tf) == 1 and tf[0]["source"] == "/World/Odd",
        tf,
    )

    # Application must succeed, the empty and points-only meshes included.
    created = case.apply_plan(plan)
    meshes: list[Any] = [obj.data for obj in created.values() if obj.type == "MESH"]
    wrong = {}
    for name, (faces, counts) in REPAIRED.items():
        found = messages(plan, bad(name), "faces-left-out")
        mesh: Any = created[bad(name)].data if by_source[bad(name)]["mesh"] is not None else None
        built = (
            None if mesh is None else [tuple(mesh.loops[i].vertex_index for i in p.loop_indices) for p in mesh.polygons]
        )
        if built != faces or not any(counts in m for m in found) or messages(plan, bad(name), "invalid-mesh"):
            wrong[name] = (built, found)
    duplicate: Any = created[bad("DuplicateFace")].data
    face_ids = [d.value for d in duplicate.attributes["faceId"].data] if "faceId" in duplicate.attributes else None
    indices = [p.material_index for p in duplicate.polygons]
    case.check(
        "faces Blender's Mesh.validate() deletes are left out with a warning, keeping the rest of the mesh, its "
        "per-face data and its subsets aligned",
        not wrong and face_ids == [10.0, 12.0] and indices == [0, 1],
        (wrong, face_ids, indices),
    )
    case.check(
        "every mesh that reaches Blender passes Mesh.validate() unchanged",
        bool(meshes) and not any(m.validate() for m in meshes),
        [m.name for m in meshes if m.validate()],
    )
    wrong = {}
    for source in SPARSE:
        usd = UsdGeom.Mesh(stage.GetPrimAtPath(source))
        blender: Any = created[source].data
        expected = (len(usd.GetPointsAttr().Get(TIME) or []), len(usd.GetFaceVertexCountsAttr().Get(TIME) or []))
        if blender is None or (len(blender.vertices), len(blender.polygons)) != expected:
            wrong[source] = (None if blender is None else (len(blender.vertices), len(blender.polygons)), expected)
    case.check("in Blender, the empty and points-only meshes have USD's point and face counts", not wrong, wrong)

    misuse: dict[str, Callable[[], object]] = {
        "build_plan(None)": lambda: case.native.build_plan(None),
        "build_plan with a non-string material purpose": lambda: case.native.build_plan(
            snapshot, viewport_material_purpose=3
        ),
        "build_plan with an unknown prim purpose": lambda: case.native.build_plan(snapshot, render_purposes=["hero"]),
        "capture with a non-time": lambda: bridge.capture("soon"),
        "Bridge(None)": lambda: case.native.Bridge(None),
    }
    raised = {}
    for name, call in misuse.items():
        try:
            call()
            raised[name] = None
        except Exception as exc:  # noqa: BLE001 - which exception it is gets recorded
            raised[name] = type(exc).__name__
    case.findings["exceptions for API misuse"] = raised
    case.check("API misuse raises Python exceptions", all(raised.values()), raised)
    case.check(
        "lookups of malformed or missing paths return None",
        snapshot.prim("not a path") is None and snapshot.prim("/Missing") is None and snapshot.dump("bad path") is None,
    )
    bridge.release()
    try:
        bridge.capture(TIME)
        after_release = None
    except RuntimeError as exc:
        after_release = str(exc)
    case.check("capture after release raises RuntimeError", after_release is not None)
