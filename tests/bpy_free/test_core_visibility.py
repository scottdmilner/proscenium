"""Each destination's participation from effective visibility and purpose, through the plan (M6 plan, C2).

A copy displays in a destination exactly when it is effectively visible and the destination includes its purpose. An
invisible copy stays in the plan, shown in neither; a copy whose purpose neither destination includes leaves it, as
does a guide no guideVisibility opinion makes explicitly visible, since the planner adds guide to the viewport's
purposes for those alone (VIS-04). Expected values come from the fixtures, or from UsdGeom after an edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd, UsdGeom

from fixtures import appearance, evaluation, interaction
from fixtures.evaluation import RENDER_PURPOSES, VIEWPORT_PURPOSES
from proscenium.core import _core

from .plan_checks import CONTEXT, SETTINGS, PlannedDrawnCopy, copies, plan_at

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TIME_CODES = [None, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0]  # Blinking's samples, its transitions, and between them


@pytest.fixture
def visibility(tmp_path: Path) -> Iterator[evaluation.VisibilityScene]:
    with evaluation.visibility_purpose(tmp_path) as scene:
        yield scene


@pytest.fixture
def stress(tmp_path: Path) -> Iterator[appearance.StressScene]:
    with appearance.nested_stress(tmp_path) as scene:
        yield scene


def _time_code(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _usd_participation(stage: Usd.Stage, path: str, time_code: Usd.TimeCode) -> tuple[bool, bool] | None:
    """UsdGeom's (viewport, render) under the default purposes; None for a copy the plan leaves out."""
    imageable = UsdGeom.Imageable(stage.GetPrimAtPath(path))
    purpose = imageable.ComputePurpose()
    # UsdGeom gives "inherited" for a proxy or render prim with no opinion up to the root, which shows it.
    effective = imageable.ComputeEffectiveVisibility(purpose, time_code)
    if purpose == UsdGeom.Tokens.guide:  # in the viewport when explicitly visible, else left out
        return (True, False) if effective == UsdGeom.Tokens.visible else None
    visible = effective != UsdGeom.Tokens.invisible
    return visible and purpose in VIEWPORT_PURPOSES, visible and purpose in RENDER_PURPOSES


def _participation(shown: dict[str, PlannedDrawnCopy]) -> dict[str, tuple[bool, bool]]:
    return {path: (copy.visible_in_viewport, copy.visible_in_render) for path, copy in shown.items()}


@pytest.mark.parametrize("time_code", TIME_CODES)
def test_participation_follows_visibility_and_purpose(
    visibility: evaluation.VisibilityScene, time_code: float | None
) -> None:
    # VIS-01, VIS-02 on F-VISIBILITY-PURPOSE's cases "inherited-visibility", "default-purposes", and "time-varying".
    chain = _core.SceneIndexChain(visibility.stage)
    try:
        shown = copies(_core.plan(chain.capture(_time_code(time_code)), SETTINGS, CONTEXT))
    finally:
        chain.release()
    expected = {
        path: (
            visibility.displays(path, time_code, VIEWPORT_PURPOSES),
            visibility.displays(path, time_code, RENDER_PURPOSES),
        )
        for path, purpose in visibility.purpose.items()
        if purpose != "guide"  # Shown/Guide authors no guideVisibility
    }
    assert _participation(shown) == expected
    assert expected["/World/Hidden/Child"] == (False, False)  # kept, shown in neither


def test_one_chain_follows_visibility_over_time(visibility: evaluation.VisibilityScene) -> None:
    # VIS-01 on case "time-varying": one chain, moved from one time code to the next, as a cache call moves it.
    chain = _core.SceneIndexChain(visibility.stage)
    try:
        shown = {t: copies(_core.plan(chain.capture(Usd.TimeCode(t)), SETTINGS, CONTEXT)) for t in (0.0, 15.0, 25.0)}
    finally:
        chain.release()
    blinking = {
        t: (at[visibility.blinking].visible_in_viewport, at[visibility.blinking].visible_in_render)
        for t, at in shown.items()
    }
    assert blinking == {0.0: (True, True), 15.0: (False, False), 25.0: (True, True)}


