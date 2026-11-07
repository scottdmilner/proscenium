"""Isolated body: the core's StageHandle and SceneIndexChain keep a stage alive only until release().

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


def chain_caller_drops_then_release() -> dict[str, Any]:
    """The caller drops its stage while a scene index chain captures from it, then the chain is released."""
    stage = Usd.Stage.CreateInMemory()
    identifier = stage.GetRootLayer().identifier
    chain = _core.SceneIndexChain(stage)
    result: dict[str, Any] = {"is_callers_stage": chain.stage() == stage}
    del stage
    gc.collect()
    chain.capture(0.0)
    result["alive_while_held"] = chain.stage() is not None and bool(Sdf.Layer.Find(identifier))
    chain.release()
    result["expired_after_release"] = _expired(identifier)
    result["stage_after_release"] = chain.stage() is not None
    result["released"] = chain.released
    return result


def chain_release_while_caller_holds() -> dict[str, Any]:
    """Releasing and deleting a scene index chain leaves a stage the caller still holds alive."""
    stage = Usd.Stage.CreateInMemory()
    chain = _core.SceneIndexChain(stage)
    chain.capture(0.0)
    chain.release()
    result = {"stage_after_release": chain.stage() == stage}
    del chain
    gc.collect()
    result["caller_stage_valid"] = bool(stage.GetPseudoRoot())
    return result
