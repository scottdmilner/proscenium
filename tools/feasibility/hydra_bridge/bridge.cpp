// Feasibility probe only: consume Blender's USD, never link a second USD build.
#include <pxr/pxr.h>
#include <pxr/external/boost/python.hpp>
#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/pyError.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usdImaging/usdImaging/sceneIndices.h>
#include <pxr/usdImaging/usdImaging/stageSceneIndex.h>
#include <pxr/imaging/hd/meshSchema.h>
#include <pxr/imaging/hd/primvarsSchema.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/sceneIndexObserver.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/xformSchema.h>
#include <pxr/imaging/hd/visibilitySchema.h>
#include <pxr/imaging/hdsi/implicitSurfaceSceneIndex.h>

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#include <psapi.h>
#elif defined(__APPLE__)
#include <dlfcn.h>
#include <mach-o/dyld.h>
#else
#include <dlfcn.h>
#include <link.h>
#endif

PXR_NAMESPACE_USING_DIRECTIVE
namespace bp = pxr_boost::python;

#define HYDRA_BRIDGE_STR2(x) #x
#define HYDRA_BRIDGE_STR(x) HYDRA_BRIDGE_STR2(x)

namespace {

// Modules defined with PXR_BOOST_PYTHON_MODULE don't get USD's automatic error
// conversion, so every entry point raises Tf errors posted during its call.
void RaiseTfErrors(const TfErrorMark &mark) {
    if (!mark.IsClean() && TfPyConvertTfErrorsToPythonException(mark)) bp::throw_error_already_set();
}

class Observer final : public HdSceneIndexObserver {
public:
    std::vector<std::pair<std::string, std::string>> events;

    void PrimsAdded(const HdSceneIndexBase &, const AddedPrimEntries &entries) override {
        for (const auto &entry : entries) events.emplace_back("added", entry.primPath.GetString());
    }
    void PrimsRemoved(const HdSceneIndexBase &, const RemovedPrimEntries &entries) override {
        for (const auto &entry : entries) events.emplace_back("removed", entry.primPath.GetString());
    }
    void PrimsDirtied(const HdSceneIndexBase &, const DirtiedPrimEntries &entries) override {
        for (const auto &entry : entries) events.emplace_back("dirtied", entry.primPath.GetString());
    }
    void PrimsRenamed(const HdSceneIndexBase &, const RenamedPrimEntries &entries) override {
        for (const auto &entry : entries) events.emplace_back("renamed", entry.newPrimPath.GetString());
    }
};

class Bridge {
public:
    explicit Bridge(const UsdStageRefPtr &stage) : stage_(stage) {
        TfErrorMark mark;
        if (!stage) throw std::invalid_argument("Expected a valid USD stage");
        UsdImagingCreateSceneIndicesInfo info;
        info.stage = stage;
        info.addDrawModeSceneIndex = false;
        // The chain already flattens inherited state at every instancing level.
        indices_ = UsdImagingCreateSceneIndices(info);
        auto mode = HdRetainedTypedSampledDataSource<TfToken>::New(HdsiImplicitSurfaceSceneIndexTokens->toMesh);
        terminal_ = HdsiImplicitSurfaceSceneIndex::New(
            indices_.finalSceneIndex,
            HdRetainedContainerDataSource::New(HdPrimTypeTokens->cube, mode, HdPrimTypeTokens->sphere, mode));
        terminal_->AddObserver(HdSceneIndexObserverPtr(&observer_));
        RaiseTfErrors(mark);
    }

    ~Bridge() { Release(); }

    // Weak: the caller owns the stage. None once it has expired.
    bp::object Stage() const { return stage_ ? bp::object(stage_) : bp::object(); }

    // The stage scene index holds a strong stage reference; drop the chain so a
    // caller-released stage can expire.
    void Release() {
        if (!terminal_) return;
        terminal_->RemoveObserver(HdSceneIndexObserverPtr(&observer_));
        indices_.stageSceneIndex->SetStage(nullptr);
        terminal_.Reset();
        indices_ = UsdImagingSceneIndices();
    }

