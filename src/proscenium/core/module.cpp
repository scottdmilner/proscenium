// The compiled core's Python module, proscenium.core._core. It links only Blender's usd_ms.
//
// Each entry point translates errors as errors.h describes.
#include <pxr/base/tf/diagnostic.h>
#include <pxr/base/tf/errorMark.h>
#include <pxr/pxr.h>

#include <pxr/external/boost/python.hpp>
#include <string>

#include "errors.h"
#include "stage_handle.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace bp = pxr_boost::python;

namespace proscenium {
namespace {

// The OpenUSD release the module was compiled against, comparable with the host's pxr.Usd.GetVersion().
bp::tuple UsdVersion() { return bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION); }

// For tests of error translation only: posts a Tf runtime error, which the entry point raises.
void PostTfError(const std::string& message) {
  const TfErrorMark mark;
  TF_RUNTIME_ERROR("%s", message.c_str());
  RaiseTfErrors(mark);
}

// The stage, or None once it has expired.
bp::object HandleStage(const StageHandle& handle) {
  const UsdStagePtr stage = handle.Stage();
  return stage ? bp::object(stage) : bp::object();
}

}  // namespace
}  // namespace proscenium

PXR_BOOST_PYTHON_MODULE(_core) {
  using namespace proscenium;
  bp::def("usd_version", &UsdVersion);
  bp::def("_post_tf_error", &PostTfError);
  bp::class_<StageHandle, bp::noncopyable>("StageHandle", bp::init<UsdStagePtr>())
      .def("stage", &HandleStage)
      .def("release", &StageHandle::Release)
      .add_property("released", &StageHandle::Released);
}
