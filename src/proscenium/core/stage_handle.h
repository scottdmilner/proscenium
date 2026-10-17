// The core's reference to a stage it was given (AGENTS.md "Compiled core": the core never keeps a released
// stage alive).
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/usd/stage.h>

namespace proscenium {

class StageHandle {
 public:
  // The stage arrives as a weak pointer and the handle adds its own reference. Tf's Python converter for a
  // TfRefPtr argument moves ownership out of the caller's Python object (pxr/base/tf/pyPtrHelpers.h), so taking
  // one would let the handle's release destroy a stage its caller still holds (runtime-record.md, M1b Phase C).
  // Throws std::invalid_argument for an expired or null stage.
  explicit StageHandle(const PXR_NS::UsdStagePtr& stage);

  // The stage while it exists: held by the handle until Release(), then only while someone else holds it.
  PXR_NS::UsdStagePtr Stage() const { return stage_; }

  // Drops the handle's reference, so the stage expires once its other holders drop theirs. Idempotent.
  void Release() { held_.Reset(); }
  bool Released() const { return !held_; }

 private:
  PXR_NS::UsdStagePtr stage_;
  PXR_NS::UsdStageRefPtr held_;
};

}  // namespace proscenium
