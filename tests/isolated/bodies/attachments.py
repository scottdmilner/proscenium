"""Isolated body: a binding holds its attached stage until the caller releases it (SRC-02).

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_attachments.py.
"""

from __future__ import annotations

import gc
import time
from pathlib import Path
from typing import Any

from pxr import Sdf

from fixtures import source_access
from proscenium.core._core import StageHandle
from proscenium.core.source_access import PayloadPolicy, SourceRegistry, SourceUnavailable
from support.usd import open_fresh

# Expiry can lag a release, by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C).
EXPIRY_WAIT = 2.0


def caller_drops_then_releases(tmp_dir: str) -> dict[str, Any]:
    """Attach, acquire, drop every caller reference, then release the attachment."""
    registry = SourceRegistry()
    binding = registry.add_attached("a", "shot")
    with source_access.reattach(Path(tmp_dir)) as scene:
        caller = open_fresh(scene.root)  # this body's own stage, so it holds the only caller reference
        caller.SetEditTarget(caller.GetSessionLayer())
        caller.DefinePrim("/Edited")  # an unsaved edit in a layer only this stage composes
        session = caller.GetSessionLayer().identifier
        watch = StageHandle(caller)
        watch.release()  # weak: says whether the stage still exists, without keeping it
        binding.attach(caller)
        binding.acquire(PayloadPolicy.LOAD_ALL)
        del caller
        gc.collect()
        layer = Sdf.Layer.Find(session)
        result: dict[str, Any] = {
            "attached_after_drop": binding.live_stage is not None,
            "edit_loaded_after_drop": layer is not None and layer.GetPrimAtPath("/Edited") is not None,
        }
        del layer
        binding.release()
        deadline = time.monotonic() + EXPIRY_WAIT
        while watch.stage() is not None and time.monotonic() < deadline:
            gc.collect()
            time.sleep(0.01)
        result["expired_after_release"] = watch.stage() is None
        result["attached_after_release"] = binding.live_stage is not None
        try:
            binding.acquire(PayloadPolicy.LOAD_ALL)
            result["acquire"] = "acquired"
        except SourceUnavailable:
            result["acquire"] = "unavailable"
        gc.collect()
        result["session_layer_freed"] = not Sdf.Layer.Find(session)
    return result
