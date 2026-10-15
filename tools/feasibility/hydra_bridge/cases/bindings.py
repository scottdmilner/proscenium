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
    # WORKAROUND for OpenUSD #3690 (src/copy_bindings.h): the core resolves copies that binding collections
    # reach with UsdShade, per instance proxy. Hydra's own bindings still miss them; the known gap below
    # stops reproducing once Blender's USD carries a fix, and the workaround can go.
    inside = oracle.face_materials(stage, "/World/Inside/Blade", TIME)
    outside = oracle.face_materials(stage, "/World/Outside/Blade", TIME)
    planned_inside, planned_outside = planned("", "/World/Inside/Blade"), planned("", "/World/Outside/Blade")
    case.findings["collection binding inside an instance"] = {
        "UsdShade": {"Inside": inside, "Outside": outside},
        "plan": {"Inside": planned_inside, "Outside": planned_outside},
    }
    case.check(
        "a collection binding that includes a prim inside one native instance binds it there and not in another "
        "instance of the same prototype, as UsdShade does (workaround for OpenUSD #3690)",
        inside == ["/World/Looks/Green"]
        and outside == [None]
        and oracle.materials_match(inside, planned_inside)
        and oracle.materials_match(outside, planned_outside),
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
    case.check(
        "a collection binding authored on an instanced asset's root (OpenUSD #3690's shape) binds each instance "
        "its own material, as UsdShade does (workaround for OpenUSD #3690)",
        tagged == {"/World/KitA/Blade": ["/World/KitA/Looks/Bark"], "/World/KitB/Blade": ["/World/KitB/Looks/Bark"]}
        and all(oracle.materials_match(tagged[s], planned_tagged[s]) for s in tagged),
        case.findings["collection binding on an instanced asset's root"],
    )
    hydra_bound = {
        p: set(snapshot.prim(p)["material_bindings"].values())
        for p in snapshot.paths()
        if snapshot.prim(p) and snapshot.prim(p)["material_bindings"]
    }
    hydra_green = {p for p, bound in hydra_bound.items() if "/World/Looks/Green" in bound}
    hydra_bark = {p for p, bound in hydra_bound.items() if any(m.endswith("/Looks/Bark") for m in bound)}
    case.findings["Hydra's own collection bindings"] = {"Green": sorted(hydra_green), "Bark": sorted(hydra_bark)}
    case.known_gap(
        "Hydra binds the collections' materials only outside native instances: Green on Loose, Bark nowhere "
        "(OpenUSD #3690; the core's workaround resolves these copies itself)",
        hydra_green == {"/World/Loose"} and not hydra_bark,
        case.findings["Hydra's own collection bindings"],
    )
    # Only the instances a binding collection reaches take the workaround: Inside (World's Picked includes its
    # Blade) and KitA and KitB (Tagged's Some, authored in the asset, includes each one's Blade); Outside and the
    # scene's other instances keep the per-prototype resolution.
    reached = sorted(snapshot.copy_bindings["instances"])
    case.check(
        "the per-copy workaround covers exactly the instances a binding collection reaches",
        reached == ["/World/Inside", "/World/KitA", "/World/KitB"],
        reached,
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

    # Moving the collection from Inside's Blade to Outside's: the next incremental capture re-resolves.
    stage.GetPrimAtPath("/World").GetRelationship("collection:Picked:includes").SetTargets(
        ["/World/Loose", "/World/Outside/Blade"]
    )
    edited = bridge.capture(TIME, incremental=True)
    edited_plan = case.native.build_plan(edited)
    edited_objects = {o["source"]: o for o in edited_plan.objects}
    after = {s: oracle.face_materials(stage, s, TIME) for s in ("/World/Inside/Blade", "/World/Outside/Blade")}
    planned_after = {s: oracle.plan_face_materials(edited_plan, edited_objects[s]) for s in after}
    case.check(
        "after a collection edit, an incremental capture binds the newly included instance and unbinds the other, "
        "as UsdShade does",
        after == {"/World/Inside/Blade": [None], "/World/Outside/Blade": ["/World/Looks/Green"]}
        and all(oracle.materials_match(after[s], planned_after[s]) for s in after)
        and sorted(edited.copy_bindings["instances"]) == ["/World/KitA", "/World/KitB", "/World/Outside"],
        (after, planned_after, edited.copy_bindings["instances"]),
    )
