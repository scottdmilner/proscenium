"""A prim's property list, its view, and what it says about properties (proscenium.ui.property_viewer_widget).

On scenes/property_viewer/property_kinds.usda; expected values are written from how the scene is built.
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.property_viewer_widget.property_list import (
    PropertyListView,
    PropertyRow,
    ValueSource,
    property_descriptions,
    property_search,
)
from proscenium.ui.widget_model import text_matching
from proscenium.ui.widget_model.list_steps import StepDirection
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from proscenium.ui.property_viewer_widget.property_list import PropertyDetails, PropertyList

BALL = Sdf.Path("/World/Ball")
VALUES = Sdf.Path("/World/Values")
ANIMATION = Sdf.Path("/World/Animation")
LINKS = Sdf.Path("/World/Links")
RED = Sdf.Path("/World/Looks/Red")
INCLUDES = "collection:lights:includes"
# Ball's properties, in the prim's order: its Sphere schema's, its applied schemas', and the authored ones.
BALL_PROPERTY_COUNT = 25
INTO = StepDirection.INTO
OUT_OF = StepDirection.OUT_OF


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    return open_stage_without_cache(copy_scene(Scene.PROPERTY_VIEWER, tmp_path) / "property_kinds.usda")


def _view(stage: Usd.Stage, path: Sdf.Path = BALL, changes: list[None] | None = None) -> PropertyListView:
    """A view of a prim's every property, unauthored ones too."""
    view = PropertyListView(None if changes is None else lambda: changes.append(None))
    view.set_stage(stage)
    view.set_query(property_search.SearchQuery(authored_only=False))
    view.show_prim(path)
    return view


def _list(view: PropertyListView) -> PropertyList:
    property_list = view.live_list()
    assert property_list is not None
    return property_list


def _details(view: PropertyListView, name: str) -> PropertyDetails:
    details = _list(view).details(name)
    assert details is not None
    return details


def _names(view: PropertyListView) -> list[str]:
    return [property_descriptions.row_name(row) for row in _list(view).rows]


def _row_index(view: PropertyListView, name: str, target: str | None = None) -> int:
    row_index = _list(view).row_index(PropertyRow(name, Sdf.Path(target) if target else None))
    assert row_index is not None
    return row_index


def test_every_property_shows_its_schemas_unauthored_ones_too(stage: Usd.Stage) -> None:
    view = _view(stage)
    names = _names(view)
    assert len(names) == BALL_PROPERTY_COUNT == _list(view).property_count
    assert names[:2] == ["collection:lights", "collection:lights:excludes"]  # the prim's property order
    assert {"radius", "doubleSided", "material:binding", "xformOp:translate"} <= set(names)
    assert not _details(view, "doubleSided").is_authored  # the Sphere schema's, with its fallback
    assert _details(view, "radius").is_authored


def test_a_new_view_shows_only_authored_properties(stage: Usd.Stage) -> None:
    view = PropertyListView()
    view.set_stage(stage)
    view.show_prim(BALL)
    property_list = _list(view)
    assert property_list.shown_property_count == 15  # of 25
    assert all(_details(view, name).is_authored for name in _names(view))


def test_a_prim_with_no_properties_shows_none_and_a_missing_prim_shows_no_list(stage: Usd.Stage) -> None:
    view = _view(stage, Sdf.Path("/World/Empty"))
    assert _list(view).rows == []
    view.show_prim(Sdf.Path("/World/Nowhere"))
    assert view.live_list() is None
    view.show_prim(None)
    assert view.live_list() is None


