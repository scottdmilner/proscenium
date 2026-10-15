"""Collection-based and purpose-specific bindings, and purpose visibility, against UsdShade and UsdGeom."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import oracle

if TYPE_CHECKING:
    from .harness import Case

TIME = 1.0
PURPOSE_MESHES = ["/World/Purposes/Inherits", "/World/Purposes/Own", "/World/Purposes/PreviewOnly"]
VISIBILITY_MESHES = [
    "/World/PurposeVis/Proxy",
    "/World/PurposeVis/Render",
    "/World/PurposeVis/Guide",
    "/World/PurposeVis/ShownGuide",
    "/World/PurposeVis/Plain",
    "/World/Rigged/Render",
    "/World/Rigged/Guide",
]


def run(case: Case) -> None:
    stage = case.open("bindings.usda")
    bridge = case.native.Bridge(stage)
    snapshot = bridge.capture(TIME)
    # Both destinations resolve the same material purpose, so each prim has one object per plan.
    plans = {
        purpose: case.native.build_plan(snapshot, viewport_material_purpose=purpose, render_material_purpose=purpose)
        for purpose in ("", "full", "preview")
    }
    by_source = {purpose: {o["source"]: o for o in plan.objects} for purpose, plan in plans.items()}

    def planned(purpose: str, source: str) -> list[set[str] | None]:
        return oracle.plan_face_materials(plans[purpose], by_source[purpose][source])

    loose = oracle.face_materials(stage, "/World/Loose", TIME)
    case.check(
        "a collection-based binding outside instances matches UsdShade",
        loose == ["/World/Looks/Green"] and oracle.materials_match(loose, planned("", "/World/Loose"), exact=True),
        (loose, planned("", "/World/Loose")),
    )
    inside = oracle.face_materials(stage, "/World/Inside/Blade", TIME)
    outside = oracle.face_materials(stage, "/World/Outside/Blade", TIME)
    case.findings["collection binding inside an instance"] = {
        "UsdShade": inside,
        "plan": planned("", "/World/Inside/Blade"),
        "other instance, UsdShade": outside,
    }
    case.known_gap(
        "a collection binding that targets a prim inside a native instance is missed",
        inside == ["/World/Looks/Green"] and outside == [None] and planned("", "/World/Inside/Blade") == [None],
        case.findings["collection binding inside an instance"],
    )

    wrong = {}
    for purpose in plans:
        for source in PURPOSE_MESHES:
            usd = oracle.face_materials(stage, source, TIME, purpose)
            if not oracle.materials_match(usd, planned(purpose, source), exact=True):
                wrong[(purpose, source)] = (usd, planned(purpose, source))
    case.check(
        "purpose-specific bindings resolve as UsdShade does, trying the purpose up the hierarchy before allPurpose",
        not wrong,
        wrong,
    )
    legacy = {p: oracle.face_materials(stage, "/World/Purposes/Legacy", TIME, p) for p in plans}
    planned_legacy = {p: planned(p, "/World/Purposes/Legacy") for p in plans}
    case.check(
        "a binding authored without MaterialBindingAPI resolves as UsdShade does",
        legacy == {"": ["/World/Looks/Blue"], "full": ["/World/Looks/Full"], "preview": ["/World/Looks/Blue"]}
        and all(oracle.materials_match(legacy[p], planned_legacy[p], exact=True) for p in plans),
        (legacy, planned_legacy),
    )

    warned = {d["source"] for d in plans[""].diagnostics if d["code"] == "binding-without-api"}
    usd = {s for s in oracle.drawn_gprims(stage) if oracle.binds_without_api(stage.GetPrimAtPath(s))}
    case.check(
        "each drawn prim binding without MaterialBindingAPI gets a binding-without-api warning, and no other",
        warned == usd == {"/World/Purposes/Legacy"},
        (warned, usd),
    )

    # UsdShade's own Tf warning for that binding is posted while the bridge is built, outside any capture.
    def legacy_warnings(diagnostics: list[dict[str, Any]]) -> int:
        return sum(
            d["code"] == "tf-warning"
            and "MaterialBindingAPI" in d["message"]
            and "/World/Purposes/Legacy" in d["message"]
            for d in diagnostics
        )

    first, second = legacy_warnings(snapshot.diagnostics), legacy_warnings(bridge.capture(TIME).diagnostics)
    case.check(
        "a Tf warning posted while the bridge is built reaches its first capture's diagnostics once, not later ones",
        (first, second) == (1, 0),
        (first, second),
    )

    tagged = {s: oracle.face_materials(stage, s, TIME) for s in ("/World/KitA/Blade", "/World/KitB/Blade")}
    planned_tagged = {s: planned("", s) for s in tagged}
    case.findings["collection binding on an instanced asset's root"] = {"UsdShade": tagged, "plan": planned_tagged}
    case.known_gap(
        "a collection binding authored on an instanced asset's root (OpenUSD #3690's shape) is missed in every "
        "instance",
        tagged == {"/World/KitA/Blade": ["/World/KitA/Looks/Bark"], "/World/KitB/Blade": ["/World/KitB/Looks/Bark"]}
        and all(p == [None] for p in planned_tagged.values()),
        case.findings["collection binding on an instanced asset's root"],
    )

    hydra = {s: snapshot.prim(s)["material_bindings"] for s in PURPOSE_MESHES}
    case.findings["Hydra's flattened bindings, per purpose"] = hydra
    case.known_gap(
        "Hydra flattens each purpose separately with no allPurpose fallback (the core falls back)",
        "preview" not in hydra["/World/Purposes/Own"] and "" in hydra["/World/Purposes/Own"],
        hydra,
    )

    objects = by_source[""]
    expected = {s: oracle.visible(stage, s, TIME) for s in VISIBILITY_MESHES}
    planned_visibility = {s: objects[s]["visible"] for s in VISIBILITY_MESHES}
    case.check(
        "effective purpose visibility matches UsdGeom, including opinions on an instance root",
        planned_visibility == expected,
        (planned_visibility, expected),
    )
    hydra_visibility = {s: snapshot.prim(s)["visible"] for s in VISIBILITY_MESHES if snapshot.prim(s)}
    case.findings["Hydra's own visibility"] = hydra_visibility
    case.known_gap(
        "Hydra doesn't image purpose visibility (the source-info filter carries it)",
        expected["/World/PurposeVis/Proxy"] is False and hydra_visibility.get("/World/PurposeVis/Proxy") is True,
        hydra_visibility,
    )
