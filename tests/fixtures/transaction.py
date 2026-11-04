"""Set up the failures the synchronization transaction must survive (docs/spec/pipeline.md#synchronization-transaction).

Each generator copies Scene.TRANSACTION (see its root.usda), opens a caller's stage over it, and yields
what a correct binding does with it: the step where a test injects a failure, and the outcome the spec
requires there. A test injects a failure by patching the step's module function, so no hook exists in
src/ (M5 plan, D12); the fixture names the step and leaves the patching to the test.

- failed_settings (F-FAILED-SETTINGS): a display published under one setting and time code, then an
  attempt under another that fails before publication. Binding State.
- publication_failure (F-PUBLICATION-FAILURE): publication failing, on a first synchronization and on a
  later one. Synchronization Transaction.
- preparation_cleanup_failure (F-PREPARATION-CLEANUP-FAILURE): preparation failing, then the disposal of
  some prepared work failing, on a first synchronization and on a later one. Pending Cleanup.
- retirement_failure (F-RETIREMENT-FAILURE): a synchronization that publishes, then fails to retire some
  of the old generation's resources. Synchronization Transaction.
- source_change (F-SOURCE-CHANGE): a contributing layer edited while the binding evaluates, and changed
  after a generation is synchronized, before cache. Source Consistency, Cached Time Codes.
- cached_time_codes (F-CACHED-TIME-CODES): time codes cached in a generation, a cache call that fails, a
  generation at the default time code, and synchronizing again. Cached Time Codes.

Resource counts follow M5's minimal planner and stub application layer: one placeholder per drawn
gprim, each an object and its bounds mesh (M5 plan, Phase B and D3).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pxr import Gf, Sdf, Usd

from proscenium.binding.results import ResultState
from proscenium.binding.source_access import PayloadPolicy
from support.usd import open_fresh

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class Step(StrEnum):
    """A step of the synchronization transaction, where a test injects a failure."""

    ACQUIRE = "acquire"
    EVALUATE = "evaluate"
    PLAN = "plan"
    PREPARE = "prepare"
    PUBLISH = "publish"
    RETIRE = "retire"
    DISPOSE = "dispose"


# The steps before publication: a failure in any leaves the published generation unchanged (TXN-02).
BEFORE_PUBLICATION = (Step.ACQUIRE, Step.EVALUATE, Step.PLAN, Step.PREPARE, Step.PUBLISH)

# Every drawn gprim's local bounds: tetra.usda's authored extent.
EXTENT = (Gf.Vec3d(0, 0, 0), Gf.Vec3d(1, 1, 1))
ROLES_PER_PLACEHOLDER = ("object", "bounds mesh")

_STILL, _MOVER, _SUB, _PAYLOADED = "/World/Still", "/World/Mover", "/World/Sub", "/World/Payloaded/Tetra"
DRAWN: dict[PayloadPolicy, frozenset[str]] = {
    PayloadPolicy.LOAD_ALL: frozenset((_STILL, _MOVER, _SUB, _PAYLOADED)),
    PayloadPolicy.LOAD_NONE: frozenset((_STILL, _MOVER, _SUB)),
}
SUB_EDITED = Gf.Vec3d(0, -6, 0)  # Sub's translation once F-SOURCE-CHANGE edits sub.usda


def translation(path: str, time_code: float | None) -> Gf.Vec3d:
    """A drawn gprim's world translation, as root.usda is built; None is the default time code."""
    if path == _MOVER:
        return Gf.Vec3d(0, 5, 0) if time_code is None else Gf.Vec3d(min(max(time_code, 0), 20), 0, 0)
    return {_STILL: Gf.Vec3d(-3, 0, 0), _SUB: Gf.Vec3d(0, -3, 0), _PAYLOADED: Gf.Vec3d(0, 0, 3)}[path]


def resource_count(policy: PayloadPolicy) -> int:
    """How many managed resources a published generation under policy holds."""
    return len(DRAWN[policy]) * len(ROLES_PER_PLACEHOLDER)


@dataclass
class TransactionScene:
    root: Path
    caller: Usd.Stage  # the caller's stage, to attach


def _open(dest: Path) -> TransactionScene:
    root = copy_scene(Scene.TRANSACTION, dest) / "root.usda"
    return TransactionScene(root=root, caller=open_fresh(root))


@dataclass
class FailedSettingsScene(TransactionScene):
    published: tuple[PayloadPolicy, float]  # the first synchronization's settings and time code; it publishes
    attempted: tuple[PayloadPolicy, float]  # the second's, set first through set_settings; it fails
    failures: tuple[Step, ...]  # where the second fails, one test run each
    outcome: ResultState


@contextmanager
def failed_settings(dest: Path) -> Generator[FailedSettingsScene]:
    """F-FAILED-SETTINGS: published under load-all at 10, then load-none requested and attempted at 20.

    The attempt fails at each step before publication in turn; at acquisition, by the caller's stage
    being released, a source reason. Afterwards the requested settings are load-none, the published
    generation is load-all at 10 with its four placeholders, and the last attempt is load-none at 20,
    failed (STATE-07's example).
    """
    yield FailedSettingsScene(
        **vars(_open(dest)),
        published=(PayloadPolicy.LOAD_ALL, 10.0),
        attempted=(PayloadPolicy.LOAD_NONE, 20.0),
        failures=BEFORE_PUBLICATION,
        outcome=ResultState.FATAL_FAILURE,
    )


@dataclass
class PublicationFailureScene(TransactionScene):
    failure: Step  # publication fails at each of its writes in turn, correspondence among them
    outcome: ResultState


