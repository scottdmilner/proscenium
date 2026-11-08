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
#include <optional>
#include <stdexcept>
#include <string>
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
  const PrimRecord* mesh;           // the same, for a mesh; null for any other gprim
  TfToken purpose;                  // USD's name
  bool visible;                     // effectively, for its own purpose
  bool explicitGuide;               // a guide whose nearest guideVisibility opinion is visible
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
GfMatrix4d Correction(const Snapshot& snapshot, const PlanSettings& settings, const PlanningContext& context) {
  if (!settings.coordinateConversion) return GfMatrix4d(1.0);
  GfMatrix4d correction = GfMatrix4d().SetScale(snapshot.metersPerUnit / context.unitScale);
  if (snapshot.upAxis == UsdGeomTokens->y) correction *= GfMatrix4d().SetRotate(GfRotation(GfVec3d::XAxis(), 90.0));
  return correction;
}

// An affine matrix's last column.
GfVec4d AffineColumn() { return {0.0, 0.0, 0.0, 1.0}; }

// The matrix's affine part: a Blender object can't hold a projective column (XFORM-05).
GfMatrix4d Affine(GfMatrix4d world) {
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
bool IsGprim(const PrimRecord& prim) { return HdPrimTypeIsGprim(prim.type) || prim.isGprim; }

// A drawn copy of each gprim in `table`, sorted by source, with its world transform composed by `instances`.
std::vector<DrawnGprim> DrawnGprims(const PrimTable& table, InstanceResolver& instances) {
  std::vector<DrawnGprim> gprims;
  for (const PrimRecord& prim : table.prims) {
    if (!IsGprim(prim)) continue;
    const std::vector<DrawnCopy>& copies = instances.CopiesOf(prim);
    if (copies.empty()) continue;
    // Flattened: in its prototype's namespace inside instances, else the world.
    const GfMatrix4d local = prim.matrix.value_or(GfMatrix4d(1.0));
    // A reset inside the prototype drops the instance's transform too (WORKAROUND for OpenUSD #862). Every copy has
    // the same hydraRoot, so it is checked once.
    const bool resets = instances.ResetsBelow(prim.path, copies.front().hydraRoot);
    const PrimRecord* mesh = prim.type == HdPrimTypeTokens->mesh ? &prim : nullptr;
    const TfToken purpose = UsdPurpose(prim);
    for (const DrawnCopy& copy : copies) {
      const TfToken* opinion = PurposeVisibilityOpinion(table, prim, copy);
      const bool explicitGuide = purpose == UsdGeomTokens->guide && opinion && *opinion == UsdGeomTokens->visible;
      DrawnGprim gprim{copy.Map(prim.path),
                       copy.context,
                       resets ? local : local * copy.world,
                       prim.extent,
                       &prim,
                       mesh,
                       purpose,
                       EffectivelyVisible(table, prim, copy),
                       explicitGuide};
      // Outside instancing, the stage scene index names a prim by its USD path, and the filtering scene indices
      // that convert it keep that.
      if (copy.context.empty() && !prim.originPath.IsEmpty()) gprim.source = prim.originPath;
      gprims.push_back(std::move(gprim));
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
  auto plan =
      std::make_shared<Plan>(Plan{snapshot.time, context, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}});
  TfTokenVector viewport = settings.viewportPurposes;
  if (!Includes(viewport, UsdGeomTokens->guide)) viewport.push_back(UsdGeomTokens->guide);
  const PrimTable table = ReadPrims(snapshot);
  InstanceResolver instances(table, /*honorResets=*/true);
  const std::vector<DrawnGprim> gprims = DrawnGprims(table, instances);
  plan->diagnostics = instances.Diagnostics();
  // The Hydra prims with a projective copy: each is reported once, a repeated problem aggregated, at its first such
  // copy in source order, so the copies of a prim inside a prototype share one diagnostic, whose message counts them.
  // Each reported prim's diagnostic index in plan->diagnostics and how many copies it covers, and by prim, its entry.
  std::vector<std::pair<std::size_t, std::size_t>> projective;
  std::unordered_map<const PrimRecord*, std::size_t> projectivePrims;
  const GfMatrix4d correction = Correction(snapshot, settings, context);
  plan->copyWorlds.reserve(16 * gprims.size());
  // Each mesh's description, made for its first copy in source order, so its source is deterministic.
  std::unordered_map<const PrimRecord*, int> geometries;
  for (const DrawnGprim& gprim : gprims) {
    const bool inViewport = Includes(viewport, gprim.purpose);
    const bool inRender = Includes(settings.renderPurposes, gprim.purpose);
    // A guide shows only where it is explicitly visible, so one that isn't is never displayed.
    if ((!inViewport && !inRender) || (gprim.purpose == UsdGeomTokens->guide && !gprim.explicitGuide)) continue;
    plan->copyViewport.push_back(gprim.visible && inViewport);
    plan->copyRender.push_back(gprim.visible && inRender);
    // Bounds and instances inherit the correction through the world transform; local geometry is unchanged.
    const GfMatrix4d corrected = gprim.world * correction;
    if (corrected.GetColumn(3) != AffineColumn()) {
      const auto [found, added] = projectivePrims.try_emplace(gprim.prim, projective.size());
      if (added) {
        projective.emplace_back(plan->diagnostics.size(), 0);
        plan->diagnostics.push_back({DiagnosticCode::kProjectiveTransform, gprim.source, {}, {}, {}, {}});
      }
      ++projective[found->second].second;
    }
    const GfMatrix4d world = Affine(corrected);
    const bool sheared = Sheared(world);
    // Each copy has one object, and its source entity is its source path, an instance-proxy path inside instances.
    const std::size_t object = plan->resources.size();
    const std::size_t boundsMesh = object + 1;
    const std::size_t shearParent = object + 2;
    Partition partition{{object, boundsMesh}};
    std::vector<std::size_t> uses{boundsMesh};
    if (sheared) {
      partition.resources.push_back(shearParent);
      uses.push_back(shearParent);
    }
    plan->partitions.push_back(std::move(partition));
    plan->resources.push_back({Role::kObject, gprim.source, 0, {gprim.source}, std::move(uses)});
    plan->resources.push_back({Role::kBoundsMesh, gprim.source, 0, {gprim.source}, {}});
    if (sheared) plan->resources.push_back({Role::kShearParent, gprim.source, 0, {gprim.source}, {}});
    plan->correspondence.push_back({object, gprim.source, gprim.instanceContext});
    AppendWorld(world, plan->copyWorlds);
    int shear = -1;
    if (sheared) {
      shear = static_cast<int>(plan->shearParentWorlds.size() / 16);
      const auto [parentWorld, objectBasis] = ShearSplit(world);
      AppendWorld(parentWorld, plan->shearParentWorlds);
      AppendWorld(objectBasis, plan->shearObjectBases);
    }
    plan->copyShears.push_back(shear);
    plan->copyObjects.push_back(static_cast<int>(object));
    int geometry = -1;
    int placeholder = -1;
    if (gprim.mesh) {
      const auto [found, added] = geometries.try_emplace(gprim.mesh, static_cast<int>(plan->geometries.size()));
      if (added) {
        GeometryDescription description{gprim.source, {}, gprim.source.GetString()};
        if (gprim.bounds) AppendBounds(*gprim.bounds, description.extent);
        plan->geometries.push_back(std::move(description));
      }
      geometry = found->second;
    } else if (gprim.bounds) {
      placeholder = static_cast<int>(plan->placeholderBounds.size() / 6);
      AppendBounds(*gprim.bounds, plan->placeholderBounds);
    }
    plan->copyGeometries.push_back(geometry);
    plan->copyPlaceholders.push_back(placeholder);
  }
  for (const auto& [index, count] : projective) {
    plan->diagnostics[index].message =
        count == 1 ? "The world transform's projective part is dropped, so it is placed by its affine part"
                   : "The world transform's projective part is dropped, so its " + std::to_string(count) +
                         " drawn copies are placed by their affine part; the first in source order is named";
  }
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
