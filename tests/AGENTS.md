# Tests: agent instructions

Read [README.md](README.md) before writing a test. It covers which layer to use, the helpers, and the fixture framework. Its [Rules](README.md#rules) apply to every test. The rules most often missed:

- Prefer the `bpy_free/` layer. Use `isolated/` only for what the blender layer's reset can't make clean, or for input that could crash native code.
- Tests run in parallel. Write only under `tmp_path`, never into the repository, and copy scenes before opening them.
- Expected results come from the spec or from how the fixture is built, never from recording the implementation's output.
- USD test scenes are `.usda` files on disk that start with a comment stating their purpose, never Python strings.

Tests of the planner follow [its rules](../packages/proscenium_sync/src/proscenium_sync/planner/AGENTS.md#tests) too.
