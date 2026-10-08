"""Reset and check in-process Blender state, so blender-layer tests can share one process.

Each pytest-xdist worker is one process running the bpy wheel; its tests run one
at a time. tests/blender/conftest.py calls these around every test:
- before: `reset()`, then `baseline_problems()` must report nothing;
- after: `cleanup()` removes what the test registered.

USD's layer registry and stage caches are per process, so tests in different
workers never share stages; within a worker, the baseline check catches leftovers.
"""

from __future__ import annotations

import gc
from collections import Counter
from collections.abc import Callable

import bpy
from pxr import Sdf, UsdUtils

import proscenium
from proscenium import addon

HandlerLists = dict[str, list[Callable[..., object]]]

# ID collections that a factory reset with use_empty=True still fills: UI data and one
# scene. all_ids is every ID at once, so it is never empty.
FACTORY_POPULATED = frozenset({"screens", "workspaces", "window_managers", "scenes", "all_ids"})


def handler_lists() -> HandlerLists:
    """Every bpy.app.handlers list by event name (load_post, undo_post, ...); the live lists."""
    handlers = bpy.app.handlers
    return {name: hlrs for name in dir(handlers) if isinstance(hlrs := getattr(handlers, name), list)}


def snapshot_handlers() -> HandlerLists:
    """Copies of the handler lists, to restore later."""
    return {name: list(fns) for name, fns in handler_lists().items()}


def handler_names(snapshot: HandlerLists) -> dict[str, Counter[str]]:
    """Handlers by module and qualified name.

    Blender re-registers its own handlers as new function objects on every
    factory reset, so the baseline compares names rather than identity.
    """
    return {event: Counter(_name(fn) for fn in fns) for event, fns in snapshot.items()}


def _name(fn: Callable[..., object]) -> str:
    # Handlers are usually functions, but any callable can be registered.
    return f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}"


def cleanup(before: HandlerLists) -> None:
    """Remove what a test left behind: the registered extension, added handlers, cached stages."""
    if addon.is_registered():
        proscenium.unregister()
    for event, fns in handler_lists().items():
        for fn in [fn for fn in fns if fn not in before.get(event, [])]:
            fns.remove(fn)
    UsdUtils.StageCache.Get().Clear()


def reset() -> None:
    """Replace Blender's data and preferences with the empty factory state (~30 ms)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Blender 5.2.2 (wheel and binary) appends pose_library's load_pre/load_post
    # handler again on every factory reset, as the same function object. Drop
    # repeats so a long-lived worker matches a fresh process.
    for fns in handler_lists().values():
        unique = list(dict.fromkeys(fns))
        if len(unique) != len(fns):
            fns[:] = unique
    gc.collect()  # releases USD layers no longer referenced from Python


def baseline_problems(baseline_handlers: dict[str, Counter[str]]) -> list[str]:
    """How the current state differs from the clean state a test may assume; empty when clean."""
    problems = []
    # Registered in-process, so a factory reset does not unregister it.
    if addon.is_registered():
        problems.append("the extension is still registered")
    # A leftover @persistent handler would fire on the next test's loads and undo steps.
    names = handler_names(snapshot_handlers())
    if names != baseline_handlers:
        extra = {event: list(names[event] - baseline_handlers.get(event, Counter())) for event in names}
        problems.append(f"handlers differ from the baseline; extra: { {e: fns for e, fns in extra.items() if fns} }")
    # Leftover datablocks cause name collisions (Mesh.001) and inflate resource counts.
    for prop in bpy.data.bl_rna.properties:
        if prop.type != "COLLECTION" or prop.identifier in FACTORY_POPULATED:
            continue
        if ids := [id_.name for id_ in getattr(bpy.data, prop.identifier)]:
            problems.append(f"bpy.data.{prop.identifier} is not empty: {ids}")
    # The factory state has exactly one scene, and it must be empty.
    scenes = list(bpy.data.scenes)
    if len(scenes) != 1 or scenes[0].objects or scenes[0].collection.children:
        problems.append(f"expected one empty scene, found {[s.name for s in scenes]}")
    # Inside a cache context, Usd.Stage.Open could hand a later test this cached stage.
    if UsdUtils.StageCache.Get().Size():
        problems.append("UsdUtils.StageCache is not empty")
    # A dirty layer still loaded would hand its unsaved edits to a later test opening the same file.
    if dirty := [layer.identifier for layer in Sdf.Layer.GetLoadedLayers() if layer.dirty and not layer.anonymous]:
        problems.append(f"file-backed layers with unsaved edits are still loaded: {dirty}")
    return problems
