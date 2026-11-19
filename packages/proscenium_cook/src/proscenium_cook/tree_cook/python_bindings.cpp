// The cook's Python module, proscenium_cook.tree_cook._cook. It links only Blender's usd_ms.
#include <pxr/pxr.h>

#include <pxr/external/boost/python.hpp>

PXR_NAMESPACE_USING_DIRECTIVE

namespace bp = pxr_boost::python;

namespace proscenium {
namespace {

// The OpenUSD release the module was compiled against, comparable with the host's pxr.Usd.GetVersion().
bp::tuple UsdVersion() { return bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION); }

}  // namespace
}  // namespace proscenium

PXR_BOOST_PYTHON_MODULE(_cook) {
  using namespace proscenium;
  bp::def("usd_version", &UsdVersion);
}
