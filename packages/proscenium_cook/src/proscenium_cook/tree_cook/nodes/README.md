# `proscenium_cook.tree_cook.nodes`

The node types' implementations: one `.cpp` per node type, holding its role's function, its diagnostic codes, and its helpers in an anonymous namespace, and the one list of them all ([plan](../../../../../../docs/plans/cook-module.md#node-types-in-c)). The first node types arrive with step 4.

| File | Holds |
|---|---|
| `node_registry.h`, `node_registry.cpp` | The one list of node types, each a type name mapped to its role's function. Loading the node definitions checks it against them, each way. |
