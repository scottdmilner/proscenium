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

    bp::object Time() const;  // None at default time
    bp::list Paths() const;
    bp::object Prim(const std::string &path) const;  // dict of what planning reads, or None
    bp::object Dump(const std::string &path) const;  // the prim's retained data sources, as text, or None
    bp::list Events() const;                         // (kind, path) tuples
    bp::dict DirtyLocators() const;                  // path -> locator strings
    bp::list Renames() const;                        // (old path, new path) tuples
    bp::list Diagnostics() const;
    // WORKAROUND for OpenUSD #3690: {"instances": [paths], "materials": {copy path: {purpose: material}}},
    // purposes "allPurpose", "preview", "full"; a material is "" when nothing binds.
    bp::dict CopyBindings() const;
};

struct PlanView {
    PlanPtr data;

    bp::object Time() const;  // None at default time
    bp::list Meshes() const;
    bp::list Materials() const;
    bp::list Objects() const;
    bp::list Diagnostics() const;
};

// Plans without holding the GIL. Each destination takes prim purposes by USD name ("default", "proxy",
// "render", "guide") and a material purpose ("" for allPurpose, "preview", "full"); None keeps the default
// (PlanSettings).
PlanView MakePlan(const SnapshotView &snapshot, const bp::object &viewportPurposes,
                  const bp::object &viewportMaterialPurpose, const bp::object &renderPurposes,
                  const bp::object &renderMaterialPurpose);

void WrapViews();

}  // namespace hydra_bridge
