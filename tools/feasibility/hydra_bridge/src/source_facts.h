// Source facts the UsdImaging chain drops, read from USD for one prim: what the source-info filter adds under the `prosceniumSource` container. See source_info_scene_index.h for
// what each fact is for.
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/tf/token.h>
#include <pxr/imaging/hd/dataSource.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/usd/relationship.h>
#include <pxr/usd/usd/timeCode.h>

#include <cstdint>
#include <functional>
#include <mutex>

namespace hydra_bridge {

// The container and its fields.
struct SourceInfoTokens {
    static const pxr::TfToken &Schema();  // prosceniumSource
    static const pxr::TfToken &TypeName();
    static const pxr::TfToken &IsGprim();
    static const pxr::TfToken &DoubleSided();
    static const pxr::TfToken &FamilyName();
    static const pxr::TfToken &FamilyIssue();  // on a mesh: why UsdGeomSubset::ValidateFamily rejects its materialBind family
    static const pxr::TfToken &Bindings();        // container: allPurpose, preview, full -> material path token
    static const pxr::TfToken &StrongPurposes();  // token array: bound strongerThanDescendants; "" is allPurpose
    // token array, on a gprim or point instancer: authored attributes UsdImaging drops (DroppedAttribute)
    static const pxr::TfToken &DroppedAttributes();
    // The purpose-visibility fields are named by the purpose they control: guide, proxy, render.
};

template <class T>
pxr::HdDataSourceBaseHandle Retained(const T &value) {
    return pxr::HdRetainedTypedSampledDataSource<T>::New(value);
}

// Builds its contents from the prim as it is now, not as it was when made: downstream scene indices keep the
// input container between notices. A build is reused until `generation` changes.
class LazyContainer final : public pxr::HdContainerDataSource {
public:
    HD_DECLARE_DATASOURCE(LazyContainer);

    pxr::TfTokenVector GetNames() override;
    pxr::HdDataSourceBaseHandle Get(const pxr::TfToken &name) override;

private:
    LazyContainer(std::function<pxr::HdContainerDataSourceHandle()> build, std::function<uint64_t()> generation);
    pxr::HdContainerDataSourceHandle Built();

    std::function<pxr::HdContainerDataSourceHandle()> build_;
    std::function<uint64_t()> generation_;
    std::mutex mutex_;
    bool valid_ = false;
    uint64_t builtAt_ = 0;
    pxr::HdContainerDataSourceHandle built_;
};

// Whether an edit to this property of `prim` can change a source fact; Hydra doesn't notice edits to most of
// them. `prim` may be invalid, as when the edit removed it.
bool SourceFact(const pxr::UsdPrim &prim, const pxr::TfToken &name);

// An attribute UsdImaging never passes to Hydra and USD doesn't read on its behalf: not defined by the
// prim's schemas, not a primvar, not a transform op, and not a GeomSubset family type or collection setting.
// Its value reaches neither the snapshot nor Blender, so the planner warns about it.
bool DroppedAttribute(const pxr::UsdPrim &prim, const pxr::TfToken &name);

// The source facts of `prim` (the contents of the prosceniumSource container); null for none.
pxr::HdContainerDataSourceHandle SourceInfo(const pxr::UsdPrim &prim);

// USD's computed extent for a point-based prim Hydra gives no extent and doesn't draw as a mesh, as an extent
// schema container; null otherwise.
pxr::HdContainerDataSourceHandle ComputedExtent(const pxr::UsdPrim &prim, const pxr::TfToken &hydraType,
                                                pxr::UsdTimeCode time);

}  // namespace hydra_bridge
