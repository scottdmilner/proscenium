// Python views over the immutable snapshot and plan. Large arrays are returned as the existing
// pxr.Vt array types (an O(1) copy-on-write copy), which support the buffer protocol.
#pragma once

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
    [[nodiscard]] bp::object Prim(const std::string &path) const;  // dict of what planning reads, or None
    [[nodiscard]] bp::object Dump(const std::string &path) const;  // the prim's retained data sources, as text, or None
    [[nodiscard]] bp::list Events() const;                         // (kind, path) tuples
    [[nodiscard]] bp::dict DirtyLocators() const;                  // path -> locator strings
    [[nodiscard]] bp::list Renames() const;                        // (old path, new path) tuples
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

// Plans without holding the GIL. Each destination takes prim purposes by USD name ("default", "proxy",
// "render", "guide") and a material purpose ("" for allPurpose, "preview", "full"); None keeps the default
// (PlanSettings).
PlanView MakePlan(const SnapshotView &snapshot, const bp::object &viewportPurposes,
                  const bp::object &viewportMaterialPurpose, const bp::object &renderPurposes,
                  const bp::object &renderMaterialPurpose);

void WrapViews();

}  // namespace hydra_bridge
