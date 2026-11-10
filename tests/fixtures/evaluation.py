"""Evaluation fixtures: the scenes M6's capture and planner are checked on, from scenes/evaluation/.

- transforms (F-TRANSFORMS): each kind of transform the planner places, a reset transform stack outside and
  inside a native instance and on a nested instance's root, a payload, a translate sampled over time, and a
  projective matrix in a layer of its own.
- units_up_axis (F-UNITS-UP-AXIS): one scene as a Y-up stage in centimeters and a Z-up stage in meters, for
  coordinate conversion into target scenes of different unit scales.
- visibility_purpose (F-VISIBILITY-PURPOSE): effective visibility, inherited and sampled over time, apart from
  each purpose, and each destination's participation.
- unsupported_content (F-UNSUPPORTED-CONTENT): placeholders and markers for untranslated types, the filters'
  conversions to meshes, and a mesh beneath an unsupported ancestor.
- point_instancers (F-POINT-INSTANCERS): point instancers' copies by their point-instance paths, by index and by
  authored id, and inside native instances.
- generated_hierarchy: a transform hierarchy generated from a recorded seed, for relations 1 and 2 on generated
  inputs (TMETA-04), written through Sdf onto hierarchy_base.usda.

Each copies its layers from Scene.EVALUATION, opens them as the caller's live stages, and yields what the
scene is built to display, written out from the layer by hand: world transforms are composed here from the
ops each layer authors, in USD's row-vector convention, never read from USD. Time codes are floats, or None
for the default time code. tests/bpy_free/test_evaluation_fixtures.py checks these against USD's own APIs.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Gf, Sdf, Usd, Vt

from proscenium.binding.source_access.stages import PayloadPolicy
from support.time_codes import TimeVariation
from support.usd import open_stage_without_cache

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable
    from pathlib import Path

Bounds = tuple[Gf.Vec3d, Gf.Vec3d]  # (min, max), local
UNIT_BOUNDS: Bounds = (Gf.Vec3d(0, 0, 0), Gf.Vec3d(1, 1, 1))  # the Tetra every mesh references
VIEWPORT_PURPOSES = frozenset({"default", "proxy"})  # the settings' defaults (DECISIONS.md "Conversion and
RENDER_PURPOSES = frozenset({"default", "render"})  # purpose settings")
LOAD = {PayloadPolicy.LOAD_ALL: Usd.Stage.LoadAll, PayloadPolicy.LOAD_NONE: Usd.Stage.LoadNone}


def translate(x: float, y: float, z: float) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetTranslate(Gf.Vec3d(x, y, z))


def rotate(axis: tuple[float, float, float], degrees: float) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(*axis), degrees))


def scale(x: float, y: float, z: float) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetScale(Gf.Vec3d(x, y, z))


def local(*ops: Gf.Matrix4d) -> Gf.Matrix4d:
    """A prim's local transform from its ops in xformOpOrder's order: the last op applies to points first."""
    result = Gf.Matrix4d(1)
    for op in ops:
        result = op * result
    return result


def world(*locals_: Gf.Matrix4d) -> Gf.Matrix4d:
    """A prim's world transform from its own local transform and its ancestors', innermost first."""
    result = Gf.Matrix4d(1)
    for matrix in locals_:
        result = result * matrix
    return result


# --- F-TRANSFORMS --------------------------------------------------------------------------------------------

ANIMATED = "/World/Animated/Geom"
ANIMATED_SAMPLES = ((0.0, 0.0), (10.0, 10.0), (20.0, 10.0), (30.0, 0.0))  # (time code, translate x)
PAYLOAD_MESHES = frozenset({"/World/Payloaded/Geom"})


def animated_x(time_code: float | None) -> float:
    """Animated's translate x at time_code: linear between samples, held outside them, 0 at the default."""
    if time_code is None:
        return 0.0  # only samples are authored, so the default time code has no opinion
    (t0, x0), *rest = ANIMATED_SAMPLES
    if time_code <= t0:
        return x0
    for t1, x1 in rest:
        if time_code <= t1:
            return x0 + (x1 - x0) * (time_code - t0) / (t1 - t0)
        t0, x0 = t1, x1
    return x0


