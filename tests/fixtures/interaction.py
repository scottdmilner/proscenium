"""Interaction fixtures: the interaction contract's cases as scenes (docs/spec/interaction-contract.md).

- kind_hierarchy (F-KIND-HIERARCHY): an assembly > group > component > subcomponent
  hierarchy whose organizational prims author nothing Hydra needs, and a mesh under no model.
- nested_selection (F-NESTED-SELECTION): nested native instances, one prototype used
  inside and outside an outer instance, and component kinds on instance roots.
- universe_membership (F-UNIVERSE-MEMBERSHIP): one case per child of /World for what is
  and is not in the browsing universe, with visibility animated between time codes.

Each copies its layer from Scene.INTERACTION, opens it as the caller's live stage, and
yields the results the scene is built to produce, written out by hand from the layer.
tests/bpy_free/test_interaction_fixtures.py checks that support/interaction_oracle.py derives
the same results from USD, so checks can compare against the oracle across the whole scene.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from support.usd import open_fresh

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pxr import Usd


@dataclass
class InteractionScene:
    root: Path
    stage: Usd.Stage  # the caller's live stage
    times: tuple[float, ...]  # time codes the checks publish generations at
    elements: dict[float, frozenset[str]]  # time -> display elements (instance-proxy paths in instance contents)
    universe: dict[float, frozenset[str]]  # time -> browsing universe
    floors: dict[str, str]  # display element -> its floor; elements not listed are their own floor
    kind_targets: dict[tuple[str, str | None], str]  # (entity, level) -> target; None is the prim level
    probes: tuple[str, ...] = ()  # paths not on the composed stage, which `displayed` must reject
    # (prim a check removes from the live stage, an entity whose floor that makes absent, a kind level)
    absent_floor: tuple[str, str, str] | None = None
    excluded: dict[str, str] = field(default_factory=dict)  # composed prim -> why it is not in the universe


def _with_ancestors(paths: frozenset[str]) -> frozenset[str]:
    """`paths` and every proper prefix of them, without the pseudo-root."""
    out = set()
    for path in paths:
        parts = path.split("/")[1:]
        out.update("/" + "/".join(parts[:n]) for n in range(1, len(parts) + 1))
    return frozenset(out)


def _open(dest: Path, layer: str) -> tuple[Path, Usd.Stage]:
    root = copy_scene(Scene.INTERACTION, dest) / layer
    return root, open_fresh(root)


@contextmanager
def kind_hierarchy(dest: Path) -> Generator[InteractionScene]:
    """F-KIND-HIERARCHY: see scenes/interaction/kind_hierarchy.usda."""
    chair = "/World/Props/Chair"
    seat, back, legs = f"{chair}/Geom/Seat", f"{chair}/Geom/Back", f"{chair}/Legs"
    shade, top, rock = "/World/Props/Lamp/Shade", "/World/Table/Top", "/Debris/Rock"
    elements = frozenset({seat, back, legs, shade, top, rock})
    root, stage = _open(dest, "kind_hierarchy.usda")
    yield InteractionScene(
        root=root,
        stage=stage,
        times=(0.0,),
        elements={0.0: elements},
        universe={0.0: _with_ancestors(elements)},
        floors={},
        kind_targets={
            (seat, None): seat,
            (seat, "subcomponent"): f"{chair}/Geom",
            (legs, "subcomponent"): legs,  # no subcomponent above Legs: its floor
            (seat, "component"): chair,
            (seat, "model"): chair,  # component derives from model
            (seat, "group"): "/World/Props",
            (top, "group"): "/World",  # assembly derives from group
            (seat, "assembly"): "/World",
            ("/World/Props", "model"): "/World/Props",  # ancestor-or-self, and group derives from model
            (rock, "model"): rock,  # under no model
        },
        probes=("/World/Props/Missing",),
        absent_floor=("/World/Table", top, "group"),
    )


@contextmanager
def nested_selection(dest: Path) -> Generator[InteractionScene]:
    """F-NESTED-SELECTION: see scenes/interaction/nested_selection.usda."""
    crate_a, crate_b = "/World/CrateA", "/World/Shelf/CrateB"
    inside = ("Body", "Hardware/Bolt1/Head", "Hardware/Bolt2/Head")
    floors = {"/World/Bolt/Head": "/World/Bolt"} | {f"{c}/{e}": c for c in (crate_a, crate_b) for e in inside}
    nested_bolt = f"{crate_a}/Hardware/Bolt1/Head"
    root, stage = _open(dest, "nested_selection.usda")
    yield InteractionScene(
        root=root,
        stage=stage,
        times=(0.0,),
        elements={0.0: frozenset(floors)},
        universe={0.0: _with_ancestors(frozenset(floors.values()))},
        floors=floors,
        kind_targets={
            (nested_bolt, None): crate_a,
            (nested_bolt, "component"): crate_a,  # not Bolt1, whose component kind is inside contents
            (nested_bolt, "subcomponent"): crate_a,  # Hardware is inside contents: the floor
            (f"{crate_b}/Body", "group"): "/World/Shelf",
            ("/World/Bolt/Head", "component"): "/World/Bolt",
            ("/World/Bolt/Head", "group"): "/World",
        },
        absent_floor=(crate_b, f"{crate_b}/Hardware/Bolt1/Head", "group"),
        excluded={
            "/World/Bolt/Head": "instance-proxy descendant",
            f"{crate_a}/Hardware": "instance-proxy descendant",
            nested_bolt: "instance-proxy descendant",
            "/Prototypes/Crate": "abstract",
        },
    )


@contextmanager
def universe_membership(dest: Path) -> Generator[InteractionScene]:
    """F-UNIVERSE-MEMBERSHIP: see scenes/interaction/universe_membership.usda. /World/Payload is unloaded."""
    always = frozenset(
        {"/World/Shown/Box", "/World/Proxy/Box", "/World/Mixed/Shown", "/World/Placeholder", "/World/Marker"}
    )
    blinker = "/World/Blinker/Box"
    root, stage = _open(dest, "universe_membership.usda")
    stage.Unload("/World/Payload")
    yield InteractionScene(
        root=root,
        stage=stage,
        times=(0.0, 5.0),
        elements={0.0: always | {blinker}, 5.0: always},
        universe={0.0: _with_ancestors(always | {blinker}), 5.0: _with_ancestors(always)},
        floors={},
        kind_targets={("/World/Shown/Box", "model"): "/World/Shown/Box"},
        probes=("/World/Inactive/Box", "/World/Payload/Box"),
        excluded={
            "/World/Hidden": "invisible",
            "/World/Hidden/Box": "invisible",
            "/World/Guide": "guide purpose",
            "/World/Guide/Box": "guide purpose",
            "/World/RenderOnly": "render-only content beneath",
            "/World/RenderOnly/Box": "render purpose",
            "/World/Mixed/Render": "render purpose",
            "/World/Inactive": "inactive",
            "/World/Payload": "unloaded payload root",
            "/World/Looks": "materials scope",
            "/World/Looks/Material": "material",
            "/World/Looks/Material/Surface": "shader",
            "/World/Empty": "nothing displayed beneath",
            "/World/Empty/Inner": "nothing displayed beneath",
            "/World/Camera": "no display support",
            "/Prototypes": "abstract",
            "/Prototypes/Abstract/Box": "abstract",
        },
    )
