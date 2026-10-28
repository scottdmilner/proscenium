"""M4's object baseline (M04-prototypes plan, B1): the structure M1b's bridge and apply.py build in Blender.

One object per drawn copy and destination, sharing only equivalent geometry, with each destination's hide flag
and materials, on the two feasibility fixtures. Expected values come from how the fixtures are built and from
UsdGeom and UsdShade; appearance values (transforms, colors, shading) are B4's.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pxr import Tf, Usd, UsdGeom, UsdShade

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
def applied(scene: BaselineScene, wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> list[dict[str, Any]]:
    result = run_isolated(wheel, BODY, "apply_scene", tmp_path, module_dir=str(hydra_bridge), scene=str(scene.root))
    assert result["errors"] == []
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
