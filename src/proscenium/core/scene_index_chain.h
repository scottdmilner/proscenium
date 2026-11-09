// The Hydra scene-index chain over a binding's evaluation stage, and the capture of a snapshot from it
// (pipeline.md "Evaluated Source Snapshot"). M6 extends the chain and the capture.
#pragma once

#include <pxr/imaging/hd/sceneIndex.h>
#include <pxr/pxr.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usdImaging/usdImaging/sceneIndices.h>

#include "snapshot.h"
#include "source_info_scene_index.h"
#include "stage_handle.h"

namespace proscenium {

class SceneIndexChain {
 public:
  // The stage arrives as a weak pointer, as StageHandle's does, and the chain's stage scene index holds its own
  // strong reference until Release(). Throws std::invalid_argument for an expired or null stage. Tf errors posted
  // while building it raise; its warnings join the first capture's diagnostics.
  explicit SceneIndexChain(const PXR_NS::UsdStagePtr& stage);
  ~SceneIndexChain();
  SceneIndexChain(const SceneIndexChain&) = delete;
  SceneIndexChain& operator=(const SceneIndexChain&) = delete;
  SceneIndexChain(SceneIndexChain&&) = delete;
  SceneIndexChain& operator=(SceneIndexChain&&) = delete;

  PXR_NS::UsdStagePtr Stage() const { return handle_.Stage(); }

  // Moves the chain to `time`, applies the stage's edits since the last capture, and copies what planning reads from
  // the terminal scene index into a new snapshot, with the Tf errors and warnings posted meanwhile as its diagnostics.
  // Runs without the GIL, copying prims in parallel: the caller holds the GIL nowhere a worker waits, and makes no
  // stage edit meanwhile. Throws std::runtime_error once released.
  SnapshotPtr Capture(PXR_NS::UsdTimeCode time);

  // Drops the chain and the handle's reference, so the core keeps no released stage alive. Idempotent.
  void Release();
  bool Released() const { return handle_.Released(); }

 private:
  void Build();  // the chain's scene indices, over the handle's stage

  StageHandle handle_;
  PXR_NS::UsdImagingSceneIndices indices_;
  SourceInfoSceneIndexRefPtr sourceInfo_;    // right after the stage scene index; null once released
  PXR_NS::HdSceneIndexBaseRefPtr terminal_;  // the last in the chain, which captures read; null once released
  Diagnostics pending_;  // warnings posted while building the chain, until the first capture takes them
};

}  // namespace proscenium
