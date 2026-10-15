cmake_minimum_required(VERSION 3.26)
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
  # Blender 5.2's floor; must be set before project(). The bridge must load wherever Blender does.
  set(CMAKE_OSX_DEPLOYMENT_TARGET "11.2" CACHE STRING "Minimum macOS version")
endif()
project(hydra_bridge LANGUAGES CXX)

if(NOT (WIN32 OR APPLE OR CMAKE_SYSTEM_NAME STREQUAL "Linux"))
  message(FATAL_ERROR "Unsupported platform for the Hydra bridge: ${CMAKE_SYSTEM_NAME}")
endif()

find_package(Python 3.13 EXACT REQUIRED COMPONENTS Interpreter)
# prepare_deps.py holds the per-platform pins and prints the checkout directory.
execute_process(
  COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/prepare_deps.py"
  OUTPUT_VARIABLE BLENDER_DEPS
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY
)
file(TO_CMAKE_PATH "${BLENDER_DEPS}" BLENDER_DEPS)

# Blender's Python headers, keeping the build interpreter's SOABI, and Blender's USD to link.
if(WIN32)
  set(Python_INCLUDE_DIR "${BLENDER_DEPS}/python/313/include")
  set(Python_LIBRARY "${BLENDER_DEPS}/python/313/libs/python313.lib")
  # The bpy wheel has no import library; only the lib repo does.
  set(USD_LIBRARY "${BLENDER_DEPS}/usd/lib/usd_ms.lib")
else()
  set(Python_INCLUDE_DIR "${BLENDER_DEPS}/python/include/python3.13")
  # Any file whose install name or SONAME is Blender's usd_ms; build.py passes the bpy wheel's.
  set(USD_LIBRARY "" CACHE FILEPATH "Blender's libusd_ms to link against")
endif()
find_package(Python 3.13 EXACT REQUIRED COMPONENTS Interpreter Development.Module)
if(NOT EXISTS "${USD_LIBRARY}")
  message(FATAL_ERROR "Blender's USD library not found: '${USD_LIBRARY}' (set USD_LIBRARY)")
endif()

Python_add_library(_hydra_bridge MODULE WITH_SOABI bridge.cpp)
target_compile_features(_hydra_bridge PRIVATE cxx_std_17)
set_target_properties(_hydra_bridge PROPERTIES CXX_EXTENSIONS OFF)
target_include_directories(_hydra_bridge SYSTEM PRIVATE
  "${BLENDER_DEPS}/usd/include"
  "${BLENDER_DEPS}/tbb/include"
)
# On the interface of Blender's exported pxr Python target; match it.
target_compile_definitions(_hydra_bridge PRIVATE PXR_BOOST_PYTHON_NO_PY_SIGNATURES)
target_link_libraries(_hydra_bridge PRIVATE "${USD_LIBRARY}")

if(WIN32)
  # Blender's CRT and STL layout: release dynamic runtime only, and USD's MSVC flags.
  set_target_properties(_hydra_bridge PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
  target_compile_options(_hydra_bridge PRIVATE /permissive- /Zc:inline /Zc:__cplusplus /bigobj /EHsc)
  target_compile_definitions(_hydra_bridge PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS)
  # oneTBB headers auto-link tbb12.lib.
  target_link_directories(_hydra_bridge PRIVATE "${BLENDER_DEPS}/tbb/lib")
else()
  set_target_properties(_hydra_bridge PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
    # The host loads its own USD first. Do not embed a machine's library paths.
    SKIP_BUILD_RPATH TRUE
    INSTALL_RPATH ""
    INSTALL_RPATH_USE_LINK_PATH FALSE
  )
  if(NOT APPLE)
    # dladdr and dl_iterate_phdr (libdl is separate before glibc 2.34).
    target_link_libraries(_hydra_bridge PRIVATE ${CMAKE_DL_LIBS})
    # libusd_ms.so's own dependencies sit beside it; let the linker find them without embedding a path.
    get_filename_component(USD_LIBRARY_DIR "${USD_LIBRARY}" DIRECTORY)
    target_link_options(_hydra_bridge PRIVATE "-Wl,-rpath-link,${USD_LIBRARY_DIR}")
  endif()
endif()

install(TARGETS _hydra_bridge LIBRARY DESTINATION .)
