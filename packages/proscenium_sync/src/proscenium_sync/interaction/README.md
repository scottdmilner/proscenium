# `proscenium_sync.interaction`

The Python display component of the [interaction contract](../../../../../docs/spec/interaction-contract.md): what the planner's correspondence is built from, read from Blender data (DECISIONS.md "Persisted correspondence", "Headless interaction functions"). `proscenium_sync.bindings` calls it.

Code in other units reaches it through the modules `__init__.py` exports ([import rules](../README.md#import-rules)); tests reach into any module.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `display_correspondence.py` | `DisplayElements`, a binding's display elements read when called: the objects its manifest names in a drawn copy's object role, ordered by identity, each with its entry key, source path, and viewport participation from its hide flag; and `correspondence()`, the planner's `Correspondence` over them on the live stage, with instance contexts from the shown generation's held plan where it holds the copy. |
| `blender_selection.py` | The display component's `apply_selection`, which mirrors display targets into a view layer's selection and active object, setting only the objects whose selection changes and the active object only when it does, since setting either again costs Blender a depsgraph update, and leaving unmanaged objects' selection alone, and `read_blender_selection`, the display's selected and active objects by element index (`BlenderSelection`). Blender selects only objects its view layer holds and shows. |
