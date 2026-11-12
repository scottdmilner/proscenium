# Scene Graph Rows

What a row of the [scene graph widget](scene-graph-ui.md) could tell a user: every piece of data a row carries, and every control a `UIList` row has over how it looks, for pairing each piece of data with the control that shows it. This is a design note, not a requirement ([Phase 3 notes](README.md)).

The data comes from [Compared with usdview and Solaris](scene-graph-ui.md#compared-with-usdview-and-solaris) and the widget's own rows. The controls come from [What a UIList can show](scene-graph-ui.md#what-a-uilist-can-show) and [Colors](scene-graph-ui.md#colors). Evidence is marked as in that note:
- **Checked:** run in the Blender 5.2.2 binary on macOS. The Unicode text styles (A4–A7) and colored label icons (A9) come from one-off probes that drew them in a `UIList` in the 3D View sidebar and were screenshotted. The rest come from the demos in [`tools/feasibility/uilist_options/`](../../tools/feasibility/uilist_options/README.md) or the proof of concept.
- **Not checked:** read from the RNA only.

## Data

"Now" is what the widget shows today. **Editor state** marks data that isn't on the stage, but kept by the editor, as Solaris keeps solo, selectability, and its viewport-only overrides; it exists only once Phase 3 defines it. "Shown by" is for the pairing, by the controls' IDs.

| ID | Data | Values | Now | Shown by |
|---|---|---|---|---|
| D1 | Name | text | label | |
| D2 | `displayName` | text, or none | in place of the name, chosen from the header's menu | |
| D3 | Path | text | tooltip | |
| D4 | Depth | integer | indentation | |
| D5 | Has children, is expanded | none, collapsed, expanded | triangle | |
| D6 | Type | schema name | icon and type column | |
| D7 | Kind | component, assembly, group, subcomponent, other | a column, and its icon in place of the type's; tooltip, details | A20, A9 |
| D8 | Invalid kind or model hierarchy | yes or no | its kind icon, and its kind in the Kind column, red (A2); tooltip | A2 |
| D9 | Specifier | def, over, class | a class's name italic (A5); an orphaned over red (A2); tooltip | A5, A2 |
| D10 | Active | active, inactive | dimmed | |
| D11 | References | yes or no, and their targets | a badge after the name; its targets in the row's tooltip; details | A11 |
| D12 | Inherits | yes or no, and their targets | a badge after the name; its targets in the row's tooltip; details | A11 |
| D13 | Specializes | yes or no, and their targets | a badge after the name; its targets in the row's tooltip; details | A11 |
| D14 | Payload | none, loaded, unloaded | a badge after the name, greyed out when unloaded; its targets and state in the row's tooltip; details | A11 |
| D15 | Inside an unloaded payload | yes or no | — | |
| D16 | Variants | which sets it has, and each set's selection | a badge after the name, greyed out when no set has a selection; the selections in the row's tooltip; details | A11 |
| D17 | Instance | yes or no | details | |
| D18 | Instance proxy | yes or no | details | |
| D19 | Search role | a match, an unmatched ancestor, or no search | unmatched ancestors dimmed | |
| D20 | Selected | yes or no | the active row | |
| D21 | In a selection of several prims | yes or no | — | |
| D22 | Ancestor of the selection | yes or no | — | |
| D23 | Last sibling, and for guide lines, whether each ancestor is a last sibling | yes or no per level | — | |
| D24 | Visibility | visible, invisible; inherited or its own; animated | | |
| D25 | Guide visibility | as visibility | | |
| D26 | Draw mode | default, origin, bounds, cards; inherited or its own | | |
| D27 | Purpose | default, render, proxy, guide | | |
| D28 | Populated | not, a child, from an ancestor, explicit | | |
| D29 | Loaded | not, a child, from an ancestor, explicit | details | |
| D30 | Solo | three states; lights and geometry separately | — **Editor state** | |
| D31 | Selectable | yes or no; inherited | — **Editor state** | |
| D32 | Bound material | name and path; inherited or its own | — | |
| D33 | Proxy prim | path, or none | — | |
| D34 | Override | none, viewport-only, post-layer, both | — **Editor state** | |

## Controls

### Text

| ID | Control | Notes |
|---|---|---|
| A1 | Dim (`active = False`) | **Checked.** `enabled = False` looks the same, so the two can't mark different states. |
| A2 | Red (`alert`) | **Checked.** |
| A3 | Dim red (`alert` with `active = False`) | **Checked.** |
| A4 | Unicode bold (Mathematical Alphanumeric Symbols) | **Checked.** Serif or sans; the sans looks closest to Blender's Inter. |
| A5 | Unicode italic | **Checked.** The block has no italic digits, so digits stay upright. |
| A6 | Unicode bold italic | **Checked.** No italic digits. |
| A7 | Unicode monospace, or serif in place of sans | **Checked.** A further style, if more are needed. |
| A8 | Marker characters beside the name (`◇ ○ × • ◆`) | **Checked:** the UI font draws them. |

A1–A3 combine with A4–A7. A4–A7 are drawn by Blender's bundled `NotoSansMath`, and their widths were within about 10% of the plain text's. They style only the ASCII letters A–Z, a–z, and, except in the italic styles, digits: an underscore or a non-ASCII letter in a name (USD allows UTF-8 names) stays plain. The styled text is only drawn; the path a menu copies, the search, and the tooltip use the prim's own name and path.

### Icons and markers

| ID | Control | Notes |
|---|---|---|
| A9 | A label's icon | One per label: one of Blender's, which follows the theme, or a preview icon (`icon_value`) in any colors. |
| A10 | Blender's fixed-color icons (`COLLECTION_COLOR_*`, `STRIP_COLOR_*`, `COLORSET_*_VEC`, `LAYERGROUP_COLOR_*`, `KEYTYPE_*_VEC`, `COLOR_RED`, `COLOR_GREEN`, `COLOR_BLUE`, `ERROR`) | **Checked.** A fixed palette. |
| A11 | Preview-icon badges, drawn as unembossed operator buttons | **Checked**, in the proof of concept. Any color and shape, each with its own tooltip and click. |
| A12 | Socket dot (`template_node_socket(color)`) | **Checked.** Any color; a click on it doesn't select the row. |

A9's preview icons, **Checked** on labels with icons drawn from pixels in four colors:
- **Plain,** each drew in its own colors.
- **Dimmed** (`active = False`), it dims with the text, so a dimmed row keeps its icon's hue.
- **Under `alert`,** it keeps its colors, while the text and Blender's icons turn red.
- **Pixels are premultiplied:** a transparent pixel must be (0, 0, 0, 0). A pixel with color and zero alpha drew its color.

Blender's own icons in other colors, such as type icons colored by state, would be preview icons drawn from Blender's source SVGs for those icons, recolored. **Not checked:** no SVG was found or drawn.

### Background

| ID | Control | Notes |
|---|---|---|
| A13 | The active row's highlight | **Checked.** One row only. |
| A14 | A depressed or toggled button's fill | **Checked.** The selection color; a row-wide one takes the row's clicks. |
| A15 | A button's red background (`alert` on a button) | **Checked.** |
| A16 | `PIE_MENU` emboss | **Checked.** A dark background behind a button. |

### Structure

| ID | Control | Notes |
|---|---|---|
| A17 | Indentation | **Checked.** One `separator(factor=2.0)` per level. |
| A18 | Disclosure triangle | **Checked.** An operator button with its own tooltip. |
| A19 | Grid lines between columns and rows | **Checked.** Drawn with empty buttons squeezed thin. |
| A20 | A text column (label) | **Checked**, as the type column. |
| A21 | A property column: an icon toggle or a checkbox | **Checked.** Editable through a getter and setter over the prim. |
| A22 | An enum column: a dropdown, an expanded enum, a menu button, or a popover | **Not checked.** |
| A23 | A progress bar or ring | **Not checked.** |
| A24 | Hiding the row: the search, or toggles for which prims are listed | **Checked** for the search. |

### Hover and menu

| ID | Control | Notes |
|---|---|---|
| A25 | The row's tooltip (`item_dyntip_propname`) | **Checked.** Text only. |
| A26 | A button's tooltip (an operator's `description`) | **Checked.** |
| A27 | Items in the row's right-click menu | **Checked** ([The widget's right-click](scene-graph-ui.md#the-widgets-right-click)). |

### Beside the list

| ID | Control | Notes |
|---|---|---|
| A28 | The details panel, for the active row | **Checked.** |
| A29 | The status line above the list, an editor's header text, the status bar | **Checked** for the status line. |
| A30 | Header toggles choosing which columns show | **Checked** for the type column. |

### Not available

- **Any text or background color:** a label has no color argument, and a row's background can't be set.
- **Theme edits:** writing the theme's List Item colors restyles every list in Blender.
- **`scale_y` on a row:** breaks the active row's highlight.
- **Vertical lines:** `LINE` separators draw only horizontally.
- **`gpu` overlays:** a list's rows report no positions. **Not checked.**

Every row has the same columns, so each column (A20–A22) and each badge (A11) takes width from the name on every row.
