# `proscenium_cook.tree_cook.nodes`

The node types' implementations: one `.cpp` per node type, holding its role's function and its helpers in an anonymous namespace, with its generated attribute header beside it, and the one list of them all ([plan](../../../../../../docs/plans/cook-module.md#node-types-in-c)).

Each `<type>_attributes.h` holds the node type's inputs and properties, and its outputs, each a typed struct naming its attributes, with the reader that fills one and the writer that commits the other. `tools/node_attributes.py render` writes them from `node_definitions.usda`, and its `check`, a pre-commit hook, fails when one is out of date. Don't edit them by hand.

| File | Holds |
|---|---|
| `node_registry.h`, `node_registry.cpp` | The one list of node types, each a type name mapped to its role's function. Loading the node definitions checks it against them, each way. |
| `node_types.h` | Each node type's function, declared for the registry. |
| `composed_stage.h`, `composed_stage.cpp` | The stage a Stage Output or Viewer composes on its layer, with every payload loaded, kept in the node's cache and returned again while its root layer stays the same. |
| `layer_from_file.cpp`, `layer_from_file_attributes.h` | Layer from File, a task: the process's shared copy of the layer at its Path, kept open in its cache between cooks. Reports an empty Path, a missing file, and one that doesn't parse. |
| `new_layer_zone.cpp`, `new_layer_zone_begin_attributes.h`, `new_layer_zone_end_attributes.h` | New Layer Zone, a zone: its begin's file, identified as a new file, and its end's Layer, the zone's finished layer. One file for the pair. Its chain, task, and layer are the machinery's. |
| `stage_output.cpp`, `stage_output_attributes.h` | Stage Output, a task: its composed stage on its linked Layer. Warns when nothing is linked, and when the root layer authors no `upAxis` or `metersPerUnit`. |
| `viewer.cpp`, `viewer_attributes.h` | Viewer, a task: its composed stage on its linked Layer, which the editor's UI shows. Its Context does nothing until zones have a context. Reports nothing of its own. |
