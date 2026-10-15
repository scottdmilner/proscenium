#include "source_facts.h"

#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/overlayContainerDataSource.h>
#include <pxr/imaging/hd/purposeSchema.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/visibilitySchema.h>
#include <pxr/imaging/hd/xformSchema.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/usd/usdGeom/boundable.h>
#include <pxr/usd/usdGeom/gprim.h>
#include <pxr/usd/usdGeom/mesh.h>
#include <pxr/usd/usdGeom/pointBased.h>
#include <pxr/usd/usdGeom/pointInstancer.h>
#include <pxr/usd/usdGeom/imageable.h>
#include <pxr/usd/usdGeom/subset.h>
#include <pxr/usd/usdGeom/tokens.h>
#include <pxr/usd/usdGeom/xformable.h>
#include <pxr/usd/usdGeom/xformOp.h>
#include <pxr/usd/usdShade/materialBindingAPI.h>
#include <pxr/usd/usdShade/tokens.h>
#include <pxr/usdImaging/usdImaging/dataSourceAttribute.h>
#include <pxr/usdImaging/usdImaging/usdPrimInfoSchema.h>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <mutex>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

const TfToken &SourceInfoTokens::Schema() {
    static const TfToken token("prosceniumSource");
    return token;
}
const TfToken &SourceInfoTokens::TypeName() {
    static const TfToken token("typeName");
    return token;
}
const TfToken &SourceInfoTokens::IsGprim() {
    static const TfToken token("isGprim");
    return token;
}
const TfToken &SourceInfoTokens::DoubleSided() {
    static const TfToken token("doubleSided");
    return token;
}
const TfToken &SourceInfoTokens::FamilyName() {
    static const TfToken token("familyName");
    return token;
}

const TfToken &SourceInfoTokens::FamilyIssue() {
    static const TfToken token("materialBindFamilyIssue");
    return token;
}

const TfToken &SourceInfoTokens::Bindings() {
    static const TfToken token("bindings");
    return token;
}

const TfToken &SourceInfoTokens::StrongPurposes() {
    static const TfToken token("strongPurposes");
    return token;
}

const TfToken &SourceInfoTokens::BindingsWithoutApi() {
    static const TfToken token("bindingsWithoutApi");
    return token;
}
const TfToken &SourceInfoTokens::DroppedAttributes() {
    static const TfToken token("droppedAttributes");
    return token;
}

LazyContainer::LazyContainer(std::function<HdContainerDataSourceHandle()> build, std::function<uint64_t()> generation)
    : build_(std::move(build)), generation_(std::move(generation)) {}

HdContainerDataSourceHandle LazyContainer::Built() {
    const uint64_t generation = generation_();
    std::lock_guard<std::mutex> lock(mutex_);
    if (!valid_ || generation != builtAt_) {
        built_ = build_();
        builtAt_ = generation;
        valid_ = true;
    }
    return built_;
}

TfTokenVector LazyContainer::GetNames() {
    HdContainerDataSourceHandle built = Built();
    return built ? built->GetNames() : TfTokenVector();
}

HdDataSourceBaseHandle LazyContainer::Get(const TfToken &name) {
    HdContainerDataSourceHandle built = Built();
    return built ? built->Get(name) : nullptr;
}

namespace {

// Prims the planner turns into objects, so a dropped attribute on them is data the scene loses.
bool ReportsDroppedAttributes(const UsdPrim &prim) { return prim.IsA<UsdGeomGprim>() || prim.IsA<UsdGeomPointInstancer>(); }

}  // namespace

bool DroppedAttribute(const UsdPrim &prim, const TfToken &name) {
    // Namespaces USD itself reads without a schema defining them: a GeomSubset family's type
    // (UsdGeomSubset, which the family verdict uses) and collection settings (UsdCollectionAPI, for bindings).
    static const char *const kRead[] = {"primvars:", "subsetFamily:", "collection:"};
    const std::string &text = name.GetString();
    return std::none_of(std::begin(kRead), std::end(kRead), [&](const char *prefix) { return TfStringStartsWith(text, prefix); }) &&
           !UsdGeomXformOp::IsXformOp(name) && !prim.GetPrimDefinition().GetAttributeDefinition(name);
}

