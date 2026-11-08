"""Planning is deterministic, and reads only its three inputs (M6 plan, C10).

Equal snapshots, settings, and contexts give plans equal in every part and its order, whether built twice from one
snapshot, from two captures at one time code, or in separate processes (PLAN-08); a plan built after its stage and
chain are released equals one built while they were alive (PLAN-09); and a plan in a separate process gives each
resource the same identity (ROLE-02). Relations 4 and 5, which PLAN-08's oracle also names, are Phase E's.
"""

from __future__ import annotations

import gc
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pxr import Usd

from fixtures import appearance, evaluation, transaction
from proscenium.core import _core
from support.usd import open_fresh

from .plan_checks import CONTEXT, SETTINGS
from .plan_process import contents

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager

SCRIPT = Path(__file__).with_name("plan_process.py")
TIME_CODES = [0.0, 15.0]  # F-TRANSFORMS' first sample, and between its samples


@pytest.fixture
def transforms(tmp_path: Path) -> Iterator[evaluation.TransformsScene]:
    with evaluation.transforms(tmp_path) as scene:
        yield scene


def _capture(stage: Usd.Stage, time: float) -> _core.Snapshot:
    chain = _core.SceneIndexChain(stage)
    try:
        return chain.capture(Usd.TimeCode(time))
    finally:
        chain.release()


def _elsewhere(root: Path, time: float) -> dict[str, Any]:
    """The plan of `root` at `time`, built in a fresh process."""
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), str(time)], check=True, capture_output=True, text=True
    )
    return json.loads(done.stdout)


@pytest.mark.parametrize("time", TIME_CODES)
def test_equal_inputs_give_equal_plans(transforms: evaluation.TransformsScene, time: float) -> None:
    # PLAN-08 on F-TRANSFORMS: one snapshot planned twice, and two captures at one time code, by separate chains.
    snapshot = _capture(transforms.stage, time)
    first = contents(_core.plan(snapshot, SETTINGS, CONTEXT))
    assert contents(_core.plan(snapshot, SETTINGS, CONTEXT)) == first
    assert contents(_core.plan(_capture(transforms.stage, time), SETTINGS, CONTEXT)) == first


@pytest.mark.parametrize(
    ("generator", "time"),
    [(evaluation.transforms, 0.0), (evaluation.transforms, 15.0), (appearance.nested_stress, 0.0)],
    ids=["transforms-0", "transforms-15", "nested-stress"],
)
def test_a_separate_process_plans_the_same(
    generator: Callable[[Path], AbstractContextManager[Any]], time: float, tmp_path: Path
) -> None:
    # PLAN-08 across processes, on F-TRANSFORMS and on F-NESTED-STRESS' nested instances, whose copies the capture
    # copies and the reader reads in parallel.
    with generator(tmp_path) as scene:
        here = contents(_core.plan(_capture(open_fresh(scene.root), time), SETTINGS, CONTEXT))
        assert _elsewhere(scene.root, time) == here


def test_a_plan_reads_nothing_but_its_inputs(transforms: evaluation.TransformsScene) -> None:
    # PLAN-09: the same plan from a snapshot whose stage and chain are gone.
    stage = open_fresh(transforms.root)
    chain = _core.SceneIndexChain(stage)
    snapshot = chain.capture(Usd.TimeCode(0.0))
    alive = contents(_core.plan(snapshot, SETTINGS, CONTEXT))
    chain.release()
    del chain, stage
    gc.collect()
    assert contents(_core.plan(snapshot, SETTINGS, CONTEXT)) == alive


def test_identities_are_the_same_in_a_separate_process(tmp_path: Path) -> None:
    # ROLE-02 on F-RETIREMENT-FAILURE: each resource's identity, its role, source entity, and place, as another
    # process derives it.
    with transaction.retirement_failure(tmp_path) as scene:
        for time in scene.time_codes:
            here = contents(_core.plan(_capture(open_fresh(scene.root), time), SETTINGS, CONTEXT))
            identities = [resource[:3] for resource in here["resources"]]
            assert [r[:3] for r in _elsewhere(scene.root, time)["resources"]] == identities
