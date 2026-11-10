#include "plan.h"

#include <pxr/base/gf/range3d.h>
#include <pxr/base/gf/rotation.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec4d.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/usd/usdGeom/imageable.h>
#include <pxr/usd/usdGeom/tokens.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

#include "instancing.h"
#include "prim_reader.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// What the planner reads of a drawn copy of a gprim.
struct DrawnGprim {
  SdfPath source;                   // on the composed stage, never a Hydra path
  SdfPathVector instanceContext;    // native-instance roots, outermost first
  GfMatrix4d world{1.0};            // USD's row-vector convention
  std::optional<GfRange3d> bounds;  // local; absent when Hydra gives the gprim no extent
  const PrimRecord* prim;           // the Hydra prim it is a copy of
  const DrawnCopy* copy;            // the resolver's, which outlives it
  const PrimRecord* mesh;           // the same, for a mesh; null for any other gprim
  TfToken purpose;                  // USD's name
  bool visible;                     // effectively, for its own purpose
  bool explicitGuide;               // a guide whose nearest guideVisibility opinion is visible
  TfToken usdType;                  // for a gprim other than a mesh; else empty
};

// (min x, min y, min z, max x, max y, max z) appended to `values`.
void AppendBounds(const GfRange3d& bounds, VtFloatArray& values) {
  for (const GfVec3d& corner : {bounds.GetMin(), bounds.GetMax()})
    for (std::size_t i = 0; i < GfVec3d::dimension; ++i) values.push_back(static_cast<float>(corner[i]));
}

// The matrix's 16 elements appended to `values` in USD's row-major layout, which is Blender's column-major one: USD
// multiplies row vectors and Blender column vectors, so each holds the other's transpose.
void AppendWorld(const GfMatrix4d& world, VtFloatArray& values) {
  for (int row = 0; row < 4; ++row) {
    const GfVec4d elements = world.GetRow(row);
    for (std::size_t column = 0; column < GfVec4d::dimension; ++column)
      values.push_back(static_cast<float>(elements[column]));
  }
}

// The prim's purpose in USD's names: Hydra names USD's default geometry, and an unimaged prim can lack one.
TfToken UsdPurpose(const PrimRecord& prim) {
  return prim.purpose.IsEmpty() || prim.purpose == HdRenderTagTokens->geometry ? UsdGeomTokens->default_ : prim.purpose;
}

bool Includes(const TfTokenVector& purposes, const TfToken& purpose) {
  return std::find(purposes.begin(), purposes.end(), purpose) != purposes.end();
}

// The correction matrix C, which every world transform takes last: in USD's row vectors, the scale
// metersPerUnit / unitScale, then +90 degrees about X for a Y-up stage. That is transforms.md's C = R_upaxis @
// Scale(scale) in Blender's column vectors. The identity with conversion off.
GfMatrix4d CoordinateConversionMatrix(const Snapshot& snapshot, const PlanSettings& settings,
                                      const PlanningContext& context) {
  if (!settings.coordinateConversion) return GfMatrix4d(1.0);
  GfMatrix4d correction = GfMatrix4d().SetScale(snapshot.metersPerUnit / context.unitScale);
  if (snapshot.upAxis == UsdGeomTokens->y) correction *= GfMatrix4d().SetRotate(GfRotation(GfVec3d::XAxis(), 90.0));
  return correction;
}

// An affine matrix's last column.
GfVec4d AffineColumn() { return {0.0, 0.0, 0.0, 1.0}; }

// The matrix's affine part: a Blender object can't hold a projective column (XFORM-05).
GfMatrix4d WithoutProjectiveComponent(GfMatrix4d world) {
  world.SetColumn(3, AffineColumn());
  return world;
}

// The bridge's tolerance (apply.py's SHEAR_TOLERANCE): a float32 matrix's rounding never reaches it.
constexpr double kShearTolerance = 1e-6;

// Whether the affine `world` shears: whether any two of its axes, USD's rows, aren't orthogonal.
bool Sheared(const GfMatrix4d& world) {
  const std::array<GfVec3d, 3> axes{GfVec3d(world.GetRow3(0)), GfVec3d(world.GetRow3(1)), GfVec3d(world.GetRow3(2))};
  for (const auto& [i, j] : {std::pair{0, 1}, std::pair{0, 2}, std::pair{1, 2}}) {
    const GfVec3d& a = axes.at(i);
    const GfVec3d& b = axes.at(j);
    if (std::abs(GfDot(a, b)) > kShearTolerance * a.GetLength() * b.GetLength()) return true;
  }
  return false;
}

