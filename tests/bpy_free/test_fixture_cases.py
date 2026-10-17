"""Fixture cases declare what acceptance.md#bespoke-fixtures requires, and agree with the matrix."""

from __future__ import annotations

import pytest

import matrix
from fixtures.registry import FIXTURES, Case

MATRIX = matrix.load()
ROWS = {row.id: row for row in MATRIX.rows}
CASES = [(fixture.id, case) for fixture in FIXTURES.values() for case in fixture.cases]


def _case_id(item: tuple[str, Case]) -> str:
    return f"{item[0]}:{item[1].name}"


@pytest.mark.parametrize("fixture_id", [f.id for f in FIXTURES.values() if f.cases])
def test_case_names_are_unique(fixture_id: str) -> None:
    names = [case.name for case in FIXTURES[fixture_id].cases]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("item", CASES, ids=_case_id)
def test_case_cites_behavior_rows_of_its_fixture(item: tuple[str, Case]) -> None:
    fixture_id, case = item
    assert case.requirements, "a case cites the rows it checks"
    for rid in case.requirements:
        row = ROWS.get(rid)
        assert row is not None, f"{rid} is not a matrix row"
        assert row.kind == "behavior", f"{rid} is a {row.kind} row"
        assert fixture_id in row.fixtures, f"{rid} does not list {fixture_id}"


@pytest.mark.parametrize("item", CASES, ids=_case_id)
def test_case_phase_is_its_rows_highest(item: tuple[str, Case]) -> None:
    _, case = item
    assert case.phase == max(ROWS[rid].phase for rid in case.requirements)


@pytest.mark.parametrize("fixture_id", [f.id for f in FIXTURES.values() if f.cases])
def test_cases_cover_started_rows(fixture_id: str) -> None:
    # Once a row's milestone has started, each fixture it lists has a case that checks it.
    cited = {rid for case in FIXTURES[fixture_id].cases for rid in case.requirements}
    due = {
        row.id
        for row in MATRIX.rows
        if row.kind == "behavior" and fixture_id in row.fixtures and row.delivery in MATRIX.started
    }
    assert due <= cited, f"uncovered: {sorted(due - cited)}"
