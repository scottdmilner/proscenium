// The compiled core's Python module, proscenium.core._core. It links only Blender's usd_ms.
#include <pxr/pxr.h>
#include <pxr/external/boost/python.hpp>

namespace bp = PXR_NS::pxr_boost::python;

namespace {

// The OpenUSD release the module was compiled against, comparable with the host's pxr.Usd.GetVersion().
bp::tuple UsdVersion() { return bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION); }

}  // namespace

PXR_BOOST_PYTHON_MODULE(_core) { bp::def("usd_version", &UsdVersion); }