@dataclass
class TransformsScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage, loading everything
    projective_root_layer_path: Path
    projective_stage: Usd.Stage  # transforms_projective.usda's
    world_matrices_by_source: dict[
        str, Gf.Matrix4d
    ]  # drawn mesh -> world transform at the default time code, Animated's at 0
    payload_meshes: frozenset[str]  # drawn only under load-all
    negative_determinant_paths: frozenset[str]  # world transform with a negative determinant
    sheared_paths: frozenset[str]  # world transform whose axes aren't orthogonal
    reset_transform_paths: frozenset[
        str
    ]  # reset the transform stack on their own prims (Socket/Geom's is on its instance root)
    instance_context: dict[str, tuple[str, ...]]  # drawn mesh inside instances -> instance roots, outermost first
    projective_mesh_path: str  # in projective_stage: the mesh placed by its matrix's affine part, with a diagnostic
    projective_world_matrix: Gf.Matrix4d  # its world transform as authored, projective column included
    projective_affine_matrix: Gf.Matrix4d  # that matrix with its last column (0, 0, 0, 1)
    # In projective_stage: the copies of the same mesh inside two native instances -> their worlds by the affine part.
    projective_instance_world_matrices: dict[str, Gf.Matrix4d]
    # The source each approximation diagnostic names, in source order: the mesh, and the instanced mesh's first copy.
    projective_diagnostic_sources: tuple[str, ...]
    variation: TimeVariation
    equal_time_codes: tuple[tuple[float, float], ...]  # pairs whose evaluated values are equal (relation 5)

    def drawn(self, policy: PayloadPolicy) -> frozenset[str]:
        return frozenset(self.world_matrices_by_source) - (
            self.payload_meshes if policy is PayloadPolicy.LOAD_NONE else frozenset()
        )

    def world_at(self, path: str, time_code: float | None) -> Gf.Matrix4d:
        return translate(animated_x(time_code), 0, 0) if path == ANIMATED else self.world_matrices_by_source[path]


def affine(matrix: Gf.Matrix4d) -> Gf.Matrix4d:
    """The matrix with its last column (0, 0, 0, 1): the part a Blender object can hold."""
    result = Gf.Matrix4d(matrix)
    result.SetColumn(3, Gf.Vec4d(0, 0, 0, 1))
    return result


