# `proscenium_cook.tree_cook`

The cook's C++ source and its compiled module, `_cook`. [AGENTS.md](AGENTS.md) has its build, boundary, style, and test rules. It imports without `bpy`; `tests/bpy_free` imports it with Blender's modules blocked.

## Python

Its only Python module is its `__init__.py`, so no import-linter contract protects modules of its own: the compiled module is invisible to import-linter.

| File | Holds |
|---|---|
| `__init__.py` | The unit's exports: every public name of the compiled module. It imports `pxr.Usd` first, which loads Blender's `usd_ms` and the converters the compiled module's arguments need. |
| `_cook.pyi` | The compiled module's types, so ty checks its callers without a build. |
| `AGENTS.md`, `CLAUDE.md` | Rules for agents working here. `CLAUDE.md` loads `AGENTS.md` for Claude Code. |
| `.clang-format` | The C++ style, the planner's. |
| `.gitignore` | Ignores the built module. |

## C++

| File | Holds |
|---|---|
| `CMakeLists.txt` | The CMake project that builds `_cook`, with the planner's settings, which `tools/native_build.py` configures. |
| `python_bindings.cpp` | Registration of `proscenium_cook.tree_cook._cook`, and `usd_version`. |