// A sheared world transform as the shear parent's world transform and its object's basis, neither sheared, as the
// bridge's apply.py splits it. GfMatrix4d::Factor gives world = r * s * r^T * u * t in USD's row vectors, r and u
// rotations: the object takes r, and its parent the scale s, then the rotation r^T * u, then the translation t. A
// reflection in either rotation moves into a negative scale.
std::pair<GfMatrix4d, GfMatrix4d> ShearSplit(const GfMatrix4d& world) {
  GfMatrix4d r(1.0);
  GfMatrix4d u(1.0);
  GfMatrix4d projection(1.0);
  GfVec3d scale(0.0);
  GfVec3d translation(0.0);
  // False for a singular matrix, whose zero scales Factor clamps, so the split is still exact to float precision.
  world.Factor(&r, &scale, &u, &translation, &projection);
  const GfMatrix4d negate = GfMatrix4d().SetScale(-1.0);
  if (r.GetDeterminant3() < 0.0) r = negate * r;  // r * s * r^T is unchanged
  if (u.GetDeterminant3() < 0.0) {
    u = negate * u;
    scale = -scale;
  }
  const GfMatrix4d parent =
      GfMatrix4d().SetScale(scale) * r.GetTranspose() * u * GfMatrix4d().SetTranslate(translation);
  return {parent, r};
}

// Whether the prim is a gprim: by its Hydra type, or for a prim Hydra doesn't image, by its USD type.
bool IsGprim(const PrimRecord& prim) { return HdPrimTypeIsGprim(prim.hydraPrimType) || prim.isGprim; }

// The Hydra paths of the point instancers in `table`. Under one, a prim Hydra doesn't image at its own path is drawn
// only through the instancer's copies of its prototypes, as the bridge's planner decides: a prototype's original, or a
// prim no point draws.
SdfPathVector PointInstancers(const PrimTable& table) {
  SdfPathVector paths;
  for (const PrimRecord& prim : table.prims)
    if (prim.instancer && prim.instancer->instanceLocations.empty()) paths.push_back(prim.hydraPath);
  return paths;
}

// Whether a filter's conversion of a prim of USD type `type` to a mesh is exact: a cube's and a plane's are; a
// sphere's, cylinder's, cone's, capsule's, and NURBS patch's are tessellated (SNAP-16).
bool ImplicitMeshConversionIsExact(const TfToken& type) {
  return type == UsdGeomTokens->Cube || type == UsdGeomTokens->Plane;
}

// The composed-stage source of the prim drawn in `copy`: an instance-proxy path inside instances. Outside instancing,
// the stage scene index names a prim by its USD path, and the filtering scene indices that convert it keep that.
SdfPath DrawnCopySourcePath(const PrimRecord& prim, const DrawnCopy& copy) {
  return copy.instanceContext.empty() && !prim.originPath.IsEmpty() ? prim.originPath
                                                                    : copy.MapHydraPathToSource(prim.hydraPath);
}

// Problems repeated across a USD prim's copies, each reported once, a repeated problem aggregated (with the user): at
// its first copy in source order, across every Hydra prim that copies it, its message counting the copies it covers.
// The USD prim is found only when a problem is reported, so planning without problems pays nothing for it.
class DrawnCopyDiagnosticAggregator {
 public:
  // `table` must outlive the reports.
  DrawnCopyDiagnosticAggregator(const PrimTable& table, Diagnostics& to) : table_(table), to_(to) {}

  // Reports `diagnostic` about `copies` of `prim`, or adds them to an equal problem's report.
  void Add(Diagnostic diagnostic, const PrimRecord& prim, const std::vector<DrawnCopy>& copies) {
    // Every copy of a Hydra prim copies one USD prim.
    Report& report = FindOrCreateReport(std::move(diagnostic), UsdPrimOf(prim, copies.front()));
    for (const DrawnCopy& copy : copies) Count(report, DrawnCopySourcePath(prim, copy));
  }

  // Reports `diagnostic` about one copy of `prim`, at `source`, or adds it to an equal problem's report.
  void Add(Diagnostic diagnostic, const PrimRecord& prim, const DrawnCopy& copy, const SdfPath& source) {
    Count(FindOrCreateReport(std::move(diagnostic), UsdPrimOf(prim, copy)), source);
  }

