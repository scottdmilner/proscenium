"""Large arrays to Blender: no Python-side copy, Blender's data matches the plan, and a format mismatch is refused.

The scene is generated rather than stored: a grid of SIZE x SIZE quads, authored through UsdGeom into a
temporary crate file, with a per-point float primvar and face-varying UVs.
"""

from __future__ import annotations

import array
import time
import tracemalloc
from typing import TYPE_CHECKING, Any

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

if TYPE_CHECKING:
    from .harness import Case


SIZE = 512  # quads per side: 263,169 points, 262,144 faces, 1,048,576 corners
REPEATS = 5  # timing samples per transfer path
TIME = 1.0


def _author(path: str) -> tuple[Usd.Stage, dict[str, Any]]:
    """The stage, and the arrays authored into it: what the plan must reproduce."""
    stage = Usd.Stage.CreateNew(path)
    mesh = UsdGeom.Mesh.Define(stage, "/Grid")
    side = SIZE + 1
    points = Vt.Vec3fArray([Gf.Vec3f(x, y, 0) for y in range(side) for x in range(side)])
    mesh.GetPointsAttr().Set(points)
    mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray([4] * (SIZE * SIZE)))
    indices = []
    for y in range(SIZE):
        for x in range(SIZE):
            first = y * side + x
            indices += [first, first + 1, first + side + 1, first + side]
    face_vertex_indices = Vt.IntArray(indices)
    mesh.GetFaceVertexIndicesAttr().Set(face_vertex_indices)
    mesh.GetSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    primvars = UsdGeom.PrimvarsAPI(mesh)
    height = primvars.CreatePrimvar("height", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex)
    heights = Vt.FloatArray([float(i % 7) for i in range(side * side)])
    height.Set(heights)
    st = primvars.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    uvs = Vt.Vec2fArray([Gf.Vec2f((i % 4) / 4, (i % 3) / 3) for i in range(len(indices))])
    st.Set(uvs)
    stage.GetRootLayer().Save()
    # Every face is a right-handed quad, so Blender's corners are USD's in order and face f starts at 4f.
    offsets = Vt.IntArray(list(range(0, 4 * SIZE * SIZE, 4)))
    authored = {
        "positions": points,
        "corner_verts": face_vertex_indices,
        "face_offsets": offsets,
        "attribute height": heights,
        "attribute st": uvs,
    }
    return stage, authored


