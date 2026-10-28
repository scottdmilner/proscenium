"""M4's object baseline (M04-prototypes plan, B1): the structure M1b's bridge and apply.py build in Blender.

One object per drawn copy and destination, sharing only equivalent geometry, with each destination's hide flag,
materials, and world transform, on the two feasibility fixtures. Expected values come from how the fixtures are
built and from UsdGeom and UsdShade.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pxr import Gf, Tf, Usd, UsdGeom, UsdShade

from fixtures import appearance

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Generator

BODY = Path(__file__).parent / "bodies/baseline.py"
MESH = Tf.Type.Find(UsdGeom.Mesh)
# Each destination's material purpose, as GRAM-12 settles: preview in the viewport, full in the final render.
PURPOSES = {"viewport": UsdShade.Tokens.preview, "render": UsdShade.Tokens.full}


@dataclass(frozen=True)
class BaselineScene:
    """A fixture's scene, with the drawn meshes each destination shows, as the fixture is built."""

    root: Path
    stage: Usd.Stage
    shown: dict[str, frozenset[str]]  # destination -> drawn meshes it shows


@pytest.fixture(params=["appearance", "stress"])
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[BaselineScene]:
    if request.param == "appearance":
        with appearance.appearance_cases(tmp_path) as cases:
            # Every mesh in the appearance scene is visible with default purpose.
            drawn = frozenset(_drawn(cases.stage))
            yield BaselineScene(cases.root, cases.stage, {"viewport": drawn, "render": drawn})
    else:
        with appearance.nested_stress(tmp_path) as stress:
            yield BaselineScene(stress.root, stress.stage, {"viewport": stress.viewport, "render": stress.render})


