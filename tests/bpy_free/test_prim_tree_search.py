"""The prim tree's search and its filter (proscenium.ui.scene_graph_widget.prim_tree.prim_search).

On scenes/scene_graph/prim_kinds.usda, expected matches are written from how the scene is built: six prims
named Lid (the class's, three crates', and the two payloaded props').
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.scene_graph_widget.prim_tree import PrimTree, prim_search
from proscenium.ui.widget_model import text_matching
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from pathlib import Path

LIDS = [
    "/_Crate/Lid",
    "/World/Geometry/Crates/Crate_01/Lid",
    "/World/Geometry/Crates/Crate_02/Lid",
    "/World/Geometry/Crates/Crate_Unique/Lid",
    "/World/Geometry/Prop_Payloaded/Lid",
    "/World/Geometry/Prop_Unloaded/Lid",  # loaded, as the stage opens
]


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    return open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")


def _search(stage: Usd.Stage, match_limit: int = 100, **query: object) -> prim_search.SearchResult:
    return prim_search.search(stage, prim_search.SearchQuery(**query), match_limit)  # ty: ignore[invalid-argument-type]


def _matches(result: prim_search.SearchResult) -> list[str]:
    return sorted(str(path) for path in result.matching_paths)


def test_name_matches_ignore_case_unless_asked(stage: Usd.Stage) -> None:
    assert _matches(_search(stage, text="LID")) == sorted(LIDS)
    assert _matches(_search(stage, text="LID", case_sensitive=True)) == []


def test_glob_path_and_regex_modes(stage: Usd.Stage) -> None:
    assert _matches(_search(stage, text="Crate_0?", mode=text_matching.MatchMode.GLOB)) == [
        "/World/Geometry/Crates/Crate_01",
        "/World/Geometry/Crates/Crate_02",
    ]
    assert _matches(_search(stage, text="looks/red", mode=text_matching.MatchMode.PATH)) == [
        "/World/Looks/Red",
        "/World/Looks/Red/Surface",
    ]
    assert _matches(_search(stage, text=r"^/World/Looks$", mode=text_matching.MatchMode.REGEX)) == ["/World/Looks"]


@pytest.mark.parametrize(
    "text",
    [
        "(",
        "a{9999999999999999999}",  # a repetition count the engine overflows on
        "(" * 1000 + "a" + ")" * 1000,  # nested past the compiler's recursion limit
    ],
    ids=["unclosed group", "overflowing repetition", "deep nesting"],
)
def test_invalid_queries_raise(stage: Usd.Stage, text: str) -> None:
    with pytest.raises(text_matching.InvalidPatternError):
        _search(stage, text=text, mode=text_matching.MatchMode.REGEX)


def test_a_search_stops_at_its_limit(stage: Usd.Stage) -> None:
    result = _search(stage, match_limit=2, text="lid")
    assert len(result.matching_paths) == 2
    assert result.is_truncated
    assert not _search(stage, match_limit=len(LIDS), text="lid").is_truncated


def test_matches_show_in_place_under_their_ancestors(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    tree.set_search(_search(stage, text="lid"))
    paths = [str(row.path) for row in tree.rows]
    assert [p for p in paths if p.endswith("/Lid")] == LIDS
    assert "/World/Looks" not in paths  # holds no match
    assert "/_Crate/Body" not in paths  # a sibling of a match
    crate_rows = [row for row in tree.rows if str(row.path) in ("/_Crate", "/_Crate/Lid")]
    assert [tree.is_match(row) for row in crate_rows] == [False, True]
    # A match can be expanded to explore what's under it, unfiltered.
    lid = tree.row_index(Sdf.Path("/_Crate/Lid"))
    assert lid is not None
    tree.toggle(lid)
    assert str(tree.rows[lid + 1].path) == "/_Crate/Lid/Panel"


def test_clearing_the_search_restores_the_expansion_from_before_it(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    tree.reveal(Sdf.Path("/World/Looks/Red"))
    before = [row.path for row in tree.rows]
    tree.set_search(_search(stage, text="lid"))
    tree.set_search(_search(stage, text="panel"))  # a second search still returns to the first's starting point
    tree.set_search(None)
    assert [row.path for row in tree.rows] == before
