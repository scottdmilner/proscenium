// Python views over the immutable snapshot and plan. Large arrays are returned as the existing
// pxr.Vt array types (an O(1) copy-on-write copy), which support the buffer protocol.
// Paths are returned as strings, and taken as Sdf.Path or strings, through Sdf's converter.
#pragma once

#include "interaction.h"
#include "plan.h"
#include "snapshot.h"

#include <pxr/external/boost/python.hpp>

#include <string>

namespace hydra_bridge {

namespace bp = PXR_NS::pxr_boost::python;

struct SnapshotView {
    SnapshotPtr data;

    [[nodiscard]] bp::object Time() const;  // None at default time
    [[nodiscard]] bp::list Paths() const;
    [[nodiscard]] bp::object Prim(const bp::object &path) const;  // dict of what planning reads, or None
    [[nodiscard]] bp::object Dump(const bp::object &path) const;  // the prim's retained data sources, as text, or None
    [[nodiscard]] bp::list Events() const;                        // (kind, path) tuples
    [[nodiscard]] bp::dict DirtyLocators() const;                 // path -> locator strings
    [[nodiscard]] bp::list Renames() const;                       // (old path, new path) tuples
    [[nodiscard]] bp::list Diagnostics() const;
    // WORKAROUND for OpenUSD #3690: {"instances": [paths], "materials": {copy path: {purpose: material}}},
    // purposes "allPurpose", "preview", "full"; a material is "" when nothing binds.
    [[nodiscard]] bp::dict CopyBindings() const;
};

struct PlanView {
    PlanPtr data;

    [[nodiscard]] bp::object Time() const;  // None at default time
    [[nodiscard]] bp::list Meshes() const;
    [[nodiscard]] bp::list Materials() const;
    [[nodiscard]] bp::list Objects() const;
    [[nodiscard]] bp::list Diagnostics() const;
    [[nodiscard]] bp::list Universe() const;
};

// M4: the baseline's core interaction functions over a plan and the live stage, which it holds weakly. Elements
// are plan object indices; entities are (source, instance context) pairs, and resolve_pick also gives the floor.
// Each runs without the GIL, and raises RuntimeError once the stage has expired; a level is None (the prim
// level) or a registered kind, and anything else raises ValueError.
struct InteractionView {
    InteractionView(const pxr::UsdStagePtr &stage, const PlanView &plan);

    [[nodiscard]] bp::object ResolvePick(std::size_t element) const;  // dict, or None for no element
    [[nodiscard]] bp::list SelectTargets(const bp::object &entities, const bp::object &level) const;
    [[nodiscard]] bp::list Displayed(const bp::object &paths) const;  // a malformed path is not displayed
    [[nodiscard]] bp::list HighlightTargets(const bp::object &targets) const;
    // {"targets": [paths], "active": path or None}
    [[nodiscard]] bp::dict SelectionFromBlender(const bp::object &selected, const bp::object &active,
                                                const bp::object &level) const;

    Interaction interaction;
};

// Plans without holding the GIL. Each destination takes prim purposes by USD name ("default", "proxy",
// "render", "guide") and a material purpose ("" for allPurpose, "preview", "full"); None keeps the default
// (PlanSettings).
PlanView MakePlan(const SnapshotView &snapshot, const bp::object &viewportPurposes,
                  const bp::object &viewportMaterialPurpose, const bp::object &renderPurposes,
                  const bp::object &renderMaterialPurpose);

// M4: what `next` changes from `published` (plan_diff.h), computed without the GIL, as {"meshes", "materials",
// "objects": [old index or -1 per new entry], "changed" and "repointable": [new object indices], "removed": [old
// object indices]}.
bp::dict DiffPlanViews(const PlanView &published, const PlanView &next);

void WrapViews();

}  // namespace hydra_bridge
