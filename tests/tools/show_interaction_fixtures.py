"""Print what the interaction fixtures contain, as the oracle sees them.

    uv run python tests/tools/show_interaction_fixtures.py                     # all three
    uv run python tests/tools/show_interaction_fixtures.py F-NESTED-SELECTION  # one or more by ID

For each fixture and each time code it publishes generations at, lists every composed
prim (instance proxies included) with what support/interaction_oracle.py derives:
whether it is in the browsing universe, whether it is a display element and its floor,
and the reason the fixture gives for excluding it. Then the fixture's hand-written kind
targets. Each fixture is built in a temporary directory, as in the tests.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

TESTS = Path(__file__).resolve().parents[1]
FIXTURE_IDS = ("F-KIND-HIERARCHY", "F-NESTED-SELECTION", "F-UNIVERSE-MEMBERSHIP")

if TYPE_CHECKING:
    from fixtures.interaction import InteractionScene


def describe(scene: InteractionScene) -> list[str]:
    from support import interaction_oracle as oracle

    lines = []
    for time in scene.times:
        gen = oracle.generation(scene.stage, time)
        lines.append(f"  time {time:g}")
        for path in oracle.all_paths(scene.stage):
            tags = ["universe"] if path in gen.universe else []
            if path in gen.elements:
                floor = gen.floors[path]
                tags.append("element" if floor == path else f"element, floor {floor}")
            lines.append(f"    {path:42} {'; '.join(tags) or '-':32} {scene.excluded.get(path, '')}".rstrip())
    lines.append("  kind targets:")
    for (entity, level), target in scene.kind_targets.items():
        lines.append(f"    {entity} at {level or 'prim'} level -> {target}")
    return lines


def main() -> int:
    # Run as a script, so tests/ is not on sys.path for the fixtures and support packages.
    sys.path.insert(0, str(TESTS))
    from fixtures.registry import FIXTURES

    chosen = sys.argv[1:] or list(FIXTURE_IDS)
    if unknown := [f for f in chosen if f not in FIXTURE_IDS]:
        raise SystemExit(f"not an interaction fixture: {', '.join(unknown)} (choose from {', '.join(FIXTURE_IDS)})")
    for fixture_id in chosen:
        build = FIXTURES[fixture_id].build
        assert build is not None
        with tempfile.TemporaryDirectory() as tmp, build(Path(tmp)) as scene:
            print(f"== {fixture_id}: {FIXTURES[fixture_id].title}")
            print("\n".join(describe(scene)))  # ty: ignore[invalid-argument-type]
    return 0


if __name__ == "__main__":
    sys.exit(main())
