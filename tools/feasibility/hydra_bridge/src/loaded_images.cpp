#include "loaded_images.h"

#include <pxr/usdImaging/usdImaging/sceneIndices.h>

#include <algorithm>
#include <cctype>
#include <stdexcept>

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

namespace hydra_bridge {

namespace {

// Any image named like a USD library: usd_ms (Blender's monolithic build) or a per-library
// usd_* build, such as a pip usd-core would bring.
bool IsUsdLibrary(const std::string &path) {
    const auto slash = path.find_last_of("/\\");
    std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
    if (name.rfind("lib", 0) == 0) name = name.substr(3);
    if (name.rfind("usd_", 0) != 0) return false;
    return name.find(".so") != std::string::npos || name.find(".dylib") != std::string::npos ||
           name.find(".dll") != std::string::npos;
}

#if defined(_WIN32)
std::string Utf8(const wchar_t *text) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    std::string result(size > 0 ? size - 1 : 0, '\0');
    if (size > 1) WideCharToMultiByte(CP_UTF8, 0, text, -1, result.data(), size, nullptr, nullptr);
    return result;
}

std::string ModulePath(HMODULE module) {
    std::wstring buffer(32768, L'\0');
    const DWORD length = GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
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

}  // namespace

std::vector<std::string> LoadedUsdLibraries() {
    std::vector<std::string> result;
    for (const auto &path : LoadedImages())
        if (IsUsdLibrary(path)) result.push_back(path);
    return result;
}

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

}  // namespace hydra_bridge