  // Names each report's first copy and counts its copies, which SummarizeRepeatedDiagnostics words into its message.
  void FinalizeDiagnosticCoverage() {
    for (auto& [key, report] : reports_) {
      Diagnostic& diagnostic = to_[report.index];
      diagnostic.sourcePath = report.first;
      diagnostic.drawnCopyCount = report.count;
    }
  }

 private:
  struct Report {
    std::size_t index = 0;  // in to_
    SdfPath first;
    std::size_t count = 0;
  };

  // The USD prim behind `prim` in `copy`, named the same for every copy Hydra's instance aggregation makes of it:
  // inside instances, its path in its innermost instance root's USD prototype (/__Prototype_N/...), else its own
  // path, which outside instancing is its USD path. Without the prototype fact, the Hydra prim stands for it.
  [[nodiscard]] SdfPath UsdPrimOf(const PrimRecord& prim, const DrawnCopy& copy) const {
    const PrimRecord* root = copy.hydraInstanceRoot.IsEmpty() ? nullptr : table_.Find(copy.hydraInstanceRoot);
    if (!root || root->instancePrototype.IsEmpty()) return prim.hydraPath;
    return SdfPath(root->instancePrototype).AppendPath(prim.hydraPath.MakeRelativePath(copy.hydraNamespaceRoot));
  }

  Report& FindOrCreateReport(Diagnostic diagnostic, SdfPath usdPrim) {
    const auto [found, added] = reports_.try_emplace({diagnostic.code, diagnostic.message, std::move(usdPrim)});
    if (added) {
      found->second.index = to_.size();
      to_.push_back(std::move(diagnostic));
    }
    return found->second;
  }

  static void Count(Report& report, const SdfPath& source) {
    if (report.count++ == 0 || source < report.first) report.first = source;
  }

  const PrimTable& table_;
  Diagnostics& to_;
  std::map<std::tuple<DiagnosticCode, std::string, SdfPath>, Report> reports_;
};

// The snapshot's diagnostics as the plan's, each about a prim reported once per USD prim
// (DrawnCopyDiagnosticAggregator). One about no prim, or a prim with no copies, names no source, and its message names
// the Hydra prim, as the bridge's planner does.
void AddSourceDiagnostics(const Snapshot& snapshot, const PrimTable& table, InstanceResolver& instances,
                          Diagnostics& to) {
  DrawnCopyDiagnosticAggregator reports(table, to);
  for (Diagnostic diagnostic : snapshot.diagnostics) {
    const PrimRecord* prim = diagnostic.sourcePath.IsEmpty() ? nullptr : table.Find(diagnostic.sourcePath);
    const std::vector<DrawnCopy>* copies = prim ? &instances.CopiesOf(*prim) : nullptr;
    if (copies && !copies->empty()) {
      reports.Add(std::move(diagnostic), *prim, *copies);
      continue;
    }
    diagnostic.hydraPrimPath = diagnostic.sourcePath;
    diagnostic.sourcePath = SdfPath();
    to.push_back(std::move(diagnostic));
  }
  reports.FinalizeDiagnosticCoverage();
}

// A drawn copy of each gprim in `table`, sorted by source, with its world transform composed by `instances`.
std::vector<DrawnGprim> DrawnGprims(const PrimTable& table, InstanceResolver& instances) {
  std::vector<DrawnGprim> gprims;
  const SdfPathVector pointInstancers = PointInstancers(table);
  for (const PrimRecord& prim : table.prims) {
    if (!IsGprim(prim)) continue;
    if (prim.hydraPrimType.IsEmpty() && !prim.instancedBy &&
        std::any_of(pointInstancers.begin(), pointInstancers.end(),
                    [&](const SdfPath& instancer) { return prim.hydraPath.HasPrefix(instancer); }))
      continue;
    const std::vector<DrawnCopy>& copies = instances.CopiesOf(prim);
    if (copies.empty()) continue;
    // Flattened: in its prototype's namespace inside instances, else the world.
    const GfMatrix4d local = prim.flattenedWorldMatrix.value_or(GfMatrix4d(1.0));
    // A reset inside the prototype drops the instance's transform too (WORKAROUND for OpenUSD #862). Every copy has
    // the same Hydra namespace root, so it is checked once.
    const bool resets = instances.ResetsBelow(prim.hydraPath, copies.front().hydraNamespaceRoot);
    const PrimRecord* mesh = prim.hydraPrimType == HdPrimTypeTokens->mesh ? &prim : nullptr;
    const TfToken purpose = UsdPurpose(prim);
    for (const DrawnCopy& copy : copies) {
      const TfToken* opinion = PurposeVisibilityOpinion(table, prim, copy);
      const bool explicitGuide = purpose == UsdGeomTokens->guide && opinion && *opinion == UsdGeomTokens->visible;
      gprims.push_back({DrawnCopySourcePath(prim, copy), copy.instanceContext,
                        resets ? local : local * copy.instanceWorldMatrix, prim.extent, &prim, &copy, mesh, purpose,
                        EffectivelyVisible(table, prim, copy), explicitGuide, prim.usdType});
    }
  }
  std::sort(gprims.begin(), gprims.end(), [](const DrawnGprim& a, const DrawnGprim& b) { return a.source < b.source; });
  return gprims;
}

}  // namespace