def test_a_destinations_purposes_change_only_its_participation(visibility: evaluation.VisibilityScene) -> None:
    """Relation 3: the same snapshot planned under settings that differ in one destination's purposes.

    Copies of an added purpose gain that destination's participation and copies of a removed one lose it. The other
    destination's participation, every transform, bounds, and source are unchanged, apart from a copy whose purpose
    neither destination includes leaving the plan. VIS-02, VIS-03 on F-VISIBILITY-PURPOSE's case "purpose-settings".
    """
    chain = _core.SceneIndexChain(visibility.stage)
    try:
        snapshot = chain.capture(Usd.TimeCode(0.0))
    finally:
        chain.release()
    before = copies(_core.plan(snapshot, SETTINGS, CONTEXT))
    viewport, render = set(VIEWPORT_PURPOSES), set(RENDER_PURPOSES)
    # (viewport purposes, render purposes, the destination changed, the purpose added or removed)
    changes = [
        (viewport - {"proxy"}, render, "viewport", "proxy"),
        (viewport, render | {"proxy"}, "render", "proxy"),
        (viewport | {"render"}, render, "viewport", "render"),
    ]
    for viewport_purposes, render_purposes, destination, purpose in changes:
        after = copies(_core.plan(snapshot, _core.PlanSettings(viewport_purposes, render_purposes), CONTEXT))
        other = "render" if destination == "viewport" else "viewport"
        added = purpose in (viewport_purposes if destination == "viewport" else render_purposes)
        changed = {path for path, p in visibility.purpose.items() if p == purpose}
        # A removed purpose the other destination lacks leaves the plan with its copies.
        left = changed if not added and purpose not in (render if destination == "viewport" else viewport) else set()
        case = (destination, purpose)
        assert after.keys() == before.keys() - left, case
        for path, copy in after.items():
            old = before[path]
            expected = (
                visibility.visible(path, 0.0) and added
                if path in changed
                else getattr(old, f"visible_in_{destination}")
            )
            assert getattr(copy, f"visible_in_{destination}") == expected, (case, path)
            assert getattr(copy, f"visible_in_{other}") == getattr(old, f"visible_in_{other}"), (case, path)
            assert (copy.world_matrix, copy.local_bounds) == (old.world_matrix, old.local_bounds), (case, path)
        # Each change shows in the plan, so the checks above could fail.
        assert left or any(
            getattr(after[p], f"visible_in_{destination}") != getattr(before[p], f"visible_in_{destination}")
            for p in changed
        ), case


def test_nested_instances_give_both_destinations_from_one_snapshot(stress: appearance.StressScene) -> None:
    # VIS-03 on F-NESTED-STRESS' case "purposes": no guide displays, and the fixture's participation per copy.
    shown = copies(plan_at(stress.stage, 0.0))
    assert (
        shown.keys() == stress.viewport_paths | stress.render_paths
    )  # the guides, never explicitly visible, leave the plan
    assert _participation(shown) == {
        path: (path in stress.viewport_paths, path in stress.render_paths) for path in shown
    }


def test_visibility_through_instance_roots(stress: appearance.StressScene) -> None:
    # Each copy takes its instance roots' visibility and purpose-visibility opinions, nested ones included, as UsdGeom
    # computes them for its instance proxy.
    stage = stress.stage
    UsdGeom.Imageable(stage.GetPrimAtPath("/World/Sheared/UnitA")).MakeInvisible()
    UsdGeom.VisibilityAPI.Apply(stage.GetPrimAtPath("/World/Mirrored/UnitB")).CreateProxyVisibilityAttr("invisible")
    UsdGeom.VisibilityAPI.Apply(stage.GetPrimAtPath("/World/Skewed/UnitC")).CreateGuideVisibilityAttr("visible")
    UsdGeom.Imageable(stage.GetPrimAtPath("/Prototypes/Unit/InnerTinted")).MakeInvisible()  # a nested instance root
    # A proxy inside the nested instances, so UnitB's opinion reaches it through two instance roots.
    UsdGeom.Imageable(stage.GetPrimAtPath("/Prototypes/Leaf/Geom")).CreatePurposeAttr("proxy")
    shown = copies(plan_at(stage, 0.0))
    expected = {
        path: participation
        for path in stress.world_matrices_by_source
        if (participation := _usd_participation(stage, path, Usd.TimeCode(0.0))) is not None
    }
    assert _participation(shown) == expected
    # The edits reached the plan, so the check above could fail.
    assert expected["/World/Mirrored/UnitB/Proxy"] == (False, False)
    assert expected["/World/Skewed/UnitC/Guide"] == (True, False)
    assert not any(expected[f"/World/Sheared/UnitA/{m}"][0] for m in ("Body", "Inner/Geom", "Proxy"))
    assert expected["/World/Skewed/UnitC/InnerTinted/Geom"] == (False, False)
    assert (expected["/World/Mirrored/UnitB/Inner/Geom"], expected["/World/Skewed/UnitC/Inner/Geom"]) == (
        (False, False),
        (True, False),
    )


