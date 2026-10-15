# 04 — Native build, distribution, and the C++/Python boundary

Research date: 2026-10-09. Scope: extending the macOS arm64 Hydra bridge
(`tools/feasibility/hydra_bridge/`) to Windows x64 and Linux x64, and the boundary questions
a production C++ core would face. **Nothing was built or run on Windows or Linux.** The
Windows/Linux findings come from static inspection of the shipped Blender 5.2.2 binaries
and the pinned dependency repos, plus the Blender and OpenUSD sources. Treat them as
predictions for CI to confirm, not as qualification.

Labels: **[path:line]** = source read in this session (paths are relative to the clones
listed below). **[URL]** = documentation fetched. **[measured]** = command run in this
session, with its output reported. **[inferred]** = reasoning, not checked.

Sources used (local shallow or sparse checkouts unless noted):

- `blender-v5.2.2/`: sparse checkout of Blender tag `v5.2.2` (`build_files/`, `source/creator`, `source/blender/python/intern`, `source/blender/io/usd`, `source/blender/render/hydra`, `lib/` submodule pointers).
- `lib-linux_x64`, `lib-windows_x64`, `lib-macos_arm64`: blobless, treeless-checkout fetches of the pinned precompiled-library revisions. File lists come from `git ls-tree`; only small files were fetched.
- `usd-v26.03/`: OpenUSD v26.03.
- Wheel and zip members pulled by HTTP range requests (`rzip.py`) from the PyPI `bpy-5.2.2` wheels (`manylinux_2_28_x86_64`, `win_amd64`) and from `blender-5.2.2-windows-x64.zip`.
- `hdusd/`: GPUOpen `BlenderUSDHydraAddon` at HEAD (`3128c2f`, 2023-11-15).
- Local: `/Applications/Blender.app` (5.2.2) and the project's `.venv` bpy wheel (macOS).

---

## 0. Headline findings

1. **Windows and Linux ship everything needed to link, and their loaders should resolve the module against Blender's already-loaded USD the same way macOS does.**
   - Windows: `usd_ms.dll` plus import library `usd_ms.lib`, headers, `tbb12.lib`, and `python313.lib` are all in `lib-windows_x64` at the v5.2.2 pin.
   - Linux: `libusd_ms.so` has SONAME `libusd_ms.so`, `RUNPATH $ORIGIN`, and the new libstdc++ ABI. It was built with GCC 14.2.1 (gcc-toolset-14) on Rocky 8, with glibc 2.28 as the floor.
   - `blender.exe` and the wheel's `bpy/__init__.pyd` both import `usd_ms.dll` directly. Blender's own `pxr/*.pyd` sit in a directory without `usd_ms.dll` and add no DLL directory for it, so they can only be resolving it through the loaded-module list. Our `.pyd` would rely on the same mechanism.
2. **Two defects in the current macOS bridge would block distribution.**
   - It was built with `minos 26.0`, but Blender 5.2's floor is `11.2` **[measured]**, so it would not load on older macOS.
   - It omits `PXR_BOOST_PYTHON_NO_PY_SIGNATURES`, which Blender's exported `pxrTargets.cmake` puts on the Python target's interface **[lib-windows_x64 usd/cmake/pxrTargets.cmake:74]**.
3. **Zero-copy transfer works today with no numpy and no custom buffer type** **[measured]**:
   - The plan exposes `VtArray<T>` objects. Their buffer protocol is O(1) and holds a reference-counted `VtArray` copy, not an element copy.
   - Python flattens the 2-D view with `memoryview(a).cast('B').cast('f')`, also with no copy.
   - Python passes the flat view to `Attribute.data.foreach_set('vector', ...)`.
   - For 1M points: 0.22 ms on the attribute path, about the cost of one memcpy. `mesh.vertices.foreach_set('co', ...)` takes 31.5 ms. A 2-D view or the raw `Vt.Vec3fArray` is **rejected** with "Array length mismatch".
4. **Distribution blocker: extensions.blender.org's Terms of Service §3.6** (last updated 10 Aug 2026) reads: *"Source code of the extension must be fully written in Python. Depending on external, pre-compiled packages is not allowed."* **[https://extensions.blender.org/terms-of-service/]**
   - A C++ core can still ship through GitHub releases, a self-hosted extension repository, or install-from-disk.
   - It cannot be listed on the official platform as the rules are worded.
   - M1b should record this.
5. **Version risk is bounded and confirmed.**
   - The USD binary and headers are byte-identical (same git blob) across 5.2.0 → 5.2.2 on macOS and Linux.
   - Blender 5.3 (`blender-v5.3-release`, currently beta) and `main` (5.4 alpha) move to **USD 26.08**, which gives a new namespace `pxrBlender_v26_08`.
   - Set `blender_version_max = "5.3.0"` (exclusive) and plan a rebuild per Blender minor release.

---

## 1. Windows x64 and Linux x64 linking

### 1.1 How Blender 5.2 builds USD (all platforms)

From `build_files/build_environment/cmake/usd.cmake` at v5.2.2:

- **Monolithic shared build, Python on, imaging on.** Options set: `-DPXR_BUILD_MONOLITHIC=ON`, `-DBUILD_SHARED_LIBS=ON`, `-DPXR_ENABLE_PYTHON_SUPPORT=ON`, `-DPXR_BUILD_IMAGING=ON`, MaterialX and OpenVDB on, OSL/HDF5/Ptex/usdview/tools off, GL on, Vulkan on everywhere except Apple **[usd.cmake:56-58, 63-102]**.
- **Custom namespace:** `string(REPLACE "." "_" USD_NAMESPACE "pxrBlender_v${USD_VERSION}")` → `-DPXR_SET_INTERNAL_NAMESPACE`. The comment gives the reason: *"to prevent conflicts when importing both bpy module and usd-core pip packages"* **[usd.cmake:60-62, 69]**. In the generated header: `#define PXR_INTERNAL_NS pxrBlender_v26_03__pxrReserved__`, `PXR_PYTHON_SUPPORT_ENABLED`, `PXR_PREFER_SAFETY_OVER_SPEED` **[lib-windows_x64 usd/include/pxr/pxr.h:16-56]**.
- **Versions:** USD 26.03, TBB v2022.3.0, Python 3.13.13, MaterialX 1.39.4 **[cmake/versions.cmake:381, 410, 851, 868]**.
- **No Boost.** `usd_noboost.diff` removes `find_package(Boost)` **[patches/usd_noboost.diff]**. USD 26.03 uses its internal `pxr_boost::python`.
- **Patches that matter to consumers:**
  - `usd_ctor.diff` renames USD's static-constructor sections from `pxrctor`/`pxrdtor` to `pxbctor`/`pxbdtor` in `pxr/base/arch/attributes.{h,cpp}` **[patches/usd_ctor.diff]**. **Consequence: consumers must compile against Blender's patched headers.** With stock v26.03 headers, `ARCH_CONSTRUCTOR` registrations (TF_REGISTRY_FUNCTION, etc.) would be emitted into sections that Blender's `libusd_ms` never scans on macOS and Windows **[inferred]**. Stock headers would also carry the wrong namespace and fail to link anyway.
  - `usd_a609a89….diff` makes Tf's Python exception class a leaked `TfStaticData` so shutdown avoids refcount operations **[patches/usd_a609a89a750f1c70f5bfd61bb418d5a09eaa6585.diff]**.
  - `usd_5744a98….diff` touches `pxr_boost::python` `function.cpp`/`pickle_support.cpp`. These are internal; consumers are unaffected **[inferred]**.
