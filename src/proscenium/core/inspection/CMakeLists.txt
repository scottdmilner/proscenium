# The inspection layer: a static library the core links, built with the core's settings
# (proscenium_compile_settings). Its sources include only USD and the standard library, and its only link input is
# Blender's USD (ICON-04). USD's headers need TBB's, which proscenium_compile_settings adds, and Python's, since
# Blender builds USD with Python: they are USD's dependencies, never the library's own includes.
add_library(proscenium_inspection STATIC kind_targets.cpp)
proscenium_compile_settings(proscenium_inspection)
target_include_directories(proscenium_inspection SYSTEM PRIVATE "${Python_INCLUDE_DIRS}")
set_target_properties(proscenium_inspection PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(proscenium_inspection PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(proscenium_inspection PRIVATE "${USD_LIBRARY}")