@contextmanager
def transforms(dest: Path) -> Generator[TransformsScene]:
    """F-TRANSFORMS: see scenes/evaluation/transforms.usda and transforms_projective.usda."""
    root, projective_root = (
        copy_scene(Scene.EVALUATION, dest) / name for name in ("transforms.usda", "transforms_projective.usda")
    )
    ordered = local(translate(1, 2, 3), rotate((0, 0, 1), 90), scale(2, 1, 1))
    pivot = translate(1, 0, 0)
    pivoted = local(translate(0, 4, 0), pivot, rotate((0, 0, 1), 90), pivot.GetInverse())
    matrix = Gf.Matrix4d((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (5, 0, 0, 1))
    sheared = Gf.Matrix4d((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (-5, 0, 0, 1))
    instanced, kit = translate(0, 0, 10), translate(1, 0, 0)
    projective = Gf.Matrix4d((1, 0, 0, 0.25), (0, 1, 0, 0), (0, 0, 1, 0), (2, 0, 0, 1))
    yield TransformsScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        projective_root_layer_path=projective_root,
        projective_stage=open_stage_without_cache(projective_root),
        world_matrices_by_source={
            "/World/Ordered/OnMesh": world(translate(0, 0, 1), ordered),
            "/World/Pivoted/Geom": pivoted,
            "/World/Matrix/Geom": matrix,
            "/World/Mirrored/Geom": local(translate(0, -3, 0), scale(-1, 2, 0.5)),
            "/World/Sheared/Geom": sheared,
            "/World/Reset/Pinned": translate(0, 5, 0),  # the reset drops Reset's translate
            "/World/Instanced/Kit/Body": world(kit, instanced),
            "/World/Instanced/Kit/Pinned": translate(0, 3, 0),  # drops Kit's and Instanced's (OpenUSD #862)
            # Socket's reset, on a nested instance's root, drops Kit's and Instanced's too (OpenUSD #862).
            "/World/Instanced/Kit/Socket/Geom": world(translate(2, 0, 0), translate(0, 0, 7)),
            "/World/Payloaded/Geom": world(rotate((1, 0, 0), 90), translate(0, 0, -5)),
            ANIMATED: translate(0, 0, 0),
        },
        payload_meshes=PAYLOAD_MESHES,
        negative_determinant_paths=frozenset({"/World/Mirrored/Geom"}),
        sheared_paths=frozenset({"/World/Sheared/Geom"}),
        reset_transform_paths=frozenset({"/World/Reset/Pinned", "/World/Instanced/Kit/Pinned"}),
        instance_context={
            "/World/Instanced/Kit/Body": ("/World/Instanced/Kit",),
            "/World/Instanced/Kit/Pinned": ("/World/Instanced/Kit",),
            "/World/Instanced/Kit/Socket/Geom": ("/World/Instanced/Kit", "/World/Instanced/Kit/Socket"),
        },
        projective_mesh_path="/World/Projective/Geom",
        projective_world_matrix=projective,
        projective_affine_matrix=affine(projective),
        # The whole world transform's affine part: the projective term reaches the instance's translation.
        projective_instance_world_matrices={
            f"/World/Kits/{kit}/Projective/Geom": affine(projective * translate(0, y, 0))
            for kit, y in (("KitA", 5), ("KitB", 10))
        },
        projective_diagnostic_sources=("/World/Kits/KitA/Projective/Geom", "/World/Projective/Geom"),
        variation=TimeVariation(start=0.0, end=30.0, samples=(0.0, 10.0, 20.0, 30.0), transitions=()),
        # Before the first sample and at it, after the last and at it, and two between the equal samples.
        equal_time_codes=((-5.0, 0.0), (35.0, 30.0), (12.5, 17.25)),
    )


# --- F-UNITS-UP-AXIS -----------------------------------------------------------------------------------------

UNIT_SCALES = (1.0, 0.01)  # the target scenes' unit_settings.scale_length the cases synchronize into


@dataclass
class UnitsScene:
    root_layer_paths: dict[str, Path]  # "y-up-cm", "z-up-m" -> its root layer
    stages: dict[str, Usd.Stage]  # the caller's live stage of each
    meters_per_unit: dict[str, float]
    up_axis: dict[str, str]
    world_matrices_by_source: dict[
        str, Gf.Matrix4d
    ]  # drawn mesh -> world transform in source units, the same in both stages
    bounds: Bounds  # every mesh's local extent
    instance_context: dict[str, tuple[str, ...]]

    def correction(self, stage: str, scale_length: float) -> Gf.Matrix4d:
        """The spec's correction matrix C, in USD's row-vector convention: world * correction (CONV-08).

        scale = metersPerUnit / scale_length, then +90 degrees about X for a Y-up stage, as
        transforms.md#coordinate-conversion's C = R_upaxis @ Scale(scale) gives it in column vectors.
        """
        return correction(self.meters_per_unit[stage], self.up_axis[stage], scale_length)


def correction(meters_per_unit: float, up_axis: str, scale_length: float) -> Gf.Matrix4d:
    """The spec's correction matrix C for a stage's metersPerUnit and upAxis, as UnitsScene.correction gives it."""
    factor = meters_per_unit / scale_length
    up = rotate((1, 0, 0), 90) if up_axis == "Y" else Gf.Matrix4d(1)
    return scale(factor, factor, factor) * up


@contextmanager
def units_up_axis(dest: Path) -> Generator[UnitsScene]:
    """F-UNITS-UP-AXIS: see scenes/evaluation/units_y_up_cm.usda and units_z_up_m.usda."""
    scenes = copy_scene(Scene.EVALUATION, dest)
    roots = {"y-up-cm": scenes / "units_y_up_cm.usda", "z-up-m": scenes / "units_z_up_m.usda"}
    yield UnitsScene(
        root_layer_paths=roots,
        stages={key: open_stage_without_cache(path) for key, path in roots.items()},
        meters_per_unit={"y-up-cm": 0.01, "z-up-m": 1.0},
        up_axis={"y-up-cm": "Y", "z-up-m": "Z"},
        world_matrices_by_source={
            "/World/Box": translate(100, 20, 50),
            "/World/Kit/Body": world(translate(0, 100, 0), translate(0, 0, 200)),
        },
        bounds=(Gf.Vec3d(0, 0, 0), Gf.Vec3d(10, 10, 10)),
        instance_context={"/World/Kit/Body": ("/World/Kit",)},
    )


# --- F-VISIBILITY-PURPOSE ------------------------------------------------------------------------------------

BLINKING = "/World/Blinking"


@dataclass
class VisibilityScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    purpose: dict[str, str]  # drawn mesh -> its computed purpose
    always_invisible: frozenset[str]  # invisible at every time code
    blinking: str  # invisible from 10 until 20, visible otherwise, the default time code included
    variation: TimeVariation
    equal_time_codes: tuple[tuple[float, float], ...]  # pairs whose evaluated values are equal (relation 5)

    def visible(self, path: str, time_code: float | None) -> bool:
        """Effective visibility: an invisible ancestor or sample makes a mesh invisible; guides aren't covered."""
        if path in self.always_invisible:
            return False
        return not (path == self.blinking and time_code is not None and 10.0 <= time_code < 20.0)

    def displays(self, path: str, time_code: float | None, purposes: Iterable[str]) -> bool:
        """Whether a destination including purposes shows the mesh. No guide is explicitly visible here."""
        return self.purpose[path] != "guide" and self.purpose[path] in set(purposes) and self.visible(path, time_code)


@contextmanager
def visibility_purpose(dest: Path) -> Generator[VisibilityScene]:
    """F-VISIBILITY-PURPOSE: see scenes/evaluation/visibility_purpose.usda."""
    root = copy_scene(Scene.EVALUATION, dest) / "visibility_purpose.usda"
    yield VisibilityScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        purpose={
            "/World/Hidden/Child": "default",
            "/World/Shown/Default": "default",
            "/World/Shown/Proxy": "proxy",
            "/World/Shown/Render": "render",
            "/World/Shown/Guide": "guide",
            "/World/ProxyGroup/Inherits": "proxy",  # inherited from ProxyGroup
            "/World/Pair/ProxyGeo": "proxy",
            "/World/Pair/RenderGeo": "render",
            BLINKING: "default",
        },
        always_invisible=frozenset({"/World/Hidden/Child"}),
        blinking=BLINKING,
        variation=TimeVariation(start=0.0, end=20.0, samples=(0.0, 10.0, 20.0), transitions=(10.0, 20.0)),
        equal_time_codes=((0.0, 5.0), (10.0, 15.0), (20.0, 25.0)),  # tokens hold between samples
    )


