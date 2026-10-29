"""Appearance fixtures: the representation feasibility cases and the stress fixture as scenes.

- appearance_cases (F-APPEARANCE-CASES): the primvar and connection cases of
  spec/support/geometry.md#representation-feasibility-cases and
  spec/support/materials.md#representation-feasibility-cases, one child of /World per case.
- nested_stress (F-NESTED-STRESS): shear, negative determinants, nonuniform scale, and a reset
  transform stack inside nested instances with differing appearance and separate purposes.

Each copies its layer from Scene.APPEARANCE, opens it as the caller's live stage, and yields
what the scene is built to display, written out by hand from the layer. Meshes inside instance
contents are named by their instance-proxy paths, one per drawn copy.
tests/bpy_free/test_appearance_fixtures.py checks these against USD's own APIs.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Gf

from support.usd import open_fresh

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pxr import Usd

Color = tuple[float, float, float]
LOOKS = "/World/Looks"


@dataclass
class AppearanceScene:
    root: Path
    stage: Usd.Stage  # the caller's live stage
    # Under `shared_roots`, each drawn mesh is in exactly one set: the equivalent uses, which share one geometry
    # resource. A representation may share more where the display stays correct (M4 plan, B5).
    shared_roots: tuple[str, ...]
    shared: tuple[frozenset[str], ...]
    # Mesh -> (interpolation, values) of the displayColor and displayOpacity it shows, its own or inherited.
    display_color: dict[str, tuple[str, tuple[Color, ...]]]
    display_opacity: dict[str, tuple[str, tuple[float, ...]] | None]
    # Mesh without subsets -> its material in the viewport (preview purpose) and final render (full); None: none.
    materials: dict[str, tuple[str | None, str | None]]
    face_materials: dict[str, tuple[str | None, ...]]  # mesh with subsets -> each face's viewport material
    # (mesh, primvar a reader of its material reads) -> the value shown: the copy's own, or the reader's fallback.
    reader_values: dict[tuple[str, str], Color | float]
    # (mesh, primvar) -> the constant string the copy inherits from its instance root.
    string_values: dict[tuple[str, str], str]
    uv_sets: dict[tuple[str, ...], dict[str, frozenset[str]]]  # UV-set names -> mesh -> its UV sets
    texture_uvs: dict[str, str]  # mesh -> the UV set its material's texture is sampled through


@dataclass
class StressScene:
    root: Path
    stage: Usd.Stage  # the caller's live stage
    world: dict[str, Gf.Matrix4d]  # drawn mesh -> world transform (USD row-vector convention)
    negative: frozenset[str]  # drawn meshes whose world transform has a negative determinant
    sheared: frozenset[str]  # drawn meshes whose world transform has non-orthogonal axes
    viewport: frozenset[str]  # drawn meshes the viewport shows (default and proxy purposes)
    render: frozenset[str]  # drawn meshes the final render shows (default and render purposes)
    display_color: dict[str, Color | None]  # drawn mesh -> its inherited constant displayColor


def _open(dest: Path, layer: str) -> tuple[Path, Usd.Stage]:
    root = copy_scene(Scene.APPEARANCE, dest) / layer
    return root, open_fresh(root)


@contextmanager
def appearance_cases(dest: Path) -> Generator[AppearanceScene]:
    """F-APPEARANCE-CASES: see scenes/appearance/appearance.usda."""
    kits = [f"/World/SharedPrototype/Kit{c}" for c in "ABC"]
    equal = "/World/EqualContent"
    colors, inherited = "/World/MeshDisplayColor", "/World/InheritedColor"
    red, blue, green, yellow = (f"{LOOKS}/{m}" for m in ("Red", "Blue", "Green", "Yellow"))
    tinted, display_tinted = f"{LOOKS}/Tinted", f"{LOOKS}/DisplayTinted"
    swatches, uvs = "/World/InstancePrimvars", "/World/NamedUVs"
    one, purposes = "/World/OneMaterial", "/World/PurposeBindings"

    # InheritedColor: the nearest opinion wins, the mesh's own, then the inner root's, then the outer's.
    own, inner_green = (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)
    outer = {"OuterRed": (1.0, 0.0, 0.0), "OuterBlue": (0.0, 0.0, 1.0)}
    inherited_color: dict[str, tuple[str, tuple[Color, ...]]] = {}
    inherited_opacity: dict[str, tuple[str, tuple[float, ...]] | None] = {}
    for root_name, outer_color in outer.items():
        for inner, bare_color in (("InnerGreen", inner_green), ("InnerBare", outer_color)):
            base = f"{inherited}/{root_name}/{inner}"
            inherited_color[f"{base}/Own"] = ("constant", (own,))
            inherited_color[f"{base}/Bare"] = ("constant", (bare_color,))
            for mesh in ("Own", "Bare"):  # only OuterRed authors an opacity
                inherited_opacity[f"{base}/{mesh}"] = ("constant", (0.75,)) if root_name == "OuterRed" else None

    unbound = [f"{equal}/Mesh{c}" for c in "ABCDEF"] + [f"{colors}/{m}" for m in ("Constant", "ConstantIndexed")]
    unbound += [f"{colors}/{m}" for m in ("Uniform", "Vertex", "FaceVarying")] + list(inherited_color)
    unbound += [f"{uvs}/PointUVs", f"{uvs}/Untyped"]
    tag_values = (("A", "props"), ("B", "props"), ("C", "screens"))
    tags = {f"/World/StringPrimvars/Tag{c}/Geom": value for c, value in tag_values}
    unbound += list(tags)
    root, stage = _open(dest, "appearance.usda")
    yield AppearanceScene(
        root=root,
        stage=stage,
        shared_roots=("/World/SharedPrototype", equal),
        shared=(
            frozenset(f"{k}/Body" for k in kits),
            frozenset(f"{k}/Lid" for k in kits),
            frozenset({f"{equal}/MeshA", f"{equal}/MeshB"}),  # equal content
            frozenset({f"{equal}/MeshC"}),  # differs only in a constant displayColor
            frozenset({f"{equal}/MeshD"}),  # differs only in its vertex st values
            frozenset({f"{equal}/MeshE"}),  # differs only in its subdivision scheme
            frozenset({f"{equal}/MeshF"}),  # differs only in its sidedness
        ),
        display_color={
            f"{colors}/Constant": ("constant", ((1.0, 0.0, 0.0),)),
            f"{colors}/ConstantIndexed": ("constant", ((0.0, 1.0, 0.0),)),
            f"{colors}/Uniform": ("uniform", ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))),
            f"{colors}/Vertex": ("vertex", ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0))),
            f"{colors}/FaceVarying": ("faceVarying", ((1.0, 0.0, 0.0),) * 3 + ((0.0, 0.0, 1.0),) * 3),
        }
        | inherited_color,
        display_opacity={
            f"{colors}/Constant": ("constant", (0.5,)),
            f"{colors}/ConstantIndexed": None,
            f"{colors}/Uniform": ("uniform", (1.0, 0.25)),
            f"{colors}/Vertex": None,
            f"{colors}/FaceVarying": ("faceVarying", (1.0, 1.0, 1.0, 0.5, 0.5, 0.5)),
        }
        | inherited_opacity,
        materials={mesh: (None, None) for mesh in unbound}
        | {f"{k}/Body": (red, red) for k in kits}  # Body's own green displayColor doesn't show
        | {f"{k}/Lid": (blue, blue) for k in kits}
        | {f"{uvs}/Typed": (f"{LOOKS}/Textured", f"{LOOKS}/Textured")}
        | {f"/World/MaterialPerInstance/Plain{c}/Geom": (m, m) for c, m in (("Red", red), ("Blue", blue))}
        | {f"{swatches}/Swatch{c}/Geom": (tinted, tinted) for c in "ABC"}
        | {f"{swatches}/Color{c}/Geom": (display_tinted, display_tinted) for c in "AB"}
        | {f"{one}/{m}": (tinted, tinted) for m in ("Triangle", "Square")}
        | {
            f"{purposes}/Both": (f"{LOOKS}/PurposePreview", f"{LOOKS}/PurposeFull"),
            f"{purposes}/PreviewOnly": (f"{LOOKS}/PurposePreview", f"{LOOKS}/PurposeAll"),
            f"{purposes}/FullOnly": (None, f"{LOOKS}/PurposeFull"),  # the viewport falls back to no material
        },
        face_materials={
            # Left is faces 0-1, Right face 2; face 3 is unassigned and takes the instance root's binding.
            "/World/FaceAssignments/TileGreen/Geom": (red, red, blue, green),
            "/World/FaceAssignments/TileYellow/Geom": (red, red, blue, yellow),
            "/World/FaceAssignments/Partitioned": (red, blue, red, blue),
        },
        reader_values={
            (f"{swatches}/SwatchA/Geom", "tint"): (1.0, 0.5, 0.0),
            (f"{swatches}/SwatchA/Geom", "rough"): 0.1,
            (f"{swatches}/SwatchB/Geom", "tint"): (0.0, 0.5, 1.0),
            (f"{swatches}/SwatchB/Geom", "rough"): 0.5,  # fallback
            (f"{swatches}/SwatchC/Geom", "tint"): (0.5, 0.5, 0.5),  # fallback
            (f"{swatches}/SwatchC/Geom", "rough"): 0.5,  # fallback
            (f"{swatches}/ColorA/Geom", "displayColor"): (0.0, 1.0, 1.0),
            (f"{swatches}/ColorB/Geom", "displayColor"): (1.0, 1.0, 1.0),  # fallback
            (f"{one}/Triangle", "tint"): (0.2, 0.2, 0.2),
            (f"{one}/Triangle", "rough"): 0.5,  # fallback
            (f"{one}/Square", "tint"): (0.9, 0.9, 0.9),
            (f"{one}/Square", "rough"): 0.9,
        },
        string_values={(mesh, "lightGroup"): value for mesh, value in tags.items()},
        uv_sets={
            (): {
                f"{uvs}/Typed": frozenset({"st", "perfuv"}),
                f"{uvs}/PointUVs": frozenset({"st"}),
                f"{uvs}/Untyped": frozenset(),
            },
            ("st", "uv*"): {
                f"{uvs}/Typed": frozenset({"st", "perfuv"}),
                f"{uvs}/PointUVs": frozenset({"st"}),
                # ST matches st case-insensitively; offset matches nothing; uv_shift matches but is constant.
                f"{uvs}/Untyped": frozenset({"ST"}),
            },
        },
        texture_uvs={f"{uvs}/Typed": "perfuv"},
    )


def _translate(x: float, y: float, z: float) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetTranslate(Gf.Vec3d(x, y, z))


def _scale(x: float, y: float, z: float) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetScale(Gf.Vec3d(x, y, z))


def _rotate_z(degrees: float) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), degrees))


@contextmanager
def nested_stress(dest: Path) -> Generator[StressScene]:
    """F-NESTED-STRESS: see scenes/appearance/nested_stress.usda."""
    # Row vectors: a prim's world transform is its local transform times its parent's world transform.
    shear = Gf.Matrix4d(1, 0, 0, 0, 0.5, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    roots = {
        "/World/Sheared/UnitA": shear,
        "/World/Mirrored/UnitB": _translate(4, 0, 0) * _scale(-1, 2, 0.5),
        "/World/Skewed/UnitC": _rotate_z(45) * _scale(3, 1, 1),
    }
    colors: dict[str, Color | None] = {
        "/World/Sheared/UnitA": (1.0, 0.0, 0.0),
        "/World/Mirrored/UnitB": (0.0, 0.0, 1.0),
        "/World/Skewed/UnitC": None,
    }
    leaf = _scale(1, -1, 1)
    world: dict[str, Gf.Matrix4d] = {}
    display_color: dict[str, Color | None] = {}
    for unit, root_world in roots.items():
        world[f"{unit}/Body"] = _translate(0, 0, 1) * root_world
        world[f"{unit}/Pinned/Pin"] = _translate(10, 0, 0)  # the reset stack drops every ancestor
        world[f"{unit}/Inner/Geom"] = leaf * _translate(2, 0, 0) * root_world
        world[f"{unit}/InnerTinted/Geom"] = leaf * _translate(0, 2, 0) * root_world
        for mesh in ("Proxy", "Render", "Guide"):
            world[f"{unit}/{mesh}"] = root_world
        for mesh in ("Body", "Pinned/Pin", "Inner/Geom", "Proxy", "Render", "Guide"):
            display_color[f"{unit}/{mesh}"] = colors[unit]
        display_color[f"{unit}/InnerTinted/Geom"] = (0.0, 1.0, 0.0)

    units_b = "/World/Mirrored/UnitB"
    leaves = ("Inner/Geom", "InnerTinted/Geom")
    # UnitB's mirror flips every copy but the reset Pin, and the Leaf's mirror flips UnitB's leaves back.
    negative = {f"{units_b}/{m}" for m in ("Body", "Proxy", "Render", "Guide")}
    negative |= {f"{u}/{m}" for u in ("/World/Sheared/UnitA", "/World/Skewed/UnitC") for m in leaves}
    # UnitA's matrix shears; UnitC's rotation inside a nonuniform scale shears; Pin's reset drops both.
    sheared = {p for p in world if p.startswith(("/World/Sheared/", "/World/Skewed/")) and not p.endswith("/Pin")}
    drawn = frozenset(world)
    root, stage = _open(dest, "nested_stress.usda")
    yield StressScene(
        root=root,
        stage=stage,
        world=world,
        negative=frozenset(negative),
        sheared=frozenset(sheared),
        viewport=frozenset(p for p in drawn if not p.endswith(("/Render", "/Guide"))),
        render=frozenset(p for p in drawn if not p.endswith(("/Proxy", "/Guide"))),
        display_color=display_color,
    )
