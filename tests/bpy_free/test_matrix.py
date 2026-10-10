"""The requirement-to-test matrix is complete and consistent, and its checker catches drift."""

from __future__ import annotations

import copy
import dataclasses
from typing import TYPE_CHECKING

import pytest

import matrix

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope="module")
def loaded() -> matrix.Matrix:
    return matrix.load()


def _row(m: matrix.Matrix, rid: str) -> matrix.Row:
    return next(r for r in m.rows if r.id == rid)


def test_matrix_passes_its_checks(loaded: matrix.Matrix) -> None:
    assert matrix.check(loaded) == []


def test_rendered_view_is_current(loaded: matrix.Matrix) -> None:
    assert matrix.VIEW.read_text(encoding="utf-8") == matrix.render(loaded), "run tools/matrix.py render"


# Each test below breaks one thing and expects the checker to say so.


def test_drifted_quote_is_reported(loaded: matrix.Matrix) -> None:
    m = copy.deepcopy(loaded)
    _row(m, "FILE-03").quote = "If any contributing layer has unsaved edits, refresh warns"
    assert any(p.startswith("FILE-03: quote not found") for p in matrix.check(m))


def test_untraced_block_is_reported(loaded: matrix.Matrix) -> None:
    m = copy.deepcopy(loaded)
    m.rows = [r for r in m.rows if r.id != "FILE-03"]
    problems = matrix.check(m)
    assert any("not traced" in p and "If any contributing layer has unsaved in-process edits" in p for p in problems)
    assert any("unknown requirement FILE-03" in p for p in problems)  # the invariant citing it


def test_ambiguous_quote_is_reported(loaded: matrix.Matrix) -> None:
    m = copy.deepcopy(loaded)
    _row(m, "FILE-03").quote = "refresh"
    assert any(p.startswith("FILE-03: quote matches") for p in matrix.check(m))


def test_field_problems_are_reported(loaded: matrix.Matrix) -> None:
    m = copy.deepcopy(loaded)
    m.rows.append(dataclasses.replace(_row(m, "FILE-03")))  # duplicate ID
    _row(m, "FILE-02").fixtures = ["F-NOT-REGISTERED"]
    _row(m, "FILE-04").delivery = "M99"
    _row(m, "FILE-05").qualified_by = "M14"  # Phase 1 behavior qualifies in M12
    problems = "\n".join(matrix.check(m))
    for expected in [
        "FILE-03 (spec/source-access.md#file-backed-refresh): duplicate ID",
        "FILE-02 (spec/source-access.md#file-backed-refresh): fixture F-NOT-REGISTERED is not in",
        "FILE-04 (spec/source-access.md#file-backed-refresh): delivery 'M99' is not a milestone",
        "FILE-05 (spec/source-access.md#file-backed-refresh): Phase 1 behavior qualifies in M12",
    ]:
        assert expected in problems


def test_started_milestone_rows_need_oracle_and_fixture(loaded: matrix.Matrix) -> None:
    m = copy.deepcopy(loaded)
    assert not _row(m, "FILE-01").oracle  # M3 fills it in; not required while M3 has not started
    m.started.add("M3")
    problems = matrix.check(m)
    assert "FILE-01 (spec/source-access.md#file-backed-refresh): M3 has started, so the row needs an oracle" in problems
    assert not any(p.startswith("FILE-02 ") and "bespoke fixture" in p for p in problems)  # it has F-DIRTY-LAYER
    assert any("BIND-02" in p and "needs a bespoke fixture" in p for p in problems)  # no fixture assigned yet


def test_invariant_citing_a_row_outside_its_links_is_reported(loaded: matrix.Matrix) -> None:
    rows = {r.id: r for r in copy.deepcopy(loaded).rows}
    rows["FILE-03"].section = "spec/pipeline.md#diagnostics"  # the File-Backed Refresh invariant cites FILE-03
    assert any("FILE-03 is in spec/pipeline.md#diagnostics" in p for p in matrix.check_invariants(rows))


def test_milestones_include_the_gate() -> None:
    assert {"M1", "M1b", "M2", "M14"} <= matrix.milestones()


# The Markdown parser and loader, on small docs and matrices written under tmp_path.


@pytest.fixture
def docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """matrix.DOCS pointed at an empty tmp dir, with the anchors cache cleared around the test."""
    monkeypatch.setattr(matrix, "DOCS", tmp_path)
    matrix.anchors.cache_clear()
    yield tmp_path
    matrix.anchors.cache_clear()


def test_repeated_headings_get_github_suffixes(docs: Path) -> None:
    (docs / "a.md").write_text("# T\n\n## Notes\n\n- one\n\n## Notes\n\n- two\n\n```\n## Notes\n```\n")
    assert matrix.anchors("a.md") == {"t", "notes", "notes-1"}
    sections = {b.text: b.sections for b in matrix.blocks("a.md")}
    assert sections["one"] == ["t", "notes"]
    assert sections["two"] == ["t", "notes-1"]


def test_wrapped_list_item_is_one_block(docs: Path) -> None:
    (docs / "a.md").write_text(
        "# T\n\n- first line\n  wrapped on\n  and again\n- second\n\nparagraph\n  indented after\n"
    )
    assert [(b.text, b.line) for b in matrix.blocks("a.md")] == [
        ("first line wrapped on and again", 3),
        ("second", 6),
        ("paragraph indented after", 8),
    ]


def test_indented_line_after_a_blank_line_is_not_a_continuation(docs: Path) -> None:
    (docs / "a.md").write_text("# T\n\n- item\n\n  separate paragraph\n")
    assert [b.text for b in matrix.blocks("a.md")] == ["item", "separate paragraph"]


def test_resolve_links(docs: Path) -> None:
    (docs / "spec").mkdir()
    assert matrix._resolve("spec/invariants.md", "pipeline.md#diagnostics") == "spec/pipeline.md#diagnostics"  # noqa: SLF001
    assert matrix._resolve("spec/invariants.md", "../PROJECT.md#goals") == "PROJECT.md#goals"  # noqa: SLF001
    assert matrix._resolve("spec/invariants.md", "#local") == "spec/invariants.md#local"  # noqa: SLF001


@pytest.mark.parametrize("target", ["https://example.com/x#y", "mailto:a@b.c", "../../src/x.py", "../../README.md#r"])
def test_resolve_ignores_external_and_outside_links(docs: Path, target: str) -> None:
    (docs / "spec").mkdir()
    assert matrix._resolve("spec/invariants.md", target) is None  # noqa: SLF001


def test_load_reports_malformed_groups_instead_of_crashing(tmp_path: Path) -> None:
    path = tmp_path / "requirements.yaml"
    path.write_text(
        "requirements:\n"
        "  - section: PROJECT.md#goals\n"  # no rows
        "  - rows: []\n"  # no section
        "  - section: PROJECT.md#goals\n"
        "    rows:\n"
        "      - {id: PH1-01, quote: x}\n"  # no delivery or phase
    )
    m = matrix.load(path)
    assert sum("needs `section` and `rows`" in p for p in m.problems) == 2
    assert [(r.id, r.delivery) for r in m.rows] == [("PH1-01", "")]
    empty = tmp_path / "empty.yaml"
    empty.write_text("started: []\n")  # no requirements key
    assert not matrix.load(empty).rows