@pytest.fixture
def result(scene: BaselineScene, wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> dict[str, Any]:
    result = run_isolated(wheel, BODY, "apply_scene", tmp_path, module_dir=str(hydra_bridge), scene=str(scene.root))
    assert result["errors"] == []
    return result


@pytest.fixture
def applied(result: dict[str, Any]) -> list[dict[str, Any]]:
    return result["objects"]


def _drawn(stage: Usd.Stage) -> dict[str, Usd.Prim]:
    """Every mesh USD draws, one per copy: instance contents through their proxies."""
    prims = Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
    return {str(p.GetPath()): p for p in prims if p.IsA(MESH)}


def _instance_context(prim: Usd.Prim) -> list[str]:
    """The native instance roots above a drawn copy, outermost first."""
    roots = [str(p.GetPath()) for p in _ancestors(prim) if p.IsInstance()]
    return roots[::-1]


def _ancestors(prim: Usd.Prim) -> Generator[Usd.Prim]:
    prim = prim.GetParent()
    while prim and not prim.IsPseudoRoot():
        yield prim
        prim = prim.GetParent()


def _resets_in_instance(prim: Usd.Prim) -> bool:
    """Whether a drawn copy or an ancestor below its nearest instance root resets the transform stack."""
    while prim and not prim.IsPseudoRoot() and not prim.IsInstance():
        if UsdGeom.Xformable(prim).GetResetXformStack():
            return True
        prim = prim.GetParent()
    return False


def _bound(prim: Usd.Prim, purpose: str) -> str | None:
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(purpose)
    return str(material.GetPath()) if material else None


def _face_materials(prim: Usd.Prim, purpose: str) -> list[str | None]:
    """Each face's material for one material purpose: its materialBind subset's, or else the mesh's."""
    faces = len(UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get())
    shown = [_bound(prim, purpose)] * faces
    for subset in UsdShade.MaterialBindingAPI(prim).GetMaterialBindSubsets():
        for face in subset.GetIndicesAttr().Get():
            shown[face] = _bound(subset.GetPrim(), purpose)
    return shown


def _by_source(objects: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in objects:
        grouped[obj["source"]].append(obj)
    return grouped


def test_one_object_per_drawn_copy_and_destination(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    drawn = _drawn(scene.stage)
    grouped = _by_source(applied)
    assert set(grouped) == set(drawn)
    for path, objects in grouped.items():
        for destination, shown in scene.shown.items():
            displaying = [o for o in objects if o[destination]]
            assert len(displaying) == (1 if path in shown else 0), (path, destination)
        if any(path in shown for shown in scene.shown.values()):
            assert all(o["viewport"] or o["render"] for o in objects), path
        else:  # a copy shown in neither destination still has one object, for correspondence
            assert len(objects) == 1, path
        for obj in objects:
            assert obj["instance_context"] == _instance_context(drawn[path]), path
            assert obj["placeholder"] is None, path
            assert obj["mesh"] is not None, path


def test_materials_per_destination(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    drawn = _drawn(scene.stage)
    for obj in applied:
        prim = drawn[obj["source"]]
        for destination, purpose in PURPOSES.items():
            if not obj[destination]:
                continue
            expected = _face_materials(prim, purpose)
            shown = [obj["slots"][slot] for slot in obj["face_slots"]]
            assert len(shown) == len(expected), obj["source"]
            for face, (sources, material) in enumerate(zip(shown, expected, strict=True)):
                assert (sources is None) == (material is None), (obj["source"], destination, face)
                assert material is None or material in sources, (obj["source"], destination, face, sources)


def test_shared_meshes_hold_equivalent_geometry(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    drawn = _drawn(scene.stage)

    def geometry(path: str) -> str:
        # Copies of one prototype mesh are one prim in the prototype; any other mesh is only itself.
        prim = drawn[path]
        return str(prim.GetPrimInPrototype().GetPath() if prim.IsInstanceProxy() else prim.GetPath())

    users: dict[str, set[str]] = defaultdict(set)
    for obj in applied:
        users[obj["mesh"]].add(geometry(obj["source"]))
    assert all(len(geometries) == 1 for geometries in users.values()), users


def test_world_transforms_match_usdgeom(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # Shear, negative and nonuniform scale, and a reset stack inside instances (XFORM-01 to XFORM-03), in the plan.
    drawn = _drawn(scene.stage)
    cache = UsdGeom.XformCache()
    wrong = [
        o["source"]
        for o in applied
        if not Gf.IsClose(Gf.Matrix4d(o["plan_world"]), cache.GetLocalToWorldTransform(drawn[o["source"]]), 1e-6)
    ]
    assert not wrong


def _sheared(world: Gf.Matrix4d) -> bool:
    """Whether a world transform's axes aren't orthogonal: its rows, in USD's row-vector convention."""
    axes = [world.GetRow3(i) for i in range(3)]
    return any(
        abs(Gf.Dot(axes[i], axes[j])) > 1e-6 * axes[i].GetLength() * axes[j].GetLength()
        for i, j in ((0, 1), (0, 2), (1, 2))
    )


def test_blender_world_transforms_match_usdgeom(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # What Blender composes once the depsgraph evaluates each object: a sheared copy through its parent empty,
    # which only sheared copies have (XFORM-03).
    drawn = _drawn(scene.stage)
    cache = UsdGeom.XformCache()
    wrong = []
    for obj in applied:
        usd = cache.GetLocalToWorldTransform(drawn[obj["source"]])
        if not Gf.IsClose(Gf.Matrix4d(obj["world"]), usd, 1e-5):
            wrong.append(obj["source"])
        assert obj["shear_parent"] == (obj["source"] if _sheared(usd) else None), obj["source"]
    assert not wrong


def test_known_gap_hydra_ignores_a_reset_inside_an_instance(scene: BaselineScene, result: dict[str, Any]) -> None:
    # WORKAROUND for OpenUSD #862 (ResetsBelow in the bridge's instancing.h): Hydra's own composition, a copy's
    # flattened transform then its instance's, is wrong exactly for the copies under a reset inside an instance.
    # This fails once Hydra honors the reset, and the workaround can go.
    drawn = _drawn(scene.stage)
    cache = UsdGeom.XformCache()
    hydra = result["hydra_world"]
    wrong = {
        s
        for s, rows in hydra.items()
        if not Gf.IsClose(Gf.Matrix4d(rows), cache.GetLocalToWorldTransform(drawn[s]), 1e-6)
    }
    assert hydra
    assert wrong == {s for s in hydra if _resets_in_instance(drawn[s])}