bool SourceFact(const UsdPrim &prim, const TfToken &name) {
    static const TfToken kNames[] = {TfToken("familyName"), TfToken("doubleSided"), TfToken("guideVisibility"),
                                     TfToken("proxyVisibility"), TfToken("renderVisibility")};
    const std::string &text = name.GetString();
    if (std::find(std::begin(kNames), std::end(kNames), name) != std::end(kNames) ||
        TfStringStartsWith(text, "material:binding") || TfStringStartsWith(text, "collection:") ||
        TfStringStartsWith(text, "subsetFamily:"))
        return true;
    // A subset's indices and element type feed its mesh's family verdict.
    static const TfToken kIndices("indices"), kElementType("elementType");
    if (prim && prim.IsA<UsdGeomSubset>() && (name == kIndices || name == kElementType)) return true;
    // Adding, removing or first authoring such an attribute changes the dropped list; a relationship of the
    // same name is harmless, since the list is rebuilt from the prim's attributes.
    return prim && ReportsDroppedAttributes(prim) && DroppedAttribute(prim, name);
}

namespace {

// The purpose a binding relationship binds for: material:binding[:<purpose>][:collection:<name>].
TfToken BindingPurpose(const UsdRelationship &rel) {
    static const std::string kPrefix = "material:binding";
    const std::string name = rel.GetName().GetString();
    if (name.size() <= kPrefix.size() || name.compare(0, kPrefix.size(), kPrefix) != 0) return TfToken();
    const std::string rest = name.substr(kPrefix.size() + 1);  // past "material:binding:"
    if (rest.compare(0, 11, "collection:") == 0) return TfToken();
    return TfToken(rest.substr(0, rest.find(':')));
}

// UsdShade's binding for each material purpose exactly (keyed allPurpose, preview, full), without its
// fallback to allPurpose, which the core applies. On a prim inside a prototype this covers what the
// prototype itself authors, collection membership and binding strength included; what is bound at or above
// the instance root is the core's to add (BoundMaterial). Paths are stored as tokens, in the stage's
// namespace (a prototype's material under /__Prototype_N), and the core maps them to Hydra paths: an SdfPath
// value made in this module isn't recognized by USD's own code (HdMakeStaticCopy posts "Unsupported type
// SdfPath"), the same type-identity boundary as Phase B's ArResolverContext.
HdContainerDataSourceHandle ResolvedBindings(const UsdPrim &prim) {
    const UsdShadeMaterialBindingAPI api(prim);
    TfTokenVector names;
    std::vector<HdDataSourceBaseHandle> values;
    for (const TfToken &purpose : UsdShadeMaterialBindingAPI::GetMaterialPurposes()) {
        UsdRelationship rel;
        const UsdShadeMaterial material = api.ComputeBoundMaterial(purpose, &rel);
        const TfToken exact = purpose == UsdShadeTokens->allPurpose ? TfToken() : purpose;
        // A winning binding whose target isn't a Material binds nothing, and UsdShade doesn't fall back past
        // it: that is recorded as an empty path. No winning binding at all records nothing.
        if (!rel || BindingPurpose(rel) != exact) continue;
        // UsdShade's allPurpose token is empty, which a container can't keep as a name.
        static const TfToken kAllPurpose("allPurpose");
        names.push_back(exact.IsEmpty() ? kAllPurpose : purpose);
        values.push_back(Retained(material ? TfToken(material.GetPath().GetString()) : TfToken()));
    }
    if (names.empty()) return nullptr;
    return HdRetainedContainerDataSource::New(names.size(), names.data(), values.data());
}

}  // namespace

// USD's computed extent for a point-based prim Hydra gives no extent and doesn't draw as a mesh (curves,
// points, HermiteCurves), so its placeholder can show bounds. Point instancers and volumes are left out:
// their extents would mean evaluating prototypes or reading field files merely for a placeholder.
HdContainerDataSourceHandle ComputedExtent(const UsdPrim &prim, const TfToken &hydraType, UsdTimeCode time) {
    if (!prim.IsA<UsdGeomPointBased>() || hydraType == HdPrimTypeTokens->mesh || hydraType == HdPrimTypeTokens->nurbsPatch)
        return nullptr;
    VtVec3fArray extent;
    if (!UsdGeomBoundable::ComputeExtentFromPlugins(UsdGeomBoundable(prim), time, &extent) || extent.size() != 2)
        return nullptr;
    return HdRetainedContainerDataSource::New(
        HdExtentSchema::GetSchemaToken(),
        HdExtentSchema::Builder()
            .SetMin(HdRetainedTypedSampledDataSource<GfVec3d>::New(GfVec3d(extent[0])))
            .SetMax(HdRetainedTypedSampledDataSource<GfVec3d>::New(GfVec3d(extent[1])))
            .Build());
}

