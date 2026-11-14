# Property Viewer UI

How Phase 3's stage editor shows one prim's properties in Blender, beside the [scene graph](scene-graph-ui.md): a list of every property the prim has, with each relationship's targets under it, and a summary of the selected property, in the widget in [`src/proscenium/ui/property_viewer_widget/`](../../src/proscenium/ui/property_viewer_widget/README.md) that a host places. This is a design note, not a requirement ([Phase 3 notes](README.md)). Like the scene graph, the widget reads a stage its host gives it, and selects through no source selection model, shows no edits through bindings, and pushes no undo step ([DECISIONS.md](../DECISIONS.md) "Phase 3 ordering").

It's built as the scene graph is, a virtualized `UIList` over a model kept apart from drawing, and shares its parts: the columns, header, and settings popover (`ui/columned_list/`), the search box (`ui/search_box.py`), the tree rows' widths, guide lines, and badges (`ui/widget_resources/tree_rows.py`), the badge icons and copy-path operator (`ui/widget_resources/`), and the timers (`ui/widget_updates.py`). What the scene graph note says of those parts, their measurements included, holds here.

Evidence is marked as in the other notes:
- **Checked:** run on Blender 5.2.2 LTS (USD 0.26.3) on one macOS machine, in the binary's 3D View sidebar through `tools/scene_graph_demo.py` on `tests/fixtures/scenes/property_viewer/property_kinds.usda`, and screenshotted, once at UI scale 0.75 and once at 0.5.
- **Tested:** covered by the widget's tests, `tests/bpy_free/test_property_list.py` and `tests/blender/test_property_viewer.py`, which run in the bpy wheel and draw nothing.
- **Not checked:** reasoned from documentation or code, but not run here.

## The widget

`property_viewer_widget/` has the scene graph's two units, by the [import rules](../../src/proscenium/README.md#import-rules):
- **`property_list/`, the model, just above the lowest tier,** imports nothing of Blender's: which properties a list shows (`property_search`), the rows and what's read of each property (`property_list`), what the list says about a property (`property_descriptions`), worded from what was read with no USD queries of its own, and one list as a widget shows it (`property_list_view.PropertyListView`), with its stage, the prim shown, its selection, query, time code, and the stage changes it follows.
- **`display/`, beside the scene graph's display,** only draws and forwards input to a `PropertyListView`.

### What a host does

1. **Registers it** with `display.register()`: its classes, a collection on the window manager, its views' key watching, and a load handler. Registering it with the scene graph shares their common classes and icons, kept while either is registered. **Tested.**
2. **Creates a view** per place it shows a list, by name: `create_view(name, shows_in_region, on_selection_changed)`. `shows_in_region(area, region)` says whether a region is showing the view now, for the key watcher, and `on_selection_changed` hears the selected property's path.
3. **Gives each view a stage**, `set_stage(name, stage)`, and then **a prim on it**, `show_prim(name, path)`, as from a scene graph view's `on_selection_changed`. A view can show its values at a time code, `set_time_code(name, time_code)`, such as the scene's current frame's (USD time code t is Blender frame t); it starts at the default time code.
4. **Takes its jumps,** if it gives `create_view` an `on_jump_to_target(path)`: each target's row then has a jump button, which hands the host the target's path to select where it shows it, as in a scene graph. The widget selects nothing itself, since it knows nothing of the scene graph.
5. **Draws it** by calling `draw_properties(layout, context, name)` and `draw_metadata(layout, context, name)` from its own panels' `draw`.

`tools/scene_graph_demo.py` hosts both widgets in each editor's sidebar: the scene graph's panel, then a Property Viewer panel showing the properties of the prim its scene graph selects, then a Property Metadata panel summarizing the selected property. It sets each view's time code from the current frame. Its jump callback selects the target's prim in that editor's scene graph and shows its properties, and for a target that's a property, as a connection's source is, selects that property too. **Checked:** a jump to Ball's `/World/Sun` target selected Sun in the scene graph and showed its properties.

Each list is 10 rows tall at most before it's dragged taller, and shows fewer when it holds fewer; it can be dragged down to 3, so a scene graph and a property viewer fit one above the other in a sidebar. The scene graph's lists are the same.

## Keyboard

