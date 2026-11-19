#include "layer_copies.h"

#include <pxr/base/tf/pathUtils.h>
#include <pxr/usd/sdf/layerUtils.h>
#include <pxr/usd/usdUtils/dependencies.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

WriteTable CopyLayer(const SdfLayerHandle& source, const SdfLayerHandle& destination) {
  destination->TransferContent(source);
  WriteTable anchored;
  if (source->IsAnonymous()) return anchored;
  UsdUtilsModifyAssetPaths(
      destination,
      [&](const std::string& authored) {
        if (authored.empty() || !TfIsRelativePath(authored)) return authored;
        // The resolver's own anchoring, as composition anchors the path to source: a bare path stays as authored when
        // no file beside source has its name, and an anonymous identifier or another resolver's stays as authored.
        std::string path = SdfComputeAssetPathRelativeToLayer(source, authored);
        if (path != authored) anchored.emplace(path, authored);
        return path;
      },
      /*keepEmptyPathsInArrays=*/true);
  return anchored;
}

}  // namespace proscenium