const char* RoleName(Role role) {
  switch (role) {
    case Role::kObject:
      return "object";
    case Role::kBoundsMesh:
      return "bounds mesh";
    case Role::kShearParent:
      return "shear parent";
  }
  throw std::invalid_argument("Not a representation role");
}

PlanSettings::PlanSettings(TfTokenVector viewport, TfTokenVector render, bool conversion)
    : viewportPurposes(std::move(viewport)), renderPurposes(std::move(render)), coordinateConversion(conversion) {
  for (TfTokenVector* purposes : {&viewportPurposes, &renderPurposes}) {
    for (const TfToken& purpose : *purposes)
      if (!Includes(UsdGeomImageable::GetOrderedPurposeTokens(), purpose))
        throw std::invalid_argument("Not a USD purpose: " + purpose.GetString());
    std::sort(purposes->begin(), purposes->end());
    purposes->erase(std::unique(purposes->begin(), purposes->end()), purposes->end());
  }
}

PlanningContext::PlanningContext(double scale, int version) : unitScale(scale), representationVersion(version) {
  if (!std::isfinite(unitScale) || unitScale <= 0.0) throw std::invalid_argument("A unit scale is positive and finite");
}

PlanPtr BuildPlan(const Snapshot& snapshot, const PlanSettings& settings, const PlanningContext& context) {
  if (context.representationVersion != 1)
    throw std::invalid_argument("The planner plans representation version 1 only");
  auto plan = std::make_shared<Plan>(
      Plan{snapshot.timeCode, context, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}});
  TfTokenVector viewport = settings.viewportPurposes;
  if (!Includes(viewport, UsdGeomTokens->guide)) viewport.push_back(UsdGeomTokens->guide);
  const PrimTable table = ReadPrims(snapshot);
  InstanceResolver instances(table, /*honorResets=*/true);
  const std::vector<DrawnGprim> gprims = DrawnGprims(table, instances);
  // Capture's first, then the resolver's, which mapping capture's can add to, then planning's own.
  AddSourceDiagnostics(snapshot, table, instances, plan->diagnostics);
  plan->diagnostics.insert(plan->diagnostics.end(), instances.Diagnostics().begin(), instances.Diagnostics().end());
  // Planning's own problems with a copy, reported once per USD prim.
  DrawnCopyDiagnosticAggregator planned(table, plan->diagnostics);
  const GfMatrix4d correction = CoordinateConversionMatrix(snapshot, settings, context);
  plan->copyWorldMatrices.reserve(16 * gprims.size());
  // Each mesh's description, made for its first copy in source order, so its source is deterministic.
  std::unordered_map<const PrimRecord*, int> geometries;
  for (const DrawnGprim& gprim : gprims) {
    const bool inViewport = Includes(viewport, gprim.purpose);
    const bool inRender = Includes(settings.renderPurposes, gprim.purpose);
    // A guide shows only where it is explicitly visible, so one that isn't is never displayed.
    if ((!inViewport && !inRender) || (gprim.purpose == UsdGeomTokens->guide && !gprim.explicitGuide)) continue;
    plan->copyVisibleInViewport.push_back(gprim.visible && inViewport);
    plan->copyVisibleInRender.push_back(gprim.visible && inRender);
    // Bounds and instances inherit the correction through the world transform; local geometry is unchanged.
    const GfMatrix4d corrected = gprim.world * correction;
    if (corrected.GetColumn(3) != AffineColumn())
      planned.Add({DiagnosticCode::kProjectiveTransform,
                   {},
                   "The world transform's projective part is dropped, so it is placed by its affine part",
                   {},
                   {},
                   {},
                   {},
                   0},
                  *gprim.prim, *gprim.copy, gprim.source);
    const GfMatrix4d world = WithoutProjectiveComponent(corrected);
    const bool sheared = Sheared(world);
    // Each behavior is decided on its own (MODEL-03): content the core doesn't translate keeps its transform,
    // participation, and correspondence. A mesh is a provisional geometry description; a filter's inexact conversion
    // to one is an approximation. Any other gprim is a placeholder, a bounds box from its usable bounds (MODEL-04), or
    // with none, an empty marker (MODEL-05), its untranslated-type diagnostic naming which.
    const GfRange3d* bounds = gprim.bounds ? &*gprim.bounds : nullptr;  // null when Hydra gives it none
    const bool marker = !gprim.mesh && !bounds;
    if (gprim.mesh && !gprim.usdType.IsEmpty() && !ImplicitMeshConversionIsExact(gprim.usdType))
      planned.Add({DiagnosticCode::kApproximatedGeometry,
                   {},
                   "Its type, " + gprim.usdType.GetString() + ", is drawn as a mesh approximating its surface",
                   {},
                   {},
                   {},
                   {},
                   0},
                  *gprim.prim, *gprim.copy, gprim.source);
    if (!gprim.mesh) {
      const TfToken& type = gprim.usdType.IsEmpty() ? gprim.prim->hydraPrimType : gprim.usdType;
      planned.Add(
          {DiagnosticCode::kUntranslatedType,
           {},
           "Its type, " + type.GetString() + ", isn't translated, so " +
               (marker ? "an empty marker stands in, since it has no usable bounds" : "a box of its bounds stands in"),
           {},
           {},
           marker ? "empty marker" : "bounding box",
           {},
           0},
          *gprim.prim, *gprim.copy, gprim.source);
    }
    // Each copy has one object, and its source entity is its source path, an instance-proxy path inside instances. A
    // marker's object holds no data.
    const std::size_t object = plan->resources.size();
    Partition partition{{object}};
    std::vector<std::size_t> uses;
    std::vector<PlannedResource> owned;
    if (!marker) owned.push_back({Role::kBoundsMesh, gprim.source, 0, {gprim.source}, {}});
    if (sheared) owned.push_back({Role::kShearParent, gprim.source, 0, {gprim.source}, {}});
    for (std::size_t i = 0; i < owned.size(); ++i) {
      partition.resourceIndices.push_back(object + 1 + i);
      uses.push_back(object + 1 + i);
    }
    plan->partitions.push_back(std::move(partition));
    plan->resources.push_back({Role::kObject, gprim.source, 0, {gprim.source}, std::move(uses)});
    plan->resources.insert(plan->resources.end(), owned.begin(), owned.end());
    plan->correspondence.push_back({object, gprim.source, gprim.instanceContext});
    AppendWorld(world, plan->copyWorldMatrices);
    int shear = -1;
    if (sheared) {
      shear = static_cast<int>(plan->shearParentWorldMatrices.size() / 16);
      const auto [parentWorld, objectBasis] = ShearSplit(world);
      AppendWorld(parentWorld, plan->shearParentWorldMatrices);
      AppendWorld(objectBasis, plan->shearObjectBasisMatrices);
    }
    plan->copyShearSplitIndices.push_back(shear);
    plan->copyObjectResourceIndices.push_back(static_cast<int>(object));
    int geometry = -1;
    int placeholder = -1;
    if (gprim.mesh) {
      const auto [found, added] = geometries.try_emplace(gprim.mesh, static_cast<int>(plan->geometries.size()));
      if (added) {
        GeometryDescription description{gprim.source, {}, gprim.source.GetString()};
        if (bounds) AppendBounds(*bounds, description.extent);
        plan->geometries.push_back(std::move(description));
      }
      geometry = found->second;
    } else if (bounds) {
      placeholder = static_cast<int>(plan->placeholderBounds.size() / 6);
      AppendBounds(*bounds, plan->placeholderBounds);
    }
    plan->copyGeometryIndices.push_back(geometry);
    plan->copyPlaceholderBoundsIndices.push_back(placeholder);
  }
  planned.FinalizeDiagnosticCoverage();
  SummarizeRepeatedDiagnostics(plan->diagnostics);
  return plan;
}

std::vector<std::pair<SdfPath, GfMatrix4d>> HydraComposedWorlds(const Snapshot& snapshot) {
  const PrimTable table = ReadPrims(snapshot);
  InstanceResolver instances(table, /*honorResets=*/false);
  std::vector<std::pair<SdfPath, GfMatrix4d>> worlds;
  for (const DrawnGprim& gprim : DrawnGprims(table, instances)) worlds.emplace_back(gprim.source, gprim.world);
  return worlds;
}

}  // namespace proscenium
