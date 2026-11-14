# `proscenium.interface`

The temporary UI, which M12 replaces (M7 plan, settled 3): the Source Select tool and minimal panels. Tier 6, between `proscenium.api` and `proscenium.addon`: it imports only `proscenium.api`, besides `bpy` and USD, so replacing it touches nothing else (`tests/bpy_free/test_import_tiers.py` checks it). Its operators declare `UNDO` only where the API pushes no undo step of its own, as for a selection; an operator calling an API function that pushes one, such as a synchronization, declares none.

Code in other units reaches it through the modules `__init__.py` exports ([import rules](../README.md#import-rules)); tests reach into any module.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `source_select_tool.py` | The Source Select tool, ported from the bridge's `select_tool.py`: a click picks what its own ray hits as the display draws it, each object's bounds box or an empty marker near its origin, shift toggles and ctrl removes, a drag selects a box by elements' world bounds' centers, and the sidebar's Proscenium tab sets the level and lists the scene's targets. Managed content is selectable exactly while a window showing it has the tool active, which message-bus subscriptions to the workspaces' tools and the windows' workspaces follow. |
| `interface_registration.py` | Registration of the UI's scene property, classes, tool, and subscriptions; the load handler, which subscribes again; and the load, undo, and redo handlers, which recompute selectability from the active tool. |
