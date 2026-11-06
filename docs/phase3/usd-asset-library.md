# USD Asset Library

How USD assets could be offered through Blender's asset system, so a user browses them by category and drags one into the scene to create a binding. This is a design note, not a requirement ([Phase 3 notes](README.md)).

Every claim marked **Checked** was run against the bpy 5.2.2 wheel in the dev environment. The wheel has no UI, so nothing here has been checked by an actual drag or click in the Asset Browser or an asset shelf; those claims are marked **Not checked**.

## Assets are `.blend` data-blocks

The asset system lists only data-blocks marked as assets in `.blend` files. It cannot list `.usd` files. Each USD asset is therefore offered through a **stand-in**: a small data-block, such as an empty Object or a Collection, marked as an asset and carrying a reference to its USD file and prim in a custom property. A library-generating tool scans a folder of USD assets and writes the stand-ins, with previews, catalogs, and tags, from background Blender. Proscenium's own synchronization could render the previews.

- **Checked:** `ID.asset_mark()` accepts any data-block from Python, including a custom node tree, a Text, a Mesh, and an Image. The Asset Browser lists only some data-block types (objects, collections, materials, worlds, node groups, actions, brushes); this list wasn't checked for 5.2.
- **Checked:** custom properties on the data-block and on its `asset_data` survive a save and an `assets_only` load. Properties defined with `bpy.props` are stored as system properties in 5.x, readable through `bl_system_properties_get()` rather than `.get()`. Without the registering extension, a custom node tree loads as `NodeTreeUndefined` with its data intact and becomes its own type again once the classes are registered.
- **Checked, not explained:** `bpy.data.libraries.write(path, {tree})` on a custom node tree crashed the wheel process. `bpy.ops.wm.save_as_mainfile` wrote the same tree. A library-generating tool should check its write path in the Blender binary.

## A stand-in is never a binding

If a stand-in were a destination collection with a binding record, each drop would copy the binding, and a second drop would disable every candidate ([Copied Bindings](../spec/source-access.md#copied-bindings)). A stand-in holds only the reference to its USD source, and each drop creates a new binding through the API. A linked stand-in is library data and is never a candidate, so linking one has no effect on copy detection.

## Where the assets appear

Two mechanisms give USD assets their own place, and they combine:

- **An asset library:** a folder registered under Preferences → File Paths → Asset Libraries, listed as its own entry in the Asset Browser. **Checked:** `context.preferences.filepaths.asset_libraries.new(name=..., directory=...)` registers one from Python, and its `import_method` can be set; a new library's default is `PACK`. Registering a library changes the user's preferences, so it would be an operator or a setting the user chooses, not something the extension does when it registers. Each asset can override the library's import method through `asset_data.preferred_import_method` with `use_preferred_import_method`.
- **Catalogs:** a hierarchy such as `USD/Props/Furniture`, defined in `blender_assets.cats.txt` at the library's root. An asset joins a catalog by `asset_data.catalog_id`, the catalog's UUID. The generating tool could derive catalogs from the USD asset folders or from USD metadata such as `kind` or `assetInfo`. Tags filter further. **Checked:** `catalog_id` and the import-method fields exist on `AssetMetaData`. **Not checked:** that a generated catalog file displays in the Asset Browser.

Suggested: a dedicated "USD Assets" library whose import method is Link, with catalogs generated from the USD folder structure.

## Adding assets

The preferred route is an asset shelf whose operators create the binding. Two other routes exist.

### Asset shelf (preferred)

An `AssetShelf` subclass shows only the USD stand-ins in a shelf in the 3D viewport, and names Proscenium operators for clicking and dragging an asset:

```python
class VIEW3D_AST_proscenium_usd(bpy.types.AssetShelf):
    bl_space_type = "VIEW_3D"
    bl_activate_operator = "PROSCENIUM_OT_add_usd_asset"  # click
    bl_drag_operator = "PROSCENIUM_OT_add_usd_asset"      # drag
    bl_options = {"NO_ASSET_DRAG"}

    @classmethod
    def asset_poll(cls, asset: bpy.types.AssetRepresentation) -> bool:
        return "USD" in asset.metadata.tags
```

- **Checked:** a shelf like this registers, with `bl_activate_operator`, `bl_drag_operator`, and `asset_poll(asset: AssetRepresentation)`. `bl_options` offers `NO_ASSET_DRAG`, `DEFAULT_VISIBLE`, `STORE_ENABLED_CATALOGS_IN_PREFERENCES`, and `ACTIVATE_FOR_CONTEXT_MENU`.
- **Checked:** the shelf passes the operator the asset as *asset reference properties*. Blender's own shelf operators (`brush.asset_activate`, `poselib.apply_pose_asset`) declare them as `asset_library_type`, `asset_library_identifier`, and `relative_asset_identifier`, so a Proscenium operator would declare the same three.
- **Not checked:** that `NO_ASSET_DRAG` stops Blender from also appending the stand-in when a drag operator is set. That is a reading of the option's name.
- **Not checked:** whether the operator can read the stand-in's USD reference without loading its `.blend` file, for instance from `asset_data` custom properties seen through `AssetRepresentation.metadata`. If it can, nothing is imported: there is no stand-in to clean up, and the operator just creates the binding. If not, it reads the stand-in with `bpy.data.libraries.load` and removes it.
- **Not checked:** placing an asset where it is dropped. Blender's pose drag operator (`poselib.blend_pose_asset`) is modal and has a `release_confirm` property, which suggests a drag operator that tracks the cursor and acts on release.

The operator gives the drop its own options (time code, payload policy) and undo step, like any other Proscenium operator.

### Import handler

Dropping a stand-in from the Asset Browser appends or links it. A `bpy.app.handlers.blend_import_post` handler sees the marker and creates a binding. **Checked:** with `wm.append` and `wm.link`, not with a drag, the handler receives a `BlendImportContext` whose `import_items` each give the imported `id`, its `id_type`, and its `append_action` (`MAKE_LOCAL` for append, `UNSET` for link). The stand-in's custom properties are intact.

### File handler

A `bpy.types.FileHandler` with `bl_file_extensions` for USD lets a user drag `.usd` files from the operating system's file browser into the viewport, calling an operator through `bl_import_operator`. It needs no library, but offers no previews or catalogs. **Checked:** the type exists in 5.2.

## Open questions

- **Where a dropped asset lands.** A drop has a position under the cursor, but the spec gives a binding no Blender-side placement. Either a binding gains a root transform, a spec change touching [transforms](../spec/support/transforms.md) and [ownership](../spec/lifecycle.md#ownership-and-lifecycle), or a dropped asset appears at its USD position.
- **One binding per asset, or one stage.** One binding per dropped asset fits the current spec. Composing dropped assets into one stage, as references, authors USD.
