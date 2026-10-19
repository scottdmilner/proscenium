"""Isolated body: a binding becomes unattached once the caller releases its attached stage (SRC-02).

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_attachments.py.
"""

from __future__ import annotations

import gc
import time
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd

from fixtures import source_access
from proscenium.core.source_access import SourceRegistry, SourceUnavailable
from support.usd import open_fresh

# Expiry can lag a release, by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C).
EXPIRY_WAIT = 2.0


def caller_releases_its_stage(tmp_dir: str) -> dict[str, Any]:
    """Attach, acquire the evaluation stage, then drop every reference to the caller's stage."""
    registry = SourceRegistry()
    binding = registry.add_attached("a", "shot", Usd.Stage.LoadAll)
    with source_access.reattach(Path(tmp_dir)) as scene:
        caller = open_fresh(scene.root)  # this body's own stage, so it holds the only reference
        session = caller.GetSessionLayer().identifier
        registry.attach("shot", caller)
        evaluation = binding.acquire()
        result: dict[str, Any] = {"attached_before": binding.live_stage == caller}
        del evaluation, caller
        deadline = time.monotonic() + EXPIRY_WAIT
        while binding.live_stage is not None and time.monotonic() < deadline:
            gc.collect()
            time.sleep(0.01)
        result["attached_after"] = binding.live_stage is not None
        try:
            binding.acquire()
            result["acquire"] = "acquired"
        except SourceUnavailable:
            result["acquire"] = "unavailable"
        gc.collect()
        # The evaluation stage held the caller's session layer; dropping it lets the layer go too.
        result["session_layer_freed"] = not Sdf.Layer.Find(session)
    return result