    bp::dict Snapshot(bp::object time) {
        TfErrorMark mark;
        if (!terminal_) throw std::runtime_error("Bridge has been released");
        observer_.events.clear();
        indices_.stageSceneIndex->ApplyPendingUpdates();
        indices_.stageSceneIndex->SetTime(
            time.is_none() ? UsdTimeCode::Default() : UsdTimeCode(bp::extract<double>(time)));
        bp::dict prims;
        std::vector<SdfPath> pending{SdfPath::AbsoluteRootPath()};
        while (!pending.empty()) {
            auto path = pending.back();
            pending.pop_back();
            auto children = terminal_->GetChildPrimPaths(path);
            pending.insert(pending.end(), children.begin(), children.end());
            auto prim = terminal_->GetPrim(path);
            if (!prim.dataSource) continue;
            bp::dict record;
            record["type"] = prim.primType.GetString();
            auto mesh = HdMeshSchema::GetFromParent(prim.dataSource);
            if (mesh) {
                auto topology = mesh.GetTopology();
                if (auto counts = topology.GetFaceVertexCounts()) record["counts"] = counts->GetTypedValue(0);
                if (auto vertices = topology.GetFaceVertexIndices()) record["indices"] = vertices->GetTypedValue(0);
            }
            auto primvars = HdPrimvarsSchema::GetFromParent(prim.dataSource);
            if (auto points = primvars.GetPrimvar(HdTokens->points).GetPrimvarValue())
                record["points"] = points->GetValue(0);
            auto xform = HdXformSchema::GetFromParent(prim.dataSource);
            if (auto matrix = xform.GetMatrix()) record["matrix"] = matrix->GetTypedValue(0);
            auto visibility = HdVisibilitySchema::GetFromParent(prim.dataSource);
            if (auto visible = visibility.GetVisibility()) record["visible"] = visible->GetTypedValue(0);
            prims[path.GetString()] = record;
        }
        bp::list events;
        for (const auto &[kind, path] : observer_.events) events.append(bp::make_tuple(kind, path));
        bp::dict result;
        result["prims"] = prims;
        result["events"] = events;
        RaiseTfErrors(mark);
        return result;
    }

private:
    UsdStagePtr stage_;
    UsdImagingSceneIndices indices_;
    HdSceneIndexBaseRefPtr terminal_;
    Observer observer_;
};

// Any loaded image named like a USD library: usd_ms (Blender's monolithic build) or a
// per-library usd_* build, such as a pip usd-core would bring.
bool IsUsdLibrary(std::string path) {
    auto slash = path.find_last_of("/\\");
    std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
    if (name.rfind("lib", 0) == 0) name = name.substr(3);
    if (name.rfind("usd_", 0) != 0) return false;
    return name.find(".so") != std::string::npos || name.find(".dylib") != std::string::npos ||
           name.find(".dll") != std::string::npos;
}

#if defined(_WIN32)
std::string Utf8(const wchar_t *text) {
    int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    std::string result(size > 0 ? size - 1 : 0, '\0');
    if (size > 1) WideCharToMultiByte(CP_UTF8, 0, text, -1, result.data(), size, nullptr, nullptr);
    return result;
}

std::string ModulePath(HMODULE module) {
    std::wstring buffer(32768, L'\0');
    DWORD length = GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
    buffer.resize(length);
    return Utf8(buffer.c_str());
}
#elif !defined(__APPLE__)
int CollectImage(dl_phdr_info *info, size_t, void *data) {
    if (info->dlpi_name && *info->dlpi_name) static_cast<std::vector<std::string> *>(data)->push_back(info->dlpi_name);
    return 0;
}
#endif

std::vector<std::string> LoadedImages() {
    std::vector<std::string> images;
#if defined(_WIN32)
    std::vector<HMODULE> modules(1024);
    DWORD needed = 0;
    HANDLE process = GetCurrentProcess();
    while (EnumProcessModules(process, modules.data(), static_cast<DWORD>(modules.size() * sizeof(HMODULE)),
                              &needed) &&
           needed > modules.size() * sizeof(HMODULE))
        modules.resize(needed / sizeof(HMODULE));
    modules.resize(std::min<size_t>(modules.size(), needed / sizeof(HMODULE)));
    for (HMODULE module : modules) images.push_back(ModulePath(module));
#elif defined(__APPLE__)
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) images.emplace_back(_dyld_get_image_name(i));
#else
    dl_iterate_phdr(CollectImage, &images);
#endif
    return images;
}

bp::list LoadedUsdLibraries() {
    bp::list result;
    for (const auto &path : LoadedImages())
        if (IsUsdLibrary(path)) result.append(path);
    return result;
}

// The image that actually provides USD imaging code to this module, as the loader bound it.
std::string UsdProvidingLibrary() {
    using Create = UsdImagingSceneIndices (*)(const UsdImagingCreateSceneIndicesInfo &);
    const void *address = reinterpret_cast<const void *>(static_cast<Create>(&UsdImagingCreateSceneIndices));
#if defined(_WIN32)
    HMODULE module = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            static_cast<LPCWSTR>(address), &module))
        throw std::runtime_error("GetModuleHandleExW failed for a USD symbol");
    return ModulePath(module);
#else
    Dl_info info{};
    if (!dladdr(address, &info) || !info.dli_fname) throw std::runtime_error("dladdr failed for a USD symbol");
    return info.dli_fname;
#endif
}

}  // namespace

PXR_BOOST_PYTHON_MODULE(_hydra_bridge) {
    bp::class_<Bridge, bp::noncopyable>("Bridge", bp::init<UsdStageRefPtr>())
        .def("stage", &Bridge::Stage)
        .def("snapshot", &Bridge::Snapshot)
        .def("release", &Bridge::Release);
    bp::def("loaded_usd_libraries", LoadedUsdLibraries);
    bp::def("usd_providing_library", UsdProvidingLibrary);
    bp::scope().attr("usd_version") = bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION);
    bp::scope().attr("usd_namespace") = HYDRA_BRIDGE_STR(PXR_INTERNAL_NS);
}
