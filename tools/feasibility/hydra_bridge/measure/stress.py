"""Generated stress scenes of controlled size for M1b's Phase E, each varying one dimension, and M4's update scenes.

Authored through Sdf into crate files under the output directory (not committed); every layer documents its
purpose and parameters. Every mesh is a plain polygon mesh (subdivisionScheme none), so neither side
subdivides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from pxr import Gf, Sdf, Usd, Vt

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

FRAMES = (1, 24)  # the animation scene's samples; one time code (the first) is imported


def _grid(side: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points, face-vertex counts and indices of a side x side quad grid in the XY plane."""
    n = side + 1
    ys, xs = np.mgrid[0:n, 0:n]
    points = np.stack([xs.ravel() / side, ys.ravel() / side, np.zeros(n * n)], axis=1).astype(np.float32)
    first = (np.arange(side)[:, None] * n + np.arange(side)[None, :]).ravel()
    indices = np.stack([first, first + 1, first + n + 1, first + n], axis=1).ravel().astype(np.int32)
    return points, np.full(side * side, 4, np.int32), indices


def _cube() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    points = np.array([(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)], np.float32) - 0.5
    indices = np.array([0, 2, 3, 1, 4, 5, 7, 6, 0, 1, 5, 4, 2, 6, 7, 3, 0, 4, 6, 2, 1, 3, 7, 5], np.int32)
    return points, np.full(6, 4, np.int32), indices


def _attribute(
    prim: Sdf.PrimSpec, name: str, type_name: Sdf.ValueTypeName, value: Any, **metadata: Any
) -> Sdf.AttributeSpec:
    variability = Sdf.VariabilityUniform if metadata.pop("uniform", False) else Sdf.VariabilityVarying
    spec = Sdf.AttributeSpec(prim, name, type_name, variability)
    if value is not None:
        spec.default = value
    for key, item in metadata.items():
        spec.SetInfo(key, item)
    return spec


def _mesh(
    parent: Sdf.PrimSpec | Sdf.Layer, name: str, geometry: tuple[np.ndarray, np.ndarray, np.ndarray], st: bool = False
) -> Sdf.PrimSpec:
    points, counts, indices = geometry
    prim = Sdf.PrimSpec(parent, name, Sdf.SpecifierDef, "Mesh")
    _attribute(prim, "points", Sdf.ValueTypeNames.Point3fArray, Vt.Vec3fArray.FromNumpy(points))
    _attribute(prim, "faceVertexCounts", Sdf.ValueTypeNames.IntArray, Vt.IntArray.FromNumpy(counts))
    _attribute(prim, "faceVertexIndices", Sdf.ValueTypeNames.IntArray, Vt.IntArray.FromNumpy(indices))
    _attribute(prim, "subdivisionScheme", Sdf.ValueTypeNames.Token, "none", uniform=True)
    if st:
        uv = points[indices][:, :2].copy()
        _attribute(
            prim,
            "primvars:st",
            Sdf.ValueTypeNames.TexCoord2fArray,
            Vt.Vec2fArray.FromNumpy(uv),
            interpolation="faceVarying",
        )
    return prim


def _xform(
    parent: Sdf.PrimSpec | Sdf.Layer,
    name: str,
    translate: tuple[float, float, float] | None = None,
    specifier: Sdf.Specifier = Sdf.SpecifierDef,
) -> Sdf.PrimSpec:
    prim = Sdf.PrimSpec(parent, name, specifier, "Xform")
    if translate is not None:
        _attribute(prim, "xformOp:translate", Sdf.ValueTypeNames.Double3, Gf.Vec3d(*translate))
        _attribute(
            prim, "xformOpOrder", Sdf.ValueTypeNames.TokenArray, Vt.TokenArray(["xformOp:translate"]), uniform=True
        )
    return prim


def _materials(layer: Sdf.Layer, colors: dict[str, tuple[float, float, float]]) -> None:
    """UsdPreviewSurface materials under /Materials, one per color."""
    scope = Sdf.PrimSpec(layer, "Materials", Sdf.SpecifierDef, "Scope")
    for name, color in colors.items():
        material = Sdf.PrimSpec(scope, name, Sdf.SpecifierDef, "Material")
        shader = Sdf.PrimSpec(material, "Surface", Sdf.SpecifierDef, "Shader")
        _attribute(shader, "info:id", Sdf.ValueTypeNames.Token, "UsdPreviewSurface", uniform=True)
        _attribute(shader, "inputs:diffuseColor", Sdf.ValueTypeNames.Color3f, Gf.Vec3f(*color))
        _attribute(shader, "outputs:surface", Sdf.ValueTypeNames.Token, None)
        output = _attribute(material, "outputs:surface", Sdf.ValueTypeNames.Token, None)
        output.connectionPathList.explicitItems = [shader.path.AppendProperty("outputs:surface")]