# --- F-UNSUPPORTED-CONTENT -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Placeholder:
    """What the planner shows for untranslated content: a bounds box, or an empty marker when bounds is None."""

    type_name: str  # the prim's USD type
    world_matrix: Gf.Matrix4d
    local_bounds: Bounds | None  # local: the authored extent as given, else USD's computed one for curves and points
    bounds_computed_from_geometry: bool  # bounds came from USD's computation, since none is authored
    visible_in_viewport: bool  # displays there under the default purposes
    visible_in_render: bool


@dataclass
class UnsupportedScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    placeholders: dict[str, Placeholder]  # each with an untranslated-type diagnostic; markers also warn
    exact_conversions: frozenset[str]  # implicit shapes the filters turn into meshes exactly
    approximated: frozenset[str]  # those turned into meshes inexactly, each with an approximation diagnostic
    supported_beneath: dict[str, tuple[Gf.Matrix4d, str]]  # mesh beneath an unsupported prim -> (world, purpose)
    kinds: dict[str, str]  # prim -> its authored kind


@contextmanager
def unsupported_content(dest: Path) -> Generator[UnsupportedScene]:
    """F-UNSUPPORTED-CONTENT: see scenes/evaluation/unsupported_content.usda."""
    root = copy_scene(Scene.EVALUATION, dest) / "unsupported_content.usda"

    def box(*corners: tuple[float, float, float]) -> Bounds:
        return Gf.Vec3d(*corners[0]), Gf.Vec3d(*corners[1])

    def shown(type_name: str, at: Gf.Matrix4d, bounds: Bounds | None, *, computed: bool = False) -> Placeholder:
        return Placeholder(type_name, at, bounds, computed, visible_in_viewport=True, visible_in_render=True)

    yield UnsupportedScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        placeholders={
            "/World/Boxed": shown("BasisCurves", Gf.Matrix4d(1), box((-1, -1, -1), (2, 2, 2))),
            # Points 0 to 2 on z, widened by half the constant width 0.2.
            "/World/Combed": shown(
                "BasisCurves", translate(3, 0, 0), box((-0.1, -0.1, -0.1), (0.1, 0.1, 2.1)), computed=True
            ),
            # Points 0 and 1 on x, widened by half their width 0.5.
            "/World/Dots": shown(
                "Points", translate(6, 0, 0), box((-0.25, -0.25, -0.25), (1.25, 0.25, 0.25)), computed=True
            ),
            "/World/Tangents": shown("HermiteCurves", translate(9, 0, 0), box((0, 0, 0), (1, 1, 0))),
            "/World/Fog": shown("Volume", translate(0, 3, 0), None),
            "/World/Placed/Strand": Placeholder(
                "BasisCurves",
                world(rotate((0, 0, 1), 90), translate(0, 15, 0)),
                box((0, 0, 0), (2, 0, 1)),
                bounds_computed_from_geometry=False,
                visible_in_viewport=False,  # render purpose
                visible_in_render=True,
            ),
            "/World/Veiled": Placeholder(
                "BasisCurves",
                translate(0, 18, 0),
                box((0, 0, 0), (0, 1, 0)),
                bounds_computed_from_geometry=False,
                visible_in_viewport=False,
                visible_in_render=False,
            ),
            "/World/Parent": Placeholder(
                "BasisCurves",
                translate(0, 21, 0),
                box((0, 0, 0), (0, 0, 1)),
                bounds_computed_from_geometry=False,
                visible_in_viewport=False,
                visible_in_render=True,
            ),
        },
        exact_conversions=frozenset({"/World/Shapes/Box"}),
        approximated=frozenset({"/World/Shapes/Ball", "/World/Shapes/Sheet"}),
        supported_beneath={"/World/Parent/Child": (world(translate(1, 0, 0), translate(0, 21, 0)), "render")},
        kinds={"/World/Placed": "component"},
    )


