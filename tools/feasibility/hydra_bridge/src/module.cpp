// Feasibility probe only: consume Blender's USD, never link a second USD build.
#include "bridge.h"
#include "diagnostics.h"
#include "fact_timings.h"
#include "loaded_images.h"
#include "python_views.h"

#include <pxr/pxr.h>
#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/pyLock.h>
#include <pxr/external/boost/python.hpp>
#include <pxr/usd/usd/timeCode.h>

PXR_NAMESPACE_USING_DIRECTIVE

// Only the preprocessor can turn a macro's value into a string literal.
// NOLINTBEGIN(cppcoreguidelines-macro-usage)
#define HYDRA_BRIDGE_STR2(x) #x
#define HYDRA_BRIDGE_STR(x) HYDRA_BRIDGE_STR2(x)
// NOLINTEND(cppcoreguidelines-macro-usage)

namespace hydra_bridge {
namespace {

bp::object Stage(const Bridge &bridge) {
    const UsdStagePtr stage = bridge.Stage();
    return stage ? bp::object(stage) : bp::object();
}

// None (or no argument) is default time; numbers and Usd.TimeCode convert through Usd's own converter.
UsdTimeCode ToTimeCode(const bp::object &time) {
    if (time.is_none()) return UsdTimeCode::Default();
    const bp::extract<UsdTimeCode> code(time);
    if (!code.check()) {
        PyErr_SetString(PyExc_TypeError, "time must be None, a number, or a Usd.TimeCode");
        bp::throw_error_already_set();
    }
    return code();
}

// SetTime, ApplyPendingUpdates, and the parallel read pass run without the GIL.
SnapshotView Capture(Bridge &bridge, const bp::object &time, bool incremental) {
    const TfErrorMark mark;
    const UsdTimeCode code = ToTimeCode(time);
    SnapshotPtr snapshot;
    {
        TF_PY_ALLOW_THREADS_IN_SCOPE();
        snapshot = bridge.Capture(code, incremental);
    }
    RaiseTfErrors(mark);
    return SnapshotView{snapshot};
}

// Phase E: the source-info filter's USD reads since the last call, as {kind: (calls, seconds)}.
bp::dict TakeFilterTimings() {
    bp::dict result;
    for (const auto &[name, calls, seconds] : TakeFactTimings()) result[name] = bp::make_tuple(calls, seconds);
    return result;
}

template <class T>
bp::list ToList(const std::vector<T> &values) {
    bp::list result;
    for (const T &value : values) result.append(value);
    return result;
}

}  // namespace
}  // namespace hydra_bridge

PXR_BOOST_PYTHON_MODULE(_hydra_bridge) {
    using namespace hydra_bridge;
    bp::class_<Bridge, bp::noncopyable>("Bridge", bp::init<UsdStagePtr>())
        .def("stage", &Stage)
        .def("capture", &Capture, (bp::arg("time") = bp::object(), bp::arg("incremental") = false))
        .def("release", &Bridge::Release);
    WrapViews();
    bp::def("take_filter_timings", &TakeFilterTimings);
    bp::def("loaded_usd_libraries", +[]() { return ToList(LoadedUsdLibraries()); });
    bp::def("usd_providing_library", &UsdProvidingLibrary);
    bp::scope().attr("usd_version") = bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION);
    bp::scope().attr("usd_namespace") = HYDRA_BRIDGE_STR(PXR_INTERNAL_NS);
}
