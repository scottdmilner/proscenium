"""M4 Phase C (C4): the baseline's interaction functions at scale, timed in-process after a synchronization.

Each operation is far below the sampler's 10 ms resolution, so it is timed with a monotonic clock, repeated, and
reported as the median and range of its repeats; the parent's runs then give the spread between processes.

- Q6: the browsing universe under both payload policies, deriving it from correspondence, `displayed` over the
  whole stage browser (every prim, and every prim with instance proxies), and expanding the prim with the most
  children, which lists them on the live stage and asks `displayed` of each.
- Q9: each interaction function, with the Blender updates it triggers, for one pick of a copy inside the deepest
  instance context, and for a box selection over the top-level prim with the most viewport elements. The kind
  promotion's share is `selection_from_blender` at a kind level against the prim level.

`selection` is the display component, the baseline's selection.py or the batched display's batch_selection.py, and
`target` what its functions take: the collection, or the batched display. On the batched display, a pick first
resolves what a ray cast at the copy would return to its element (`pick_element`, timed too).
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from typing import TYPE_CHECKING, Any

import bpy
from mathutils import Matrix
from pxr import Usd

if TYPE_CHECKING:
    from collections.abc import Callable

SINGLE_REPEATS = 20
WHOLE_REPEATS = 5
LEVELS = ("component", "assembly")


def _timed(repeats: int, call: Callable[[], Any]) -> tuple[dict[str, float], Any]:
    times, result = [], None
    for _ in range(repeats):
        start = time.perf_counter()
        result = call()
        times.append(time.perf_counter() - start)
    return {"median": statistics.median(times), "min": min(times), "max": max(times), "repeats": repeats}, result


def measure(native: Any, selection: Any, stage: Usd.Stage, plan: Any, target: Any, time_code: float) -> dict:
    """Every timing, by operation name, with the sizes it covered."""
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    interaction = native.Interaction(stage, plan)
    records = plan.objects
    universe = plan.universe
    results: dict[str, Any] = {}
    sizes: dict[str, Any] = {"objects": len(records), "universe (payloads loaded)": len(universe)}

    # Q6: the universe, the whole stage browser, and expansion.
    results["derive universe"], _ = _timed(SINGLE_REPEATS, lambda: native.rebuild_correspondence(plan))
    prims = [str(p.GetPath()) for p in stage.Traverse()]
    proxies = [str(p.GetPath()) for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())][1:]
    sizes |= {"browser prims": len(prims), "browser prims with instance proxies": len(proxies)}
    results["displayed, every prim"], shown = _timed(WHOLE_REPEATS, lambda: interaction.displayed(prims))
    results["displayed, with instance proxies"], _ = _timed(WHOLE_REPEATS, lambda: interaction.displayed(proxies))
    sizes["browser prims displayed"] = sum(shown)
    widest = max(universe, key=lambda path: len(stage.GetPrimAtPath(path).GetChildren()))

    def expand() -> list[bool]:
        children = stage.GetPrimAtPath(widest).GetFilteredChildren(Usd.TraverseInstanceProxies())
        return interaction.displayed([str(child.GetPath()) for child in children])

    results["expand the widest prim"], expanded = _timed(SINGLE_REPEATS, expand)
    sizes |= {"widest prim": widest, "its children": len(expanded)}

    # Q9: one pick, inside the deepest instance context among the viewport's elements.
    viewport = [i for i, r in enumerate(records) if r["viewport"]]
    picked = max(viewport, key=lambda i: (len(records[i]["instance_context"]), -i))
    sizes |= {"picked": records[picked]["source"], "its instance roots": len(records[picked]["instance_context"])}
    if hasattr(selection, "pick_element"):
        hit = _hit(target, picked, records[picked])
        results["single: pick_element"], found = _timed(SINGLE_REPEATS, lambda: selection.pick_element(target, *hit))
        assert found == picked, (found, picked)
        sizes["picked batch's instances"] = next((len(b.elements) for b in target.batches if picked in b.elements), 0)
    results |= _entry("single", SINGLE_REPEATS, interaction, selection, view_layer, target, [picked], "component")

    # A box selection over the top-level prim with the most viewport elements.
    tops = Counter(r["floor"].split("/")[1] for r in (records[i] for i in viewport))
    top, count = tops.most_common(1)[0]
    elements = interaction.highlight_targets([f"/{top}"])
    sizes |= {
        "assembly": f"/{top}",
        "its kind": Usd.ModelAPI(stage.GetPrimAtPath(f"/{top}")).GetKind(),
        "its viewport elements": len(elements),
    }
    results |= _entry("assembly", WHOLE_REPEATS, interaction, selection, view_layer, target, elements, "assembly")

    # The universe without payloads: the other payload policy, captured after unloading every payload.
    stage.Unload("/")
    bridge = native.Bridge(stage)
    sizes["universe (no payloads)"] = len(native.build_plan(bridge.capture(time_code)).universe)
    bridge.release()
    stage.Load("/")
    return {"timings": results, "sizes": sizes}


def _hit(display: Any, element: int, record: Any) -> tuple[Any, Matrix]:
    """What a ray cast at `element`'s copy returns: its object, or its prototype, and its world matrix."""
    kept = display.objects.get(element)
    if kept is not None:
        return kept, kept.matrix_world.copy()
    batch = next(b for b in display.batches if element in b.elements)
    matrix = record["matrix"]
    # USD multiplies row vectors (translation in the last row); Blender multiplies column vectors.
    world = Matrix([[matrix[row, col] for col in range(4)] for row in range(4)]).transposed()
    return batch.prototype, batch.carriers[0].matrix_world @ world