# --- F-POINT-INSTANCERS --------------------------------------------------------------------------------------


@dataclass
class PointInstancerScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    world_matrices_by_source: dict[str, Gf.Matrix4d]  # drawn copy, by its point-instance path -> world transform
    sources: dict[str, str]  # drawn copy -> the composed-stage prim it is a copy of
    instance_context: dict[
        str, tuple[str, ...]
    ]  # drawn copy -> native-instance roots, instancer, point, outermost first
    floors: dict[str, str]  # drawn copy -> its floor: the outermost native-instance root or point instancer
    invisible: frozenset[str]  # drawn copies of points the instancer hides (invisibleIds)
    primvars: dict[str, dict[str, float | int]]  # drawn copy -> its point's per-point and its instancer's constant ones
    prototypes: frozenset[str]  # the gprims under an instancer's prototypes: no copy at their own paths


@contextmanager
def point_instancers(dest: Path) -> Generator[PointInstancerScene]:
    """F-POINT-INSTANCERS: see scenes/evaluation/point_instancers.usda."""
    root = copy_scene(Scene.EVALUATION, dest) / "point_instancers.usda"
    scatter, tagged, protos = "/World/Scatter", "/World/Tagged", "/World/Scatter/Protos"
    # Each prototype's prims drawn per point, by their path below the prototype root's parent, with their transforms
    # relative to it, the root's own included, as UsdGeomPointInstancer composes a point's prototype.
    leaf = {"Leaf/Blade": translate(0, 0, 5)}
    rock = {"Rock": Gf.Matrix4d(1)}
    pebble = {"Pebble/Geom": translate(0, 0, 1)}
    world: dict[str, Gf.Matrix4d] = {}
    sources: dict[str, str] = {}
    contexts: dict[str, tuple[str, ...]] = {}
    floors: dict[str, str] = {}
    primvars: dict[str, dict[str, float | int]] = {}

    def draw(
        instancer: str, point: str, prims: dict[str, Gf.Matrix4d], frame: Gf.Matrix4d, outer: tuple[str, ...] = ()
    ) -> None:
        # frame: the point's scale, then orientation, then position, then the instancer's world transform.
        for below, prim_local in prims.items():
            path = f"{instancer}/{point}/{below}"
            world[path] = prim_local * frame
            sources[path] = f"{instancer}/Protos/{below}"  # each instancer keeps its prototypes in its own Protos
            context = (*outer, instancer, f"{instancer}/{point}")
            if below.startswith("Pebble/"):  # Pebble is a native instance inside the point's prototype
                context = (*context, f"{instancer}/{point}/Pebble")
            contexts[path] = context
            floors[path] = outer[0] if outer else instancer

    # Scatter: its translate, then rotateZ, so in row vectors the rotation applies first.
    scatter_world = local(translate(10, 0, 0), rotate((0, 0, 1), 90))
    frames = {
        0: translate(0, 0, 0),
        1: scale(2, 1, 1) * rotate((1, 1, 1), 120) * translate(1, 0, 0),
        2: scale(1, 2, 1) * translate(2, 0, 0),
        3: translate(3, 0, 0),
    }
    drawn = {0: leaf, 1: rock, 2: leaf, 3: pebble}
    for index, prims in drawn.items():
        draw(scatter, f"__index_{index}", prims, frames[index] * scatter_world)
        for below in prims:
            primvars[f"{scatter}/__index_{index}/{below}"] = {"heat": index + 0.5, "groupId": 7}
    # Tagged: ids 10, -3, 7, and 12, which coincides with 10.
    for point, x in (("__id_10", 0), ("__id_n3", 2), ("__id_7", 4), ("__id_12", 0)):
        draw(tagged, point, rock, translate(x, 0, 0) * translate(0, 10, 0))
    # Each Kit instance's Spray, translated inside the prototype.
    for kit, y in (("KitA", 20), ("KitB", 30)):
        spray = f"/World/Kits/{kit}/Spray"
        for index, position in ((0, translate(0, 0, 0)), (1, translate(0, 2, 0))):
            draw(
                spray,
                f"__index_{index}",
                {"Pellet": Gf.Matrix4d(1)},
                position * translate(1, 0, 0) * translate(0, y, 0),
                outer=(f"/World/Kits/{kit}",),
            )
    yield PointInstancerScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        world_matrices_by_source=world,
        sources=sources,
        instance_context=contexts,
        floors=floors,
        invisible=frozenset({f"{scatter}/__index_2/Leaf/Blade", f"{tagged}/__id_7/Rock"}),
        primvars=primvars,
        prototypes=frozenset(
            {
                f"{protos}/Leaf/Blade",
                f"{protos}/Rock",
                f"{protos}/Pebble/Geom",
                f"{protos}/Unused",
                f"{protos}/Wisp",
                f"{tagged}/Protos/Rock",
                "/World/Kits/KitA/Spray/Protos/Pellet",
                "/World/Kits/KitB/Spray/Protos/Pellet",
            }
        ),
    )