def _bind(prim: Sdf.PrimSpec, material: str) -> None:
    prim.SetInfo("apiSchemas", Sdf.TokenListOp.CreateExplicit(["MaterialBindingAPI"]))
    rel = Sdf.RelationshipSpec(prim, "material:binding", False)
    rel.targetPathList.explicitItems = [Sdf.Path(f"/Materials/{material}")]


def _layer(path: Path, purpose: str, parameters: dict[str, Any], frames: tuple[int, int] | None = None) -> Sdf.Layer:
    layer = Sdf.Layer.CreateNew(str(path))
    layer.documentation = f"Phase E stress scene: {purpose}. Parameters: {parameters}"
    layer.defaultPrim = "World"
    if frames:
        layer.startTimeCode, layer.endTimeCode = frames
    return layer


def mesh_size(path: Path, side: int) -> dict[str, Any]:
    """One mesh: a side x side quad grid with face-varying UVs."""
    parameters = {"side": side, "points": (side + 1) ** 2, "faces": side * side}
    layer = _layer(path, "one large mesh", parameters)
    with Sdf.ChangeBlock():
        _mesh(_xform(layer, "World"), "Grid", _grid(side), st=True)
    layer.Save()
    return parameters


def prim_count(path: Path, count: int) -> dict[str, Any]:
    """Many small meshes: cubes in groups of 100 Xforms, alternating between two bound materials."""
    parameters = {"meshes": count, "group size": 100}
    layer = _layer(path, "many small meshes", parameters)
    cube = _cube()
    with Sdf.ChangeBlock():
        _materials(layer, {"Red": (0.8, 0.1, 0.1), "Blue": (0.1, 0.1, 0.8)})
        world = _xform(layer, "World")
        for group_index in range(0, count, 100):
            group = _xform(world, f"Group_{group_index // 100}", (0, 0, 2.0 * (group_index // 100)))
            for i in range(group_index, min(group_index + 100, count)):
                holder = _xform(group, f"Cube_{i}", (2.0 * (i % 100), 0, 0))
                mesh = _mesh(holder, "Mesh", cube)
                _bind(mesh, "Red" if i % 2 else "Blue")
    layer.Save()
    return parameters


def instancing(path: Path, clusters: int, leaves: int = 10, side: int = 32) -> dict[str, Any]:
    """Nested native instances: instanceable clusters of instanceable leaves, each leaf a grid mesh.

    Half the clusters bind a different material at their instance root, which splits Hydra's instancers.
    """
    parameters = {
        "clusters": clusters,
        "leaves per cluster": leaves,
        "leaf grid side": side,
        "leaf instances": clusters * leaves,
    }
    layer = _layer(path, "nested native instancing with appearance variation", parameters)
    with Sdf.ChangeBlock():
        _materials(layer, {"Green": (0.1, 0.7, 0.2), "Gold": (0.8, 0.6, 0.1)})
        assets = Sdf.PrimSpec(layer, "Assets", Sdf.SpecifierClass, "")
        leaf = _xform(assets, "Leaf", specifier=Sdf.SpecifierClass)
        _mesh(leaf, "Blade", _grid(side), st=True)
        cluster = _xform(assets, "Cluster", specifier=Sdf.SpecifierClass)
        for i in range(leaves):
            child = _xform(cluster, f"Leaf_{i}", (0, 0, 1.1 * i))
            child.referenceList.explicitItems = [Sdf.Reference(primPath="/Assets/Leaf")]
            child.instanceable = True
        world = _xform(layer, "World")
        for i in range(clusters):
            instance = _xform(world, f"Cluster_{i}", (1.2 * (i % 50), 1.2 * (i // 50), 0))
            instance.referenceList.explicitItems = [Sdf.Reference(primPath="/Assets/Cluster")]
            instance.instanceable = True
            _bind(instance, "Green" if i % 2 else "Gold")
    layer.Save()
    return parameters


def animation(path: Path, side: int = 256, movers: int = 1000) -> dict[str, Any]:
    """A deforming grid (points sampled every frame) and many cubes with animated translations."""
    parameters = {"deforming grid side": side, "animated cubes": movers, "frames": FRAMES}
    layer = _layer(path, "animated points and transforms, imported at one time code", parameters, FRAMES)
    points, counts, indices = _grid(side)
    cube = _cube()
    with Sdf.ChangeBlock():
        world = _xform(layer, "World")
        grid = _mesh(world, "Wave", (points, counts, indices), st=True)
        attr = grid.attributes["points"]
        for frame in range(FRAMES[0], FRAMES[1] + 1):
            moved = points.copy()
            moved[:, 2] = 0.1 * np.sin(6.0 * points[:, 0] + 0.3 * frame)
            layer.SetTimeSample(attr.path, frame, Vt.Vec3fArray.FromNumpy(moved))
        movers_root = _xform(world, "Movers")
        for i in range(movers):
            holder = _xform(movers_root, f"Mover_{i}", (2.0 * (i % 40), 2.0 * (i // 40), 1))
            translate = holder.attributes["xformOp:translate"]
            for frame in range(FRAMES[0], FRAMES[1] + 1):
                layer.SetTimeSample(translate.path, frame, Gf.Vec3d(2.0 * (i % 40), 2.0 * (i // 40), 1 + 0.1 * frame))
            _mesh(holder, "Mesh", cube)
    layer.Save()
    return parameters


def updates(path: Path, copies: int) -> dict[str, Any]:
    """M4 Phase C: every update scenario at one size.

    `copies` native instances of a two-mesh, two-material asset, all behind one payload, and as many cubes
    outside instances, alternating between the two materials; and a grid whose topology changes between time
    codes 1 and 2.
    """
    sides = (16, 17)
    parameters = {"asset copies": copies, "unique cubes": copies, "morph grid sides": sides, "frames": (1, 2)}
    layer = _layer(path, "update scenarios: instances behind a payload, unique meshes, changing topology", parameters)
    layer.startTimeCode, layer.endTimeCode = 1, 2
    cube = _cube()
    with Sdf.ChangeBlock():
        _materials(layer, {"Red": (0.8, 0.1, 0.1), "Blue": (0.1, 0.1, 0.8)})
        assets = Sdf.PrimSpec(layer, "Assets", Sdf.SpecifierClass, "")
        asset = _xform(assets, "Asset", specifier=Sdf.SpecifierClass)
        _bind(_mesh(asset, "Body", _grid(8)), "Red")
        _bind(_mesh(_xform(asset, "Top", (0, 0, 1)), "Lid", cube), "Blue")
        payloads = Sdf.PrimSpec(layer, "Payloads", Sdf.SpecifierClass, "")
        held = _xform(payloads, "Copies", specifier=Sdf.SpecifierClass)
        for i in range(copies):
            copy = _xform(held, f"Copy_{i}", (2.0 * (i % 100), 2.0 * (i // 100), 0))
            copy.referenceList.explicitItems = [Sdf.Reference(primPath="/Assets/Asset")]
            copy.instanceable = True
        world = _xform(layer, "World")
        _xform(world, "Copies").payloadList.explicitItems = [Sdf.Payload(primPath="/Payloads/Copies")]
        unique = _xform(world, "Unique", (0, 0, -4))
        for i in range(copies):
            holder = _xform(unique, f"Cube_{i}", (2.0 * (i % 100), 2.0 * (i // 100), 0))
            _bind(_mesh(holder, "Mesh", cube), "Red" if i % 2 else "Blue")
        morph = _mesh(_xform(world, "Morph", (0, 0, 4)), "Grid", _grid(sides[0]))
        for frame, side in zip((1, 2), sides, strict=True):
            points, counts, indices = _grid(side)
            for name, value in (
                ("points", Vt.Vec3fArray.FromNumpy(points)),
                ("faceVertexCounts", Vt.IntArray.FromNumpy(counts)),
                ("faceVertexIndices", Vt.IntArray.FromNumpy(indices)),
            ):
                layer.SetTimeSample(morph.attributes[name].path, frame, value)
    layer.Save()
    return parameters


# Scene name -> (generator, time code imported). One small and one large size per dimension that matters;
# instances-100 is the CI smoke scene.
SCENES: dict[str, tuple[Callable[[Path], dict[str, Any]], float]] = {
    "mesh-64": (lambda p: mesh_size(p, 64), 1.0),
    "mesh-2048": (lambda p: mesh_size(p, 2048), 1.0),
    "prims-10000": (lambda p: prim_count(p, 10000), 1.0),
    "instances-100": (lambda p: instancing(p, 100), 1.0),
    "instances-1000": (lambda p: instancing(p, 1000), 1.0),
    "animation": (animation, 1.0),
    "updates-100": (lambda p: updates(p, 100), 1.0),
    "updates-1000": (lambda p: updates(p, 1000), 1.0),
    "updates-10000": (lambda p: updates(p, 10000), 1.0),
}
STRESS = ["mesh-64", "mesh-2048", "prims-10000", "instances-1000", "animation"]
UPDATES = ["updates-100", "updates-1000", "updates-10000"]  # M4 Phase C's sizes


def generate(name: str, directory: Path) -> tuple[Path, dict[str, Any]]:
    """Write the scene, replacing an earlier one, and check that it composes; returns its path and parameters."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.usdc"
    path.unlink(missing_ok=True)
    generator, _ = SCENES[name]
    parameters = generator(path)
    stage = Usd.Stage.Open(str(path))
    if not stage or not stage.GetPrimAtPath("/World"):
        raise RuntimeError(f"stress scene {name} did not compose")
    return path, parameters
