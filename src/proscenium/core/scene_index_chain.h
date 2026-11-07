// The Hydra scene-index chain over a binding's evaluation stage, and the capture of a snapshot from it
// (pipeline.md "Evaluated Source Snapshot"). M6 extends the chain and the capture.
#pragma once

#include <pxr/imaging/hd/sceneIndex.h>
#include <pxr/pxr.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usdImaging/usdImaging/sceneIndices.h>

#include "snapshot.h"
#include "stage_handle.h"

namespace proscenium {

class SceneIndexChain {
 public:
  // The stage arrives as a weak pointer, as StageHandle's does, and the chain's stage scene index holds its own
  // strong reference until Release(). Throws std::invalid_argument for an expired or null stage.
  explicit SceneIndexChain(const PXR_NS::UsdStagePtr& stage);
  ~SceneIndexChain();
  SceneIndexChain(const SceneIndexChain&) = delete;
  SceneIndexChain& operator=(const SceneIndexChain&) = delete;
  SceneIndexChain(SceneIndexChain&&) = delete;
  SceneIndexChain& operator=(SceneIndexChain&&) = delete;

  PXR_NS::UsdStagePtr Stage() const { return handle_.Stage(); }

  // Moves the chain to `time`, applies the stage's edits since the last capture, and copies what planning reads from
  // the terminal scene index into a new snapshot. Runs without the GIL. Throws std::runtime_error once released.
  SnapshotPtr Capture(PXR_NS::UsdTimeCode time);

  // Drops the chain and the handle's reference, so the core keeps no released stage alive. Idempotent.
  void Release();
  bool Released() const { return handle_.Released(); }

 private:
  StageHandle handle_;
  PXR_NS::UsdImagingSceneIndices indices_;
  PXR_NS::HdSceneIndexBaseRefPtr terminal_;  // the last in the chain, which captures read; null once released
};

}  // namespace proscenium
