# Node Tree

The primitives of Phase 3's stage editor: a node tree whose nodes read USD layers, author new ones, and write them to files. This note covers the first feature set: how the tree cooks its layers, its socket types, its nodes, and the cook module that does the work. This is a design note, not a requirement ([Phase 3 notes](README.md)).

The tree's pass is a *cook*, as in Houdini: the tree cooks its layers, and a zone recooks when a change reaches it. "Evaluation" is the core's, reading a source through Hydra, and the glossary's *evaluation stage*; "build" is what a synchronization does to the display.

Evidence is marked as in the other notes:
- **Checked:** run headless in the bpy 5.2.2 LTS wheel (USD 0.26.3) on one macOS machine, an Apple M1 Max, each in one case unless stated, by throwaway probes that aren't in the repository. Some probes called a C++ module built against Blender's USD headers and linked to its `usd_ms` through `tools/native_build.py`. ALab is the production-scale fixture ([docs/testing/alab/](../testing/alab/)), at `entry.usda`.
- **Not checked:** reasoned from USD's or Blender's documentation, but not run here.

Everything not marked is design: what the editor should do, for the user to settle.

## Summary

- **The tree is the source of truth.** Every layer the tree authors is a function of the tree and the files it reads, recooked when a change reaches what it depends on. Written files are the tree's output; the tree never reads them back.
- **A layer read from a file is never authored into.** A Layer from File, and every layer it composes, holds the file as the process has it. Edits go into zones' layers, which are anonymous in memory and reach a stage only through links. A zone can own a file that a read layer composes, such as `lighting.usda` under a shot or a chair a set references: a Substitution Zone reads the root, names the files it composes as items, and puts each item's zone in that file's place everywhere the composition names it, and Write saves the zone to it. The zone's begin reads the root itself, so the tree has no second copy of the root without the zones; any other read layer that composes a zone's file warns.
- **Layers flow along links.** A *Layer* socket carries a finished layer; an *Editable Layer* socket carries a layer being authored, and exists only inside the zone that authors it, apart from the active Viewer's input.
- **A zone checks its edits against a context.** Its nodes see the zone's layer composed over a context derived from a Substitution Zone item's File: the layers weaker than the file's position, for a sublayer, or the file's own sublayers, for a reference's or payload's target, each with its own item's zone in its place. A Layer linked to its Context Hint input overrides it. The Stage Outputs' stages only verify, warning of edits a stronger opinion hides.
- **A node's place in its chain sets the order of authoring, not the strength of opinions.** Opinion strength is USD's: a layer's opinions are stronger than its sublayers', and a prim's own opinions are stronger than its arcs'.
- **Value sockets are USD's value types,** one per stored type (`float3`, `double3`, `quatf`, …), with roles such as `color3f` chosen where an attribute is created.
- **Prim sockets carry paths, not prims.** Each path is checked against the stage where it is used.
- **Stage Output nodes name the root layers of the tree's stages.** A tree may have several, each displayed by its own binding, and Write saves the zones any of them composes through links; any other zone warns that it won't be saved. A **Viewer** node names the stage the editor's UI shows, and saves nothing. Conversion between USD's and Blender's axes and units happens only where the tree meets Blender: at a Stage Output, and in later nodes that bring Blender data into a layer.
- **The tree cooks as a DAG.** A zone recooks when its own nodes change, when its Template changes, or when a change reaches something it read from another layer, and no other zone does work.

## Scope

The first feature set:
- Read USD layers from files.
- Read a composition, pick layers it composes, edit each in a zone, and substitute the zones into that composition, so the stage shows the whole composition with the edits.
- Author new layers, empty or from a template. In them, create and edit prims (type, specifier, API schemas, `active`, `kind`, `instanceable`), set or block attributes' default values, set transforms, author layer metadata, and author sublayers, references, payloads, variant sets, and relocates.
- Write the authored layers to their files.

Later:
- **Inherits and specializes,** with the same list-edit modes as Reference and Payload. `class` prims, which Create Prim can author, matter mostly as their targets.
- **Time samples and value clips.** Set Attribute authors default values only.
- **Array-valued attributes,** including primvars, which are arrays even when their interpolation is constant: `primvars:displayColor` is `color3f[]` (**Checked**). With them come attribute metadata and variability (`interpolation`, `elementSize`), and a source for their values: most naturally a node that writes a Blender object's data into a layer, converting from Blender's Z-up and unit scale into the zone's metrics. That bridge needs its own note.
- **Relationships and attribute connections.** A shader network is authored as connections (**Checked:** `color3f inputs:diffuseColor.connect = </…>`). Material binding follows from relationships and Edit Prim applying `MaterialBindingAPI`. A bridge from Blender materials to UsdShade needs its own note.
- **Collections and light linking.** Edit Prim applies `CollectionAPI`. A collection's membership expression is a `pathExpression` value, which a Prims socket could supply; includes and excludes need relationships.
- **Dictionary values:** `customData`, `assetInfo`, `customLayerData`, and attribute metadata such as `documentation` and `colorSpace`.
- **Layer offsets** on sublayers, references, and payloads.
- **For-each zones** over the prims an expression matches, and **math nodes** on USD value types.
- **A repeating Variant Zone,** landing with for-each zones, so the two share one rule for how a zone repeats and what its per-run outputs are. Several variants on one prim, such as five colors, then take one zone, not one per variant. The proposed design:
  - The begin node takes a list of variants (`red, green, blue, gold, black`), and the chain runs once per variant in list order, each run authoring into its variant. A one-item list is the Variant Zone of the first feature set.
  - New begin outputs: **Variant**, a `token` with the current run's variant name, and **Index**, an `int`.
  - A **Switch** node takes one value per variant name and outputs the current run's, like Geometry Nodes' Menu Switch. Five colors are one Switch feeding one Set Attribute. It's useful outside variants too, such as an asset's LODs.
  - The cook unrolls the zone. Each run is one linear chain, so the rule of one Editable Layer in one chain holds, and a Create Prim inside makes a spec per variant, since each variant's path differs. Reports name the variant they came from, and inspection shows one variant's result at a time.
  - **Not checked:** whether a Python node tree can use `NodeSocketMenu` with items that change, or the Switch needs its own enum property; how a `CollectionProperty` list looks on a begin node, drawn as a UIList.
  - To decide: which variant the composed stage displays (the first in the list, a Default property on the begin node, or only what a Set Variant Selection selects).
- **Asset paths** that Ar resolves, in a path property or a File input, which arcs author verbatim, for resolver URIs, search paths, and expression variables (`` `"{SHOT}"` ``).
- **A File In-Place Edit Zone,** which starts from its own file's content and writes back to it. Zones are separated by where their starting content comes from, not by who owns the file: a New Layer Zone never reads its file, while this zone reads it once and writes over it, a cycle. After a save the file holds the zone's edits, so a recook that read the file would apply them twice, and edits can't be made idempotent in general. The proposed design:
  - The zone recooks from a base it captured, never from the file, so changing a value recooks from the base.
  - **Save,** on the end node, writes the file and keeps the base, so the user can tweak and save again. It compares the file with the base before the first save, and with what it last saved after, and asks when they differ.
  - **Commit,** on the end node, saves, makes the written file the new base, and archives the chain as locked history that records its base's content hash. An archived chain can be reactivated only while the file matches that base, so it never applies twice.
  - Re-capture is allowed while the zone has never saved or its chain is empty, as after a Commit. It's how outside changes come in.
  - Its output is a Layer that composes through links like any zone's. Links from it are dashed, as a Context Hint link is, and warn that Write doesn't save the zone, which saves only from its own end node. Write warns when a zone it saves composes one with unsaved edits.
  - To decide: whether Commit archives or clears the chain; where the base lives (the `.blend`, or a sidecar file beside the target), since memory alone loses it when the `.blend` is reopened; how undo treats a Save or Commit, since the file and the base change outside Blender's undo.
- **`.usdz`** as a Write format, through `UsdUtils.CreateNewUsdzPackage`.
- **A transform stack socket and op nodes:** Translate, Rotate with its order, Orient, Scale, Matrix, and a Pivot node that wraps a stack in a pivot and its inverse, linked into Set Transform for full control of a stack. Reading a prim's composed stack into such a value lands with for-each zones, since a stack differs per prim.
- **Cooking a wave's zones in parallel** ([Cooking the Layers](#cooking-the-layers)).

## Cooking

### Layers as values

A *Layer* is immutable inside the tree: a layer read from a file, or the result of a zone. An *Editable Layer* is a layer under construction. An *authoring node* takes one Editable Layer in and gives one out.

