"""Isolated body: the core's StageHandle keeps a stage alive only until release().

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_stage_handle.py.
"""

from __future__ import annotations

import gc
import time
from typing import Any

from pxr import Sdf, Usd

from proscenium.core import _core

# Expiry can lag release(), by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C).
EXPIRY_WAIT = 2.0


def _expired(identifier: str) -> bool:
    deadline = time.monotonic() + EXPIRY_WAIT
    while Sdf.Layer.Find(identifier):
        if time.monotonic() > deadline:
            return False
        gc.collect()
        time.sleep(0.01)
    return True


def caller_drops_then_release() -> dict[str, Any]:
    """The caller drops its stage while the handle holds it, then the handle is released."""
    stage = Usd.Stage.CreateInMemory()
    identifier = stage.GetRootLayer().identifier
    handle = _core.StageHandle(stage)
    result: dict[str, Any] = {"is_callers_stage": handle.stage() == stage}
    del stage
    gc.collect()
    result["alive_while_held"] = handle.stage() is not None and bool(Sdf.Layer.Find(identifier))
    handle.release()
    result["expired_after_release"] = _expired(identifier)
    result["stage_after_release"] = handle.stage() is not None
    result["released"] = handle.released
    return result


def release_while_caller_holds() -> dict[str, Any]:
    """Releasing and deleting the handle leaves a stage the caller still holds alive."""
    stage = Usd.Stage.CreateInMemory()
    handle = _core.StageHandle(stage)
    handle.release()
    handle.release()  # idempotent
    result = {"stage_after_release": handle.stage() == stage}
    del handle
    gc.collect()
    result["caller_stage_valid"] = bool(stage.GetPseudoRoot())
    return result
