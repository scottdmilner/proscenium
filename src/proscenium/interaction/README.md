# `proscenium.interaction`

The Python display component of the [interaction contract](../../../docs/spec/interaction-contract.md): what the core's correspondence is built from, read from Blender data (DECISIONS.md "Persisted correspondence", "Headless interaction functions"). Tier 4, beside `proscenium.synchronization`: it may import `proscenium.binding` and the compiled core, and `proscenium.api` calls it.

Code in other units reaches it through the modules `__init__.py` exports ([import rules](../README.md#import-rules)); tests reach into any module.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `display_correspondence.py` | `DisplayElements`, a binding's display elements read when called: the objects its manifest names in a drawn copy's object role, ordered by identity, each with its entry key, source path, and viewport participation from its hide flag; and `correspondence()`, the core's `Correspondence` over them on the live stage, with instance contexts from the shown generation's held plan where it holds the copy. |
