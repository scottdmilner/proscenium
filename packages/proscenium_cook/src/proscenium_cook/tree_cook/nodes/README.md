# `proscenium_cook.tree_cook.nodes`

The node types' implementations: one `.cpp` per node type, holding its role's function and its helpers in an anonymous namespace, with its generated attribute header beside it, and the one list of them all ([plan](../../../../../../docs/plans/cook-module.md#node-types-in-c)).

Each `<type>_attributes.h` holds the node type's inputs and properties, and its outputs, each a typed struct naming its attributes, with the reader that fills one and the writer that commits the other. `tools/node_attributes.py render` writes them from `node_definitions.usda`, and its `check`, a pre-commit hook, fails when one is out of date. Don't edit them by hand.

| File | Holds |
|---|---|
| `node_registry.h`, `node_registry.cpp` | The one list of node types, each a type name mapped to its role's function. Loading the node definitions checks it against them, each way. |
| `node_types.h` | Each node type's function, declared for the registry. |
| `layer_from_file.cpp`, `layer_from_file_attributes.h` | Layer from File, a task: the process's shared copy of the layer at its Path, kept open in its cache between cooks. Reports an empty Path, a missing file, and one that doesn't parse. |
| `stage_output.cpp`, `stage_output_attributes.h` | Stage Output, a task: the stage composed on its linked Layer, with every payload loaded, kept in its cache and returned again while its root layer stays the same. Warns when nothing is linked, and when the root layer authors no `upAxis` or `metersPerUnit`. |