def test_values_and_where_they_come_from(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.set_time_code(Usd.TimeCode(2))
    expected = {
        "radius": ("2.0", ValueSource.DEFAULT),
        "doubleSided": ("false", ValueSource.FALLBACK),
        "notes": ('"hello"', ValueSource.DEFAULT),
        "texture": ("@textures/ball.png@", ValueSource.DEFAULT),
        "counts": ("[12] 0, 1, 2, 3, 4, 5, 6, 7, …", ValueSource.DEFAULT),
        "frame": (
            "((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))",
            ValueSource.DEFAULT,
        ),
        "primvars:displayColor": ("[1] (1.0, 0.0, 0.0)", ValueSource.DEFAULT),
        "xformOp:translate": ("(0.0, 0.0, 1.0)", ValueSource.TIME_SAMPLES),  # the sample at time code 2
        "pulse": ("2.0", ValueSource.TIME_SAMPLES),  # its samples, not its default, at a numeric time code
        "xformOpOrder": ("[1] xformOp:translate", ValueSource.DEFAULT),
        "purpose": ("None (blocked)", ValueSource.FALLBACK),
        "material:binding": ("/World/Looks/Red", ValueSource.NONE),
        INCLUDES: ("[2] /World/Sun, /World/Ball", ValueSource.NONE),
        "proxyPrim": ("No targets", ValueSource.NONE),
    }
    for name, (value, source) in expected.items():
        details = _details(view, name)
        assert (property_descriptions.row_value_text(details), details.value_source) == (value, source), name
    assert _details(view, "purpose").is_blocked
    view.set_time_code(Usd.TimeCode(3))
    assert property_descriptions.row_value_text(_details(view, "xformOp:translate")) == "(0.0, 0.0, 2.0)"


def test_a_schema_fallback_and_an_authored_default_are_told_apart(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.set_time_code(Usd.TimeCode(2))
    fallback, default = _details(view, "doubleSided"), _details(view, "radius")
    assert (fallback.value_source, fallback.is_authored) == (ValueSource.FALLBACK, False)
    assert (default.value_source, default.is_authored) == (ValueSource.DEFAULT, True)
    assert "Schema fallback" in property_descriptions.row_tooltip(fallback, PropertyRow("doubleSided")).splitlines()
    assert "Authored default value" in property_descriptions.row_tooltip(default, PropertyRow("radius")).splitlines()
    assert ValueSource.FALLBACK.value != ValueSource.DEFAULT.value


def test_value_text_writes_values_as_a_layer_does() -> None:
    # A float keeps its decimal point even when whole; an integer has none, and an exponent marks a float itself.
    assert [property_descriptions.value_text(value, "double") for value in (1.0, -2.0, 0.0, 1e6, 1.5)] == [
        "1.0",
        "-2.0",
        "0.0",
        "1e+06",
        "1.5",
    ]
    assert property_descriptions.value_text(1, "int") == "1"
    assert property_descriptions.value_text(Gf.Vec3f(0.5, 1e-7, 3), "float3") == "(0.5, 1e-07, 3.0)"
    assert property_descriptions.value_text(["a", "b"], "string[]") == '[2] "a", "b"'
    assert property_descriptions.value_text(None, "float") == "None"


def test_connections_are_an_attributes_targets(stage: Usd.Stage) -> None:
    view = _view(stage, RED)
    details = _details(view, "outputs:surface")
    assert details.target_paths == (Sdf.Path("/World/Looks/Red/Surface.outputs:surface"),)
    assert property_descriptions.row_value_text(details) == "→ /World/Looks/Red/Surface.outputs:surface"
    assert not details.missing_target_paths


def test_declarations_as_a_layer_writes_them(stage: Usd.Stage) -> None:
    view = _view(stage)
    expected = {
        "radius": "double",
        "purpose": "uniform token",
        "counts": "custom int[]",
        "material:binding": "rel",
        "missing": "custom rel",
    }
    assert {name: property_descriptions.declaration_text(_details(view, name)) for name in expected} == expected


@pytest.mark.parametrize(
    ("name", "time_code", "mark"),
    [
        # Its samples are at 1 and 3: a key at 1, between keys at 2, and at the default time code, no value at all.
        ("sampled", 1, property_descriptions.AnimationMark.KEY),
        ("sampled", 2, property_descriptions.AnimationMark.BETWEEN_KEYS),
        ("sampled", None, None),
        ("held", 1, property_descriptions.AnimationMark.KEY),  # one sample is still a key
        ("held", 2, property_descriptions.AnimationMark.BETWEEN_KEYS),  # held after it
        ("curve", 1, property_descriptions.AnimationMark.KEY),  # a spline's knot
        ("curve", 2, property_descriptions.AnimationMark.BETWEEN_KEYS),
        ("clipped", 3, property_descriptions.AnimationMark.KEY),  # a value clip's sample
        ("clipped", 2, property_descriptions.AnimationMark.BETWEEN_KEYS),
        ("still", 1, None),  # a default value isn't animated
    ],
)
def test_the_keyframe_icon_marks_a_key_at_the_time_code_or_between_keys(
    stage: Usd.Stage, name: str, time_code: float | None, mark: property_descriptions.AnimationMark | None
) -> None:
    view = _view(stage, ANIMATION)
    view.set_time_code(Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code))
    details = _details(view, name)
    assert property_descriptions.animation_mark(details) is mark


def test_the_source_line_says_whether_a_key_is_here(stage: Usd.Stage) -> None:
    view = _view(stage, ANIMATION)
    view.set_time_code(Usd.TimeCode(1))
    sampled = _details(view, "sampled")
    assert (
        "From 2 time samples; a key at this time code"
        in property_descriptions.row_tooltip(sampled, PropertyRow("sampled")).splitlines()
    )
    view.set_time_code(Usd.TimeCode(2))
    curve = _details(view, "curve")
    assert (
        "From spline; between keys at this time code"
        in property_descriptions.row_tooltip(curve, PropertyRow("curve")).splitlines()
    )


def test_expanding_a_relationship_shows_its_targets_under_it(stage: Usd.Stage) -> None:
    view = _view(stage)
    property_list = _list(view)
    includes_index = _row_index(view, INCLUDES)
    property_list.toggle(includes_index)
    assert _names(view)[includes_index : includes_index + 3] == [INCLUDES, "/World/Sun", "/World/Ball"]
    assert property_list.rows[includes_index + 1].depth == 1
    assert property_list.property_row_index(includes_index + 2) == includes_index
    assert property_list.shown_property_count == BALL_PROPERTY_COUNT
    property_list.toggle(includes_index + 1)  # a target's row toggles its property
    assert len(property_list.rows) == BALL_PROPERTY_COUNT


def test_a_target_the_stage_has_nothing_at_is_missing(stage: Usd.Stage) -> None:
    view = _view(stage)
    _list(view).set_expanded("missing", expand=True)
    details = _details(view, "missing")
    target_row = PropertyRow("missing", Sdf.Path("/World/Nowhere"))
    assert property_descriptions.is_target_missing(details, target_row)
    assert not property_descriptions.is_target_missing(details, PropertyRow("missing"))
    assert property_descriptions.row_tooltip(details, target_row).endswith("Nothing on the stage at this path")
    assert not _details(view, INCLUDES).missing_target_paths


def test_selection_and_expansion_carry_over_to_the_next_prim_by_name(stage: Usd.Stage) -> None:
    view = _view(stage)
    _list(view).set_expanded("material:binding", expand=True)
    view.select_row(_row_index(view, "material:binding", "/World/Looks/Red"))
    assert view.selected_path == BALL.AppendProperty("material:binding")  # a target's row selects its property
    stage.GetPrimAtPath("/World/Sun").CreateRelationship("material:binding").AddTarget("/World/Looks/Red")
    view.apply_pending_changes()
    view.show_prim(Sdf.Path("/World/Sun"))
    assert view.selected_path == Sdf.Path("/World/Sun.material:binding")
    assert "/World/Looks/Red" in _names(view)  # still expanded, and its same target still selected
    assert view.selected_row == PropertyRow("material:binding", Sdf.Path("/World/Looks/Red"))
    view.show_prim(RED)  # no property of that name
    assert view.selected_path is None


def test_collapsing_a_selected_targets_property_selects_the_property(stage: Usd.Stage) -> None:
    view = _view(stage)
    _list(view).set_expanded(INCLUDES, expand=True)
    view.select_row(_row_index(view, INCLUDES, "/World/Sun"))
    view.toggle_row(_row_index(view, INCLUDES))
    assert view.selected_row == PropertyRow(INCLUDES)
    assert view.active_row_index() == _row_index(view, INCLUDES)


def test_right_shows_targets_then_steps_into_them_and_left_steps_back_out(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_property(INCLUDES)
    view.step(INTO, every_property=False)  # shows its targets, and stays on it
    assert view.selected_row == PropertyRow(INCLUDES)
    assert "/World/Sun" in _names(view)
    view.step(INTO, every_property=False)  # steps into its first target
    assert view.selected_row == PropertyRow(INCLUDES, Sdf.Path("/World/Sun"))
    view.step(INTO, every_property=False)  # a target's row has nothing to step into
    assert view.selected_row == PropertyRow(INCLUDES, Sdf.Path("/World/Sun"))
    view.step(OUT_OF, every_property=False)  # out of the target, to its property
    assert view.selected_row == PropertyRow(INCLUDES)
    view.step(OUT_OF, every_property=False)  # hides its targets
    assert "/World/Sun" not in _names(view)
    view.select_property("radius")
    view.step(INTO, every_property=False)  # a property with no targets stays as it is
    assert view.selected_row == PropertyRow("radius")
    assert len(_names(view)) == BALL_PROPERTY_COUNT


def test_shift_shows_or_hides_every_propertys_targets(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_property("radius")
    view.step(INTO, every_property=True)
    targets = {"/World/Looks", "/World/Sun", "/World/Ball", "/World/Looks/Red", "/World/Nowhere"}
    assert targets <= set(_names(view))
    assert view.selected_row == PropertyRow("radius")
    view.select_row(_row_index(view, INCLUDES, "/World/Sun"))
    view.step(OUT_OF, every_property=True)  # the selected target's row is hidden: its property is selected
    assert len(_names(view)) == BALL_PROPERTY_COUNT
    assert view.selected_row == PropertyRow(INCLUDES)
    view.toggle_row(_row_index(view, "missing"), every_property=True)  # Shift-click on a chevron does the same
    assert targets <= set(_names(view))


def test_select_property_by_name(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_property("radius")
    assert view.selected_path == BALL.AppendProperty("radius")
    view.select_property("nothing")
    assert view.selected_path is None


@pytest.mark.parametrize(
    ("query", "expected_names"),
    [
        (property_search.SearchQuery("XFORM"), ["xformOp:translate", "xformOpOrder"]),
        (property_search.SearchQuery("double", authored_only=False), ["doubleSided"]),
        (property_search.SearchQuery("XFORM", case_sensitive=True), []),
        (property_search.SearchQuery("collection:*:includes", text_matching.MatchMode.GLOB), [INCLUDES]),
        (property_search.SearchQuery(r"Ball\.rad", text_matching.MatchMode.REGEX), ["radius"]),
        (property_search.SearchQuery("primvars", authored_only=True), ["primvars:displayColor"]),
    ],
)
def test_search_filters_the_properties(
    stage: Usd.Stage, query: property_search.SearchQuery, expected_names: list[str]
) -> None:
    view = _view(stage)
    view.set_query(query)
    assert _names(view) == expected_names
    assert _list(view).property_count == BALL_PROPERTY_COUNT


def test_authored_only_leaves_out_the_schemas_fallbacks(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.set_query(property_search.SearchQuery(authored_only=True))
    assert all(_details(view, name).is_authored for name in _names(view))
    assert "doubleSided" not in _names(view)
    shown_count = _list(view).shown_property_count
    assert property_descriptions.status_text(shown_count, BALL_PROPERTY_COUNT) == (
        f"{shown_count} of {BALL_PROPERTY_COUNT} properties"
    )
    assert property_descriptions.status_text(1, 1) == "1 property"


def test_an_invalid_pattern_shows_every_property_and_says_why(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.set_query(property_search.SearchQuery("[", text_matching.MatchMode.REGEX))
    assert view.search_error.startswith("Search: ")
    assert len(_names(view)) == BALL_PROPERTY_COUNT


def test_stage_changes_mark_the_view_once_and_are_read_after(stage: Usd.Stage) -> None:
    changes: list[None] = []
    view = _view(stage, changes=changes)
    ball = stage.GetPrimAtPath(BALL)
    ball.GetAttribute("radius").Set(3.0)  # a value: an info-only change of a shown property
    ball.CreateAttribute("added", Sdf.ValueTypeNames.Float)  # a resync
    assert changes == [None]
    assert view.apply_pending_changes()
    assert "added" in _names(view)
    assert property_descriptions.row_value_text(_details(view, "radius")) == "3.0"
    stage.GetPrimAtPath("/World/Sun").SetMetadata("comment", "elsewhere")  # another prim's field
    assert not view.has_pending_change


def test_adding_a_target_shows_it_under_its_expanded_relationship(stage: Usd.Stage) -> None:
    view = _view(stage)
    _list(view).set_expanded("material:binding", expand=True)
    stage.GetPrimAtPath(BALL).GetRelationship("material:binding").AddTarget("/World/Looks")
    view.apply_pending_changes()
    assert "/World/Looks" in _names(view)


def test_removing_the_prim_drops_the_list_and_its_selection(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_property("radius")
    stage.RemovePrim(BALL)
    view.apply_pending_changes()
    assert view.live_list() is None
    assert view.selected_path is None
    assert view.prim_path == BALL  # shown again if a prim comes back there


def test_the_view_holds_no_stage(tmp_path: Path) -> None:
    stage = open_stage_without_cache(copy_scene(Scene.PROPERTY_VIEWER, tmp_path) / "property_kinds.usda")
    view = _view(stage)
    view.select_property("radius")
    del stage
    gc.collect()
    assert view.is_stage_expired()
    assert view.selected_path is None
    assert view.apply_pending_changes()  # drops the list, as a change
    assert view.property_list is None


def test_tooltips_and_metadata(stage: Usd.Stage) -> None:
    view = _view(stage)
    translate = _details(view, "xformOp:translate")
    tooltip = property_descriptions.row_tooltip(translate, PropertyRow("xformOp:translate"))
    assert tooltip.splitlines()[:2] == ["/World/Ball.xformOp:translate", "double3"]
    assert "No value" in tooltip.splitlines()  # time samples alone give the default time code, a view's first, none
    metadata = _list(view).metadata("xformOp:translate")
    assert metadata is not None
    assert (metadata.first_time_sample, metadata.last_time_sample) == (1.0, 3.0)
    lines = property_descriptions.metadata_lines(translate, metadata, PropertyRow("xformOp:translate"))
    assert "Time samples: 3, from 1.0 to 3.0" in lines
    assert len(metadata.opinion_layer_identifiers) == 1
    color = _details(view, "primvars:displayColor")
    assert color.interpolation == "constant"
    unauthored = property_descriptions.row_tooltip(_details(view, "doubleSided"), PropertyRow("doubleSided"))
    assert "Unauthored: no layer has an opinion on it" in unauthored
    expanded = property_descriptions.disclosure_tooltip(_details(view, INCLUDES), is_expanded=True)
    assert expanded.startswith(f"Hide the targets of {INCLUDES}. Shift-click: every property's.\nKeys: Right")


def test_a_targets_name_is_its_prims_or_its_prim_and_propertys() -> None:
    prim_target = PropertyRow("material:binding", Sdf.Path("/World/Looks/Red"))
    property_target = PropertyRow("outputs:surface", Sdf.Path("/World/Looks/Red/Surface.outputs:surface"))
    assert property_descriptions.row_name(prim_target) == "/World/Looks/Red"
    assert property_descriptions.row_name(prim_target, shows_target_path=False) == "Red"
    assert property_descriptions.row_name(property_target, shows_target_path=False) == "Surface.outputs:surface"
    assert property_descriptions.row_name(PropertyRow("radius"), shows_target_path=False) == "radius"


@pytest.mark.parametrize(
    ("name", "value", "declaration"),
    [
        ("assets", "[2] @textures/a.png@, @textures/b.png@", "custom asset[]"),
        ("big", "9007199254740993", "custom int64"),  # past a double's exact integers, written whole
        ("category", "prop", "custom uniform token"),
        ("empty", "[0]", "custom int[]"),
        ("enabled", "true", "custom bool"),
        ("infinite", "inf", "custom float"),
        ("mode", "fast", "custom token"),
        ("notANumber", "nan", "custom float"),
        ("offset", "(0.5, -0.25)", "custom float2"),
        ("orientation", "(1.0, 0.0, 0.0, 0.0)", "custom quatf"),  # the real part first
        ("primvars:st", "[4] (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)", "texCoord2f[]"),
        ("ratio", "0.333333", "custom float"),  # six significant digits
        ("small", "0.5", "custom half"),
        ("start", "12", "custom timecode"),
        ("tags", '[2] "red", "round"', "custom string[]"),
    ],
)
def test_each_value_type_is_written_as_a_layer_writes_it(
    stage: Usd.Stage, name: str, value: str, declaration: str
) -> None:
    details = _details(_view(stage, VALUES), name)
    assert (property_descriptions.row_value_text(details), property_descriptions.declaration_text(details)) == (
        value,
        declaration,
    )


def test_primvars_interpolation_and_element_size(stage: Usd.Stage) -> None:
    view = _view(stage, VALUES)
    weights_metadata = _list(view).metadata("primvars:weights")
    assert weights_metadata is not None
    assert (_details(view, "primvars:weights").interpolation, weights_metadata.element_size) == ("vertex", 2)
    assert _details(view, "primvars:st").interpolation == "faceVarying"
    assert _details(view, "primvars:st:indices").interpolation == ""  # a primvar's indices aren't a primvar
    lines = property_descriptions.metadata_lines(
        _details(view, "primvars:weights"), weights_metadata, PropertyRow("primvars:weights")
    )
    assert "Interpolation: vertex, element size 2" in lines


def test_documentation_display_group_and_opinions_in_two_layers(stage: Usd.Stage) -> None:
    view = _view(stage, VALUES)
    metadata = _list(view).metadata("documented")
    assert metadata is not None
    assert metadata.display_group == "Showcase"
    assert metadata.documentation.startswith("A value with documentation")
    assert [Path(identifier).name for identifier in metadata.opinion_layer_identifiers] == [
        "property_kinds.usda",  # the strongest, whose value shows
        "property_kinds_weaker.usda",
    ]
    assert property_descriptions.row_value_text(_details(view, "documented")) == "1.0"


@pytest.mark.parametrize(
    ("name", "value", "source", "is_time_varying"),
    [
        ("sampled", "1.0", ValueSource.TIME_SAMPLES, True),  # halfway from 0 at 1 to 2 at 3
        ("held", "5.0", ValueSource.TIME_SAMPLES, False),  # one sample, one value for all time
        ("defaultAndSampled", "2.0", ValueSource.TIME_SAMPLES, True),  # its samples outrank its default
        ("curve", "5.0", ValueSource.SPLINE, True),  # linear from 0 at 1 to 10 at 3
        ("clipped", "20.0", ValueSource.VALUE_CLIPS, True),  # the clip's samples, 10 at 1 and 30 at 3
        ("still", "4.0", ValueSource.DEFAULT, False),
        ("blocked", "None (blocked)", ValueSource.NONE, False),
    ],
)
def test_each_value_source_at_a_time_code(
    stage: Usd.Stage, name: str, value: str, source: ValueSource, is_time_varying: bool
) -> None:
    view = _view(stage, ANIMATION)
    view.set_time_code(Usd.TimeCode(2))
    details = _details(view, name)
    assert (property_descriptions.row_value_text(details), details.value_source) == (value, source)
    assert details.is_time_varying is is_time_varying
    assert details.is_animated is (source in (ValueSource.TIME_SAMPLES, ValueSource.SPLINE, ValueSource.VALUE_CLIPS))


def test_value_clips_count_the_clip_layers_opinion(stage: Usd.Stage) -> None:
    view = _view(stage, ANIMATION)
    view.set_time_code(Usd.TimeCode(2))
    metadata = _list(view).metadata("clipped")
    assert metadata is not None
    assert [Path(identifier).name for identifier in metadata.opinion_layer_identifiers] == [
        "property_kinds.usda",
        "property_kinds_clip.usda",
    ]


@pytest.mark.parametrize(
    ("name", "value", "target_paths", "missing_paths"),
    [
        ("none", "No targets", [], []),
        (
            "many",
            "[3] /World/Ball, /World/Sun, /World/Nowhere",
            ["/World/Ball", "/World/Sun", "/World/Nowhere"],
            ["/World/Nowhere"],
        ),
        ("toProperty", "/World/Ball.radius", ["/World/Ball.radius"], []),
        ("driven", "→ /World/Ball.radius", ["/World/Ball.radius"], []),
        ("drivenWithValue", "3.0", ["/World/Ball.radius"], []),  # its value shows, its connection under it
        ("broken", "→ /World/Ball.nothing", ["/World/Ball.nothing"], ["/World/Ball.nothing"]),
    ],
)
def test_each_kind_of_target(
    stage: Usd.Stage, name: str, value: str, target_paths: list[str], missing_paths: list[str]
) -> None:
    details = _details(_view(stage, LINKS), name)
    assert property_descriptions.row_value_text(details) == value
    assert [str(path) for path in details.target_paths] == target_paths
    assert sorted(str(path) for path in details.missing_target_paths) == missing_paths
    assert details.is_authored


def test_a_property_target_is_named_by_its_prim_and_property(stage: Usd.Stage) -> None:
    view = _view(stage, LINKS)
    _list(view).set_expanded("toProperty", expand=True)
    target_row = PropertyRow("toProperty", Sdf.Path("/World/Ball.radius"))
    assert _list(view).row_index(target_row) is not None
    assert property_descriptions.row_name(target_row, shows_target_path=False) == "Ball.radius"