def run(case: Case) -> None:
    stage, authored = _author(str(case.tmp / "large.usdc"))
    timings: dict[str, float] = {}
    start = time.perf_counter()
    snapshot = case.native.Bridge(stage).capture(TIME)
    timings["capture"] = time.perf_counter() - start
    start = time.perf_counter()
    plan = case.native.build_plan(snapshot)
    timings["build_plan"] = time.perf_counter() - start
    (mesh,) = plan.meshes
    side = SIZE + 1
    arrays = {
        "positions": ("f", side * side * 3),
        "corner_verts": ("i", SIZE * SIZE * 4),
        "face_offsets": ("i", SIZE * SIZE),
    }
    attributes = {a["name"]: a for a in mesh["attributes"]}
    views = {name: memoryview(mesh[name]) for name in arrays}
    views.update({f"attribute {name}": memoryview(a["data"]) for name, a in attributes.items()})
    case.check(
        "plan arrays are Vt arrays exposing read-only contiguous buffers in Blender's element types",
        all(isinstance(mesh[name], Vt.Vec3fArray | Vt.IntArray) for name in arrays)
        and all(v.readonly and v.c_contiguous and v.format in ("f", "i") for v in views.values())
        and all(memoryview(mesh[name]).nbytes // 4 == count for name, (_, count) in arrays.items()),
        {name: (v.format, v.shape) for name, v in views.items()},
    )
    total_bytes = sum(v.nbytes for v in views.values())
    # The plan against what the scene authored, so that the Blender comparison below checks translation too.
    wrong = [
        name
        for name, array_ in authored.items()
        if name not in views or views[name].cast("B").tobytes() != memoryview(array_).cast("B").tobytes()
    ]
    case.check(
        "plan positions, corners, face offsets and attributes equal the authored arrays, byte for byte",
        not wrong and attributes["st"]["domain"] == "CORNER" and attributes["height"]["domain"] == "POINT",
        wrong,
    )

    collection = case.collection()
    tracemalloc.start()
    start = time.perf_counter()
    (obj,) = case.apply.apply(plan, collection).objects
    timings["apply"] = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    case.findings["plan array bytes"] = total_bytes
    case.findings["peak Python allocation during apply"] = peak

    # Each transfer on its own: what Python allocates while Blender reads one plan buffer.
    blender: Any = obj.data
    transfers = {
        "position": lambda: blender.attributes["position"].data.foreach_set(
            "vector", _flat(case, mesh["positions"], "f")
        ),
        ".corner_vert": lambda: blender.attributes[".corner_vert"].data.foreach_set(
            "value", _flat(case, mesh["corner_verts"], "i")
        ),
        "material_index": lambda: blender.attributes["material_index"].data.foreach_set(
            "value", _flat(case, mesh["material_indices"], "i")
        ),
        "height": lambda: blender.attributes["height"].data.foreach_set(
            "value", _flat(case, attributes["height"]["data"], "f")
        ),
        "st": lambda: blender.attributes["st"].data.foreach_set("vector", _flat(case, attributes["st"]["data"], "f")),
        "loop_start": lambda: blender.polygons.foreach_set("loop_start", _flat(case, mesh["face_offsets"], "i")),
    }
    allocated = {}
    for name, transfer in transfers.items():
        tracemalloc.start()
        transfer()
        allocated[name] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    case.findings["peak Python allocation per transfer"] = allocated
    # A copy of any array would allocate at least its size; 64 KiB is far below the smallest (1 MiB).
    copied = {name: size for name, size in allocated.items() if name != "loop_start" and size > 64 * 1024}
    case.check("attribute and corner transfers allocate no copy of the plan's arrays", not copied, allocated)
    case.known_gap(
        "Blender copies the face offsets: polygons.foreach_set('loop_start') allocates a temporary of 4 bytes per face",
        allocated["loop_start"] >= SIZE * SIZE * 4,
        allocated["loop_start"],
    )
    case.check(
        "application as a whole allocates no more than that one temporary (plus 64 KiB)",
        peak <= allocated["loop_start"] + 64 * 1024,
        (peak, allocated["loop_start"]),
    )

    case.check("Blender accepts the large mesh unchanged", not blender.validate())
    wrong = []
    for prop, collection_data, plan_array, fmt in [
        ("vector", blender.attributes["position"].data, mesh["positions"], "f"),
        ("value", blender.attributes[".corner_vert"].data, mesh["corner_verts"], "i"),
        ("vector", blender.uv_layers["st"].uv, attributes["st"]["data"], "f"),
        ("value", blender.attributes["height"].data, attributes["height"]["data"], "f"),
    ]:
        expected = memoryview(plan_array).cast("B")
        out = array.array(fmt, bytes(expected.nbytes))
        collection_data.foreach_get(prop, out)
        if out.tobytes() != expected.tobytes():
            wrong.append(prop)
    loop_starts = array.array("i", bytes(SIZE * SIZE * 4))
    blender.polygons.foreach_get("loop_start", loop_starts)
    if loop_starts.tobytes() != memoryview(mesh["face_offsets"]).cast("B").tobytes():
        wrong.append("loop_start")
    case.check("Blender's arrays equal the plan's, byte for byte", not wrong, wrong)

    refused = False
    try:
        case.apply.flat(Vt.DoubleArray([1.0, 2.0]), case.apply.BufferFormat.FLOAT)
    except TypeError:
        refused = True
    case.check("a buffer whose format differs from Blender's is refused rather than read item by item", refused)

    # The fast path, measured against the per-item path foreach_set takes for a Python list. Each is the
    # minimum of REPEATS runs: a single sample on a shared CI runner can be several times slower (a macOS
    # binary run once measured 4.8x).
    positions = blender.attributes["position"].data
    flat_positions = case.apply.flat(mesh["positions"], case.apply.BufferFormat.FLOAT)
    as_list = flat_positions.tolist()

    def fastest(source: Any) -> float:
        samples = []
        for _ in range(REPEATS):
            start = time.perf_counter()
            positions.foreach_set("vector", source)
            samples.append(time.perf_counter() - start)
        return min(samples)

    timings["foreach_set from the plan buffer"] = fastest(flat_positions)
    timings["foreach_set from a Python list"] = fastest(as_list)
    case.findings["timings (s)"] = timings
    case.check(
        "foreach_set takes the fast path for plan buffers (at least 5x faster than from a list)",
        timings["foreach_set from the plan buffer"] * 5 < timings["foreach_set from a Python list"],
        timings,
    )


def _flat(case: Case, plan_array: Any, fmt: str) -> memoryview:
    return case.apply.flat(plan_array, case.apply.BufferFormat(fmt))
