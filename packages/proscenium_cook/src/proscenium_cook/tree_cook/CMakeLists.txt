# The cook's module, _cook, with the planner's settings (proscenium_sync's planner/CMakeLists.txt).
cmake_minimum_required(VERSION 3.26)
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
  # Blender 5.2's floor; must be set before project(). The cook must load wherever Blender does.
  set(CMAKE_OSX_DEPLOYMENT_TARGET "11.2" CACHE STRING "Minimum macOS version")
endif()
project(proscenium_cook LANGUAGES CXX)

if(NOT (WIN32 OR APPLE OR CMAKE_SYSTEM_NAME STREQUAL "Linux"))
  message(FATAL_ERROR "Unsupported platform for the cook: ${CMAKE_SYSTEM_NAME}")
endif()

# The locked Blender release's headers (and Windows import libraries); tools/native_build.py passes them.
set(BLENDER_DEPS "" CACHE PATH "Blender's dependency checkout (tools/blender_deps.py)")
if(NOT EXISTS "${BLENDER_DEPS}/usd/include/pxr/pxr.h")
  message(FATAL_ERROR "Blender's dependency headers not found: '${BLENDER_DEPS}' (set BLENDER_DEPS)")
endif()

# Blender's Python headers, keeping the build interpreter's SOABI, and Blender's USD to link.
if(WIN32)
  set(Python_INCLUDE_DIR "${BLENDER_DEPS}/python/313/include")
  set(Python_LIBRARY "${BLENDER_DEPS}/python/313/libs/python313.lib")
  # The bpy wheel has no import library; only the lib repo does.
  set(USD_LIBRARY "${BLENDER_DEPS}/usd/lib/usd_ms.lib")
else()
  set(Python_INCLUDE_DIR "${BLENDER_DEPS}/python/include/python3.13")
  # Any file whose install name or SONAME is Blender's usd_ms; native_build.py passes the bpy wheel's.
  set(USD_LIBRARY "" CACHE FILEPATH "Blender's libusd_ms to link against")
endif()
find_package(Python 3.13 EXACT REQUIRED COMPONENTS Interpreter Development.Module)
if(NOT EXISTS "${USD_LIBRARY}")
  message(FATAL_ERROR "Blender's USD library not found: '${USD_LIBRARY}' (set USD_LIBRARY)")
endif()

# The settings every target of this build shares: C++17, Blender's USD headers as system includes, the cook's
# warnings, and on Windows Blender's runtime and USD's MSVC flags.
function(proscenium_compile_settings target)
  target_compile_features(${target} PRIVATE cxx_std_17)
  set_target_properties(${target} PROPERTIES CXX_EXTENSIONS OFF)
  target_include_directories(${target} SYSTEM PRIVATE
    "${BLENDER_DEPS}/usd/include"
    "${BLENDER_DEPS}/tbb/include"
  )
  # Warnings for the build's own code; USD's headers are system includes.
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4)
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
  endif()
  # Clang's nearest equivalents of MSVC's /W4 shadowing (C4456-C4458) and size_t narrowing (C4267), so a macOS
  # build reports what the Windows one would.
  if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    target_compile_options(${target} PRIVATE -Wshadow-all -Wshorten-64-to-32)
  endif()
  if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    # USD's tf/hashset.h includes libstdc++'s deprecated <ext/hash_set>, which #warns in every file that
    # reaches sdf/path.h. USD builds itself with the same flag (cmake/defaults/gccclangshareddefaults.cmake).
    # Deprecated functions still warn: that is -Wdeprecated-declarations.
    target_compile_options(${target} PRIVATE -Wno-deprecated)
  endif()
  if(WIN32)
    # Blender's CRT and STL layout: release dynamic runtime only, and USD's MSVC flags.
    set_target_properties(${target} PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
    target_compile_options(${target} PRIVATE /permissive- /Zc:inline /Zc:__cplusplus /bigobj /EHsc)
    target_compile_definitions(${target} PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS)
  else()
    set_target_properties(${target} PROPERTIES CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN ON)
  endif()
endfunction()

Python_add_library(_cook MODULE WITH_SOABI
  cook_diagnostics.cpp
  node_contexts.cpp
  node_definitions.cpp
  node_graph.cpp
  node_ids.cpp
  node_input_reader.cpp
  nodes/composed_stage.cpp
  nodes/layer_from_file.cpp
  nodes/new_layer_zone.cpp
  nodes/node_registry.cpp
  nodes/stage_output.cpp
  nodes/viewer.cpp
  python_bindings.cpp
  python_error_translation.cpp
  task_graph.cpp
  tree_cook.cpp
  tree_reading.cpp
  zone_chains.cpp
)
proscenium_compile_settings(_cook)
# Sources include the cook's headers from this directory, wherever they sit: "node_input_reader.h".
target_include_directories(_cook PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
# On the interface of Blender's exported pxr Python target; match it.
target_compile_definitions(_cook PRIVATE PXR_BOOST_PYTHON_NO_PY_SIGNATURES)
target_link_libraries(_cook PRIVATE "${USD_LIBRARY}")

if(WIN32)
  # oneTBB headers auto-link tbb12.lib.
  target_link_directories(_cook PRIVATE "${BLENDER_DEPS}/tbb/lib")
else()
  set_target_properties(_cook PROPERTIES
    # The host loads its own USD first. Do not embed a machine's library paths.
    SKIP_BUILD_RPATH TRUE
    INSTALL_RPATH ""
    INSTALL_RPATH_USE_LINK_PATH FALSE
  )
  if(NOT APPLE)
    # libusd_ms.so's own dependencies sit beside it; let the linker find them without embedding a path.
    get_filename_component(USD_LIBRARY_DIR "${USD_LIBRARY}" DIRECTORY)
    target_link_options(_cook PRIVATE "-Wl,-rpath-link,${USD_LIBRARY_DIR}")
  endif()
endif()

install(TARGETS _cook LIBRARY DESTINATION .)