def _entry(  # noqa: PLR0913 - the chain's whole context
    name: str,
    repeats: int,
    interaction: Any,
    selection: Any,
    view_layer: Any,
    target: Any,
    picks: list[int],
    highlighted: str,
) -> dict[str, dict[str, float]]:
    """A pick or a box selection through every function, as the contract chains them, highlighting at a level."""
    results: dict[str, dict[str, float]] = {}
    results[f"{name}: resolve_pick"], entities = _timed(
        repeats, lambda: [interaction.resolve_pick(element) for element in picks]
    )
    pairs = [(e["source"], e["instance_context"]) for e in entities]
    results[f"{name}: select_targets, prim level"], _ = _timed(repeats, lambda: interaction.select_targets(pairs))
    targets: dict[str, Any] = {}
    for level in LEVELS:
        results[f"{name}: select_targets, {level}"], targets[level] = _timed(
            repeats, lambda level=level: interaction.select_targets(pairs, level)
        )
    results[f"{name}: highlight_targets, {highlighted}"], shown = _timed(
        repeats, lambda: interaction.highlight_targets(targets[highlighted])
    )
    active = shown[:1]

    def mirror() -> None:
        selection.apply_selection(view_layer, target, set(shown), set(active))
        view_layer.update()

    def clear() -> None:
        selection.apply_selection(view_layer, target, set(), set())
        view_layer.update()

    times = []
    for _ in range(repeats):
        clear()
        start = time.perf_counter()
        mirror()
        times.append(time.perf_counter() - start)
    results[f"{name}: apply_selection, with the depsgraph update"] = {
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
        "repeats": repeats,
    }
    results[f"{name}: read_blender_selection"], blender = _timed(
        repeats, lambda: selection.read_blender_selection(view_layer, target)
    )
    results[f"{name}: selection_from_blender, prim level"], _ = _timed(
        repeats, lambda: interaction.selection_from_blender(blender.selected, blender.active)
    )
    for level in LEVELS:
        results[f"{name}: selection_from_blender, {level}"], _ = _timed(
            repeats, lambda level=level: interaction.selection_from_blender(blender.selected, blender.active, level)
        )
    clear()
    return results