HdContainerDataSourceHandle SourceInfo(const UsdPrim &prim, const UsdImagingDataSourceStageGlobals &globals) {
    TfTokenVector names;
    std::vector<HdDataSourceBaseHandle> values;
    auto add = [&](const TfToken &name, HdDataSourceBaseHandle value) {
        names.push_back(name);
        values.push_back(std::move(value));
    };
    if (!prim.GetTypeName().IsEmpty()) add(SourceInfoTokens::TypeName(), Retained(prim.GetTypeName()));
    if (UsdGeomGprim gprim{prim}) {
        add(SourceInfoTokens::IsGprim(), Retained(true));
        bool doubleSided = false;
        // Get also returns the schema fallback, which is true for Plane.
        if (gprim.GetDoubleSidedAttr().Get(&doubleSided)) add(SourceInfoTokens::DoubleSided(), Retained(doubleSided));
    }
    // USD's own verdict on a mesh's materialBind family (overlaps in a nonOverlapping family, and so on).
    if (UsdGeomMesh mesh{prim}) {
        static const TfToken kMaterialBind("materialBind");
        std::string reason;
        if (!UsdGeomSubset::GetGeomSubsets(mesh, TfToken(), kMaterialBind).empty() &&
            !UsdGeomSubset::ValidateFamily(mesh, UsdGeomTokens->face, kMaterialBind, &reason))
            add(SourceInfoTokens::FamilyIssue(), Retained(TfToken(reason)));
    }
    if (UsdGeomSubset subset{prim}) {
        TfToken family;
        if (subset.GetFamilyNameAttr().Get(&family)) add(SourceInfoTokens::FamilyName(), Retained(family));
    }
    // Authored opinions only: the fallbacks depend on having no opinion anywhere up the hierarchy. Read at the
    // graph's time, and dirtied when an animated one changes with it.
    if (UsdGeomImageable imageable{prim}) {
        for (const TfToken &purpose : {UsdGeomTokens->guide, UsdGeomTokens->proxy, UsdGeomTokens->render}) {
            const UsdAttribute attribute = imageable.GetPurposeVisibilityAttr(purpose);
            if (attribute && attribute.HasAuthoredValue())
                add(purpose, UsdImagingDataSourceAttributeNew(attribute, globals, prim.GetPath(),
                                                              HdDataSourceLocator(SourceInfoTokens::Schema(), purpose)));
        }
    }
    if (UsdGeomImageable(prim) || UsdGeomSubset(prim)) {
        HdContainerDataSourceHandle bindings = ResolvedBindings(prim);
        if (bindings) add(SourceInfoTokens::Bindings(), bindings);
    }
    // UsdShade honors these too, posting a Tf warning each time it resolves them; that warning can come while
    // the bridge is built, or from any caller, so the plan reports the fact itself.
    if ((UsdGeomImageable(prim) || UsdGeomSubset(prim)) && !prim.HasAPI<UsdShadeMaterialBindingAPI>()) {
        VtTokenArray unapplied;
        for (const UsdRelationship &rel : prim.GetRelationships())
            if (TfStringStartsWith(rel.GetName().GetString(), "material:binding") && rel.HasAuthoredTargets())
                unapplied.push_back(rel.GetName());
        if (!unapplied.empty()) add(SourceInfoTokens::BindingsWithoutApi(), Retained(unapplied));
    }
    if (prim.HasAPI<UsdShadeMaterialBindingAPI>()) {
        const UsdShadeMaterialBindingAPI binding(prim);
        VtTokenArray strong;
        auto isStrong = [](const UsdRelationship &rel) {
            return UsdShadeMaterialBindingAPI::GetMaterialBindingStrength(rel) == UsdShadeTokens->strongerThanDescendants;
        };
        for (const TfToken &purpose : UsdShadeMaterialBindingAPI::GetMaterialPurposes()) {
            const UsdRelationship direct = binding.GetDirectBindingRel(purpose);
            const std::vector<UsdRelationship> collections = binding.GetCollectionBindingRels(purpose);
            if ((direct.HasAuthoredTargets() && isStrong(direct)) ||
                std::any_of(collections.begin(), collections.end(), isStrong))
                strong.push_back(purpose == UsdShadeTokens->allPurpose ? TfToken() : purpose);
        }
        if (!strong.empty()) add(SourceInfoTokens::StrongPurposes(), Retained(strong));
    }
    if (ReportsDroppedAttributes(prim)) {
        VtTokenArray dropped;
        for (const UsdAttribute &attribute : prim.GetAuthoredAttributes())
            if (attribute.HasAuthoredValue() && DroppedAttribute(prim, attribute.GetName()))
                dropped.push_back(attribute.GetName());
        if (!dropped.empty()) add(SourceInfoTokens::DroppedAttributes(), Retained(dropped));
    }
    if (names.empty()) return nullptr;
    return HdRetainedContainerDataSource::New(names.size(), names.data(), values.data());
}

}  // namespace hydra_bridge