@contextmanager
def publication_failure(dest: Path) -> Generator[PublicationFailureScene]:
    """F-PUBLICATION-FAILURE: publication fails, on a first synchronization and on one replacing a display.

    On the first, nothing remains afterwards: no content, manifest, generation, or correspondence. On the
    later one, the published generation is the earlier one, whole, and its display unchanged. Prepared
    work is disposed of either way, and no undo step is pushed.
    """
    yield PublicationFailureScene(**vars(_open(dest)), failure=Step.PUBLISH, outcome=ResultState.FATAL_FAILURE)


@dataclass
class PreparationCleanupFailureScene(TransactionScene):
    prepared_before_failure: int  # preparation fails once this many resources are prepared
    failed_disposals: tuple[str, ...]  # the roles of the prepared resources whose disposal then fails
    outcome: ResultState


@contextmanager
def preparation_cleanup_failure(dest: Path) -> Generator[PreparationCleanupFailureScene]:
    """F-PREPARATION-CLEANUP-FAILURE: preparation fails after two placeholders, and two disposals fail.

    Disposal fails for one object and one bounds mesh, so two leftovers remain, inactive (linked in no
    scene, in no manifest or correspondence) and in the ledger, and the attempt is fatal, reporting both
    failures. The published generation is unchanged: none on a first synchronization, the earlier one on a
    later. Through save and reopen the leftovers and the ledger stay, and no cleanup runs; a retry with the
    failures removed then disposes of both, unless an unmanaged object has been given the leftover bounds
    mesh, which the retry releases intact instead.
    """
    yield PreparationCleanupFailureScene(
        **vars(_open(dest)),
        prepared_before_failure=4,
        failed_disposals=ROLES_PER_PLACEHOLDER,
        outcome=ResultState.FATAL_FAILURE,
    )


@dataclass
class RetirementFailureScene(TransactionScene):
    time_codes: tuple[float, float]  # the two synchronizations', the second replacing the first's display
    failed_retirements: tuple[str, ...]  # the roles of the old generation's resources whose removal fails
    outcome: ResultState


@contextmanager
def retirement_failure(dest: Path) -> Generator[RetirementFailureScene]:
    """F-RETIREMENT-FAILURE: synchronized at 0, then at 10, whose retirement fails for one object and its mesh.

    The second synchronization completes with issues: its generation is published at 10, and the two
    obsolete resources stay, noncanonical, outside the display and correspondence, and in the ledger with
    retryable cleanup diagnostics.
    """
    yield RetirementFailureScene(
        **vars(_open(dest)),
        time_codes=(0.0, 10.0),
        failed_retirements=ROLES_PER_PLACEHOLDER,
        outcome=ResultState.COMPLETED_WITH_ISSUES,
    )


@dataclass
class SourceChangeScene(TransactionScene):
    sub_layer: Path  # the contributing layer the changes are made to

    def edit(self) -> None:
        """Move Sub to SUB_EDITED in sub.usda in memory, as a caller editing it would."""
        layer = Sdf.Layer.Find(str(self.sub_layer))
        layer.GetAttributeAtPath(f"{_SUB}.xformOp:translate").default = SUB_EDITED

    def rewrite_on_disk(self) -> None:
        """Move Sub to SUB_EDITED in sub.usda's file only, for a reload to read.

        The modification time moves forward by 2 s, so a reload that goes by it sees the change.
        """
        mtime_ns = self.sub_layer.stat().st_mtime_ns
        copy = Sdf.Layer.OpenAsAnonymous(str(self.sub_layer))
        copy.GetAttributeAtPath(f"{_SUB}.xformOp:translate").default = SUB_EDITED
        copy.Export(str(self.sub_layer))
        os.utime(self.sub_layer, ns=(mtime_ns + 2_000_000_000, mtime_ns + 2_000_000_000))


@contextmanager
def source_change(dest: Path) -> Generator[SourceChangeScene]:
    """F-SOURCE-CHANGE: sub.usda changes while the binding evaluates, or after a generation, before cache.

    A test calls edit from inside the patched evaluation step: the attempt fails before publication with a
    diagnostic naming sub.usda, and the published generation is unchanged. After a synchronization, edit,
    a reload of rewrite_on_disk's change, or attaching the stage again each make cache cache nothing and
    report that the binding needs synchronizing.
    """
    scene = _open(dest)
    yield SourceChangeScene(**vars(scene), sub_layer=scene.root.parent / "sub.usda")


@dataclass
class CachedTimeCodesScene(TransactionScene):
    synchronized: float  # the generation's own time code
    cached: tuple[float, ...]  # cached in one call: Mover's translation differs at each
    failing: tuple[float, ...]  # a later call, failing at failure: it caches none of them
    failure: Step
    synchronized_again: float  # a new generation, holding only this time code


@contextmanager
def cached_time_codes(dest: Path) -> Generator[CachedTimeCodesScene]:
    """F-CACHED-TIME-CODES: synchronized at 0, then 5, 10, and 20 cached, then a call for 15 that fails.

    Each cached time code's placeholder transforms are translation's at it, with no new generation, no last
    attempt, and no undo step; the failing call leaves the generation's cached time codes 0, 5, 10, and 20
    and its keys as they were. A generation synchronized at the default time code caches nothing and
    succeeds. Synchronizing again at 10 gives a generation holding 10 alone.
    """
    yield CachedTimeCodesScene(
        **vars(_open(dest)),
        synchronized=0.0,
        cached=(5.0, 10.0, 20.0),
        failing=(15.0,),
        failure=Step.PREPARE,
        synchronized_again=10.0,
    )
