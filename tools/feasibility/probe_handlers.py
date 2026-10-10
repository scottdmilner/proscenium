"""Probe 3: do load_post, undo_post, and redo_post handlers fire reliably?"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from _common import Probe

if TYPE_CHECKING:
    from collections.abc import Callable


def run() -> dict[str, Any]:
    import bpy
    from bpy.app.handlers import persistent

    p = Probe("handlers")
    fired: Counter[str] = Counter()

    def make(name: str, keep: bool) -> Callable[..., None]:
        def handler(*_args: Any) -> None:
            fired[name] += 1

        return persistent(handler) if keep else handler

    registered = {
        "load_post": make("load_post", True),
        "undo_post": make("undo_post", True),
        "redo_post": make("redo_post", True),
    }
    transient = make("load_post_transient", False)
    for event, fn in registered.items():
        getattr(bpy.app.handlers, event).append(fn)
    bpy.app.handlers.load_post.append(transient)
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        p.fact("load_post fires on read_factory_settings", lambda: fired["load_post"])
        # read_factory_settings may already have cleared the transient handler.
        if transient not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(transient)
        blend = p.tmp / "h.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        before = fired["load_post"]
        bpy.ops.wm.open_mainfile(filepath=str(blend))
        p.check("persistent load_post fires once per open_mainfile", lambda: fired["load_post"] - before, expect=1)
        p.check("transient load_post removed by file load", lambda: transient not in bpy.app.handlers.load_post)

        bpy.ops.ed.undo_push(message="base")
        bpy.data.objects.new("H", None)
        bpy.ops.ed.undo_push(message="add H")
        p.fact("undo returns", lambda: sorted(bpy.ops.ed.undo()))
        p.check("undo_post fires once per undo", lambda: fired["undo_post"], expect=1)
        p.fact("redo returns", lambda: sorted(bpy.ops.ed.redo()))
        p.check("redo_post fires once per redo", lambda: fired["redo_post"], expect=1)
        p.fact("counts", lambda: dict(fired))
    finally:
        for event, fn in registered.items():
            handlers = getattr(bpy.app.handlers, event)
            if fn in handlers:
                handlers.remove(fn)
        if transient in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(transient)
    return p.result()
