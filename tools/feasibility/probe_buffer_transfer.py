"""Probe 9 (M1b): can USD arrays reach Blender mesh data without a Python-side copy?

Vt arrays expose the buffer protocol; Blender's foreach_set takes a buffer directly
only when it is a flat sequence whose format matches the RNA raw type. Timings are
single runs on one machine, recorded as facts, not benchmarks.
"""

from __future__ import annotations

import time
from typing import Any

from _common import Probe

N = 1_000_000
PROBE_INDEX = 123_457


def run() -> dict[str, Any]:
    import bpy
    from pxr import Gf, Vt

    p = Probe("buffer_transfer")
    points = Vt.Vec3fArray([Gf.Vec3f(i, 2 * i, 3 * i) for i in range(N)])
    flat = _view(points).cast("B").cast("f")
    mesh: Any = bpy.data.meshes.new("buffer_transfer")  # stubs lack Attribute.data
    mesh.vertices.add(N)
    position = mesh.attributes["position"].data

    p.check("Vt.Vec3fArray exposes a read-only buffer", lambda: _view(points).readonly)
    p.check("flat view keeps format 'f' and 3N elements", lambda: (flat.format, flat.shape), ("f", (3 * N,)))
    p.check("raw Vt.Vec3fArray is rejected", lambda: _rejected(position, "vector", points))
    p.check("2-D memoryview is rejected", lambda: _rejected(position, "vector", _view(points)))
    p.fact("attribute position foreach_set (ms)", lambda: _timed(position, "vector", flat))
    p.check(
        "attribute position receives the values",
        lambda: tuple(mesh.vertices[PROBE_INDEX].co),
        (float(PROBE_INDEX), 2.0 * PROBE_INDEX, 3.0 * PROBE_INDEX),
    )
    p.fact("vertices.co foreach_set (ms)", lambda: _timed(mesh.vertices, "co", flat))
    p.fact("bytes() copy of the same buffer (ms)", lambda: _timed_copy(flat))
    p.check("Vt.IntArray buffer sets loop vertex indices", lambda: _int_indices(bpy), [0, 1, 2])
    bpy.data.meshes.remove(mesh)
    return p.result()


def _view(array: Any) -> memoryview:
    # The pxr stubs don't declare the buffer protocol that Vt arrays implement.
    return memoryview(array)


def _rejected(collection: Any, attr: str, value: Any) -> bool:
    try:
        collection.foreach_set(attr, value)
    except (RuntimeError, TypeError):
        return True
    return False


def _timed(collection: Any, attr: str, value: Any) -> float:
    start = time.perf_counter()
    collection.foreach_set(attr, value)
    return round((time.perf_counter() - start) * 1000, 2)


def _timed_copy(value: Any) -> float:
    start = time.perf_counter()
    bytes(value)
    return round((time.perf_counter() - start) * 1000, 2)


def _int_indices(bpy: Any) -> list[int]:
    from pxr import Vt

    mesh = bpy.data.meshes.new("buffer_transfer_indices")
    try:
        mesh.vertices.add(3)
        mesh.loops.add(3)
        indices = _view(Vt.IntArray([0, 1, 2]))
        mesh.loops.foreach_set("vertex_index", indices)
        return [loop.vertex_index for loop in mesh.loops]
    finally:
        bpy.data.meshes.remove(mesh)
