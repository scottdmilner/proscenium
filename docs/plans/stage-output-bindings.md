# Stage Output bindings: plan

This plan makes the temporary UI's cook tree give each Stage Output node a binding of its own. Each cook attaches the node's stage to that binding and synchronizes it, so the tree shows in the 3D View as any caller's stage does. [node-tree.md](../phase3/node-tree.md#stage-outputs-and-the-viewer) designs this. The front end maps each Stage Output to its binding, so the plain-data tree holds no binding identifiers, and it hands the binding the stage as a caller-supplied source ([Source Stages](../spec/source-access.md#source-stages)).

The plan needs one addition to the synchronizer: the spec's **Remove binding** operation ([Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle), OWN-14; API-08), which M11 delivers. This plan brings its API call forward. Everything else uses `proscenium_sync`'s public API as it is: `create_binding`, `attach`, `set_settings`, `synchronize`, `release`, `in_scene` and `binding_statuses`.

The work runs over several commits, so it goes in a worktree of its own, branched from `main` once the node UI is merged.

## Requirements

### The synchronizer's removal call

- **A call removes a binding**, for example `BINDINGS.remove_binding(binding_id)` and `handle.remove()`. It removes the binding's configuration and its managed content, and keeps detached and unrelated content, as OWN-14 and OWN-15 say. It releases the binding's runtime stages and held plans, as `release()` does. Afterwards the binding's handles raise, except for `release()`, and no scene lists it (API-08).
- **It returns a `Result`,** and it runs alone as the other exclusive operations do. Called during a synchronization, a cache call or a cleanup retry, it raises `ReentrantCallError` and changes nothing.
- **Undo:** an invocation that commits pushes exactly one undo step, with global undo on outside background mode. Undo restores the binding with its records and content, as undoing a [removed destination](../spec/lifecycle.md#removed-destination) does.
- **Failure safety** follows [Lifecycle Failure Safety](../spec/lifecycle.md#lifecycle-failure-safety)'s Remove binding outcome. A disposal that fails stays in the pending-cleanup ledger on the binding index's Text, which outlives the configuration ([Removed Destination](../spec/lifecycle.md#removed-destination)). It carries a `removal-failed` diagnostic and the `remove` originating operation. The configuration is removed anyway, and the removal completes with issues. Open question 1 records how much of M11 this brings forward.

Step 1 settles how removal works (`synchronization/binding_removal.py`):

- **Refusals.** Removal refuses, changing nothing, while the ledger, the binding index, the manifest, the generation or the last attempt can't be read, since it would change them ([Schema Versions](../spec/lifecycle.md#schema-versions)). It refuses a binding that isn't usable as the other operations do. It also refuses a binding with copies, even though one is canonical: the copies' records would make the binding a candidate again, and copies are never deleted automatically ([Copied Bindings](../spec/source-access.md#copied-bindings)).
- **What it removes.** The content the manifest names and the binding's own leftovers in the ledger go through `synchronization/datablock_removal.py`'s `remove_unused`, the removal that cleanup and retirement share. The leftovers are the binding's managed content too, so removal disposes of them and resolves their entries. A leftover that fails again keeps its ledger key and code with a fresh diagnostic, as a retry gives it. One anything else uses is released intact (OWN-15).
- **Objects are unlinked first.** The managed objects are unlinked from the destination before their users are read, as publication unlinks what retirement removes. Otherwise, once a view layer has bases, the Scene counts as a user of every object in the destination, and everything would be released instead of removed. Each object released intact is linked again. A leftover stays unlinked, so it's inactive.
- **The destination goes only when nothing else needs it.** It's removed, taking the binding's records with it, when it then holds nothing and only the collections and scenes linking it, and the binding index's entry, use it. Otherwise only the binding's records come off, and it stays as an ordinary collection. Removing it would break the collection links of unmanaged content linked into it (OWN-07).
- **The binding index's entry is removed,** as [Canonical Candidate](../spec/source-access.md#canonical-candidate) says, so no entry names a destination that stays without the binding's records.
- **The scenes' stored source selections keep the binding's entries,** reported unresolved, as a removed destination's are. Undoing the removal resolves them again.
- **Docs:** the matrix rows (OWN-14, API-08) get this plan's delivery and their oracles. The bindings README lists the call, and M11's milestone says what remains of its Remove binding work.

### The Stage Output node

- **A Scene property,** a pointer to the scene the binding displays in. A suggested default: `init` sets it to the context's scene, as `init` already sets a tree's only Viewer. A Stage Output with no scene has no binding, and the node and the Cook panel say why.
- **The coordinate conversion property** the node already carries becomes the binding's setting, through `set_settings(coordinate_conversion=...)` before each synchronization.
- **A stored binding identifier,** a hidden string property on the node. It's front-end state: `cook_tree_layer` doesn't write it into the tree's layer, so the cook never sees it.
- **Duplicating a Stage Output clears its binding identifier,** so the copy makes a binding of its own on its next cook, as a new node does. A suggested mechanism is the node's `copy` callback. Copy-and-paste goes through it too, and so does copying a whole tree (open question 3).

### Cooking

On each cook, for each Stage Output, keyed by node ID:

1. **Find or make its binding.** If the stored identifier names a binding in the node's scene, use it. Otherwise, call `create_binding(scene, name=...)` and store the new identifier. The name is suggested to be the tree's and the node's names. A stored identifier can name no binding in that scene because the user deleted the destination, an undo removed the binding, or the node's scene changed (see below).
2. **Attach the stage, if it's a new one.** That happens when the binding has no live stage or a different one. Pass `confirm=True`: the front end owns these stages, and their anonymous root layers get new identifiers after every file reload, and whenever a relink gives the node a different root.
3. **Set the conversion setting, then synchronize** at the scene's current frame.
4. **No stage:** a Stage Output that's unlinked, or whose input failed, keeps its binding and its last display, and the binding is released. The cook's own diagnostic says why.

- **The Cook operator keeps `{"REGISTER"}` without `UNDO`,** since each synchronization that publishes pushes its own undo step. A cook therefore pushes one step per Stage Output it changes, and one that changes nothing pushes none (UNDO-10). Whether a cook should be one step is open question 4.
- **A raise for one Stage Output,** a defect or a record that can't be read, is reported as that Stage Output's failure, and the others still synchronize.
- **The report** names each Stage Output's binding and its synchronization result. The operator's summary counts the synchronizations that failed.
- **Kept cooks:** loading a file drops the kept cooks, and the synchronizer's own handler drops the bindings' stages. The next cook attaches again, with confirmation. Nothing holds a stage across a load.

### Removing bindings

- **Changing a node's scene** removes its binding in the old scene. The node then makes a new one in the new scene on its next cook.
- **A deleted Stage Output's binding is removed on the next cook.** The tree records which bindings its nodes made, for example as a hidden collection property of identifiers. A cook records each binding where it makes it, so a binding that a scene change leaves behind, when the node makes a new one in its new scene, is in the record too. A cook removes each recorded binding that no Stage Output still names, and drops it from the record. A suggested reason not to remove it from the node's `free` callback: Blender also frees nodes when it frees a tree, on a file load or an undo step's reload, and removing bindings then would delete them for good.
- **A copied tree** names no bindings of its own, since the copies' nodes are cleared (open question 3). Its record starts empty, so it removes nothing the original made.
- **Deleting a whole tree** leaves its bindings in their scenes as ordinary bindings. The user can remove each one through the binding UI.
- **The binding UI** gets a Remove button that calls the new removal call, so a binding left behind can be removed without deleting its collection by hand.
- **A binding that isn't usable can't be removed,** whether its configuration can't be read or it's a copy with no canonical candidate. Removal refuses it, as the other operations do, so the binding UI shows why and offers no Remove button. **Nor can a binding with copies,** though its canonical candidate is usable: the binding UI offers it Synchronize, but no Remove button, and says why. That's accepted until M11's repair work (make a new binding, or detach): until then, the user deletes a copy's collection by hand, which removes it with its records ([Removed Destination](../spec/lifecycle.md#removed-destination)).

### Reload

A binding's `reload` would reread the zones' anonymous layers and discard what the cook wrote ([node-tree.md](../phase3/node-tree.md), "Reload"). Until that question is settled, the binding UI doesn't offer Reload on a binding a Stage Output made, and the Cook panel says to cook again instead. Telling the bindings apart needs no record of its own, since it's a lookup of the trees' recorded identifiers.

## Steps

Each step is one commit, with its tests and docs.

1. **The removal call** in `proscenium_sync`, with its spec-row updates, and tests for removal, undo and redo, reentrancy, and preserving unrelated content.
2. **The Remove button** in the binding UI.
3. **The Stage Output's scene and binding identifier,** and clearing the identifier on duplicate. The tree's layer doesn't change, and `test_cook_tree_layer` checks that it holds neither property.
4. **Cooking into bindings:** find or make, attach, set the conversion setting, synchronize, and report. `cook-module.md`'s "A minimal front end" entry changes, since the cook now hands stages to bindings.
5. **Removing the bindings of deleted nodes and changed scenes,** through the tree's record.
6. **Hiding Reload** for Stage Output bindings.

## Tests

These are Blender-layer tests, building the tree through bpy as the cook tree tests do:
- A cook makes one binding per Stage Output, in the node's scene, and displays its stage. A second cook reuses the binding and its live stage, and a change to the tree updates the display.
- Duplicating a Stage Output gives the copy its own binding on its next cook, and leaves the original's unchanged.
- Deleting a Stage Output and cooking removes its binding and content, and keeps the other Stage Outputs'. Undo restores both the node and the binding.
- Changing the node's scene moves its binding.
- After the file is saved and reopened, a cook attaches the new stage to the same binding.
- A Stage Output with no scene, or with nothing linked, makes no binding, and the cook says why.

## Open questions

1. **How much of M11's removal comes forward** (settled by step 1). Remove binding's full failure safety needs M11's decision record on retaining unresolved ownership information. This plan delivers removal with the ledger keeping failed disposals as it does now, which is OWN-14 and API-08 on the success path and on a failed disposal. M11 keeps the decision record, cleanup that reaches the ledger entries of a binding that no longer exists, fault injection at each commit point, and `F-LIFECYCLE-FAILURE`.
2. **Whether a cook synchronizes every Stage Output, or only those whose stage changed.** Step 4 synchronizes every one that has a stage, so this decides whether to skip the unchanged ones. `possibly_out_of_date()` tells which bindings may be stale. Incremental synchronization makes an unchanged one cheap, but how cheap a recooked zone's transfer is hasn't been checked ([node-tree.md](../phase3/node-tree.md), "Incremental synchronization").
3. **Copying a whole tree** (settled for a copy by step 3). Blender calls each node's `copy` callback when a node tree datablock is copied. **Checked:** after `tree.copy()`, the copy's Stage Output had no identifier and the original's kept its own. Whether appending a tree from another file calls it isn't checked. If it doesn't, one fix is to clear any identifier that the tree's own record doesn't list.
4. **Whether a cook should be one undo step.** Each synchronization that publishes pushes its own step, so undoing a cook that changed N Stage Outputs takes N steps. Making it one needs the synchronizer to let a caller group several operations into one step, which is an API change and would need its UNDO requirements revisited ([Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state)).