A zone's **chain** is the sequence of nodes reached from its begin's Editable Layer output by following Editable Layer links, each from one node's Editable Layer output to the next node's Editable Layer input, up to and including its end; a link to the Viewer isn't part of it. Its nodes are *chain nodes*. A Variant Zone's begin and end are chain nodes of their parent's chain, and the stretch between them is the variant's own chain.
- An Editable Layer output links to one input, and may also link to the active Viewer ([Viewer](#viewer)). A branch would author edits that never reach the zone's end, or need a hidden copy to reach it.
- A Layer output links to any number of inputs.
- An Editable Layer never leaves its zone, apart from its link to the active Viewer. Its zone's end gives the finished layer out as a Layer.

### What a zone holds

A New Layer Zone or a Variant Zone holds its chain ([Layers as Values](#layers-as-values)). The chain is a single path, since an Editable Layer links to one input and never leaves its zone, so the cook finds it by following links forward from the begin. Membership decides which layer a node authors into and which stage it checks against; zones don't repeat in the first feature set, so it decides nothing that runs per element.
- **A Variant Zone is a stretch of its parent's chain.** A node's innermost zone is the innermost begin and end pair around it on its chain, and that zone's variant path is where the node authors.
- **A Substitution Zone holds the New Layer Zones its items' Files link into** ([Substitution Zone](#substitution-zone)). It authors nothing and has no chain: it decides which file each of those zones takes the place of, and which context it checks against.
- **Every other node belongs to no zone:** Prim, Match Prims, Value, Convert, Layer from File, the Stage Outputs, and the Viewer. Each outputs a value (a path, an expression, a constant, or a finished layer) and checks against no zone's stage. Matching and checks happen at the node that uses the value ([Where a Path Is Searched](#where-a-path-is-searched)), so a Prim node feeding two zones is cooked once and checked in each.
- **A chain node's value outputs may feed any node,** such as Create Prim's Prim output in one zone feeding a node in another, which then depends on that Create Prim ([Cooking the Layers](#cooking-the-layers)).

[Node Zones](node-zones.md#what-a-zone-holds)' prototype rule 1, every node downstream of the begin, would pull the other zone's node in through that Prim link. For layer zones, downstream runs along Editable Layer links only. For-each zones, later, add their own: downstream along the begin's per-element outputs, where a value node fed by the current element runs per element and belongs inside.

Errors, each following from the chain:
- **A branch:** an Editable Layer output linked to two inputs, other than the active Viewer, reported on the node that branches.
- **A broken chain:** the path from a begin doesn't reach its end, because it dead-ends or the end's input comes from another chain, which is also how an Editable Layer crossing into another zone appears. The end reports it, and each node past the break reports that its edits never reach the end.
- **An authoring node in no chain:** its Editable Layer input is unlinked or doesn't trace back to a begin. It reports it, and the nodes after it pass nothing on.
- **Overlapping zones:** pairs on one chain must nest as brackets, so begin 1, begin 2, end 1, end 2 is an error on both pairs. A Variant Zone whose begin isn't on a New Layer Zone's chain is an error.
- **A mismatched pair:** an end that the chain of a begin other than its own reaches. Pairs are named by a relationship ([The Tree as Plain Data](#the-tree-as-plain-data)), not by structure, so this is checked.
- **A Substitution Zone's own errors** are on its begin and its end ([Substitution Zone](#substitution-zone)). A New Layer Zone nested in one can hold a Variant Zone, and a Substitution Zone never sits on a chain.

Muted nodes stay on their chain and pass their Editable Layer through.

Drawing is the front end's, and the cook doesn't depend on it. A chain zone's outline takes its chain's members, and value nodes (Prim, Match Prims, Value, Convert) whose consumers are all in the zone, as Node Zones' rule 2 does. A Layer from File is never drawn inside one, since that would suggest the zone authors it, nor is a Viewer, including one linked partway down a chain, or a value node with consumers in two zones. A Substitution Zone's outline takes its begin, its end, the New Layer Zones it holds whole, and value nodes whose consumers are all inside it: it shows which edits go into that composition.

### Order of authoring and strength of opinions

A chain runs in order, and each node sees the stage as the nodes before it left it. That order decides:
- **Which value a field keeps** when two nodes set the same one: the later replaces the earlier, as USD does when the same spec is authored twice.
- **How list edits combine:** each node applies its edit to the layer's list op in chain order, as USD's editing API does ([List Edits](#list-edits)). Sublayers are a plain ordered list, not a list op: each Sublayer node appends, so an earlier node's layers are stronger.
- **What a node checks against:** the zone's stage ([The Zone's Stage](#the-zones-stage)). A prim created downstream doesn't exist yet for a node upstream.

It decides nothing else. Every opinion a layer holds is stronger than every opinion its sublayers hold, wherever its Sublayer node sits in the chain, and a prim's local opinions are stronger than those its references bring, wherever its Reference node sits. The node editor's inspection of a node should show strength as USD composes it, since the chain's order suggests otherwise.

#### List edits

Reference and Payload nodes edit a list op in one of four modes: Prepend, Append, Delete, or Explicit. Each node applies its edit in chain order, so the tree's result is what the same edits made through USD would give. **Checked**, by `UsdReferences` calls on one prim in one layer, each sequence in one case:

| Sequence | Resulting list op |
|---|---|
| Prepend `a`, append `b`, prepend `c` | prepended `[a, c]`, appended `[b]` |
| Prepend `a` and `b`, delete `a` | deleted `[a]`, prepended `[b]` |
| Delete `a`, prepend `a` | deleted `[a]`, prepended `[a]` |
| Prepend `a`, explicit `[b]` | explicit `[b]` |
| …then prepend `c` | explicit `[b, c]` |
| …then delete `b` | explicit `[c]` |

So:
- **Prepend and Append:** every prepended item is stronger than every appended one, whatever the chain order. Within each, an earlier node's item is stronger.
- **Delete** removes the item from what weaker layers contribute, and from what earlier nodes added in this layer. A later Prepend or Append of a deleted item adds it back: the delete still applies to weaker layers, and the add puts it in its new place, so the pair moves the item. That relies on composition applying a list op's deletes before its adds, which held for references and for `apiSchemas` (**Checked**):

| Weaker layer | Stronger layer | Composed, strongest first |
|---|---|---|
| references `[ra, rb]` | delete `ra`, prepend `ra` | `[ra, rb]` |
| references `[rb, ra]` | delete `ra`, prepend `ra` | `[ra, rb]` |
| references `[ra, rb]` | delete `ra`, append `ra` | `[rb, ra]` |
| references `[ra, rb]` | delete `ra` | `[rb]` |
| none | delete `ra`, prepend `ra` | `[ra]` |
| `apiSchemas` `[MaterialBindingAPI, GeomModelAPI]` | delete `GeomModelAPI`, prepend `GeomModelAPI` | `[GeomModelAPI, MaterialBindingAPI]` |
| `apiSchemas` `[GeomModelAPI, MaterialBindingAPI]` | delete `GeomModelAPI` | `[MaterialBindingAPI]` |

- **Explicit** replaces everything earlier nodes authored in this list in this layer. Later Prepend and Append nodes add to the explicit list in chain order, both at its end, and a later Delete removes from it. A node whose edit a later Explicit discards warns, since it authors nothing.

The node editor's inspection shows the resulting list op, since the chain's order alone doesn't show strength.

### The zone's stage

A zone's nodes check and search against its layer, as the chain has left it, composed over the zone's **context**. The zone's layer is stronger, and the context weaker. This is the stage Match Prims matches against, that Set Attribute reads attribute types from, that Prim search offers paths from, and that existence checks use. A department layer needs one: **Checked:** a layer opened as a stage on its own doesn't see a prim its sibling layer defines. The context is:
- **Derived from the File,** when the zone's File comes from a [Substitution Zone](#substitution-zone)'s item: the layers weaker than the File's position in that layer stack, such as `env.usda` for a `lighting.usda` that `shot.usda` sublayers above it. They're composed as the Substitution Zone outputs them, so a file among them that is another item's, or that they compose, is that item's zone: with env and lighting both items of the shot's zone, lighting checks against env's edits, the opinions the Stage Output shows under it. Inspection shows the derived context ("checks against `env.usda`, from `shot.usda`"). Once layer offsets arrive, the root's offsets carry over into it.
  - Positions come from the composition as read from files, which USD keeps acyclic, so a zone's context never holds the zone itself. The exception is a file composed both above and below another item, such as a `lighting.usda` that `shot.usda` sublayers and that a chair under `env.usda` also sublayers: its context would compose its own zone, and the item reports it.
  - For a File that a reference or payload targets, the derived context is the file's own composition, what every arc to it brings in: the layers it sublayers. So it doesn't depend on which occurrence the item names, since a file composed in several places is substituted at every one ([Substitution Zone](#substitution-zone)). Those sublayers sit under the file, not beside it, so once the zone takes the file's place they're composed only if the zone's own layer sublayers them. Two ways keep them:
    - **Edit a sublayer instead of the file.** A department usually edits one of an asset's sublayers, such as `chair_look.usda`, which the begin's search lists too; its context is the layers weaker than it in the asset's layer stack, and nothing is lost.
    - **Sublayer them explicitly,** to replace the file itself: the zone's chain has a Sublayer node for each, fed by a Layer from File, or by that item's zone for one that is itself an item, which a one-time action on the begin node can create. Those files aren't written, so there's no cycle.

    Reading them from the file the zone writes, as a Template or a live copy of its `subLayers`, would be the cycle that keeps a New Layer Zone from reading its own file: after a save, the zone's own sublayers would come back and be added again. The zone warns for each of the file's sublayers its layer doesn't sublayer, naming both ways.
- **The Layer linked to the Context Hint input,** which overrides the derived context. It's for a zone whose context no item can give: a layer that a root built in the tree sublayers, since a Substitution Zone reads only files; a layer meant to sit over something the tree doesn't compose, such as a fix delivered to another department; and a target that should be checked against more than its own sublayers.
- **Empty** otherwise.

The tree derives a context from nothing else, such as where the zone's output is linked, since relinking would then silently change what the zone checks against.
- The zone's End output carries only the zone's own layer. The context is never written or composed into it, as with Solaris's Layer Break.
- A zone sees only the context it's given. Opinions stronger than the zone in the final stage aren't visible to its checks, as in Solaris, where a LOP sees only what's upstream.
- A Context Hint link is an edge in the tree, so the tree's acyclicity rules out a zone's own output coming back as its context.
- Inside a Variant Zone, the stage has that variant selected.

A Context Hint link looks different from a link that composes, since it's only read for checks, and it's the exception: a File from an item needs no link. Two ways to draw it:
- **A dashed or dotted link.** Blender's `NodeLink` has no style property (**Checked:** its RNA properties are `is_valid`, `is_muted`, `from_node`, `to_node`, `from_socket`, `to_socket`, `is_hidden`, `multi_input_sort_id`), so a Python tree would draw its own overlay with the `gpu` module, as [Node Zones](node-zones.md) does for zone outlines.
- **A hollow socket shape** that stays hollow when linked. `NodeSocket.display_shape` offers `CIRCLE_DOT`, `SQUARE_DOT`, and `DIAMOND_DOT` beside the solid shapes (**Checked**, by listing the enum). **Not checked:** how a `_DOT` shape looks once linked. The socket shape is the cheaper option, since Blender draws it.

**Verification.** After the tree cooks, each zone's edits are also looked up in every Stage Output's stage that composes the zone, the full composition a binding displays, which includes layers stronger than the zone. When a stronger opinion there hides an edit, such as a Set Attribute value a stronger layer overrides, the node that made the edit warns, naming the Stage Output. The lookup only produces warnings: types, paths, and what a zone authors always come from the zone's own stage, so a zone's result never depends on where it ends up in the final composition. A zone no Stage Output's stage composes gets no verification warnings.
- **It looks up only the zone's own edits,** from the edit table ([Provenance](#provenance)), never the whole stage: for each property entry, whether the first spec in the output stage's `GetPropertyStack` is in the zone's layer, and for a prim field, the first spec in the prim stack holding the field. **Checked:** a value authored inside a variant had its strongest spec in the zone, at `/S{v=a}B.userProperties:x`; a value a stronger layer overrode had its strongest spec in that layer; a zone's `kind` had its strongest spec holding `kind` in the zone.

### Editing a layer in a composition the tree reads

A root the tree doesn't own often composes layers owned by different files, and the tree owns only some of them. For example, `shot.usda` sublayers `anim.usda`, `lighting.usda`, and `env.usda`, strongest first, and the tree authors only lighting. The user displays the whole shot while editing lighting:
1. A [Substitution Zone](#substitution-zone)'s begin reads `shot.usda`, and has one item, `lighting.usda`, picked from the files the shot composes.
2. The item's File links into a New Layer Zone's File input, inside the Substitution Zone. The zone's context is derived from that File: `env.usda`.
3. The New Layer Zone's end links into the item's input on the Substitution Zone's end, whose output feeds a Stage Output.

The begin reads the files, and the end makes the substituted copies, so there's no cycle. The zone is composed, so Write saves `lighting.usda` ([Writing](#writing)), and the read layers are never written. Verification warns where `anim.usda`, stronger than the zone, hides a lighting edit.

The zone replaces `lighting.usda` rather than editing it: a New Layer Zone never reads its own file, so when `lighting.usda` already exists, the zone warns that Write would discard its content. It can start from another file as its Template, such as another shot's lighting, but an item puts a zone only where the composition names the item's file, so keeping `lighting.usda`'s content while editing it waits for the File In-Place Edit Zone ([Scope](#scope)).

The same works at any depth: a zone can replace a sublayer of a sublayer, or an asset that a set references, such as `chair.usda` under `set.usda` under `shot.usda`. One Substitution Zone holds every zone edited in its root, as items of one begin and one end.

**The tree shows the root one way.** The root's file is read only by the Substitution Zone's begin, which has no Layer output, so every stage, Template, Context Hint, and arc that reaches the root gets it with the zones in place, the composition Write's files will make. Two rules keep other reads from showing a file as it was before Write:
- A Layer from File, or another Substitution Zone's root, that composes a zone's file without that zone in its place warns, naming the file and the zone. Two shots that reference one edited chair each read through their own Substitution Zone, and each has an item for `chair.usda` whose input takes the one chair zone's Layer.
- A Layer from File or a Substitution Zone reading a zone's file itself is an error on both ([Writing](#writing)).

**Every occurrence of the file is substituted.** Once Write saves the zone to its file, every arc to that file sees the edit, so substituting every occurrence makes the stage before Write match the stage after it. Substituting one occurrence would show a stage no written set of files can produce. Editing one occurrence is an override in a zone over the composition, or a new file referenced there. On ALab, one capacitor entity is named by 13 layers.

**The substitution is scoped to the Substitution Zone.** A layer holding a file's identifier would take that file's place in every stage in the process that composes its path. So every zone's layer is anonymous, and the Substitution Zone's end outputs anonymous copies that name the zone's layer in place of the file ([Substitution Zone](#substitution-zone)). Only what flows out of it sees the zone: other stages in the process, such as another binding or one Blender's own USD importer opened, see the files on disk. **Checked:** with `shot.usda` sublayering `anim`, `lighting`, and `env` on disk, a stage on such a copy had the layer stack copy, `anim`, zone, `env`, and the zone's value; a stage on `shot.usda` open at the same time had `shot`, `anim`, `lighting`, `env`, and the file's value; `Sdf.Layer.Find` of `lighting.usda` didn't return the zone; and neither stage reported composition errors.

### Cooking the layers

A zone's layer starts empty or as a copy of the zone's Template ([Templates](#new-layer-zone)), and the chain authors on top:
- **Each zone's layer is anonymous** (`Sdf.Layer.CreateAnonymous`), never holding its file's identifier, so it reaches a stage only through links ([Editing a Layer in a Composition the Tree Reads](#editing-a-layer-in-a-composition-the-tree-reads)). A Sublayer, Reference, or Payload node linked to a zone authors the zone's anonymous identifier, which Write maps to its file's path ([Writing](#writing)).
- **A zone cooks into a scratch layer, and its content moves with `TransferContent`,** so stages composing the layer see one change. **Checked:** after `TransferContent`, a stage referencing the layer composed its new content, and USD reported no errors. Clearing the layer and authoring into it again made the stage recompose in between, which reported the reference's default prim as unresolved.
- **Same tree, same layer:** an unchanged tree and unchanged inputs author the same content in the same order, so written files diff cleanly. **Checked:** Sdf kept root prims in the order they were created.
- **Converted values are kept while their inputs are unchanged.** `TransferContent` compares values, so an equal heavy array in a new buffer costs a full comparison, while the same `VtArray` costs nothing ([Measurements](#measurements)).

A zone no Stage Output composes ([Writing](#writing)) still cooks, so its nodes report errors and inspection shows its layer.

**The tree cooks as a DAG of tasks,** doing only the work a change requires. A New Layer Zone is one task, since its chain runs in order and each node sees the stage as the nodes before it left it. Layer from File is a task of its own, and so are a Substitution Zone's begin and its end, with the zones it holds between them. Value nodes (Prim, Match Prims, Value, Convert) carry no stage and are computed as inputs to the tasks that use them. A zone depends on other tasks three ways, each with its own rule:
1. **Its own content:** its nodes, and the value inputs into them, such as another zone's Create Prim's Prim output. The tree's change notices mark it ([The Tree as Plain Data](#the-tree-as-plain-data)), and the zone recooks.
2. **Its Template's content,** which is copied into the zone: any change to the Template's layer recooks it.
3. **What it reads:** its context, including the zones substituted into it, and the layers its chain's composition nodes name (Sublayer, Reference, Payload), whether another zone's output or a Substitution Zone's. A zone that references another authors only that zone's identifier, which stays stable since its layer is kept, so the other zone's content matters only through what this one read from it, such as a target prim's existence. It recooks only when a change reaches a recorded read.

The other tasks:
- **Layer from File** changes when its Path changes, and when its file is reread, on request ([Layer from File](#layer-from-file)); a reread layer's change notices then reach the tasks that read it.
- **A Substitution Zone's begin** reads its root as Layer from File does, then its sublayers and arcs; its items' files and positions are recorded reads of the root, matched as a zone's are.
- **A Substitution Zone's end** redoes its copies only when the root or the set of linked items changes ([Substitution Zone](#substitution-zone)). The copies name each zone's anonymous identifier, not its content, so they come before the zones they name: a zone whose context holds the copies reads its sibling zones through them, and recooks when a change reaches one of those reads.

So recooking a base zone, or an asset a shot references, recooks only the zones that read what changed. **Checked,** with zones of 10,000 prims ([Measurements](#measurements)): recooking one department cost 14 ms of C++ authoring, and its transfer and recompose rose from 13 ms with 2 zones to 33 ms with 8, then stayed flat at 32 zones; a structural recook of the base stayed at about 40 ms; recooking all 32 zones took 1.1 s with C++ authoring.

**Recorded reads.** Nodes read their zone's stage only through a reader that records each read, so a zone's output depends only on its content, its Template, and its recorded reads, by construction:

| Node | Reads | Affects the layer |
|---|---|---|
| Match Prims, at the node using it | which prims the expression matches | which prims get edits |
| Set Attribute | an existing attribute's type | the type authored |
| Set Transform | the composed `xformOpOrder` and which ops exist | whether it writes the order; After and Before copy it |
| Variant Zone | whether the prim has the variant set and variant | whether it authors them |
| Reports and verification | which prims and properties exist, `allowedTokens`, stronger opinions | diagnostics only |

Reads are kept by kind and path: a subtree (Match Prims, at its expression's fixed prefix: `/World/Set` for `/World/Set//Lamp*`, `/` for `//Lamp*`), a prim at a path (existence, type, specifier, `active`, variant sets), a property at a path (existence and type), a value at a path (such as `xformOpOrder`), and layer metadata.

**Matching changes to reads.** Each zone's stage listens for `Usd.Notice.ObjectsChanged`, ignoring the notices its own cook causes, both its chain's authoring into the scratch layer and the transfer into its layer, and the zone recooks when:
- a resynced path is at or below a read's path, or inside a subtree read;
- a changed-info path is a value or type read's path, or a prim read's path (prim metadata);
- changed info at `/` names a field a layer-metadata read holds.

A recook reruns the zone's diagnostics too, since they're reads, and if its content comes out the same, its transfer sends no notice further downstream, so there's no separate re-check. **Checked:** which notices a stage composing a zone over a base layer received when the base changed by `TransferContent`:

| Base edit | Resynced | Changed info only (fields) |
|---|---|---|
| a value | | the attribute (`default`) |
| add or remove a prim | the prim | |
| add an attribute | the attribute | |
| change an attribute's type | | the attribute (`default`, `typeName`) |
| change `kind`, a prim's type, or `active`; add a variant set | the prim | |
| change `xformOpOrder` | | `xformOpOrder` (`default`) |
| an attribute on an unrelated prim | that attribute | |
| `upAxis` on the base layer | | `/` (`upAxis`) |
| add a sublayer to the base | each property it contributes | `/` (`subLayers`, `subLayerOffsets`), and its ancestors with no fields |
| identical content | no notice | |
| two layers in one `Sdf.ChangeBlock` | one notice with both edits | |

So an attribute's type change is changed info, not a resync, and a change to a layer stack resyncs exactly what it contributes, not `/`.

**Order.** Dirty tasks cook serially in topological order, upstream first, each against its upstream tasks' committed results. Zones whose upstream tasks have all committed form a wave, and a wave's transfers go in one `Sdf.ChangeBlock`, in node-ID order, so each downstream stage gets one notice; one change block cut the transfers to a quarter with 2 zones, and by a tenth to a fifth with 32, where the transfers themselves dominate (**Checked**, [Measurements](#measurements)). The result doesn't depend on the order tasks ran in.

**Not checked,** for the first implementation to measure:
- A zone's stage composes its whole context, so 32 departments over an ALab-sized context hold 32 sets of composed prim indices. If that's too much: a population mask limited to the zone's reads (`UsdStagePopulationMask`), or one stage shared between zones with the same context.
- A node's edits recompose the zone's stage before the next node reads it. The measured recooks had no stage composing the scratch layer.

**Later: cooking a wave's zones in parallel.** Each zone would cook on a worker into its own scratch layer, through a private stage over its context, while the shared contexts are only read; the wave then commits on one thread. Reading a stage from many threads while nothing writes is USD's documented model, and `UsdStage::GetPrimAtPath` is documented as safe for readers. Not checked: several threads each opening a stage over one shared context and authoring into separate layers, whether their layers match a serial cook, and the speedup.

### Diagnostics

Each node reports its own errors and warnings on itself.
- A node with an error passes its Editable Layer through unchanged, and the nodes after it run, so the rest of the result still shows.
- Composition errors (`UsdStage::GetCompositionErrors`), such as an unresolved asset path or a relocate USD rejects, are reported on the node that authored the arc ([Provenance](#provenance)). An arc in a file the tree reads reports on the Layer from File node or Substitution Zone begin that reads it.
- Verification warnings from a Stage Output's stage are reported on the node whose edit is hidden ([The Zone's Stage](#the-zones-stage)).
- Write refuses while any node that some Stage Output depends on has an error, so a file never holds a result with an edit missing. Errors on nodes with no path of links to a Stage Output don't block Write.

### Provenance

The cook records, from its first version, which node authored each edit and where each asset path came from, in two tables per zone layer. They're built while the zone authors and recooked with it, so an unchanged zone keeps its tables as it keeps its layer. Neither is stored in the layer: `customData` would be written by Write, and would appear in the change notices reuse relies on.

**The edit table** holds the node that last wrote each item:

| Item | Key | Example |
|---|---|---|
| A property's default | property path | `/World/Chair.visibility` → Set Attribute |
| A prim field | prim path and field | `/World/Chair` `kind` → Edit Prim |
| A list-op item | prim path, field, and item | `/Set` references `@…/chair.usda@` → Reference |
| Layer metadata | field and item | a `subLayers` entry → Sublayer; a `relocates` entry → Relocate |
| A prim spec | prim path | Create Prim; Template content → the zone's begin node; implicit `over` ancestors → the node that needed them |

- Paths are keyed as authored, so an edit inside a variant is at `/A{look=red}Child`.
- Only the last writer is kept. A node whose write a later node replaces is warned while authoring, as [List Edits](#list-edits) does for Explicit.
- Inspection shows which node authored a value from it, and verification looks up its entries.

**Composition errors map to nodes through the C++ error types' fields.** The source layer picks the table: a zone's, or, for a Substitution Zone's copy, that zone's end node. Within it, an arc error's site path, arc type, and asset path pick the entry; a sublayer error's `layer` and `sublayerPath`; a relocate error's `layer`, source, and target. **Checked,** through a C++ module reading `UsdStage::GetCompositionErrors`, on a stage whose root sublayered a stronger layer, a zone, and a Substitution Zone's copy:

| Error | Fields |
|---|---|
| unresolved reference on `/A` | `sourceLayer` the zone, `site` `/A`, `assetPath`, arc type reference |
| unresolved reference inside a variant | `site` `/S{v=a}B`, while `rootSite` is `/S/B` |
| reference to a missing prim | `targetLayer` `prop.usda`, `unresolvedPath` `/Nope` |
| unresolved payload | as a reference, arc type payload |
| missing sublayer | `layer` the zone, `sublayerPath` |
| unresolved reference in a Substitution Zone's copy | `sourceLayer` the copy |
| relocate with its target under its source; relocate of a reference's own prim | `layer`, `sourcePath`, `targetPath` |

- The source layer was the layer that authored the arc, not the stage's root, and the site path carried the variant selection, matching the edit table's keys.
- Python's composition errors expose only `errorType` and `rootSite`, whose path drops the variant, which is one reason the cook module is C++ ([The Cook Module](#the-cook-module)).
- `TfEnum::GetName` returned empty names for the error and arc types, so the cook compares the enums' values.

**The write table** says how Write writes each asset path. `UsdUtils.ModifyAssetPaths`, which Write uses, calls its mapping once per distinct string in a layer (**Checked:** 10 calls for 10 distinct strings), so the table is keyed by zone layer and in-memory string, and holds only the paths Write changes; any other is written as authored ([Writing](#writing)):

| Path came from | In memory | Written as |
|---|---|---|
| A zone, linked into Sublayer, Reference, or Payload | the zone's `anon:` identifier | the zone's file, relative to the file being written |
| A file path: a Layer from File's Path, or a relative path in a Template | absolute | relative to the file being written |
| An absolute path in a Template | as authored | as authored |
| Typed into a node, such as `./tex.png` as an `asset` value | absolute, anchored to the zone's file, so the stage finds the texture before Write | exactly as typed |
| Anything else, such as a resolver's identifier | as authored | as authored |

- The typed case keeps the typed string, not one recomputed from the file, so `tex.png` stays `tex.png` for a resolver's search paths.
- A path from a Template and one from a Layer from File can be the same absolute string yet be written differently, which is why the table records where each came from rather than inferring it.
- When one string has two written forms in one layer, such as `/abs/x.png` typed in one node and built from a Layer from File's Path in another, Write uses the Path's and warns on the node that typed it.

### Stage Outputs and the Viewer

Each **Stage Output** node names one of the tree's stages: the stage composed on its input Layer as root layer. A tree may have several, such as an asset and the shot that references it, each tied to its own binding. That stage is the caller-supplied source its binding displays ([Source Stages](../spec/source-access.md#source-stages)). Its zones' layers are in-process edits, which the binding displays without their being written ([Layer State and Reloading](../spec/source-access.md#layer-state-and-reloading)).
- An output makes no layer of its own: its root is a Layer from File's layer, a zone's layer, or a Substitution Zone's copy, whichever is linked in, and two outputs linked to one layer share it.
- The cook's result holds, for each Stage Output, keyed by its node's ID, the stage composed on the layer linked into it, with every payload loaded. It's the stage verification uses too, so each root is composed once. The front end hands it to the Stage Output's binding, whose own evaluation stage applies the binding's payload policy ([Source Stages](../spec/source-access.md#source-stages)), and maps each Stage Output to its binding, so the plain-data tree needs no binding identifiers.
- A zone composed by two Stage Outputs is still written once, to its one File ([Writing](#writing)), and verified against both.

A **Viewer** node names the stage the editor's UI shows ([Viewer](#viewer)). The cook's result holds the active Viewer's stage, or none when no Viewer is active, and the cook knows nothing of the UI that shows it.

A Stage Output converts for display. It carries the binding's coordinate conversion setting ([Coordinate Conversion](../spec/support/transforms.md#coordinate-conversion)), which corrects from the stage's `upAxis` and `metersPerUnit` into Blender's Z-up scene at its unit scale. Nothing inside a zone converts: Configure Layer only authors metadata, and nodes work in their layer's own units and axis. The extension never changes USD's process-wide up-axis fallback (a `plugInfo.json` setting), since that would change how every tool in the process, Blender's own USD importer included, reads files that author no `upAxis`.

Stage metadata is read from the root layer only. **Checked:** a stage whose root layer authors no metrics, over a sublayer authoring `upAxis = Z`, `metersPerUnit = 1.0`, and `startTimeCode = 10`, reported Y, 0.01, and 0.0, which are USD's fallbacks. So a Stage Output warns when its root layer authors no `upAxis` or `metersPerUnit`: the stage then falls back to Y-up and centimeters.

### Writing

A **Write** operator saves each composed zone's layer to its zone's file, in the format its extension names (`.usda`, `.usdc`, `.usd`).
- A zone is *composed* when a path of composition links runs from its end node to any Stage Output: each link enters a Sublayer, Reference, or Payload node, an item's input on a Substitution Zone's end, or a Stage Output itself. A Template, Context Hint, or Viewer link doesn't compose the zone it comes from, since that zone's layer isn't part of a Stage Output's stage, and viewing never decides what is saved.
- A zone that isn't composed warns that Write won't save it, and Write skips it, so a zone left unlinked while the user works on it never overwrites its file. That includes a zone linked only as another zone's Template or Context Hint, or only to the Viewer.
- Composition is decided by links, not by what the stage currently shows: a zone referenced inside a variant that isn't selected is still composed, since the written file references it.
- Layers read from files are never written.
- Relative asset paths are made absolute in memory, since an anonymous layer has no directory to resolve a relative one against. Write makes them relative again, to the file being written, in one `UsdUtils.ModifyAssetPaths` pass over a copy before exporting, so a written set of files can be moved together. The write table says how each path is written ([Provenance](#provenance)):
  - A zone's anonymous identifier, authored by a Sublayer, Reference, or Payload node linked to the zone, becomes the zone's file's path, relative to the file being written.
  - Paths the tree built from file paths, including a Template's relative paths, are written relative to the file that holds them.
  - A relative path typed into a zone, such as `./tex.png` as an `asset` value, is anchored to the zone's file in memory, so the stage finds it before Write, and written exactly as typed.
  - Any other asset path is written as authored, so a resolver's path is never broken.
- Two zones with the same file, or a zone whose file a Layer from File or a Substitution Zone's begin reads, is an error on both nodes.
- Overwriting a file the tree hasn't written asks first. A New Layer Zone discards the file's content, so it also warns while the user works ([New Layer Zone](#new-layer-zone)).
  - The record of what the tree has written is the paths alone, kept with the tree in the `.blend`. Its warning is a one-time one: once the tree has written a file, it never warns about that file again, even if someone changes the file afterward.
  - The record is the front end's: the node's warning and Write's question are both there, and the cook neither takes nor returns it.

Writing is separate from saving the `.blend`, which holds the tree but none of its layers. **Checked:** written relative to a zone file in another directory, exported, and reopened, a zone copied from a Template matched the Template's own stage in every asset value and prim ([New Layer Zone](#new-layer-zone)).

## Sockets

| Socket | Carries | Links |
|---|---|---|
| Layer | A finished layer, by identifier | One output to any number of inputs |
| File | A file a Substitution Zone's root composes: the identifier composition resolved, and its position there | From a Substitution Zone's item to one New Layer Zone's File input; an unlinked File input is a text field |
| Editable Layer | A layer being authored | One output to one input, inside its zone, and to the active Viewer |
| Prim | One prim path | Any number; converts to Prims |
| Prims | A path expression, matched where it is used | Any number |
| Value sockets, one per USD value type ([Values and USD Types](#values-and-usd-types)) | A constant value of that type | Any number |

A zone's Context Hint input is a Layer socket whose link is drawn apart from the others ([The Zone's Stage](#the-zones-stage)).

A File socket exists for one link: it hands a New Layer Zone the file it takes the place of, and the position its context comes from ([The Zone's Stage](#the-zones-stage)). Unlinked, a New Layer Zone's File input is a typed path, for a new file no read layer composes. Layer from File and a Substitution Zone's begin read a file named by a Path property, since nothing in the tree produces a file for them to read. A substitution matches an item by the identifier composition resolved, never by resolving a typed path, so another relative spelling, a symlink, or a typo can't make it miss. File is apart from the `asset` value socket, an attribute value (`SdfAssetPath`) that Set Attribute authors.

**Checked:** a custom socket declared with `use_multi_input=True` took two links in a custom Python node tree.

### Prim and Prims

A Prim carries an `SdfPath`. A Prims carries an `SdfPathExpression`, such as `/World//Lamp*`, matched against the stage at the node that uses it: the zone's stage, or, for an external reference's target, the referenced layer's stage. **Checked:** a collection's membership expression `/World//Lamp*` matched `/World/LampA` and `/World/Sub/LampB` and not `/World/Chair`, through `Usd.CollectionAPI.ComputeIncludedPaths`; an unparseable expression raised a Tf error with its column.

A path inside a zone is in the namespace of that zone's layer. A layer that is later referenced keeps its own paths, which USD maps onto the referencing prim; the editor doesn't rewrite them.

### Values and USD types

The value sockets are USD's own value types, so a value reaches its attribute with the type it was made with, and the editor has no conversion table of its own. A USD value type is a stored type plus an optional role: `float3`, `point3f`, `normal3f`, `vector3f`, `color3f`, and `texCoord3f` all store a `GfVec3f` (**Checked**, through `Sdf.ValueTypeNames`), and the role only says what the value means. So there is one socket per stored type, and the role is chosen where an attribute is created:

| Family | Sockets (USD's names) | Roles they carry |
|---|---|---|
| Scalars | `bool`, `uchar`, `int`, `uint`, `int64`, `uint64`, `half`, `float`, `double`, `timecode` | |
| Text | `string`, `token`, `asset` | |
| Vectors | `half2`–`half4`, `float2`–`float4`, `double2`–`double4`, `int2`–`int4` | `point3*`, `normal3*`, `vector3*`, `color3*`, `color4*`, `texCoord2*`, `texCoord3*` |
| Quaternions | `quath`, `quatf`, `quatd` | |
| Matrices | `matrix2d`, `matrix3d`, `matrix4d` | `frame4d` |

Blender has only a few socket shapes, so each family's sockets share a color, and a socket's tooltip and inspection name its exact type. Of USD's other value types, `opaque` and `group` aren't attribute values a user sets. `pathExpression`, the type of a collection's membership expression (**Checked**), waits for collections.

- **Across a link,** a value converts only where nothing is lost: `half` to `float` to `double`, the same widening in each vector width, and `int` to `int64`. Any other pair is an invalid link; a **Convert** node does it explicitly, rounding as USD's own casts do.
- **Precision:** a node's own value is a Blender property, and Blender's `FloatProperty` stores 32 bits (**Checked:** 100000.1 read back as 100000.1015625). The `double` and 64-bit integer sockets, and the nodes that make their values, store them some other way, such as a decimal string, so that `xformOp:translate`, a `double3`, is exact.
- **Blender's sockets:** the editor defines its own value sockets. Blender's `NodeSocketVector` is one type whose width is a `dimensions` setting, and Blender's float sockets are single precision. **Checked:** a custom tree accepted `NodeSocketFloat`, `NodeSocketVector`, `NodeSocketMatrix`, and `NodeSocketString`, and `dimensions` exists on a vector interface socket. **Not checked:** the precision of a socket's `default_value`.

## Nodes

Each node lists its inputs, outputs, and properties (set on the node, not linked), then what it authors and what it reports.

Two rules hold across nodes:
- **Known sets are offered.** Wherever a node takes a token from a known set, it offers that set as a menu or a search: a token attribute's schema `allowedTokens` (`visibility`, `purpose`, `subdivisionScheme`, …), the registered kinds (**Checked:** `group`, `component`, `assembly`, `model`, `subcomponent`), registered schema and API schema names, and variant sets and variants on the stage being checked. The set is a suggestion where USD allows other values: **Checked:** setting `subdivisionScheme` to `bogus` succeeded and read back `bogus`, and a pipeline can register its own kinds. A value outside the set is a warning, not an error. `upAxis` is the one closed set.
- **Optional fields are unauthored unless set.** A field of Edit Prim or Configure Layer has three states: unauthored, set, and, for list ops, removed. Unauthored differs from setting the fallback: `active = true` in a stronger layer overrides a weaker layer's `active = false`, while leaving it unauthored lets the weaker opinion through. A Blender `BoolProperty` alone can't hold the three states, so each field has an explicit "author this" toggle or an enum with an unauthored item.

### Layer from File

Reads a layer.
- **Properties:** Path, a Blender path (`//` relative to the `.blend`; [The Tree as Plain Data](#the-tree-as-plain-data)).
- **Outputs:** Layer.
- **Authors:** nothing. The layer is the process's shared copy, so it shows unsaved edits other tools made to it, and rereads only on request ([Layer State and Reloading](../spec/source-access.md#layer-state-and-reloading)).
- **Reports:** a file that doesn't exist or doesn't parse; a file it composes that a zone owns, as a warning that its output shows that file as it was before Write ([Editing a Layer in a Composition the Tree Reads](#editing-a-layer-in-a-composition-the-tree-reads)).

### New Layer Zone

Authors a new layer. A begin node and an end node, paired as in [Node Zones](node-zones.md).
- **Begin inputs:** File, where Write saves the layer, typed or from a [Substitution Zone](#substitution-zone)'s item; Template (Layer, optional), the layer the zone starts from; Context Hint (Layer, optional), overriding the context derived from the File ([The Zone's Stage](#the-zones-stage)).
- **Begin outputs:** Editable Layer: empty, or a copy of the Template.
- **End inputs:** Editable Layer; Default Prim (Prim, optional), the root prim that a reference or payload without a target prim composes.
- **End outputs:** Layer.
- **Authors:** `defaultPrim`, when given, replacing the Template's.
- **Reports:** a default prim that isn't a root prim of the layer; a sublayer of its target File that its layer doesn't sublayer, since its context checks against it ([The Zone's Stage](#the-zones-stage)); a file another zone, a Layer from File, or a Substitution Zone's begin also uses; a File that already exists and that the tree hasn't written, as a warning that Write would discard its content. The warning stops once the tree has written the file, by the front end's record of written paths ([Writing](#writing)). To keep the content, the zone writes another file, with the existing one as its Template or under it in its context; editing a file in place waits for the File In-Place Edit Zone ([Scope](#scope)).

**Templates.** The zone's layer starts as a copy of the Template's prims and layer metadata, and the chain authors on top. The Template is an input like any other, read live and never written, so the tree stays the source of truth and the zone's file is pure output.
- A Template is a Layer from File, another zone's output, or a Substitution Zone's. This is how the tree duplicates a layer: the duplicate is a new zone, and its File gives it its own save path from the moment it exists, so no two zones write the same content to one file.
- A relative asset path in the Template is relative to the Template's file, and copied verbatim it would resolve elsewhere or not at all. So the zone starts as a `TransferContent` copy, then one `UsdUtils.ModifyAssetPaths` pass makes each relative path an absolute path anchored to the Template's file: `./textures/wood.png` in `templates/template.usda` becomes `/…/templates/textures/wood.png`. The absolute paths are for memory only, since the zone's layer is anonymous, with no directory for a relative path to resolve against; Write makes them relative to the zone's own file, such as `../../templates/textures/wood.png` from `shots/seq/` ([Writing](#writing)). A Substitution Zone's copies use the same routine.

**Checked,** on a Template with a relative path in each place one can live (sublayers; a reference and a payload, the payload as a bare `prop.usda`; a reference inside a variant; `asset` and `asset[]` values, time-sampled asset values, and a `<UDIM>` path; `customData`, `assetInfo`, and `customLayerData`; value clips' `assetPaths` and `manifestAssetPath`), and one absolute path:
- `TransferContent` copies paths verbatim, so a copy resolved none of them: 9 of 9 asset values unresolved, 4 composition errors, and the sublayer's prim missing, whether the copy was anonymous or saved in another directory.
- After the anchoring pass, the copy's stage matched the Template's in every asset value and prim. The clips' paths and `customLayerData` were anchored too, the absolute path was left as authored, and `<UDIM>` survived; it reads as unresolved on both stages, since a UDIM path resolves per tile.
- Written relative to a zone file in `shots/seq/`, exported, and reopened, the zone matched the Template's stage again, with the absolute path still as authored.
- With USD's default resolver, anchoring gives a filesystem path. **Not checked:** a custom resolver's anchored identifiers, and a bare path such as `prop.usda` that a resolver's search paths would find, which anchoring ties to the file beside the Template (here that file existed, so the result was the same).

Zones sit side by side: one zone's Layer output links into another zone's Template, Context Hint, Sublayer, or Reference, or into an item's input on a Substitution Zone's end. A cycle between zones is a cycle in the tree, which the tree's links already rule out.

### Substitution Zone

Reads a root layer and puts zones' layers in place of files it composes, at every occurrence and any depth ([Editing a Layer in a Composition the Tree Reads](#editing-a-layer-in-a-composition-the-tree-reads)). A begin node and an end node, paired as in [Node Zones](node-zones.md), with one *item* per substituted file, as Geometry Nodes' zones have items: each item is an output on the begin and an input on the end.
- **Begin properties:** Path, the root's file, as Layer from File's; Items, each a file the root composes, picked from a search that lists each once with how it's composed ("sublayer 2 of `shot.usda`", "referenced by 13 prims in 4 layers"). The search also offers authored sublayer paths that don't resolve, so a department layer can start before its file exists. It never offers the root itself, since there's nothing to substitute it into: a zone for the root is the stage's root.
- **Begin outputs:** one File per item: for a sublayer, with its position in that layer stack, from which a zone derives its context; for a reference's or payload's target, marked as one, since its context is its own sublayers ([The Zone's Stage](#the-zones-stage)). The begin has no Layer output, so the root is never seen without its substitutions.
- **End inputs:** one Layer per item, a zone's output.
- **End outputs:** Layer: an anonymous copy of the root that names each linked zone's layer wherever the composition names that item's file, or the root itself while no item is linked.
- **Authors:** nothing. The copies are never written.
- **Reports:** on the begin, a file that doesn't exist or doesn't parse, and an item its root no longer composes. On the end, an unlinked item, as a warning that the stage shows its file as it was before Write; a linked zone whose File isn't the item's file, such as one nested in another root's Substitution Zone for a different file; and an item that the substituted composition no longer reaches, such as a chair whose set another item's zone replaces without referencing it, as a warning that its zone's edits don't show.

An item's File usually links into a New Layer Zone nested in the Substitution Zone. A zone can also feed items of several Substitution Zones, one in each root that composes its file, such as a chair two shots reference: it takes its File and context from one item, and each other end checks that its item names the same file.

A substitution replaces every occurrence of a file, so a position is for the context only, not an address the substitution needs. A file that is both a sublayer and a target, or a sublayer in two layer stacks, takes its context from the first occurrence listed, and the item reports the others. The File carries the identifier composition resolved, so nothing resolves the path again. Sublayers are read from each layer's `subLayers` without composing. Arc targets need a composed stage, which loads payloads.

How the end makes its copies:
- Walk the layer graph from the root, through each layer's own composition dependencies (`GetCompositionAssetDependencies`: sublayers, references, payloads, arcs inside variants), without composing or loading payloads. A dependency that doesn't open, such as a sublayer whose file doesn't exist yet, stays in the graph by its anchored path, so a zone for it can still take its place. **Not checked:** the probe below skipped dependencies that didn't open.
- The ancestors are every layer from which a substituted file can be reached. Each is copied into an anonymous layer, the root included.
- Each copy's asset paths are rewritten in one `UsdUtils.ModifyAssetPaths` pass, each mapped by what it resolves to from the original layer: a substituted file becomes its zone's identifier, an ancestor its copy's, and any other relative path becomes absolute. Paths are compared by resolved identifier, or by anchored path for one that doesn't open, so `./sets/../assets/chair.usda` and `../assets/chair.usda` name the same file.
- The copies are redone only when the root or the set of linked items changes. Recooking a zone moves content into the same anonymous layer, which the copies already name.

An item's input on the end is a composition link, so a zone linked into it is composed ([Writing](#writing)).

**Checked** on a scene with a nested sublayer and a chair composed five ways: both zones took every occurrence (the nested sublayer, and the chair as a reference, a payload, a reference inside a variant, and a reference spelled through another directory); four ancestors were copied, and no copy named a substituted file; a relative reference that wasn't substituted, and a relative texture, still resolved; a stage on `shot.usda` open at the same time showed the files, without the zone among its layers and with `chair.usda` unchanged; neither stage reported composition errors.

**Checked** on ALab (4,309 layers reachable from `entry.usda`, 2,600 of them contributing prim specs), for three files, in ms:

| File | Ancestors | Their size | Copy | Rewrite |
|---|---|---|---|---|
| median depth (a cable's modelling layer) | 12 | 0.24 MB | 3 | 5 |
| most ancestors (a solder mesh) | 59 | 18.6 MB | 12 | 23 |
| largest ancestors (a resistor mesh) | 59 | 18.6 MB | 11 | 19 |

- Finding the ancestors took a further 12 to 14 ms, and walking the graph 0.1 s with its layers already open, as the begin's stage holds them (3.8 to 10.7 s from cold).
- In all three, the zone contributed exactly the prim specs the file contributed on `entry.usda`, the file contributed none on the copy, both stages had 11,886 prims, and neither reported composition errors.
- Rewriting with `Sdf.Layer.UpdateCompositionAssetDependency`, once per arc, gave the same results in 110 to 310 ms, since each call traverses the layer.
- A new stage on the root copy took 0.24 to 0.33 s in one run and 1.6 to 2.1 s in another, paid only when the root copy is new.

### Stage Output

Names one of the tree's stages, which a binding displays ([Stage Outputs and the Viewer](#stage-outputs-and-the-viewer)).
- **Inputs:** Layer, the root layer.
- **Properties:** the binding's coordinate conversion setting.
- **Reports:** a root layer that authors no `upAxis` or `metersPerUnit`, as a warning.

### Viewer

Names the stage the editor's UI shows. A tree may hold several Viewer nodes, but one is active, as in Geometry Nodes; the front end passes only the active one to the cook and strips the rest, as it strips reroutes.
- **Inputs:** Layer or Editable Layer.
- **Properties:** Context, a checkbox, on by default.
- **Authors:** nothing.
- **On a Layer,** its stage has that layer as root, as a Stage Output's does.
- **On an Editable Layer partway down a chain,** the zone's cook copies its scratch layer into the Viewer's own anonymous layer, with `TransferContent`, as it passes the node the Viewer is linked after, and the Viewer's stage has that copy as root. It's one copy per cook of that zone, about a zone transfer's cost; running the chain a second time up to that node would author everything twice. Nodes after the Viewer's point still run and report.
- **Context:** when the Viewer's input is a New Layer Zone's Editable Layer or its end's Layer, the stage composes it over the zone's context ([The Zone's Stage](#the-zones-stage)), the stage that zone's nodes check against, so the view matches at every point in the chain and at its end. Off, the stage holds the layer alone. For any other Layer, such as a Layer from File's or a Substitution Zone's, there's no context, and the checkbox does nothing. Toggling it recomposes only the Viewer's stage.
- **What a change recooks:** linking the Viewer to another point in a chain recooks that zone once, to take the copy there; the zone's own result is unchanged, so its transfer sends no notice downstream. Any other change that reaches only the Viewer recooks no zone.
- **Not composed:** a link into the Viewer doesn't make a zone composed for Write ([Writing](#writing)).
- **Not converted:** its stage feeds no binding, so it isn't converted between USD's and Blender's axes and units.

The Viewer isn't a zone's member and is never drawn inside one ([What a Zone Holds](#what-a-zone-holds)). The front end shows its stage in [Scene Graph UI](scene-graph-ui.md)'s tree, in the node editor's sidebar, where selecting a row selects no Blender objects; the same tree in the 3D View's sidebar shows a binding's stage and selects with the viewport. Path searches are unaffected: they read the stage of the node using the path ([Where a Path Is Searched](#where-a-path-is-searched)), and the Viewer uses none.

### Prim

A single prim path.
- **Properties:** Path, with a search over the prims of the stage where its output is used ([Where a Path Is Searched](#where-a-path-is-searched)).
- **Outputs:** Prim.
- **Reports:** a path that isn't absolute, or names a property or variant.

#### Where a path is searched

Prim and Match Prims take no stage input. Their search reads the stage of the node their output links to, at that node's input: the zone's stage as the nodes before it left it ([The Zone's Stage](#the-zones-stage)), or, for a Reference's or Payload's Target, the source layer's stage. That is the stage that checks the path, so the search never offers a path its consumer would reject.
- A stage input couldn't show a chain partway: linking a Prim node to the Editable Layer mid-chain would branch it, and a finished Layer lacks the prims the zone itself creates. For a Target, it would duplicate the Source Layer link.
- An unlinked Prim node has no search; its path is checked once it is linked. Create Prim's Prim output supplies most paths in a zone without typing.
- The search reads each consumer's stage from the last cook, so typing doesn't cook the tree.
- An output linked to several nodes searches every consumer's stage, labeling each match by its consumer. The same path naming different prims in different layers is ordinary USD, not an error.

### Match Prims

Prims matched by an expression.
- **Properties:** Expression, such as `/World//Lamp*`, with a preview of its matches searched as [Prim's](#where-a-path-is-searched) is.
- **Outputs:** Prims.
- **Reports:** an expression that doesn't parse. An expression that matches nothing is a warning on the node that uses it.

### Value and Convert

- **Value:** a constant of the USD value type its Type property names. Outputs that type's socket.
- **Convert:** inputs one value socket and outputs another of the same width, such as `double3` to `float3` or `float` to `int`, converting as USD's own casts do. Reports a value out of the target type's range.

### Create Prim

Authors one new prim spec. Edit Prim edits prims that already exist.
- **Inputs:** Editable Layer; Parent (Prim, default `/`); Name (String).
- **Properties:** Specifier (`def`, `over`, `class`); Type, with a search over the schema types the process has registered (`Xform`, `Scope`, `Mesh`, `Sphere`, …), empty for a typeless prim.
- **Outputs:** Editable Layer; Prim, the new prim's path.
- **Authors:** the spec, and `over` specs for any ancestors its layer lacks.
- **Reports:** a name that isn't a valid identifier; a prim this layer already has a spec for, from its Template or an earlier Create Prim. An `over` on a prim a sublayer defines is ordinary and reports nothing.

### Edit Prim

Edits prim-level fields on each matched prim.
- **Inputs:** Editable Layer; Prims.
- **Properties,** each unauthored unless set:
  - API schemas: Apply prepends a schema to `apiSchemas`, and Remove authors a `delete`. A multiple-apply schema takes an instance name.
  - `active`, `kind`, and `instanceable`.
  - Type name and specifier, such as an `over` that gives a typeless prim a type.
- **Outputs:** Editable Layer.
- **Authors:** each set field. Prims without a spec in this layer get an `over`. **Checked:** applying `CollectionAPI` with the instance name `lights` listed `CollectionAPI:lights` in the prim's applied schemas.
- **Reports:** an API schema that isn't registered; a single-apply schema given an instance name, or a multiple-apply schema without one.

### Set Attribute

Sets or blocks one attribute's default value on each matched prim.
- **Inputs:** Editable Layer; Prims; Value, whose socket is the stored type of the Type property (Value mode only).
- **Properties:** Mode, Value or Block; Name, such as `radius` or `userProperties:note`; Type, a USD value type with its role (`double`, `color3f`), which the node fills in from the zone's stage when the attribute exists.
- **Outputs:** Editable Layer.
- **Authors:** in Value mode, the attribute's default value; in Block mode, a value block (`SdfValueBlock`), so the attribute falls back to its schema's value, ignoring weaker layers' values and time samples. An attribute the zone's stage already has keeps its type and variability: an authored attribute, or a schema's built-in one, including those of API schemas Edit Prim applied. **Checked:** `Sphere.radius` is `double`, and setting a Mesh's `subdivisionScheme` authored a `uniform` spec with `custom = false`. A new attribute is created with Type, and as custom when no schema defines it. Prims without a spec in this layer get an `over`.
- **Reports:** a Type whose stored type differs from the attribute's on a matched prim; an array-valued attribute. A Type that differs only in role, such as `float3` set on a `color3f`, is a warning, and the attribute keeps its own role.

A stronger layer's default value overrides a weaker layer's time samples, so setting an animated attribute stops its animation in the composed stage. **Checked:** a default of 5.0 in a stronger sublayer read 5.0 at time 1, over a weaker sublayer's samples of 1.0 and 2.0. Set Attribute should warn when it does this.

**A single transform op.** An op is an attribute plus its entry in `xformOpOrder`, so Set Attribute may set an `xformOp:*` attribute, such as a pivot's `xformOp:translate:rotatePivot`, which edits that op's value exactly. It warns on a prim whose composed `xformOpOrder` doesn't list the op, since the value then has no effect.

### Set Transform

Sets each matched prim's local transform.
- **Inputs:** Editable Layer; Prims; in Components mode, Translate (`double3`), Rotate (`float3`, Euler XYZ in degrees), and Scale (`float3`), the types of the ops it authors (**Checked**); in Matrix mode, Transform (`matrix4d`).
- **Properties:** Mode, Components or Matrix; Placement, Replace, Edit, After, or Before; Reset Xform Stack, a checkbox.
- **Outputs:** Editable Layer.
- **Authors:** in Components mode, `translate`, `rotateXYZ`, and `scale`, all three, since the node always has a value for each; in Matrix mode, one `transform`. It writes `xformOpOrder` only when the result's order differs from the one on the zone's stage, so for a prim whose stack already has these ops, the zone's layer holds only their values.
- **Reports:** a prim that isn't Xformable; each op it discards; an op it sets or discards that has time samples, since the value set here stops that animation ([Set Attribute](#set-attribute)); a reset it clears that the zone's stage had.

**Placement,** where the node's ops go relative to the prim's composed stack:
- **Replace:** the stack becomes exactly the node's ops. It warns, naming each op it discards (such as `orient`, `transform`, or a pivot). An op goes with its inverse, so a replaced order never orphans an `!invert!` op.
- **Edit:** sets the values of the ops the prim already has, matched by name, and keeps its order. An op the prim lacks is added after its existing ops, with a warning.
- **After:** appends the node's ops after the existing ones, an offset in the prim's local space.
- **Before:** puts them before the existing ones, an offset in the parent's space.
- After and Before name their ops with a suffix from the node's prim name (`xformOp:translate:Nudge`), so they never collide with the prim's own ops and show which node added them. The zone's layer then holds a copy of the composed order, so a weaker layer changing that order changes the result, which the zone's recorded reads cover ([Cooking the Layers](#cooking-the-layers)).

**Reset Xform Stack** sets whether the result ignores the parent's transform. When checked, the order starts with `!resetXformStack!`, and After and Before keep it first. When it differs from the zone's stage, the node writes the order, in Edit placement too.

**Showing the stack.** For its matched prims, the node shows each composed stack and its result, marking each op kept, set, added, or discarded, with prims that share a stack grouped and counted. It's report data the cook returns per node, alongside diagnostics, and the front end draws it in the node's sidebar or inspection.

What production stacks look like, **Checked** on ALab's composed stage, with `UsdGeom.XformCommonAPI` tried on each prim:

| Op stack | Prims |
|---|---|
| none | 2,179 |
| `translate rotateXYZ scale`, or a part of it | 1,361 |
| `translate orient scale` | 438 |
| `transform` | 185 |
| pivot stacks (`translate:rotatePivot`, `!invert!` ops, `translate:scalePivot`) | 43 |
| other (`rotateZXY:rotate`, a lone `rotateXYZ`) | 4 |

Of 4,210 Xformable prims, 10 have time-sampled ops and none resets the transform stack; `XformCommonAPI` accepted exactly the 3,544 with no ops or with part of `translate rotateXYZ scale`. So Replace loses nothing on the 84 percent whose stacks are empty or part of `translate rotateXYZ scale`; on the rest, with `orient`, a matrix, or pivots, Edit, After, and Before keep the existing ops. A single op, such as a pivot's position, is set with Set Attribute ([Set Attribute](#set-attribute)). Full control of a stack's ops waits for the transform stack socket ([Scope](#scope)).

### Configure Layer

Authors the zone's layer metadata.
- **Inputs:** Editable Layer.
- **Properties,** each unauthored unless set: `upAxis` (`Y` or `Z`) and `metersPerUnit`; `startTimeCode`, `endTimeCode`, `timeCodesPerSecond`, and `framesPerSecond`; `doc`.
- **Outputs:** Editable Layer.
- **Authors:** each set field. Two Configure Layer nodes setting the same field follow the chain's order: the later replaces the earlier.

A zone authors metrics only when they're set, never Blender's Z-up and meters by default. Stage metadata is read from a stage's root layer only ([Stage Outputs and the Viewer](#stage-outputs-and-the-viewer)), so a zone's metrics apply where its layer is the root, such as a Stage Output's root or an asset opened on its own, and inspection shows that metrics on a sublayer or a referenced layer have no effect on the stage composed over them. `timeCodesPerSecond` is the exception, since it scales time across layer boundaries; it matters once time samples arrive (**Not checked**, from USD's documentation). The zone's Default Prim stays on its End node, since it's the layer's interface to arcs, checked against the finished layer.

### Sublayer

Adds layers to the Editable Layer's sublayers.
- **Inputs:** Editable Layer; Layers (Layer, multi-input).
- **Outputs:** Editable Layer.
- **Authors:** each layer's path, appended to `subLayers` in the multi-input's order, strongest first, after the layers earlier Sublayer nodes appended.
- **Reports:** a layer listed twice.

The Editable Layer's own opinions stay stronger than every sublayer's ([Order of Authoring and Strength of Opinions](#order-of-authoring-and-strength-of-opinions)).

**Checked:** in one case, a multi-input socket's `links` listed two links in the reverse of the order they were made. **Not checked:** whether `links` follows the drawn order, which the user can rearrange.

### Reference and Payload

Two nodes with the same sockets, editing the references or payloads of each matched prim.
- **Inputs:** Editable Layer; Prims, the prims that hold the arc; Source Layer (Layer, External mode only); Target (Prim, optional in External mode).
- **Properties:** Mode, External (a layer and an optional prim in it) or Internal (a prim in this layer stack); List Edit, Prepend (USD's default), Append, Delete, or Explicit ([List Edits](#list-edits)).
- **Outputs:** Editable Layer.
- **Authors:** one arc per matched prim, in the list edit's mode. With no Target, an external arc composes the source layer's default prim.
- **Reports:** an external arc without Target to a layer with no default prim; a Target the source doesn't have; composition errors on the arc; an edit a later Explicit node discards, as a warning.

The prims that hold the arc must exist where the node runs: create them first. A payload composes only when its stage loads it. The tree's own checks (searches, matching, type lookup) should load every payload, while the display follows its binding's payload policy.

### Variant Zone

Authors opinions inside one variant. A begin node and an end node, inside a New Layer Zone.
- **Begin inputs:** Editable Layer; Prim, the prim that owns the variant set.
- **Begin properties:** Variant Set, Variant.
- **Begin outputs:** Editable Layer, whose edits land in the variant.
- **End inputs and outputs:** Editable Layer.
- **Authors:** the variant set and the variant, if the prim lacks them, then every edit inside the zone at the variant's path: an edit to `/A/Child` inside `look=red` is authored at `/A{look=red}Child` (**Checked**, through `UsdVariantSet.GetVariantEditContext`). Nested zones on the same prim or a descendant nest the variants.
- **Reports:** an edit inside the zone to a prim outside the owner's subtree; a node inside the zone that authors layer metadata, such as Sublayer (`subLayers`), Relocate (`relocates`), or Configure Layer, since a variant holds only prim specs.

Inside the zone, nodes check against the zone's stage with this variant selected. A variant's opinions are weaker than the owner's local opinions in the same layer stack. A variant that switches between asset files is a Reference node inside the zone.

### Set Variant Selection

- **Inputs:** Editable Layer; Prims.
- **Properties:** Variant Set, Variant.
- **Outputs:** Editable Layer.
- **Authors:** the variant selection on each matched prim.
- **Reports:** a variant set or variant the composed prim doesn't have, as a warning, since a layer this one is later composed with may add it.

### Relocate

Moves a prim that an arc brings in to another path.
- **Inputs:** Editable Layer; Source (Prim); Target (Prim).
- **Outputs:** Editable Layer.
- **Authors:** an entry in the layer's `relocates` metadata. **Checked:** `Sdf.Layer` exposes `relocates` in Python.
- **Reports:** a Source the zone's own layers define, which USD silently drops; a Source missing from the zone's stage; and the composition errors USD reports for it.

USD reports only some invalid relocates, so Relocate checks its own Source. **Checked,** one case each:

| Relocate | Error | Result |
|---|---|---|
| a prim the zone defines itself, `/E/Child` → `/E/Moved` | none | `/E/Child` gone, and no `/E/Moved` |
| a prim from a reference | none | moved |
| a source that doesn't exist | none | nothing |
| target under its source | `InvalidAuthoredRelocation` | |
| the reference's own prim | `InvalidAuthoredRelocation` | |

## The cook module

The cook is C++, in a compiled module of its own, apart from the core. It authors and composes through Sdf and Usd only, with no Hydra and no Blender.
- **It takes** the tree as a USD layer ([The Tree as Plain Data](#the-tree-as-plain-data)), Blender's arrays as buffers keyed by name, and an optional base directory for `//` paths.
- **It returns,** keyed by node ID, each Stage Output's stage, composed on the layer linked into it, which it also verifies against ([Stage Outputs and the Viewer](#stage-outputs-and-the-viewer)); the active Viewer's stage; and each node's report: its diagnostics and report data, such as Set Transform's stacks.
- **The Blender-side Python** turns the node tree into that layer, reads Blender's data with `foreach_get`, hands each Stage Output's stage to its binding as a caller-supplied source ([Source Stages](../spec/source-access.md#source-stages)), and synchronizes like any other caller.

### Why C++

PROJECT.md prefers Python, and adopts a compiled component when measurements show Python can't meet the budgets, or when it reuses OpenUSD functionality that Blender's Python `pxr` doesn't expose. The cook does the second: Python's composition errors expose only `errorType` and `rootSite`, while mapping an error to the node that authored it needs the C++ types' source layer, site with its variant path, asset path, and arc type ([Provenance](#provenance)). The measurements support it ([Measurements](#measurements)):
- **Where the cook's own code is the work, C++ was much faster:** 2.2 to 4.6 times on authoring loops, and 30 times on converting arrays into `VtArray`s. Whole recooks were 1.5 to 2.9 times faster on tweaks and 1.1 to 1.7 times on structural recooks, since recomposing, transfers, Blender's evaluation, and writing are the same in either language.
- **What comes later grows that share:** for-each zones and trees of many zones multiply the authoring calls, and bringing animated Blender data in converts arrays on every frame (about 96 ms per frame for 10 million positions through `FromNumpy`, against about 6 ms in C++).
- **The core's toolchain already exists:** `tools/native_build.py`, the linkage audit, clang-format, and clang-tidy. A second compiled module reuses it, though the distribution build needs extending to it ([Where It Lives](#where-it-lives)).
- **Splitting the work,** a Python cook with native helpers for hot loops, would put node behavior in two languages, and porting later would rewrite every node.
- **The cost is slower iteration** while the design moves; this note's node sections are the reference that limits it.

In either language, the cook authors through the Sdf API, which was faster than the Usd API in both.

### Where it lives

- **A lowest-tier unit with its own compiled module,** `src/proscenium/cook/` holding `_cook`, beside `core/`. It imports without `bpy`, and neither unit imports the other: the core never needs to know where a stage came from, and the cook never needs the core. The inspection layer is the precedent for native code kept apart from the core.
- **The node tree's front end is a higher-tier unit:** the `bpy` code that turns the tree into its layer, reads Blender's arrays, and calls the cook. It hands stages to bindings through `api/`, so the cook meets the display only through the public API every caller uses.
- **Stages cross as `pxr` Python objects.** Both modules link Blender's `usd_ms`, so they share no C++ types or headers.
- **The cook's reports are per node,** not a binding's diagnostics, so they get their own type rather than `binding/results.py`'s.

What it costs:
- `tools/build_extension.py` builds only `src/proscenium/core/`. It would build a second CMake project, or one project would produce both modules; the linkage audit and the manifest's `[build]` exclusions would cover both.
- AGENTS.md's boundary rules apply to the new module: Tf errors and C++ exceptions become Python exceptions, buffers are read-only and typed as Blender's, the GIL is released while waiting, and OpenUSD workarounds are labeled. The core's small error translation is duplicated at first rather than split into a shared library.
- The new unit goes in src/proscenium/README.md's tier table, `tests/bpy_free/test_import_tiers.py`, its directory READMEs, and AGENTS.md's Layout and Compiled core sections.

This note holds the design and its decisions; there's no plan file in `docs/plans/` while Phase 3 has no milestone. PROJECT.md records compiled components in DECISIONS.md, so the module gets a row there when it becomes product code.

### The tree as plain data

The tree is a USD layer. Each node is a prim, its properties are typed attributes, and links are attribute connections. That the tree and its output are both USD is a feature: values keep their exact USD types, a multi-input's order is its connection list's order, `#` comments carry a test's purpose, Python and C++ read and write it through the same Sdf, and a test tree can be opened in USD tools.

```usda
#usda 1.0
(
    "An example tree: one Set Attribute, muted, that would block an attribute on /World/Chair."
)
def NodeTree "Tree"
{
    int tree:format = 1

    def SetAttribute "Set_20_Attribute"
    {
        int node:version = 1
        bool node:mute = true
        opaque inputs:layer.connect = </Tree/Begin.outputs:layer>
        string inputs:prims = "/World/Chair"
        token props:mode = "block"
        opaque outputs:layer
    }
}
```

- **The whole tree is one layer,** while each zone authors its own anonymous layer, since USD composes and saves whole layers and layer metadata (`defaultPrim`, `upAxis`, `subLayers`, `relocates`) is per layer. The tree stays one layer: links cross zones, and a connection names a path in its own layer's namespace; nodes outside every zone need a home in any case; splitting by zone would make the front end decide membership, which the cook owns ([What a Zone Holds](#what-a-zone-holds)); reuse doesn't need the split; and a test has one tree file.
- **The root prim is `/Tree`,** of type `NodeTree`, and every node is a direct child of it, never nested under a prim per zone. Nesting would make moving a node into another zone change its path, which USD reports as a rename, so the node and everything downstream would recook, and the format would fix a membership rule.
- **The format's version is `int tree:format` on the root prim.** It changes only with the convention; a node type's changes go in its `node:version`, which every node authors, never leaving it to the definition's default, so an old tree never reads as the current version and can be upgraded.
- **A node's ID is its Blender name,** unique within its tree. Python can't read Blender's internal node identifier in 5.2 (**Checked:** a custom node's RNA properties include `name` but no identifier). A rename then reads as a node replaced, so it and everything downstream recook once.
- **Prim names** map from Blender names reversibly: each `_` doubles to `__`, and each character USD's identifiers reject, including a leading digit, becomes `_<hex codepoint>_`. A single `_` always starts an escape, so decoding is unambiguous. **Checked** with `Sdf.Path.IsValidIdentifier` (USD 0.26's Python has no `IsValidPrimName`): 13 names, among them `N.001` → `N_2e_001`, `Set Attribute` → `Set_20_Attribute`, `1st` → `_31_st`, `Größe` and `日本語ノード` unchanged, `a😀b` → `a_1f600_b`, `_2e_` → `__2e__`, and a 63-character name, all encoded to valid identifiers, decoded exactly, and stayed distinct.
- **Inputs, outputs, and properties** are `inputs:`, `outputs:`, and `props:` attributes. Layer and Editable Layer sockets are `opaque` attributes, USD's type for an attribute that only carries connections; other inputs have their own types, and an unauthored input reads the definition's default. **Checked:** an `opaque` attribute refused a value with an error, and its connection survived exporting the layer to text and importing it again.
- **A begin node names its end** with `rel zone:end`, whose one target is the end prim. A relationship targets a prim in the tree itself, so it reads as the tree's own structure, unlike a Prim value, which names a prim in an authored layer.
- **A Substitution Zone's items** are on its begin, each under a stable identifier from a counter on the begin, as node uids are ([Node Zones](node-zones.md#pairing)), which names its File output on the begin and its input on the end, such as `outputs:item_3:file` and `inputs:item_3:layer`. Its file is a `string` attribute under the same identifier on the begin, the path as composition resolved it. So reordering items, or picking another file for one, keeps its links.
- **The front end strips reroutes, frames, and inactive Viewers.** The cook sees only the logical graph.
- **Muting:** `node:mute` is authored only when true. Each node type's definition says what a muted node passes through, such as its Editable Layer, and the cook follows it.
- **Paths are strings.** Path properties and File, Prim, and Prims values are `string`s, as is any value a node authors as an `asset` or a path, such as Set Attribute's Value with Type `asset`; the node's definition names the type it authors. As `asset` values, USD's dependency tools would list a test tree's paths as its dependencies, and a relative path would anchor to the tree's file; as `SdfPath`s, copying the tree could remap paths that name prims in other layers. A string keeps the path as typed, which Write's mapping needs ([Writing](#writing)).
- **Heavy data from Blender isn't in the tree.** A node that reads Blender data names its source with a string key and has an `int` serial, which the front end increments when the depsgraph reports that data changed, so a data change is a one-attribute change in the tree. The caller passes the buffers beside the tree, as `foreach_get` filled them, and the cook copies each into a `VtArray` with one `memcpy` only when its serial changed, otherwise keeping the array it has. Tests keep each buffer in a file beside the tree, such as `.npy`. Inline arrays wouldn't be copied, since a shared `VtArray` moves without copying, but they would make the tree large to compare, export, and read, and would tie the data's changes to the graph's.
- **Node positions (`UsdUI`) appear only in test files,** to make them readable in USD tools. The front end doesn't write them, and the cook ignores the `ui:` namespace.

**The `//` base directory.** The cook takes an optional base directory beside the tree, never in it: the front end passes the saved `.blend`'s directory, and tests pass their tmp directory.
- With no base directory, a `//` path is an error on its node, asking to save the `.blend`.
- A changed base directory is a change to every node with a `//` path.
- Any other path goes to USD's resolver as written, so a custom resolver's identifiers work. A path starting with `./` or `../` warns, since it would resolve against the process's working directory.

**Node definitions.** Each node type is defined once, in a node definitions file (such as `node_definitions.usda`) shipped in the package, with one `class` prim per node type, named for the type, which is also the type name of that node's prims in a tree. Each holds the type's `node:version`, its `doc`, and its `inputs:`, `outputs:`, and `props:` attributes with their types and defaults. Menus are `allowedTokens`, and `customData` holds what USD's types can't: the socket kind (`Layer`, `EditableLayer`, `File`, `Prim`, `Prims`), multi-input, what a muted node passes through, a zone node's role and partner, and Blender UI hints.
- Both sides load it as data through Sdf, and neither registers it with USD. The front end builds its node classes from it when the extension registers. The cook checks trees against it and reads an unauthored value as the definition's default, so a tree authors only what differs.
- Behavior is in C++ only, and a test checks that each definition has an implementation and the reverse. Front-end behavior the file can't declare, such as Set Attribute's Value socket following its Type, or dynamic menus, is a Python hook on that node type.
- **Not a registered schema.** The cook reads the tree through Sdf, which never consults USD's schema registry, so a schema's fallbacks wouldn't reach it anyway. Registration is also unreliable: **Checked** with a codeless schema, `Plug.Registry().RegisterPlugins` found its types when it ran before anything used the schema registry, and didn't find them when a stage had been opened first, though registration reported success; an extension enabled mid-session always registers late. The registered definition also returned no `customData`.
- **Checked:** read straight through `Sdf.Layer.FindOrOpen` after the schema registry was in use, the same file gave back each prim's `doc` and each attribute's type, default, `allowedTokens`, and `customData`. USD tools opening a test tree see prims of an unknown type, with no fallbacks, and accept them without error (**Checked**).

**Muted nodes in Blender.** A Python node can't define its own internal links. **Checked:** `Node.internal_links` is read-only with no `new()`, and `Node`'s overridable functions (`init`, `update`, `insert_link`, `draw_buttons`, `poll`, and others) include none for internal links. Blender chooses them itself: a muted node with inputs Prims (string), Layer (a custom socket), and Value (float), and output Layer, got exactly Layer → Layer, and a muted node with a float input and output got float → float. The cook follows the definitions file's pass-through, and a `blender/` test checks, for every node type, that Blender's automatic internal links match it; a mismatch is fixed by reordering that node's sockets.

**Reuse.** The front end regenerates the whole tree on every change into a scratch layer and moves it with `TransferContent` into a tree layer the cook keeps. USD then names exactly what changed. **Checked,** with a stage on the kept layer listening for `Usd.Notice.ObjectsChanged`, on an eight-node tree:

| Change | What USD reported |
|---|---|
| None | no notice |
| One value | that attribute, as a change of value only |
| One new link | the input it enters, only |
| A node renamed | the old and new prims, resynced, and the input linked to it |

- USD gives what changed, not what depends on it. Sdf reads links forward (**Checked:** a connection list came back in the order authored), but has no index of a node's downstream nodes, and links aren't composition arcs, so Pcp's dependency tracking doesn't apply. The cook makes that index once per tree load and marks the changed nodes' tasks dirty ([Cooking the Layers](#cooking-the-layers)).
- Python's `Sdf.Notice.LayersDidChange` doesn't expose the changed paths; the C++ notice carries a change list per layer, so the cook could work from the tree's layer without a stage (**Not checked**, from USD's API).

### Measurements

**Checked:** a probe recooked one zone's layer the way [Cooking the Layers](#cooking-the-layers) says: author into a scratch layer, then `TransferContent` into the live anonymous layer that a stage composes over a context. Each authoring loop ran twice, in Python and in C++. On every recook, both loops authored the same specs in the same order, and their layers exported identically. Handing the paths from Python to C++ took at most 1.1 ms and isn't counted in the C++ times. Each case ran in its own process, and times are the median of five recooks after a warm-up. The cases:
- **Create:** Create Prim plus three Set Attributes per prim.
- **Over:** Match Prims, then a Set Attribute `over` on each match. The context was generated, or ALab's `entry.usda` with every payload loaded, matched by `/root//`.
- **Arcs:** a Reference per prim to a 21-prim asset.

Each case ran in two modes. In the *tweak* mode, every recook authored the same specs with new values. In the *structural* mode, every other recook renamed the leaf prims (Over: dropped every other over); its figures are the median over both kinds of recook.

Authoring alone, in ms, Python / C++:

| Case | Specs | Through Sdf | Through the Usd API |
|---|---|---|---|
| Create | 1,000 | 17.7 / 4.1 | 45 / 19 |
| Create | 10,000 | 175 / 41 | 438 / 189 |
| Over | 10,101 | 42 / 16 | 191 / 119 |
| Over, ALab | 11,886 | 50 / 19 | 219 / 134 |
| Arcs | 1,000 (21,011 prims composed) | 12.2 / 3.4 | 113 / 97 |

A whole recook, in ms: Sdf authoring, then the transfer and recompose and the matching, which are USD's work in either language:

| Case | USD's work, tweak / structural | Recook, tweak, Python / C++ | Recook, structural, Python / C++ |
|---|---|---|---|
| Create, 1,000 | 3.2 / 16.8 | 21 / 7.2 | 35 / 21 |
| Create, 10,000 | 39 / 195 | 214 / 80 | 371 / 236 |
| Over, 10,101 | 23 / 39 | 65 / 39 | 62 / 48 |
| Over, ALab | 39 / 169 | 89 / 58 | 196 / 182 |
| Arcs, 1,000 | 1.2 / 42 | 13.4 / 4.6 | 54 / 46 |

- **The cook's code versus USD:** C++ Sdf authoring took about 0.45 µs per call (a spec, a field, or a default value), and Python about 1.9 µs. The Python loop was 2.2 to 4.6 times slower than the C++ one. Python's overhead was 8 to 66 percent of a whole recook: largest in tweaks that create prims, and smallest in structural recooks, where recomposition dominates (8 percent over ALab).
- **The API matters more than the language:** C++ through the Usd API was slower than Python through Sdf in every case.
- `TransferContent` costs a measurable amount even with no stage open (30 ms at 10,000 created specs, tweak).
- Reading a changed value after the transfer took at most 0.05 ms, so no recompose was left over for the first read.
- Not measured: the binding's synchronization of the result; what the cook's own bookkeeping (walking the tree, recorded reads, provenance) adds on top of the authoring loops.

**Checked, several zones composed:** a base zone created N prims as in Create, Z−1 department zones each put an over with one attribute on all N prims, and a root zone sublayered them all, with the departments strongest. Times in ms, Python / C++ for authoring:

| Zones × prims | Authoring every zone | Transfers, each on its own | Transfers in one `Sdf.ChangeBlock` | Tweak one department: authoring / transfer and recompose | Structural base recook: authoring / transfer and recompose |
|---|---|---|---|---|---|
| 2 × 1,000 | 22 / 5.6 | 19 | 4.7 | 3.9 / 1.4, then 1.2 | 17 / 3.6, then 3.4 |
| 8 × 1,000 | 45 / 16 | 28 | 13 | 3.9 / 1.4, then 2.7 | 18 / 3.7, then 3.4 |
| 32 × 1,000 | 135 / 47 | 56 | 46 | 4.1 / 1.4, then 2.6 | 16 / 3.5, then 3.6 |
| 2 × 10,000 | 207 / 51 | 206 | 53 | 38 / 14, then 13 | 170 / 38, then 44 |
| 8 × 10,000 | 427 / 150 | 311 | 145 | 37 / 14, then 33 | 161 / 36, then 43 |
| 32 × 10,000 | 1,283 / 515 | 633 | 563 | 37 / 14, then 30 | 159 / 36, then 39 |

- **Recooking one zone costs about the same however many zones the stage composes.** A department tweak's transfer and recompose rose from 13 to 33 ms between 2 and 8 zones at 10,000 prims, then stayed flat at 32. A structural recook of the base stayed at about 40 ms.
- **A full recook scales with the whole tree:** 1.8 s in Python and 1.1 s with C++ authoring for 32 zones of 10,000 prims.
- **Transferring every zone in one `Sdf.ChangeBlock`** recomposes once. It cut the transfers to a quarter with 2 zones, and by a tenth to a fifth with 32, where the transfers themselves dominate.

**Checked, a heavy geometry attribute:** one zone set a Mesh's `points` (`point3f[]`) from a numpy array, with a small attribute beside it. Each size ran three ways: a new array each recook; the same `VtArray` reused while only the small attribute changed; and the same numpy array converted again each recook, so the values were equal but the buffer new. Times in ms:

| Points (array size) | numpy to `VtArray` | Authoring | Transfer: new values / same `VtArray` / equal values, new buffer | Read on the stage, and as numpy | Write `.usdc` | Write `.usda` |
|---|---|---|---|---|---|---|
| 100,000 (1.2 MB) | 1.1 | 0.02–0.03 | 0.01 / 0.00 / 0.11 | ≤ 0.01 | 6–10 (1.2 MB) | 40–42 (3.3–3.7 MB) |
| 1,000,000 (12 MB) | 9.4 | 0.02–0.06 | 0.01 / 0.00 / 0.97 | ≤ 0.02 | 21–26 (12 MB) | 365–398 (33–37 MB) |
| 10,000,000 (120 MB) | 94–96 | 0.02–0.10 | 0.02 / 0.00 / 9.7 | ≤ 0.04 | 61–153 (120 MB) | 3,218–3,681 (334–369 MB) |

- **Authoring and composing a heavy array costs almost nothing:** the attribute holds the `VtArray` without copying, and the stage reads it back, and numpy views it, without copying.
- **The cost is the conversion into a `VtArray`:** about 1.3 GB/s through `Vt.Vec3fArray.FromNumpy`.
- **`TransferContent` compares values.** An equal array in a new buffer cost a full comparison (about 12 GB/s), and the same `VtArray` cost nothing.
- **Writing `.usda` was 7 to 53 times slower than `.usdc`,** and about three times the size: 3.2 to 3.7 s for 10 million points. Write could warn when a heavy layer's file is `.usda`.
- Not measured: time-sampled arrays.

**Checked, getting mesh data out of Blender:** a quad grid built with `foreach_set`, with a UV map, read into preallocated numpy arrays with `foreach_get`, then converted to `VtArray`s. Each conversion ran through `FromNumpy`, and, for 3-vectors, through a C++ function that copies the buffer into a `VtVec3fArray` with one `memcpy`. Both gave equal arrays. Times in ms:

| Vertices (corners) | Positions: `vertices.co` / `position` attribute | Positions to `VtArray`: `FromNumpy` / C++ copy | Face counts (`polygons.loop_total`) | Corner indices (`.corner_vert` attribute) | Counts and indices to `VtArray` (`FromNumpy`) | UVs (attribute), to `VtArray` | Corner normals, to `VtArray`: `FromNumpy` / C++ copy |
|---|---|---|---|---|---|---|---|
| 100,000 (397,000) | 1.9 / 0.02 | 0.97 / 0.03 | 3.3 | 0.12 | 1.1 | 0.2, 1.7 | 1.4, 3.7 / 0.07 |
| 1,000,000 (4.0 M) | 19 / 0.31 | 9.3 / 0.32 | 33 | 0.92 | 11 | 1.5, 17 | 13, 38 / 0.96 |
| 10,000,000 (40 M) | 189 / 2.6 | 94 / 3.1 | 331 | 11 | 117 | 12, 180 | 116, 377 / 10 |

A Subdivision modifier at level 1, read from the evaluated object (`evaluated_get(depsgraph).data`), times in ms:

| Vertices out (in) | `depsgraph.update()` | First read of positions | Second read | `to_mesh()` and a read |
|---|---|---|---|---|
| 99,000 (25,000) | 0.09 | 57 | 0.03 | 0.08 |
| 1.0 M (250,000) | 0.09 | 368 | 0.26 | 0.64 |
| 10 M (2.5 M) | 0.16 | 3,238 | 3.0 | 29 |

- **Blender's attribute API is the fast path:** the `position`, `.corner_vert`, and UV attributes copy at memory speed (about 46 GB/s for positions), 30 to 95 times faster than `vertices.co` or `polygons.loop_total`. A Python loop over 100,000 vertices took 42 ms. `.corner_vert` is an internal name (its leading dot), so it may change between Blender releases.
- **`FromNumpy` is the bottleneck,** at about 1.3 GB/s. A C++ `memcpy` into the `VtArray` was 30 times faster, so 10 million positions take about 6 ms from Blender to a `VtArray`, against 96 ms through `FromNumpy`. `foreach_get` can't write into a `VtArray` directly: its buffer is read-only from Python (it raised an error), so the data is copied twice either way.
- **Face counts have no fast path found:** `polygons.loop_total` took 331 ms at 10 million faces. Topology changes less often than positions, so the cook can keep it while the mesh's topology is unchanged. Not checked: whether `loop_start` or another attribute is faster.
- **A modifier's result is computed when it's first read, not at `depsgraph.update()`:** the first read of a subdivided mesh took 3.2 s at 10 million vertices, and a second read 3 ms. So a node that reads an evaluated mesh pays Blender's evaluation on the read. That it's Blender deferring subdivision until the mesh is needed is inferred, not checked.
- Not measured: other platforms; other attribute domains and types; reading every frame of an animation; a Blender with a window, where subdivision may run on the GPU.

## Effects on the Synchronizer's Contracts

The editor is a caller of the synchronizer, and its layers raise contract questions to decide in [DECISIONS.md](../DECISIONS.md) when Phase 3 work reaches them ("Phase 3 ordering"):
- **Dirty layers:** unwritten zone layers are always dirty, so every synchronization reports the dirty-layer diagnostic ([Layer State and Reloading](../spec/source-access.md#layer-state-and-reloading)).
- **Reload:** a binding's `reload` rereads every dirty contributing layer. Zones' layers and Substitution Zones' copies, a Stage Output's root among them, are anonymous, with no file to reread, so reloading would discard their content. Either reload skips layers the editor authors, or the editor recooks them after a reload.
- **Undo:** the tree is Blender data, so undo restores it, and its layers are recooked from it. A synchronization pushes one undo step ([Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state)), so one run on undo would push a step and clear the redo stack.
- **Incremental synchronization:** `TransferContent` compares content and notifies only what changed ([Cooking the Layers](#cooking-the-layers)), so an unchanged zone sends nothing. **Not checked:** whether a recooked zone's transfer, through the binding's synchronization, keeps Phase 2's [affected content](../spec/incremental.md#affected-content) as small as its notice.

## Testing

Following "Phase 3 ordering", the cook can be written and tested without `bpy` alongside Phases 1 and 2:
- The cook module takes the tree as a USD layer ([The Tree as Plain Data](#the-tree-as-plain-data)) and cooks the layers. The Blender node tree is a front end that produces that layer.
- Tests check the layers and the composed stage through the USD API, with expected values from the spec of each node, and view them with other USD tooling.
- Each test's input tree and expected output are `.usda` files on disk with a comment saying what they check, and any Blender buffers beside them, such as `.npy` files.
- Zone membership and its errors follow [What a Zone Holds](#what-a-zone-holds); pairing through Blender's operators follows [Node Zones](node-zones.md#testing).
- **Reuse:** a differential test applies random edits to trees of base and department zones, and after each, compares the incremental result with a recook of every zone: the layers must match exactly. Each read kind also gets an edit that must invalidate it and one that must not. A debug mode always recooks every zone and checks the same.
- Every node definition has an implementation in the cook, and the reverse.
- In `blender/`: for every node type, Blender's automatic internal links for a muted node match the definition's pass-through.

## Open questions

- **Names.** Is "New Layer Zone" the zone's name; "Layer", "Editable Layer", and "File" the sockets'; "Substitution Zone" the zone that reads a root and substitutes into it, and "item" each file it substitutes; and "Context Hint" the input's?
- **Value socket count:** about 30 socket types, one per stored type. A single Value socket that carries any type, checked when linked, would be one socket type, at the cost of showing no type until the tree cooks.
- **Drawing a Context Hint link:** a dashed link drawn by the editor, or a hollow socket shape ([The Zone's Stage](#the-zones-stage))?
- **Verification:** whether it runs on every cook or only on request. It looks up only the zone's own edits ([Provenance](#provenance)), but each output stage it looks them up in composes the whole stage.
- **Coordinate conversion:** whether the editor's Stage Outputs request the binding's conversion on. The spec's default is off, and the editor's choice as a caller changes nothing in the spec.
- **Rereading layers the tree doesn't own:** when another department updates `anim.usda`, the user rereads it on request ([Layer State and Reloading](../spec/source-access.md#layer-state-and-reloading)). Does the request live on the Layer from File node, for every layer its stage composes, or on each layer?
- **Errors in a chain:** pass the layer through, as above, or stop the chain?