# --- Generated transform hierarchies -------------------------------------------------------------------------

GENERATED_SEEDS = (3, 17, 29, 101, 2026)  # recorded, so each generated input is reproducible (TMETA-04)
_DEPTH = 3  # levels of Xforms below World, at most; the last holds only meshes
_RESET = 0.15  # the chance a prim below World resets the transform stack


@dataclass
class HierarchyScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    seed: int
    meters_per_unit: float
    up_axis: str
    world_matrices_by_source: dict[
        str, Gf.Matrix4d
    ]  # drawn mesh -> world transform, composed here from the ops written
    reset_transform_paths: frozenset[str]  # the prims, meshes or Xforms, whose own ops reset the transform stack


def _ops(rng: random.Random) -> list[tuple[str, object, Gf.Matrix4d]]:
    """A prim's random ops, in xformOpOrder's order: (op type, value, matrix). Values are exact in binary."""
    ops: list[tuple[str, object, Gf.Matrix4d]] = []
    for _ in range(rng.randint(0, 3)):
        kind = rng.choice(("translate", "rotateX", "rotateY", "rotateZ", "scale"))
        if kind == "translate":
            x, y, z = (rng.randint(-8, 8) / 2 for _ in range(3))
            ops.append((kind, Gf.Vec3d(x, y, z), translate(x, y, z)))
        elif kind == "scale":
            x, y, z = (rng.choice((-1.0, 0.5, 1.0, 2.0)) for _ in range(3))
            ops.append((kind, Gf.Vec3d(x, y, z), scale(x, y, z)))
        else:
            degrees = rng.randrange(-180, 181, 15)
            axis = {"rotateX": (1, 0, 0), "rotateY": (0, 1, 0), "rotateZ": (0, 0, 1)}[kind]
            ops.append((kind, float(degrees), rotate(axis, degrees)))
    return ops


