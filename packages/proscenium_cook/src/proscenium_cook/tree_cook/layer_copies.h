// Copies of layers the tree reads: a New Layer Zone's start from its Template, and, from step 19 of the plan, a
// Substitution Zone's copies. A relative asset path in a layer is relative to its file, so a copy anchors each one to
// that file, and its write table records it, so Write can make it relative to the file it writes (docs/phase3/
// node-tree.md "New Layer Zone" and "Provenance").
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/sdf/layer.h>

#include <map>
#include <string>

namespace proscenium {

// A zone layer's write table: each asset path Write changes, by the string the layer holds, mapped to the path as its
// source authored it. Each so far is a path a copy anchored, which Write makes relative to the file it writes. One
// anchored string that two authored paths share keeps the first that the anchoring pass meets. The table is keyed by
// string, as UsdUtilsModifyAssetPaths maps paths, so an absolute path the source authors as the very string a relative
// one anchors to is written relative too: both name one file, and the written set still resolves it.
using WriteTable = std::map<std::string, std::string>;

// Replaces destination's content with source's, through TransferContent, then makes each relative asset path absolute,
// anchored to source's file, in one UsdUtilsModifyAssetPaths pass. An absolute path, an anonymous layer's identifier,
// and a resolver's identifier stay as authored, and so does a bare path such as prop.usda when no file beside source
// has that name, since a resolver's search paths may find it. An anonymous source has no file, so nothing is anchored.
// Returns the paths anchored.
WriteTable CopyLayer(const PXR_NS::SdfLayerHandle& source, const PXR_NS::SdfLayerHandle& destination);

}  // namespace proscenium
