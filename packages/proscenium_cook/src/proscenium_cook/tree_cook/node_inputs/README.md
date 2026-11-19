# `proscenium_cook.tree_cook.node_inputs`

The generated input headers, one per node type: a struct of its typed inputs and properties, and the reader that fills it through `node_input_reader.h`. `tools/node_inputs.py render` writes them from `node_definitions.usda`, and its `check`, a pre-commit hook, fails when one is out of date. Don't edit them by hand. There are none until the first node type's definition, in step 4 of [the plan](../../../../../../docs/plans/cook-module.md).