- **Python linkage on Unix:** USD is configured with `PYTHON_LIBRARY` pointed at **libtbb** *"so it doesn't complain"*, to avoid embedding a static Python. Python symbols are left undefined, and macOS adds `-undefined dynamic_lookup` **[usd.cmake:27-46]**. `libusd_ms.so` has 170 undefined `Py*` symbols and no `libpython` NEEDED entry **[measured: llvm-nm/llvm-readelf on the wheel's libusd_ms.so]**.

### 1.2 What ships where (v5.2.2)

| | macOS arm64 | Linux x64 | Windows x64 |
|---|---|---|---|
| Binary install | `Blender.app/Contents/Resources/lib/libusd_ms.dylib` [measured] | `<root>/lib/libusd_ms.so` (portable `TARGETDIR_LIB "lib"`) [source/creator/CMakeLists.txt:394-397] | `blender.shared/usd_ms.dll` [measured: zip listing]; listed in `blender.shared.manifest` (an SxS assembly) [measured] |
| bpy wheel | `bpy/lib/libusd_ms.dylib` [measured] | `bpy/lib/libusd_ms.so` (78.7 MB) [measured] | `bpy/usd_ms.dll` next to `bpy/__init__.pyd` [measured]; the source says *"Important the DLL's are next to `__init__.pyd` otherwise it won't load"* [source/creator/CMakeLists.txt:410-413] |
| Python `pxr` | `…/5.2/python/lib/python3.13/site-packages/pxr` | same layout; `_tf.so` RUNPATH `$ORIGIN/../../../../../../../lib` [measured] | `5.2/python/lib/site-packages/pxr/Tf/_tf.pyd`, which imports `usd_ms.dll` and `python313.dll` [measured] |
| Pinned lib repo | `lib-macos_arm64@a76ef917` | `lib-linux_x64@ecbd06cf` | `lib-windows_x64@60d6e96b` [blender-v5.2.2 `git ls-tree HEAD lib/`] |
| Link artifact in lib repo | `usd/lib/libusd_ms.dylib` | `usd/lib/libusd_ms.so` (unversioned) | `usd/lib/usd_ms.lib` (import lib), `usd_ms.dll`, `usd_ms_d.{dll,lib}` |
| Headers in lib repo | `usd/include` | `usd/include` (2069 files) | `usd/include` (`pxr.h` present) |
| TBB | `tbb/include`, `libtbb.dylib` | `tbb/lib/libtbb.so.12` | `tbb/lib/tbb12.lib`, `tbb/bin/tbb12.dll` |
| Python | `python/include/python3.13` | `python/include/python3.13` | `python/313/include`, `python/313/libs/python313.lib` |
| CMake package | not harvested | not harvested | `usd/pxrConfig.cmake`, `usd/cmake/pxrTargets*.cmake` (Windows harvest copies the whole tree) [usd.cmake:204-210] |

Notes:

- The **wheel's Windows package has no `.lib` and no headers.** The import library must come from `lib-windows_x64` **[measured: wheel listing]**.
- The shipped binaries are **not byte-identical to the lib-repo blobs** (git blob hashes differ for the wheel's `libusd_ms.so` and `usd_ms.dll`) **[measured]**. That is expected, since stripping, rpath edits, and signing change bytes. Linking needs only matching exports, but the record should not claim identity.
- `blender.exe` imports `usd_ms.dll`, `tbb12.dll`, `tbbmalloc_proxy.dll`, and `python313.dll` directly **[measured: llvm-objdump -p on blender.exe from the 5.2.2 zip]**. The wheel's `bpy/__init__.pyd` imports `usd_ms.dll`, `tbb12.dll`, and `python313.dll` **[measured]**. **USD is therefore always loaded before any extension code runs**, in both hosts.
- Exports exist for the APIs the bridge uses:
  - Windows `usd_ms.dll` exports 22,888 `pxrBlender` symbols, including `HdFlatteningSceneIndex` members, `UsdImagingCreateSceneIndices`, `TfPyConvertTfErrorsToPythonException`, and `pxr_boost::python::converter::registry::lookup` **[measured: llvm-objdump -p]**.
  - Linux exports 104,649 dynamic symbols with the same functions **[measured: llvm-nm -D]**.

### 1.3 Compiler / ABI constraints

**Windows (MSVC)**

- Blender compiles with `/MD` (release dynamic CRT) **[platform_win32.cmake:282-287]** and bundles an app-local CRT in `blender.crt/` (msvcp140, vcruntime140, vcruntime140_1) **[platform_win32.cmake:180; measured: zip listing]**.
- `usd_ms.dll` and `_tf.pyd` show linker version **14.44** (VS 2022 17.14). They import `MSVCP140.dll`/`VCRUNTIME140*.dll`, not the `D` debug variants **[measured]**, so `_ITERATOR_DEBUG_LEVEL=0` (the release default). Our build must use the Release or RelWithDebInfo configuration, never Debug, because Debug selects `/MDd` and `_ITERATOR_DEBUG_LEVEL=2`, which changes STL layouts.
- **Toolset pin.** Microsoft's v14x binary-compatibility rule says the CRT loaded at run time must be at least as new as the newest toolset that built any linked binary **[inferred from MS binary-compat docs, not fetched this session]**. Inside `blender.exe` the CRT is Blender's app-local copy from VS 17.14. **Build with toolset ≤ 14.44**, for example `vcvarsall.bat x64 -vcvars_ver=14.44` or the CMake `-T v143,version=14.44`. A newer runner toolset (VS 2026, 14.5x) risks missing-entry-point failures in the binary host.
- USD's MSVC flags that consumers should mirror: `/permissive- /Zc:inline /Zc:__cplusplus /bigobj /EHsc`, and the defines `NOMINMAX WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS` **[usd-v26.03 cmake/defaults/msvcdefaults.cmake:12-117]**. Blender's patch removes `/Zi` only **[patches/usd.diff:1-12]**.
- **TBB auto-link.** oneTBB headers emit `#pragma comment(lib, "tbb12.lib")` under MSVC unless `__TBB_NO_IMPLICIT_LINKAGE` is set **[tbb/include/oneapi/tbb/detail/_config.h:357-364]**. Add `${deps}/tbb/lib` to the link directories, or link `tbb12.lib` explicitly. Never define `_DEBUG`, which selects `tbb12_debug.lib`.
- **Interface define.** Define `PXR_BOOST_PYTHON_NO_PY_SIGNATURES`, which is on the Python target's interface **[pxrTargets.cmake:74; usd-v26.03 pxr/external/boost/python/CMakeLists.txt:327]**. `signature_element` keeps the same layout either way **[usd-v26.03 pxr/external/boost/python/detail/signature.hpp:30-35]**, so omitting it is probably benign. Matching the exported interface is still the safe choice **[inferred]**.
- **No export macros.** Do **not** define `PXR_STATIC` or any `*_EXPORTS`. The `*_API` macros then resolve to `dllimport`, which exported data such as `HdTokens` requires **[inferred from USD api.h conventions]**.

**Linux (GCC)**

- Built on Rocky 8 with `gcc-toolset-14` **[build_environment/linux/linux_rocky8_setup.sh:39]**. Blender's library dir is the "glibc 2.28 ABI" set **[platform_unix.cmake:13-17]**. The `.comment` section of `libusd_ms.so` reads `GCC: (GNU) 14.2.1 20250110 (Red Hat 14.2.1-11)`. Its maximum symbol versions are `GLIBC_2.27` and `GLIBCXX_3.4.22` **[measured]**: the devtoolset model links newer libstdc++ pieces statically, so the binary needs only the system's `libstdc++.so.6`.
- **`_GLIBCXX_USE_CXX11_ABI=1`.** There are 4,907 exported `__cxx11` symbols **[measured]**. Keep the compiler default and never force `0`.
- **Build in `quay.io/pypa/manylinux_2_28_x86_64`** (AlmaLinux 8, GCC 14 toolchain **[https://github.com/pypa/manylinux]**). This reproduces Blender's floor. Building on `ubuntu-latest` (glibc 2.39) would raise the required GLIBC/GLIBCXX versions above what Blender supports **[inferred]**. Check with `objdump -T | grep GLIBC_` in CI.
- **Python symbols:** Blender's executable statically links Python and exports `Py*`/`_Py*` through its version script **[source/creator/symbols_unix.map; platform_unix.cmake:1041-1042]**. The module must **not** link `libpython`. `Python_add_library(... MODULE)` with `Development.Module` already behaves this way.
- **Visibility:** compile our module with `-fvisibility=hidden -fvisibility-inlines-hidden`, so only `PyInit_*` is exported and none of our symbols interpose on other extensions **[inferred]**. Cross-module type identity still works:
  - pxr_boost compares `typeid(x).name()` strings under GCC/Clang (`PXR_BOOST_PYTHON_TYPE_ID_NAME`) **[usd-v26.03 pxr/external/boost/python/type_id.hpp:33-42]**.
  - `TfType` falls back from `type_info*` to `type_info::name()` lookup **[usd-v26.03 pxr/base/tf/typeInfoMap.h:68-94]**.

**macOS (already working, but two fixes needed)**

- Set `CMAKE_OSX_DEPLOYMENT_TARGET=11.2`. `libusd_ms.dylib` and Blender have `minos 11.2`, while the current bridge has `minos 26.0` **[measured: otool -l LC_BUILD_VERSION]**.
- Add `PXR_BOOST_PYTHON_NO_PY_SIGNATURES` (see Windows).

### 1.4 How the module finds the already-loaded USD

| Platform | Mechanism | Evidence |
|---|---|---|
| macOS | Load command `@rpath/libusd_ms.dylib`, no LC_RPATH. dyld matches the install name `@rpath/libusd_ms.dylib` of the image the host already loaded. | Bridge passes in both hosts [runtime-record]; `otool -D` = `@rpath/libusd_ms.dylib` [measured] |
| Linux | `DT_NEEDED libusd_ms.so`, **no RUNPATH**. glibc's loader reuses an already-loaded object whose SONAME matches before searching paths. SONAME is `libusd_ms.so` [measured]. | Loader behavior **[inferred]**; CI must verify. If the host hasn't loaded USD, the result is `ImportError` (safe). |
| Windows | Import table `usd_ms.dll`. The loader checks the **loaded-module list** ("whether a DLL with the same module name is already loaded into memory (no matter which folder it was loaded from)") before directory search [https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order]. | Blender's own `pxr/Tf/_tf.pyd` imports `usd_ms.dll` from a directory that doesn't contain it [measured], and Blender's `pxr/__init__.py` adds no DLL directory [measured]. It loads only because `usd_ms.dll` is already in the process. **[inferred, strong]** |

Windows details:

- Python ≥ 3.8 resolves extension DLL dependencies with `LOAD_LIBRARY_SEARCH_*` flags: the module's own directory, system directories, and `os.add_dll_directory` entries, not `PATH` **[inferred from Python 3.8 What's New; page not fetched]**. The loaded-module check happens earlier and does not depend on those flags **[inferred]**.
- Do **not** call `os.add_dll_directory` on Blender's directories as the primary mechanism. It is unnecessary, and if USD were somehow not loaded it would mask the error.
- Do add a **pre-import guard** in Python: `ctypes.WinDLL` with `GetModuleHandleW("usd_ms.dll")` must return non-null. Otherwise raise a clear error instead of letting the loader search.
- USD's own `Tf.WindowsImportWrapper` adds every `PATH` entry (or `PXR_USD_WINDOWS_DLL_PATH`) with `os.add_dll_directory` while it imports `pxr` modules **[usd-v26.03 pxr/base/tf/__init__.py:20-56]**. This is a pitfall if another `usd_ms.dll` sits on `PATH` and loads first. It cannot happen inside Blender, where `blender.exe` loads its own DLL before Python starts.
- Same-named DLL from elsewhere: pip `usd-core` in the bpy-wheel venv, if imported before `bpy`, could own the `usd_ms.dll` slot. Whether usd-core's Windows DLL is actually named `usd_ms.dll` was **not verified**. If it is, our module's imports of `pxrBlender_*` symbols would fail at load time ("procedure not found") rather than corrupt memory **[inferred]**, because Windows binds by DLL name plus symbol name and the namespaces differ.

### 1.5 Concrete CMake generalization

The current file hard-fails on non-macOS **[hydra_bridge/CMakeLists.txt:4-6]**. A cross-platform version looks like this (sketch, not tested):

```cmake
cmake_minimum_required(VERSION 3.26)
project(hydra_bridge LANGUAGES CXX)

# Per-platform pinned lib repo + where to link USD from.
if(APPLE)
  set(BLENDER_LIB_REPO lib-macos_arm64)  set(BLENDER_LIB_REV a76ef917...)
  set(CMAKE_OSX_DEPLOYMENT_TARGET 11.2 CACHE STRING "" FORCE)   # Blender 5.2 minos
elseif(WIN32)
  set(BLENDER_LIB_REPO lib-windows_x64) set(BLENDER_LIB_REV 60d6e96b...)
elseif(UNIX)
  set(BLENDER_LIB_REPO lib-linux_x64)   set(BLENDER_LIB_REV ecbd06cf...)
endif()
# prepare_deps.py: sparse-checkout per platform:
#   all:     usd/include tbb/include
#   mac/lin: python/include/python3.13
#   windows: python/313/include python/313/libs/python313.lib usd/lib/usd_ms.lib tbb/lib/tbb12.lib

find_package(Python 3.13 EXACT REQUIRED COMPONENTS Interpreter Development.Module)
Python_add_library(_hydra_bridge MODULE WITH_SOABI bridge.cpp)
target_compile_features(_hydra_bridge PRIVATE cxx_std_17)
target_include_directories(_hydra_bridge SYSTEM PRIVATE ${DEPS}/usd/include ${DEPS}/tbb/include)
target_compile_definitions(_hydra_bridge PRIVATE PXR_BOOST_PYTHON_NO_PY_SIGNATURES)

if(WIN32)
  target_compile_options(_hydra_bridge PRIVATE /permissive- /Zc:inline /Zc:__cplusplus /bigobj /EHsc)
  target_compile_definitions(_hydra_bridge PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
  set_property(TARGET _hydra_bridge PROPERTY MSVC_RUNTIME_LIBRARY MultiThreadedDLL)  # /MD always
  target_link_directories(_hydra_bridge PRIVATE ${DEPS}/tbb/lib)    # tbb12.lib auto-link
  target_link_libraries(_hydra_bridge PRIVATE ${DEPS}/usd/lib/usd_ms.lib)
  # Python313.lib: FindPython's Development.Module provides it; or force ${DEPS}/python/313/libs.
elseif(APPLE)
  target_link_libraries(_hydra_bridge PRIVATE ${BLENDER_USD_LIB})   # @rpath/libusd_ms.dylib
  set_target_properties(_hydra_bridge PROPERTIES SKIP_BUILD_RPATH TRUE INSTALL_RPATH "")
else()  # Linux
  # Link against any file with SONAME libusd_ms.so: the uv env's bpy/lib, the Blender
  # tarball's lib/, or the lib repo blob. Do NOT embed an rpath.
  target_link_libraries(_hydra_bridge PRIVATE ${BLENDER_USD_LIB})
  set_target_properties(_hydra_bridge PROPERTIES SKIP_BUILD_RPATH TRUE INSTALL_RPATH ""
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN ON)
  target_link_options(_hydra_bridge PRIVATE -Wl,--no-undefined-version)  # optional
endif()
```

Other changes:

- **`bridge.cpp`:** replace the `<mach-o/dyld.h>` loaded-library probe with a per-platform probe (see §2). Derive `usd_namespace` from `PXR_INTERNAL_NS` via stringification instead of hard-coding it.
- **`build.py`:** replace the `otool`/`nm -m` audit with per-platform audits:
  - Linux: `readelf -d` (NEEDED contains `libusd_ms.so`, no RUNPATH/RPATH, no `libpython`); `objdump -T` (undefined `pxrBlender_` symbols; max GLIBC ≤ 2.28 and GLIBCXX ≤ the manylinux_2_28 baseline).
  - Windows: `dumpbin /imports` (imports from `usd_ms.dll`, `python313.dll`, `MSVCP140.dll`; no `*D.dll`); `dumpbin /headers` (linker ≤ 14.44).
  - Also check for any bundled `usd*`/`tbb*`/`python*` library and fail the build if one is found.
- **Linker input on Linux:** linking against the bpy wheel's `bpy/lib/libusd_ms.so`, already in the uv environment, avoids fetching the 79 MB blob. The SONAME is what gets recorded **[inferred]**.

### 1.6 CI in GitHub Actions

- **macOS:** `macos-latest` (arm64). Already supported by `.github/actions/setup-blender`. Add `CMAKE_OSX_DEPLOYMENT_TARGET=11.2`.
- **Linux:**
  - *Build job* in `container: quay.io/pypa/manylinux_2_28_x86_64` (GCC 14, glibc 2.28). Install `uv` and use `/opt/python/cp313-cp313/bin/python`.
  - *Test job* on `ubuntu-latest`. The existing composite action installs the X/GL libraries and downloads the Blender tarball. Pass the built module between jobs as an artifact.
  - Optional: run `auditwheel show` on the bridge wheel only as a GLIBC report. Do not let it graft libraries, since `auditwheel repair` would bundle `libusd_ms.so` (forbidden).
- **Windows:** `windows-latest`. Use `ilammy/msvc-dev-cmd` (or `vcvarsall`) with `toolset: 14.44`. Confirm in CI that the runner image has a 14.44 toolset installed; if not, add it with the VS installer component `Microsoft.VisualStudio.Component.VC.14.44.17.14.x86.x64` **[inferred]**.
- **Dependency headers:** a blobless sparse checkout of `https://projects.blender.org/blender/lib-<platform>.git` at the pinned SHA, as `prepare_deps.py` does today.
  - Git transport worked from this machine.
  - The web "raw" endpoints returned **HTTP 403** to `curl` without a browser User-Agent [measured]. Don't depend on them.
  - Cache `external/blender-deps` with `actions/cache` keyed by `<platform>-<lib-rev>`.
  - `git ls-tree -l` (sizes) forces blob downloads in a blobless clone, so avoid it [measured: it stalled].
- **Blender binary:** already cached and checksum-verified by `setup-blender` for all three platforms. Linux and Windows downloads come from `download.blender.org`. Note that `download.blender.org` also returns 403 to Python's default User-Agent [measured].
- **Runs per platform:**
  - Build.
  - Static audit (above).
  - The existing probe (`run.py`) in **both** the wheel and the binary.
  - An "exactly one USD" check (§2).
  - A shutdown-clean check: exit code 0 and no stderr crash banner.

---

## 2. Exactly one USD loaded

**In-process checks (C++), per platform**

- macOS: `_dyld_image_count` / `_dyld_get_image_name` (current code **[bridge.cpp:110-117]**).
- Linux: `dl_iterate_phdr`, collecting `dlpi_name`. Prefer this over parsing `/proc/self/maps`, which also works.
- Windows: `EnumProcessModules` + `GetModuleFileNameExW` (psapi), or `CreateToolhelp32Snapshot`.
- **Provenance check (stronger than counting names):** resolve the image that provides a USD function as *our module* sees it, and compare it with the image backing Python's `pxr` (look up `pxr.Usd._usd.__file__` and that module's dependency).
  - POSIX: `dladdr((void*)&UsdStage::Open, &info)` → `info.dli_fname`.
  - Windows: `GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | …UNCHANGED_REFCOUNT, addr, &h)` + `GetModuleFileNameW`.
  - Assert that the path equals the single `usd_ms` image found by enumeration.
- **What to flag:** any image whose basename matches `usd_ms`, `libusd_*`, `usd_*.dll`, or `_tf`/`_usd` modules outside Blender's `site-packages`. Non-monolithic USD builds (usd-core) could use per-library names, which were not verified.

**Python-level checks**

- `pxr.__file__` must be under the host's bundled `site-packages`:
  - Binary: `…/5.2/python/lib/…/site-packages/pxr`.
  - Wheel: `bpy/5.2/python/lib/…/site-packages/pxr`.
- `importlib.metadata.distribution("usd-core")` should be absent in the test venv.
- `pxr.Usd.GetVersion() == (0, 26, 3)`, and the module's `usd_namespace` constant should match.

**Pitfalls**

- **pip `usd-core` in the bpy-wheel venv.** Both provide a top-level `pxr`. If `pxr` is imported before `bpy`, the venv's `pxr` wins and two USDs coexist. Blender's namespace keeps them from clashing at the symbol level **[usd.cmake:60-62]**, but stages are not interchangeable. Passing a usd-core `Stage` to our module fails the pxr_boost conversion (`ArgumentError`/`TypeError`: no registered converter), because our module queries Blender's registry **[inferred]**. The project lock contains `bpy` (which pulls `numpy`) and not `usd-core` [measured: uv.lock].
- **Import order:** the extension must import `pxr`/`bpy` before the native module. In the binary this is always true. In the wheel, `import bpy` loads `usd_ms` via `bpy/__init__.so|pyd` **[measured: Windows pyd imports; inferred for Linux]**. Without it, the loader fails cleanly with `ImportError` on all three platforms, because no RUNPATH, rpath, or DLL directory points at USD **[inferred]**.
- **Different USD file per host is expected.** The wheel's `bpy/lib/` and the binary's `lib/` or `blender.shared/` are different files with the same SONAME/install name. The same module works with each **[runtime-record, macOS]**.
- **Windows arm64:** Blender 5.2 also pins `lib/windows_arm64@c65cd3db` and PyPI ships `bpy-5.2.2-…-win_arm64.whl` [measured]. The project says three platforms, so state explicitly that windows-arm64 is unsupported (omit it from `platforms`).

---

## 3. Stage exchange with Python `pxr`

**How it works today.** `bp::init<UsdStageRefPtr>()` asks the pxr_boost converter registry, which lives in Blender's `usd_ms`, to convert the Python `Usd.Stage`.

- Python holds stages through the `TfWeakPtr` holder (`class_<UsdStage, StagePtr, noncopyable>`) **[usd-v26.03 pxr/usd/usd/wrapStage.cpp:193]**, with `TfPyRefPtrFactory` return policies **[wrapStage.cpp:212-228]**.
- `TfRefPtr<T>` from-Python conversion is registered by `TfPyPtrHelpers` **[usd-v26.03 pxr/base/tf/pyPtrHelpers.h:150, 396-400]**.
- The registry entry point `pxr_boost::python::converter::registry::lookup` is exported on every platform (checked on Windows and Linux) **[measured]**. Each module's `registered<T>::converters` static reference is initialized by that shared lookup.

**Windows type identity.**

- pxr_boost uses `std::type_info` equality on MSVC. `PXR_BOOST_PYTHON_TYPE_ID_NAME` is defined only for GCC-family compilers **[type_id.hpp:33-42]**.
- MSVC's `type_info::operator==` compares decorated names (vcruntime `__std_type_info_compare`), so identity holds across DLLs **[inferred; well known, not fetched]**. This is the same mechanism Blender's own `pxr/*.pyd` modules rely on with `usd_ms.dll`.
- `TfType::FindByTypeid` falls back to `type_info::name()` when the `type_info*` cache misses **[usd-v26.03 pxr/base/tf/type.cpp:512-533; typeInfoMap.h:68-94]**.
- Result: no Windows-specific code is expected. Data symbols (`HdTokens`, `TfType` singletons) need `dllimport`, which the USD headers supply when no `*_EXPORTS` or `PXR_STATIC` is defined **[inferred]**.

**Pitfall: converter registration is process-global and modules never unload.** Python cannot unload extension modules. If the user updates the extension in the same session, the new `.so`/`.pyd` registers `class_<Bridge>` again. The registry keys on the type name, so it keeps the **old** converter and warns *"to-Python converter … already registered"* **[inferred from pxr_boost registry semantics]**. Mitigations:

- Put all bound C++ types in a namespace that changes with every build, e.g. `namespace proscenium::native::v0_1_0_<git-sha>`.
- Tell users to restart Blender after updating.
- Blender already falls back to "rename and queue removal" when uninstall cannot delete files, such as a locked `.pyd` on Windows **[bpy 5.2 scripts addons_core/bl_pkg/bl_extension_ops.py:317-324]**.

**GIL handling.**

- USD provides `TF_PY_ALLOW_THREADS_IN_SCOPE()` (and `TfPyLock::BeginAllowThreads`) **[usd-v26.03 pxr/base/tf/pyLock.h:105-181]**. USD's own wrappers use it in `stage.cpp`, `prim.cpp`, and `schemaRegistry.cpp`.
- Pattern: (1) with the GIL held, convert inputs (stage, time) into C++ values; (2) release the GIL, then run Hydra `ApplyPendingUpdates`/`SetTime`/traversal and build the immutable plan in pure C++ (no `bp::object`); (3) reacquire the GIL and wrap the plan.
- Python-registered `Tf.Notice` listeners and Python Plug plugins take the GIL themselves through `TfPyLock` **[inferred]**.
- Caller contract: no Python thread may edit the stage during capture. USD stages are not safe for concurrent writes.
- The bridge currently holds the GIL throughout **[bridge.cpp:62-104]**.

**Strong vs weak stage references.**

- `UsdImagingStageSceneIndex` stores a **strong** `UsdStageRefPtr _stage` **[usd-v26.03 pxr/usdImaging/usdImaging/stageSceneIndex.h:154]**. Any retained Hydra chain therefore keeps the stage alive, independent of the bridge's own `stage_` member.
- To honor the caller-release contract in `source-access.md#in-memory-sources`:
  - Keep the bridge's own reference as `UsdStageWeakPtr`.
  - Provide `release()`, which calls `stageSceneIndex->SetStage(nullptr)` **[stageSceneIndex.h:72]** and drops the chain.
  - Or rebuild the chain per refresh from a weak pointer that is checked for expiry.
- The probe's "bridge retains it after the caller releases" result **[runtime-record]** is the opposite of what the contract needs.

---

## 4. Zero-copy plan transfer

### 4.1 Vt arrays already implement the buffer protocol (v26.03)

From `usd-v26.03/pxr/base/vt/arrayPyBuffer.cpp`:

- `Vt_getbuffer` allocates a small wrapper holding **a copy of the `VtArray`**. That copy is O(1): VtArray is copy-on-write and shares storage via a refcount. The wrapper points `view->buf` at `array.cdata()` and increfs the Python object **[arrayPyBuffer.cpp:160-200, 213-272]**.
- **Read-only.** Writable requests are refused **[arrayPyBuffer.cpp:228-235]**, and so are Fortran-contiguous requests **[:222-226]**.
- Format is the scalar sub-element: `GfVec3f` → `'f'`, matrices → `'d'`/`'f'`, ints → `'i'`, bool → `'?'`, half → `'e'`. The shape includes the element dimensions: `Vec3f[N]` → `(N,3)`, `Matrix4d[N]` → `(N,4,4)` **[arrayPyBuffer.cpp:58-157]**.
- Enabled types: built-in numerics, vecs, matrices, ranges, `Rect2i`, quats, and dual quats **[arrayPyBuffer.h:30-41]**. `module.cpp` installs them at `pxr.Vt` import **[usd-v26.03 pxr/base/vt/module.cpp:14, 34]**.
- **Lifetime:** a memoryview keeps a `VtArray` reference to the data. That data outlives both the Python `Vt` object and the C++ plan, and later source edits can't change it, because writers detach under COW. This matches the "Lifetime" check in the record **[runtime-record]**.

Measured in the project's bpy wheel (macOS) **[measured]**:

```text
memoryview(Vt.Vec3fArray(4))   -> format 'f', shape (4, 3), readonly True, c_contiguous True
memoryview(Vt.IntArray(3))     -> 'i', (3,)
memoryview(Vt.Matrix4dArray(2))-> 'd', (2, 4, 4)
```

### 4.2 What Blender's `foreach_set` accepts (v5.2.2 source plus measurements)

From `source/blender/python/intern/bpy_rna.cc`:

- `foreach_parse_args` rejects an object that is a buffer but **not a sequence** **[bpy_rna.cc:5832-5838]**. It then uses `tot = PySequence_Size(seq)` **[:5841]**. For a 2-D memoryview or a `Vt.Vec3fArray`, that is N, not 3N.
- With `set`, Blender calls `PyObject_GetBuffer(seq, PyBUF_ND | PyBUF_FORMAT)` and requires the format character to match the RNA raw type exactly: `'f'` float, `'i'` signed int, `'I'` unsigned, `'?'` bool, `'d'`, `'q'`, `'B'`, `'h'`… **[bpy_rna.cc:5922-5973, 6007-6028]**. `B` is assumed when the format is NULL.
- If the format matches, the buffer pointer goes straight to `RNA_property_collection_raw_set` with no Python-side copy **[:6020-6024]**. Otherwise Blender falls back to per-item `PySequence_GetItem` **[:6031-…]**.
- **Read-only buffers work for `foreach_set`**, since it does not request `PyBUF_WRITABLE`. `foreach_get` into a Vt view fails ("couldn't access the py sequence") **[measured]**.

Measurements (1,000,000 points, bpy wheel, macOS arm64) **[measured: `tools/feasibility/probe_buffer_transfer.py`]**:

| Call | Result |
|---|---|
| `attributes['position'].data.foreach_set('vector', Vt.Vec3fArray)` | **rejected**: "Array length mismatch (expected 3000000, got 1000000)" → RuntimeError |
| same with `memoryview(arr)` (2-D) | **rejected**, same error |
| same with `memoryview(arr).cast('B').cast('f')` (flat, still zero-copy) | **ok, 0.22–0.35 ms**; values verified at index 123457 |
| `mesh.vertices.foreach_set('co', flat)` | ok, **31.5 ms** (per-element RNA path) |
| `bytes(flat)` (a reference 12 MB memcpy) | 0.36 ms |
| `array.array('f')` into `vertices.co` | 31.3 ms |
| `loops.foreach_set('vertex_index', memoryview(Vt.IntArray))` | ok (`'i'` matches signed int) |

These are single runs on one machine, not benchmarks.

**Recipe:**

- `flat = memoryview(vt_array).cast('B').cast(fmt)`, where `fmt` is the array's scalar format.
- Use **attribute** collections (`mesh.attributes[name].data.foreach_set('value'|'vector'|'color', flat)`) rather than the legacy `vertices`/`loops`/`polygons` element properties wherever 5.2 provides an attribute. The attribute path is about 100× faster.
- The single copy into Blender's own storage is unavoidable, because the extension cannot hand ownership to Blender.

**C++ plan rule:** emit arrays in **exactly** Blender's raw element types. Examples: `VtArray<GfVec3f>` for positions and normals, `VtArray<int>` for indices and counts, `VtArray<GfVec2f>` for UVs, `VtArray<GfMatrix4f>` (`'f'`) for object matrices if they go through a float RNA array, and `VtArray<bool>` for flags. Any mismatch silently drops to the per-item fallback.

### 4.3 Options compared

| Option | Copies | Dependencies | Notes |
|---|---|---|---|
| **A. Plan returns `VtArray`s through existing `pxr.Vt` converters (recommended)** | 0 in Python | none (no numpy) | Verified end to end (above). Ownership is automatic via VtArray COW. Read-only, as the immutable plan requires. Converters are already registered by Blender's `pxr.Vt`; the bridge already returns `Vt.Vec3fArray` **[runtime-record "existing Vt converter used"]**. |
| B. Custom type with `tp_as_buffer` (raw CPython API) on our plan object | 0 | none | Gives direct 1-D views and avoids `.cast`. USD does exactly this to its own types **[arrayPyBuffer.cpp:286-304]**. More code; only worth it if a plan storage type isn't a VtArray. |
| C. nanobind `nb::ndarray` / pybind11 buffers | 0 | nanobind/pybind11 in the build | Can coexist: Blender's process already loads pybind11 (MaterialX, OCIO, OIIO, OSL) and nanobind (OpenVDB) modules alongside pxr_boost **[build_environment/cmake/{materialx,opencolorio,openimageio,openvdb,osl}.cmake depend on external_pybind11/nanobind]**. But stages and Vt values still need pxr_boost conversion, so one module would carry two binding frameworks. No gain over A. |
| D. numpy arrays | 0 (with capsule base) | numpy C API | numpy is bundled in both hosts (`bpy` wheel depends on numpy [uv.lock]), but A needs none. Avoid ABI coupling to numpy's C API. |
| E. Stable ABI (abi3) | — | — | **Not compatible.** pxr_boost uses non-limited internals (`PyHeapTypeObject`, `tp_dict`, …) in 43 places **[usd-v26.03 pxr/external/boost/python/src/object/class.cpp etc.; measured grep]**, and Vt writes `tp_as_buffer` directly. Also pointless, because `usd_ms` itself imports `python313.dll` [measured] and the module is tied to one Blender/USD build anyway. |

**Recommendation: A.** The plan is an immutable C++ object (`std::shared_ptr<const Plan>`). Its large members are `VtArray<T>`, exposed as read-only properties that return `bp::object(vtArray)`, an O(1) VtArray copy. The Python apply layer does `memoryview(x).cast('B').cast(fmt)` and calls attribute `foreach_set`. No numpy, no new binding library, no custom buffer code.

---

## 5. Errors, not crashes

**Converting Tf errors.**

- Bridge entry points defined with `PXR_BOOST_PYTHON_MODULE` do **not** get USD's automatic conversion. USD modules get it from `TF_WRAP_MODULE` → `Tf_PyPostProcessModule` → `WrapForErrorHandling`, which wraps each function in a `TfErrorMark` plus `TfPyConvertTfErrorsToPythonException` **[usd-v26.03 pxr/base/tf/pyModule.cpp:131-185, 362-375]**.
- Do one of the following:
  1. Use the `TfPyRaiseOnError<>` call policy on every `.def` **[pxr/base/tf/pyError.h]**. It stores a `TfErrorMark` in the argument package and raises after the call.
  2. Write explicit wrappers: `TfErrorMark m; …; if (!m.IsClean() && TfPyConvertTfErrorsToPythonException(m)) bp::throw_error_already_set();`. Both functions are exported **[measured: Windows/Linux export tables]**.
- **C++ exceptions** thrown out of a bound function are translated by `handle_exception_impl`:
  - `bad_alloc` → `MemoryError`
  - `out_of_range` → `IndexError`
  - `invalid_argument` → `ValueError`
  - other `std::exception` → `RuntimeError`
  - `...` → `RuntimeError("unidentifiable C++ exception")`

  **[usd-v26.03 pxr/external/boost/python/src/errors.cpp:27-63]**. The bridge's `throw std::invalid_argument` becomes `ValueError`.
- **Worker-thread errors:** `WorkParallelForN` and `WorkDispatcher` move `TfError`s from TBB workers back to the calling thread via `TfErrorTransport` **[usd-v26.03 pxr/base/work/loops.h:24-41; dispatcher.h:106-176]**, so a mark set on the calling thread sees them. C++ exceptions inside TBB `parallel_for` propagate to the waiting thread **[inferred, TBB semantics]**.
- **Warnings and status:** install a `TfDiagnosticMgr::Delegate` scoped to the capture to collect `TF_WARN`/`TF_STATUS` into plan diagnostics **[inferred]**.

**What can still terminate Blender**

- **`TF_FATAL_ERROR` / `TF_AXIOM` / fatal coding errors.** `PostFatal` runs delegates, then either prints and `exit(1)` (runtime) or logs a crash and aborts **[usd-v26.03 pxr/base/tf/diagnosticMgr.cpp:360-400]**. They are unrecoverable, and a delegate cannot cancel them.
- **Null data-source dereference.** Hydra schema getters return null handles (`GetTopology()`, `GetFaceVertexCounts()`, `GetPrimvarValue()`). The bridge checks each **[bridge.cpp:78-96]**, and every new accessor must too.
- **Unchecked indexing.** `VtArray::operator[]` is unchecked. Out-of-range `faceVertexIndices`, subset indices, indexed-primvar indices, or instance indices read out of bounds.
- **Integer overflow** in size arithmetic (`counts` sums, `N*3`).
- **Stack overflow** from recursive traversal of deep hierarchies or material networks. Use explicit stacks, as `Snapshot` does **[bridge.cpp:67-73]**.
- **Exceptions escaping destructors or `noexcept` code** (including Hydra observer callbacks) → `std::terminate`.
- **Use-after-free** of observers. The bridge registers `HdSceneIndexObserverPtr(&observer_)` on a member and removes it in the destructor **[bridge.cpp:55-58]**. Any path that destroys the chain out of order is a hazard.
- **ABI mismatch** (wrong headers, toolset, or CRT). Avoid it with the build audits in §1.

**Validation pattern, all in C++ before anything reaches Python or Blender.** Wrap each prim's extraction in a function that returns `std::expected`-like `{plan_part | diagnostic}`. Check:

- topology: `counts[i] >= 3`, `sum(counts) == indices.size()`, `0 <= indices[j] < points.size()`;
- primvar length versus interpolation (constant 1, uniform = faces, vertex = points, faceVarying = corners, or `indices.size()` when indexed, with indices `< values.size()`);
- subset indices within the face count;
- finite floats (optional);
- matrices invertible where needed;
- instance indices within instancer prototype counts.

A failure becomes a diagnostic plus a placeholder, never an exception thrown mid-traversal, so one bad prim does not abort the plan. Compute sizes with `size_t` or checked multiplication.

**No sandboxing.** An in-process native module cannot be isolated. Running capture in a subprocess would lose access to in-memory and unsaved stages (`source-access.md#in-memory-sources`) and to the caller's stage identity. Signals (SIGSEGV, access violations) cannot be safely turned into exceptions. The milestone already accepts this: "a C++ core moves geometry validation to where a bug terminates Blender" **[M01b-evaluation-gate.md]**.

---

## 6. Distribution

**Manifest and build mechanics (bpy 5.2 `blender_ext.py`)**

- `platforms` is an optional list of non-empty strings **[blender_ext.py:1990]**. Identifiers follow `platform_from_this_system()`: `macos-arm64`, `linux-x64`, `windows-x64` (also `windows-arm64`, `linux-arm64`, `macos-x64`) **[:2129-2169]**.
- `--split-platforms` requires `platforms` **[:4593-4601]**. It **only filters `wheels`** by platform; every other file goes into every platform zip **[:2392-2418]**. Output names get a `-<platform>` suffix, and a `[build.generated] platforms = [...]` block is appended to the archived manifest **[:4776-4838]**.
  - Consequence: a loose `.so`/`.pyd` inside the extension directory is **not** filtered.
  - Either build one zip per platform on that platform's runner, with only that platform's binary present and `platforms = ["<that one>"]`, which fits `tools/build_extension.py`'s "for the current platform" model.
  - Or ship the native module as a per-platform **wheel** listed in `wheels`, which split-platforms filters automatically.
- **Wheels** are extracted into a **shared** `<extensions>/.local/lib/python3.13/site-packages` **[bpy 5.2 scripts/modules/addon_utils.py:1393-1400, 1783-1810]**, which every extension shares. Bundle the module **inside the extension package** instead (e.g. `proscenium/_native/_core.cpython-313-darwin.so`), so it is private to Proscenium and versioned with it.
- The CLI has no check that rejects binaries; it only skips compressing `.whl` files **[blender_ext.py:704-712]**.
- **Python ABI tag:** a version-specific `cpython-313-*`/`cp313-win_amd64` suffix (non-abi3, §4.3). Use `Python_add_library(... WITH_SOABI)`, as the bridge already does.
- **`blender_version_max`** is exclusive (`filter_blender_version >= version_max` excluded) **[blender_ext.py:2545]**.

**Version pinning evidence**

- 5.2.0, 5.2.1, and 5.2.2 all have USD 26.03 [measured: versions.cmake at each tag].
- 5.2.0's lib pins differ from 5.2.2's on Linux and macOS, but **`usd/lib/libusd_ms.{so,dylib}` and `usd/include` have identical git blob and tree IDs**. The only changes are `xr_openxr_sdk` files **[measured: git ls-tree/diff of lib-linux_x64 30d9f881→ecbd06cf, lib-macos_arm64 5a140a8c→a76ef917]**. Windows has the same pin across 5.2.x.
- `blender-v5.3-release` (5.3 beta) and `main` (5.4 alpha) have **USD 26.08**, the same Python 3.13.13, and TBB 2022.3 [measured]. The namespace becomes `pxrBlender_v26_08`, so a 5.2 build would fail to load on 5.3, cleanly through unresolved symbols, never silently **[inferred]**.
- **Recommendation:** `blender_version_min = "5.2.0"`, `blender_version_max = "5.3.0"`. Run a CI job that checks each new 5.2.x tag's lib pins for the USD blob ID.
- Point-release risk: low, but not zero, because Blender could patch USD in an LTS lib update. The blob-ID check catches it.

**Platform policy**

- **extensions.blender.org ToS §3.6** forbids non-Python source and "external, pre-compiled packages" (updated 10 Aug 2026) **[https://extensions.blender.org/terms-of-service/]**.
- The manual's wheel page allows wheels "bundled unmodified from Python's package index" **[https://docs.blender.org/manual/en/latest/advanced/extensions/python_wheels.html, via raw rst]**. That allows third-party PyPI wheels but not the project's own compiled core.
- §3.5 requires reviewable, non-obfuscated code.
- **Conclusion:** a C++ core means distributing outside extensions.blender.org: a self-hosted extension repository JSON, GitHub releases, or install-from-disk.

**Signing and quarantine**

- **macOS:**
  - Blender.app is hardened-runtime signed (Team 68UA947AUU) with `com.apple.security.cs.disable-library-validation = true` [measured: `codesign -d --entitlements`]. That is why an ad-hoc-signed third-party `.so` loads.
  - The bridge is `adhoc,linker-signed` [measured], which is enough on arm64.
  - Gatekeeper quarantine applies when a quarantined file is opened through LaunchServices. Blender extracts zips with Python `zipfile`, which does not copy the `com.apple.quarantine` xattr, and Blender's own downloads via urllib do not set it **[inferred; test: `xattr -w com.apple.quarantine …` on a zip, install from disk, import]**.
  - Optional hardening: Developer ID signing plus `notarytool` submission of the zip. Stapling is not possible for a bare `.so`, but the online check works.
- **Windows:** SmartScreen and Mark-of-the-Web gate shell-launched executables, not DLLs loaded by a running process. Defender may still scan, and unsigned `.pyd` files load normally **[inferred]**. Authenticode signing is optional and reduces false positives.
- **Linux:** no signing.

---

## 7. Prior art

- **Blender's own Hydra** (`source/blender/render/hydra`) is compiled into Blender, not an extension. Its Python API, `bpy.types.HydraRenderEngine` with `bl_delegate_id` → `_bpy_hydra.engine_create` **[bpy 5.2 scripts/modules/_bpy_types.py:1612-1651]**, lets add-ons drive Hydra render-delegate **plugins**. Those plugins are C++ shared libraries registered through `pxr.Plug`, and they must be built against Blender's exact USD headers and namespace: the same constraint Proscenium faces.
- **AMD BlenderUSDHydraAddon ("hdusd", v3.0.0 for Blender 4.0+, last commit 2023-11-15)** [hdusd HEAD]:
  - Builds its **own** monolithic USD, copying Blender's `usd.cmake` options (`PXR_BUILD_MONOLITHIC=ON`, same imaging, MaterialX, and OpenVDB settings) against Blender's precompiled-lib tree **[hdusd/build.py:178-267]**.
  - Applies a patch set similar to Blender's (removing `/Zi`, the debug-python naming) **[hdusd/patches/usd.diff]**.
  - Builds `hdRpr` against `usd_ms` **[build.py:371-410]**.
  - At runtime it uses **Blender's** `pxr` (`from pxr import Plug`), appends its `libs/lib` to `PATH` on Windows, and calls `Plug.Registry().RegisterPlugins(...)` **[hdusd/src/hydrarpr/__init__.py:20-48]**.
  - On Windows its render-studio component rewrites a `pxr/__init__.py` to `os.add_dll_directory` and `ctypes.CDLL(usd_ms.dll)` **[build.py:430-442]**.
  - Its per-OS zips are named `…-{os}.zip` **[build.py:723]**.
  - Lessons: each release was tied to one Blender version and one platform build; a home-built USD must match Blender's configuration exactly; the project went dormant. Whether its namespace matched Blender's was not verified here.
- **Blender issue #76490** ("Included USD libraries cause symbol conflict with addons using USD binding"; `TF_DEBUG_ENVIRONMENT_SYMBOL multiple symbol definitions`, reported on macOS) motivated the custom-namespace approach **[search result https://developer.blender.org/T76490; issue page returned 403, so details unverified]**. Lesson: the namespace converts mixed-USD situations into clean load failures. Never bundle a second USD.
- **Binding coexistence:** Blender's process already loads pxr_boost (USD), pybind11 (MaterialX, OCIO, OIIO, OSL), and nanobind (OpenVDB) modules **[build_environment/cmake/*.cmake]**. Mixing frameworks per module is proven at process level.
- No other public extension was found that links Blender's `usd_ms` from a Python extension module, as opposed to a Hydra plugin. The bridge appears to be novel in this respect (searched only briefly).

---

## 8. Effort, risk, and recommended build matrix

| Platform | Work remaining | Effort | Top risks |
|---|---|---|---|
| **macOS arm64** | `CMAKE_OSX_DEPLOYMENT_TARGET=11.2`; add `PXR_BOOST_PYTHON_NO_PY_SIGNATURES`; generalize the audit; quarantine test; optional notarization | 0.5–1 day | Deployment target (current build won't load before macOS 26); Apple libc++ availability errors when lowering the target (e.g. `std::filesystem`, `<format>`) |
| **Linux x64** | manylinux_2_28 container build; Linux audit (NEEDED/SONAME/no RUNPATH/GLIBC ceiling); `dl_iterate_phdr` probe; test on ubuntu-latest in wheel + binary | 1–2 days | SONAME-reuse assumption (inferred, needs CI proof); accidentally building on a newer glibc; X/GL runtime deps for headless tests (handled by existing action) |
| **Windows x64** | Fetch `usd_ms.lib`, `tbb12.lib`, `python313.lib`, and headers; MSVC flags/defines; pin toolset ≤ 14.44; `EnumProcessModules` probe; pre-import `GetModuleHandleW` guard; test in wheel + binary | 2–4 days | CRT/toolset newer than `blender.crt`; loaded-module resolution (strongly inferred, needs CI proof); long MSVC compile times for Hydra headers; locked `.pyd` on update (Blender falls back to stale rename); converter re-registration after in-session update |
| All | Versioned C++ namespace for bound types; error-mark wrappers; GIL release around capture; weak stage reference + `release()`; per-platform zips | 1–2 days | ToS §3.6 rules out extensions.blender.org; every Blender minor release (5.3 → USD 26.08) needs a rebuild and new lib pins |

**Recommended matrix (M1b and later)**

| Job | Runner | Build env | Link input | Test hosts |
|---|---|---|---|---|
| macos-arm64 | `macos-latest` | Xcode clang, `-mmacosx-version-min=11.2` | `bpy/lib/libusd_ms.dylib` (uv env) or Blender.app | bpy wheel + Blender 5.2.2 binary |
| linux-x64 | build: `ubuntu-latest` + `container: manylinux_2_28_x86_64`; test: `ubuntu-latest` | GCC 14 (gcc-toolset), glibc 2.28 | `bpy/lib/libusd_ms.so` (uv env) | bpy wheel + Blender 5.2.2 tarball |
| windows-x64 | `windows-latest` | MSVC toolset 14.44, `/MD`, Release | `lib-windows_x64@60d6e96b` `usd/lib/usd_ms.lib`, `tbb/lib/tbb12.lib` | bpy wheel + Blender 5.2.2 zip |

Common to every job: headers from `lib-<platform>` at the v5.2.2 pin (sparse, cached by SHA); a static audit; the 27-check probe in both hosts; the exactly-one-USD and provenance check; a shutdown exit code of 0. Outputs: one extension zip per platform with `platforms = ["<platform>"]` and `blender_version_max = "5.3.0"`. Windows-arm64 and Linux-arm64 are explicitly excluded.

---

## Housekeeping note

Running `uv run --offline python …` once in the project directory re-synced `.venv` ("Uninstalled 2 packages / Installed 2 packages"). That restored the environment to `uv.lock` but did change the venv. Later commands used `.venv/bin/python` directly. No project files were edited.