The list's keys work as the scene graph's, through the watcher the widgets share (`widget_resources/list_keys.py`; [Keyboard](scene-graph-ui.md#keyboard)): Right shows the selected property's targets, or steps into its first one if they show; Left hides them, or steps out of a target to its property; Shift with either shows or hides every property's targets, as a Shift-click on a chevron does. Up and Down move between rows, and a view whose search text is being typed leaves Left and Right to its text box. A host says which regions show each view (`create_view(name, shows_in_region, on_selection_changed)`), for the watcher. **Tested:** each step, in the model; and by `tests/isolated/test_list_keys.py`, in a window with simulated events on macOS 5.2.2, a scene graph's panel and a property viewer's in one Properties editor: Right over the property viewer's row showed its first property's targets and told only its host, and then Right over the tree's row expanded the tree's, leaving the property viewer as it was.

## The model

- **Only authored properties show at first,** in the prim's property order (`GetProperties`); turning off the search box's authored-only toggle shows the prim's schemas' unauthored ones too. **Tested:** a Sphere with two applied schemas shows 15 of its 25, and all 25 with the toggle off.
- **A property's targets show under it.** A relationship's targets, and an attribute's connections, are its targets; a property with any has a chevron, and expanding it splices a row per target in after its own, indented one level with a guide line from the chevron. A target's row toggles and selects as its property's. **Tested.**
- **Selection and expansion are kept by property name,** so showing another prim keeps the same property selected and the same ones expanded where the prim has them, and one property can be compared across prims. A selected target stays selected where the new prim's property has that target, and otherwise its property is selected. **Tested.**
- **Details are read when a row first draws,** at the view's time code, and cached until the stage or the time code changes; the metadata panel's are read when it first asks.
- **Stage edits reach the rows after the edit.** The view listens for `Usd.Notice.ObjectsChanged`, marks itself changed, and its timer reads the prim's properties again once the edit is over. Any resync, or a field change on the shown prim or its properties, reads them all again: one prim's properties are few, and a relationship's targets change by an info-only notice, so a cheaper path for values would miss them. Another prim's field changes nothing shown. **Tested:** a value, an added attribute, and an added target each show after the read; another prim's metadata marks nothing.
- **The view holds no stage.** It holds the stage's pseudo-root, so once the stage's last owner drops it, the view shows "Stage closed" and selects nothing. **Tested.** A removed prim leaves the view showing "No prim at" its path, which shows again if a prim comes back there.
- **Where a value comes from** is `Usd.ResolveInfo`'s source at the view's time code, the time its value is read at: a schema's fallback, for an attribute no layer has a value for; an authored default value, which holds at every time code no animation overrides; time samples, value clips, or a spline; or none. A fallback and an authored default are told apart in the tooltip and the metadata panel ("Schema fallback", "Authored default value"), and a fallback's row is dimmed. A host shows values at the scene's frame, so it reads at numeric time codes; at the default time code, where a view starts, an attribute with only time samples has no value and no badge. **Tested.**

## The prim's summary

Above the list, the view says what its prim is, as the scene graph's row tooltip does ([Icons and tooltips](scene-graph-ui.md#icons-and-tooltips)), compacted:
- its path;
- its type, specifier, and kind on one line (`Type: Xform   Spec: Def   Kind: component`);
- anything unusual: inactive, a kind its ancestors don't support, an instance proxy;
- its instancing and each composition arc with its targets, a line each, led by the scene graph's badge for it, greyed out as the scene graph greys it, as for an unloaded payload.

Its lines are three quarters of a row's height apart, closer than rows, since they're text. A label too long for its region would show with its middle cut out for an ellipsis, so a line too long for the region wraps instead (`ui/text_wrapping.py`): it's measured with `blf` in the UI's font at its scale, and breaks after a slash, dot, colon, comma, or space, so a path breaks between its elements and shows whole. The metadata panel's lines wrap the same way. **Checked:** in the binary, `/World/Geometry/Crates/Crate_Unique.xformOpOrder` in the metadata panel wrapped after `Crate_Unique.`, with no ellipsis. They're worded as the scene graph's tooltip words them, by what the widgets share (`widget_model.prim_detail_text`, from what `widget_model.prim_details` reads of the prim), read once per list, so again after any stage change that touches the prim. The status line, which counts the properties the search shows, is below the search box, with the settings gear. **Tested:** a prim with a kind, an inherit, and a reference, its badges, an unloaded payload's greyed badge, an instance's badge, and that deactivating a prim adds "Inactive". **Checked:** in the binary, on `prim_kinds.usda`'s `Crate_Unique`, at three quarters of a row's height: the lines read clearly, and the badges kept their shape.

## A row

| Column | Shows |
|---|---|
| Name | A target's indent and guide line; the chevron, on a property with targets; the icon; the property's name, or a target's name (its prim's, and a property's after a dot); and the keyframe icon. With the Value column hidden, a target's row shows its full path and jump button here. |
| Value | On a target's row, its jump button and its full path, red if the stage has nothing there, when the button is disabled. Otherwise, the value at the view's time code, as a layer writes it: numbers to six significant digits, a float always with a decimal point (`1.0`, where an integer is `1`), `true` and `false`, strings quoted, asset paths as `@path@`, and an array as its length and its first eight elements (`[12] 0, 1, …`). A relationship shows its target, or its count and first targets; an attribute with connections and no value, `→` its source; a blocked value, `None (blocked)`. |
| Type | Hidden by default. The declaration as a layer writes it before the name: `custom`, `uniform`, and the value type (`custom uniform token[]`), or `rel`. |
| Copy Path | The shared copy button, copying the property's path, or a target's. |

Which columns show, and their widths, are in the settings popover, as the scene graph's. Type is hidden by default, since a row's tooltip and the metadata panel give its declaration; shown, it's 5 units, and Copy Path a button's width. Value takes a share of what they leave, 60% by default and 50% to 90%, and the name the rest, so Value stays wider than the name at any width. The name keeps at least 4 units, the chevron, icon, and a few letters, and in a region too narrow for that, the columns shrink. Without a region's width to read, Value is 7 units. **Checked:** at the 3D View sidebar's factory width, at UI scale 0.75 and a share of 65%, Value took about twice the name's width, which kept three or four letters of each name. **Not checked:** the 60% default.

- **Icons:** a relationship's `LINKED`, an attribute with connections' `NODETREE`, a primvar's `GROUP_VCOL`, an xform op's (`xformOp:*`, `xformOpOrder`) `ORIENTATION_LOCAL`, any other attribute's `DOT`, and a target's `FORWARD`. **Checked.**
- **Dimmed when unauthored:** a property no layer has an opinion on, which shows its schema's fallback, draws dimmed, as an inactive prim does in the scene graph. **Checked.**
- **Red when a target is missing:** a target the stage has nothing at (no object for a relationship's, no property for a connection's) draws in the alert's red. **Checked.**
- **The keyframe icon:** an animated value, from time samples, a spline, or value clips, gets a diamond after its name, outlined in the Dope Sheet's keyframe border as Blender's keyframes are, and filled in the color Blender gives an animated property's field: its keyed color (the theme's State `inner_key`) when the value has a key at the view's time code, a time sample, a clip's sample, or a spline's knot, and its animated color (`inner_anim`) between keys. A single time sample is a key at its own time code and between keys elsewhere, as in Blender. The icons are drawn again when the theme's colors change (`widget_resources/keyframe_icons.py`). The tooltip names the source and says which ("From 3 time samples; a key at this time code"). **Tested:** a key and between keys for time samples, a single sample, a spline, and value clips, and the icons' fill and border colors. **Checked:** in the binary at frame 2, the keyed color on `xformOp:translate`, keyed there, and the animated color on two values between keys.
- **Tooltips:** a row's says its path, declaration, value, where the value comes from, a primvar's interpolation, and its targets, and a target's says whose target it is and whether it's missing; the triangle's says what a click does. **Tested:** the text.

## Search

The search box filters the properties by name, path, glob, or regular expression, as the scene graph's matches text, and a toggle, on by default, shows only authored properties. A property list is flat, so nothing shows for holding a match, and an expanded property's targets show with it. An invalid regular expression shows every property, with the error on the status line. **Tested.**

## The metadata panel

`draw_metadata` lists a summary of the selected property, its lines as close together as the prim summary's: its path, declaration, value and source, its time samples' count and range, a primvar's interpolation and element size, its target count and the selected target, its display group, how many layers have an opinion on it and the strongest, and its documentation. A full metadata view, every field of every opinion, is for later.

## Open questions

- Should a namespace (`primvars:`, `xformOp:`, `collection:lights:`) group its properties under a row of its own, as a tree?
- How should a value too long for its cell, such as a matrix or a long array, be read in full: its tooltip, the metadata panel, or a popup?
- Where do edits to values go, once Phase 3 edits the stage?