def test_animated_purpose_visibility_reaches_each_capture(visibility: evaluation.VisibilityScene) -> None:
    # Authored purpose visibility is read at the chain's time, so an animated opinion follows it.
    stage = visibility.stage
    proxy = "/World/Shown/Proxy"
    attribute = UsdGeom.VisibilityAPI.Apply(stage.GetPrimAtPath(proxy)).CreateProxyVisibilityAttr()
    attribute.Set("inherited", Usd.TimeCode(0.0))
    attribute.Set("invisible", Usd.TimeCode(10.0))
    chain = _core.SceneIndexChain(stage)
    try:
        shown = {t: copies(_core.plan(chain.capture(Usd.TimeCode(t)), SETTINGS, CONTEXT)) for t in (0.0, 10.0)}
    finally:
        chain.release()
    assert {t: at[proxy].visible_in_viewport for t, at in shown.items()} == {
        t: _usd_participation(stage, proxy, Usd.TimeCode(t)) == (True, False) for t in (0.0, 10.0)
    }
    assert shown[0.0][proxy].visible_in_viewport != shown[10.0][proxy].visible_in_viewport  # the check above could fail


def test_an_explicitly_visible_guide_displays_in_the_viewport(tmp_path: Path) -> None:
    # VIS-04 on F-UNIVERSE-MEMBERSHIP's case "explicit-guide": its ancestor's guideVisibility makes it visible.
    with interaction.universe_membership(tmp_path) as scene:
        shown = copies(plan_at(scene.stage, 0.0))
        # Made invisible, it stays in the plan, shown in neither, as any invisible copy does.
        UsdGeom.Imageable(scene.stage.GetPrimAtPath("/World/VisibleGuide")).MakeInvisible()
        hidden = copies(plan_at(scene.stage, 0.0))
    guide = "/World/VisibleGuide/Box"
    assert (shown[guide].visible_in_viewport, shown[guide].visible_in_render) == (True, False)
    assert "/World/Guide/Box" not in shown
    assert (hidden[guide].visible_in_viewport, hidden[guide].visible_in_render) == (False, False)


def test_placeholders_take_visibility_and_purpose(tmp_path: Path) -> None:
    # MODEL-06 on F-UNSUPPORTED-CONTENT's case "per-behavior", and a supported mesh beneath unsupported curves.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        shown = copies(plan_at(unsupported.stage, 0.0))
    for path, expected in unsupported.placeholders.items():
        assert (shown[path].visible_in_viewport, shown[path].visible_in_render) == (
            expected.visible_in_viewport,
            expected.visible_in_render,
        ), path
    for path, (_, purpose) in unsupported.supported_beneath.items():
        assert (shown[path].visible_in_viewport, shown[path].visible_in_render) == (
            purpose in VIEWPORT_PURPOSES,
            purpose in RENDER_PURPOSES,
        )


def test_settings_refuse_another_purpose() -> None:
    with pytest.raises(ValueError, match="Not a USD purpose"):
        _core.PlanSettings({"default", "preview"}, RENDER_PURPOSES)
    settings = _core.PlanSettings(["proxy", "default", "proxy"], RENDER_PURPOSES)
    assert settings.viewport_purposes == ("default", "proxy")  # sorted, each once