def _write_ops(spec: Sdf.PrimSpec, ops: list[tuple[str, object, Gf.Matrix4d]], *, reset: bool) -> Gf.Matrix4d:
    """Author ops on spec, after a reset of the transform stack if reset; its local transform."""
    names = []
    for index, (kind, value, _matrix) in enumerate(ops):
        name = f"xformOp:{kind}:op{index}"
        type_name = Sdf.ValueTypeNames.Double3 if kind in {"translate", "scale"} else Sdf.ValueTypeNames.Double
        Sdf.AttributeSpec(spec, name, type_name).default = value
        names.append(name)
    order = Sdf.AttributeSpec(spec, "xformOpOrder", Sdf.ValueTypeNames.TokenArray, Sdf.VariabilityUniform)
    order.default = Vt.TokenArray(["!resetXformStack!", *names] if reset else names)
    return local(*(matrix for _kind, _value, matrix in ops))


@contextmanager
def generated_hierarchy(dest: Path, seed: int) -> Generator[HierarchyScene]:
    """A transform hierarchy generated from seed onto scenes/evaluation/hierarchy_base.usda (TMETA-04).

    World gets random ops, then up to three levels of Xforms below it, each with two to four children, a child a
    mesh or, above the last level, an Xform too; every prim gets zero to three random translate, rotate, and scale
    ops, negative and nonuniform scales included, so shears arise, and may reset the transform stack. The stage is
    in centimeters or meters, Y-up or Z-up. Written to hierarchy.usda through Sdf, so one seed writes the same bytes.
    """
    rng = random.Random(seed)
    base = Sdf.Layer.OpenAsAnonymous(str(copy_scene(Scene.EVALUATION, dest) / "hierarchy_base.usda"))
    layer = Sdf.Layer.CreateNew(str(dest / "hierarchy.usda"))
    layer.TransferContent(base)
    layer.documentation = f"A generated transform hierarchy, seed {seed} (tests/fixtures/evaluation.py)"
    meters_per_unit, up_axis = rng.choice((0.01, 1.0)), rng.choice(("Y", "Z"))
    layer.pseudoRoot.SetInfo("metersPerUnit", meters_per_unit)
    layer.pseudoRoot.SetInfo("upAxis", up_axis)
    world_spec = layer.GetPrimAtPath("/World")
    world_matrix = _write_ops(world_spec, _ops(rng), reset=False)
    drawn: dict[str, Gf.Matrix4d] = {}
    resets: set[str] = set()

    def build(parent: Sdf.PrimSpec, parent_world: Gf.Matrix4d, depth: int) -> None:
        for index in range(rng.randint(2, 4)):
            mesh = depth == _DEPTH or rng.random() < 0.3
            spec = Sdf.PrimSpec(parent, f"{'Mesh' if mesh else 'Group'}{index}", Sdf.SpecifierDef)
            spec.typeName = "Mesh" if mesh else "Xform"
            reset = rng.random() < _RESET
            matrix = _write_ops(spec, _ops(rng), reset=reset)
            path = str(spec.path)
            if reset:
                resets.add(path)
            at = world(matrix) if reset else world(matrix, parent_world)
            if mesh:
                spec.referenceList.Prepend(Sdf.Reference(primPath="/Shapes/Tetra"))
                drawn[path] = at
            else:
                build(spec, at, depth + 1)

    build(world_spec, world_matrix, 1)
    layer.Save()
    root = dest / "hierarchy.usda"
    yield HierarchyScene(root, open_stage_without_cache(root), seed, meters_per_unit, up_axis, drawn, frozenset(resets))
