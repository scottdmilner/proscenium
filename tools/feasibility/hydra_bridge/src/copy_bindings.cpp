#include "copy_bindings.h"

#include <pxr/usd/usd/collectionAPI.h>
#include <pxr/usd/usd/collectionMembershipQuery.h>
#include <pxr/usd/usd/primRange.h>
#include <pxr/usd/usdGeom/imageable.h>
#include <pxr/usd/usdGeom/subset.h>
#include <pxr/usd/usdShade/materialBindingAPI.h>
#include <pxr/usd/usdShade/tokens.h>

#include <algorithm>
#include <array>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// Whether `query` can include `root` or anything below it. A path expression can match anywhere, so it is
// assumed to.
bool Reaches(const UsdCollectionMembershipQuery &query, const SdfPath &root) {
    if (!query.UsesPathExpansionRuleMap()) return true;
    if (query.IsPathIncluded(root)) return true;
    for (const auto &[path, rule] : query.GetAsPathExpansionRuleMap())
        if (path != root && path.HasPrefix(root)) return true;
    return false;
}

bool HasCollectionBinding(const UsdPrim &prim) {
    for (const UsdRelationship &rel : prim.GetRelationships())
        if (UsdShadeMaterialBindingAPI::CollectionBinding::IsCollectionBindingRel(rel)) return true;
    return false;
}

// Whether any prim binds a collection, visiting each prim once: the stage's own prims, then each prototype's,
// not their instances. Most scenes have none, and this costs a fraction of the instance-proxy pass.
bool AnyCollectionBinding(const UsdStagePtr &stage) {
    for (const UsdPrim &prim : stage->Traverse())
        if (HasCollectionBinding(prim)) return true;
    for (const UsdPrim &prototype : stage->GetPrototypes())
        for (const UsdPrim &prim : UsdPrimRange(prototype))
            if (HasCollectionBinding(prim)) return true;
    return false;
}

}  // namespace

std::optional<size_t> MaterialPurposeIndex(const TfToken &purpose) {
    if (purpose == UsdShadeTokens->allPurpose) return 0;
    if (purpose == UsdShadeTokens->preview) return 1;
    if (purpose == UsdShadeTokens->full) return 2;
    return std::nullopt;
}

CopyBindings ComputeCopyBindings(const UsdStagePtr &stage) {
    CopyBindings result;
    if (!stage || !AnyCollectionBinding(stage)) return result;
    // Instance proxies too: a collection authored inside an asset is seen on each instance, with its
    // targets in that instance's namespace.
    std::vector<UsdPrim> instances;
    std::vector<UsdCollectionMembershipQuery> queries;
    for (const UsdPrim &prim : stage->Traverse(UsdTraverseInstanceProxies(UsdPrimDefaultPredicate))) {
        if (prim.IsInstance()) instances.push_back(prim);
        for (const UsdRelationship &rel : prim.GetRelationships()) {
            if (!UsdShadeMaterialBindingAPI::CollectionBinding::IsCollectionBindingRel(rel)) continue;
            if (const UsdCollectionAPI collection = UsdShadeMaterialBindingAPI::CollectionBinding(rel).GetCollection())
                queries.push_back(collection.ComputeMembershipQuery());
        }
    }
    if (queries.empty()) return result;
    // Traversal order puts an outer instance before the instances nested in it; a reached outer instance
    // covers them.
    for (const UsdPrim &instance : instances) {
        const SdfPath &path = instance.GetPath();
        const bool covered = std::any_of(result.instances.begin(), result.instances.end(),
                                         [&](const SdfPath &outer) { return path.HasPrefix(outer); });
        if (covered) continue;
        if (std::any_of(queries.begin(), queries.end(), [&](const auto &query) { return Reaches(query, path); }))
            result.instances.push_back(path);
    }
    std::vector<UsdPrim> copies;
    for (const SdfPath &path : result.instances)
        for (const UsdPrim &prim :
             UsdPrimRange(stage->GetPrimAtPath(path), UsdTraverseInstanceProxies(UsdPrimDefaultPredicate)))
            if (prim.IsA<UsdGeomImageable>() || prim.IsA<UsdGeomSubset>()) copies.push_back(prim);
    const std::array purposes{UsdShadeTokens->allPurpose, UsdShadeTokens->preview, UsdShadeTokens->full};
    for (size_t p = 0; p < purposes.size(); ++p) {
        // UsdShade's own resolution, in parallel; it falls back to allPurpose itself.
        const std::vector<UsdShadeMaterial> bound =
            UsdShadeMaterialBindingAPI::ComputeBoundMaterials(copies, purposes[p]);
        for (size_t i = 0; i < copies.size(); ++i)
            result.materials[copies[i].GetPath()][p] = bound[i] ? bound[i].GetPath() : SdfPath();
    }
    return result;
}

}  // namespace hydra_bridge
