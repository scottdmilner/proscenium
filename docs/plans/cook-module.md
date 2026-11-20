# Cook module: plan

How Phase 3's cook becomes a package of its own, `proscenium_cook`. The cook takes one node tree as a USD stage. It returns a stage for each Stage Output node and one for the active Viewer, which each cook names, and a report for each node that has diagnostics. Most of the design is in [node-tree.md](../phase3/node-tree.md), a design note, and this plan builds it. Neither adds a requirement. Where this plan settles something the note leaves open, it says so, and the note gets the same change.

The cook is bpy-free authoring code, so it may proceed alongside Phases 1 and 2 ([DECISIONS.md](../DECISIONS.md) "Phase 3 ordering"). It authors only anonymous layers of its own and the stages it composes on them. It never authors a caller's layers or stages, reads none of Blender's data, and doesn't call the synchronizer. Out of scope:
- the Blender front end that turns a node tree into the tree's stage and hands each Stage Output's stage to a binding, which depends on the synchronizer;
- nodes that read Blender data, and the buffers they'd pass beside the tree;
- the note's **Later** list ([Scope](../phase3/node-tree.md#scope)).

## The interface

### Input

The cook takes the tree as a `Usd.Stage` whose root layer holds it, in [the note's format](../phase3/node-tree.md#the-tree-as-plain-data): a `/Tree` prim of type `NodeTree` with `int tree:format`, every node a child prim of it, links as attribute connections, and `rel zone:end` from each begin to its end. Muting, the `//` base directory, and node IDs work as the note says.
- **It reads only the root layer, through Sdf,** never the composed stage. A tree has no composition arcs, and a sublayer or arc in its root layer is a tree-level error. The note describes the input as a layer. A stage is the input here because the incremental cook listens for `Usd.Notice.ObjectsChanged` on it ([Reuse](../phase3/node-tree.md#the-tree-as-plain-data)): the caller regenerates the tree into a scratch layer and moves it into the stage's root layer with `TransferContent`, and USD names exactly what changed.
- **The caller keeps the stage.** The cook holds it from its construction until it's dropped, and never edits it.
- **Its other inputs** are an optional base directory for `//` paths, given once, and the active Viewer's node ID, given to each `cook`, or none.

### Output

One call to `cook(viewer=None)` returns a `CookResult`:

| Field | Holds |
|---|---|
| `stage_outputs` | One `Usd.Stage` per Stage Output node, keyed by node ID: the stage composed on the layer linked into it, with every payload loaded. An unlinked Stage Output, or one whose input layer failed, has no stage and reports why. |
| `viewer_stage` | The active Viewer's `Usd.Stage`, or `None`, composed as [the note's Viewer](../phase3/node-tree.md#viewer) says, and reused while its root layer stays the same, as a Stage Output's is. An unlinked Viewer, or one whose input layer failed, has no stage. An unlinked one reports nothing, since the editor shows there's nothing to view. |
| `node_reports` | One `NodeReport` per node that has diagnostics or report data, keyed by node ID. A node with neither has no entry. |
| `tree_diagnostics` | Problems that belong to no node: an unreadable tree, an unknown `tree:format`, a sublayer or arc in the tree's layer. |

**The cook cooks one Viewer, the one `cook` names** (with the user). The editor shows one Viewer at a time, so the others don't run, and a zone makes at most one copy for a Viewer partway down its chain. The tree keeps every Viewer, so switching Viewers changes no tree, and a test tree can hold several, one per case. A Viewer that isn't active keeps no stage, and a node it was linked to no copy, from an earlier cook, so switching through Viewers on a heavy scene holds one Viewer's stage, not one per Viewer ever shown; switching back composes it again. An ID that names no Viewer, such as one the editor sends after the Viewer is deleted, is a tree warning, `unknown-viewer`, and the cook goes on with none, so the Stage Outputs still get their stages.

- A `NodeReport` holds `diagnostics`, a tuple of `NodeDiagnostic`s, and `report_data`, which starts empty and later holds data such as [Set Transform's stacks](../phase3/node-tree.md#set-transform).
- A `NodeDiagnostic` holds a `severity` (error or warning), a `code` from a fixed vocabulary in the cook, a `message`, and, where the problem has one, the `source_path` in the authored layer it concerns. These are the cook's own types, not `proscenium_sync.results`' ([Where It Lives](../phase3/node-tree.md#where-it-lives)).
- Returned stages share the cook's anonymous layers. Each cook returns a Stage Output's same stage while its root layer stays the same, since a binding reuses its evaluation stage only while the source stage's root and session layers stay the same, and tools author in the session layer ([Source Stages](../spec/source-access.md#source-stages)). A stage kept after the cook is dropped keeps its layers alive and still composes. The cook keeps no stage it returned alive beyond its own lifetime.
- `cook` raises only for misuse, such as a stage that has expired. Problems in the tree are diagnostics. The rest of the tree still cooks ([Diagnostics](../phase3/node-tree.md#diagnostics)).

### API

A suggested shape, settled in step 2:

```python
import proscenium_cook

tree_cook = proscenium_cook.TreeCook(tree_stage, base_directory=blend_directory)  # holds tree_stage
result = tree_cook.cook()  # a full cook first; then only what changed (step 13)
result.stage_outputs["Stage Output"]  # a Usd.Stage
result.node_reports["Set Attribute"].diagnostics
```

`TreeCook` is the stateful object because reuse needs state: the zones' layers, their edit tables, and their recorded reads stay between cooks, so returned stages keep composing the same layers. Until step 13 every `cook` recooks the whole tree into the layers it keeps.

## Evaluating the tree

The cook evaluates the tree as a DAG of tasks, as [Cooking the Layers](../phase3/node-tree.md#cooking-the-layers) describes. A full cook and an incremental one (step 13) share one graph and one scheduler. The only difference is which tasks are dirty: every task in a full cook, and only those a change reaches in an incremental one. That's why the differential test can expect identical layers.

### Two graphs

- **The node graph:** one vertex per node and one edge per link, read from the tree's connections and `zone:end` relationships. It must be acyclic (step 3), and it decides chains and zone membership.
- **The task graph:** the units of work, built from the node graph:

| Task | Made from | Produces |
|---|---|---|
| Layer from File | one node | the file's layer |
| New Layer Zone | its begin, its chain, and its end, run in chain order | the zone's layer, edit table, and recorded reads; a copy for the active Viewer partway down its chain |
| Substitution Zone begin | one node | the root's layers, and each item's File and position |
| Substitution Zone end | one node | the root's anonymous copies |
| Stage | one Stage Output or Viewer | the stage composed on its input layer |

Value nodes (Prim, Match Prims, Value, Convert) aren't tasks. Each is computed once per cook, in the node graph's order, so its value is ready before any node that uses it, and a Prims expression is matched at the node that uses it, against that node's stage. A value node fed by a chain node, such as a Prim from another zone's Create Prim, makes its consumer's task depend on that zone's task.

### Edges between tasks

A task waits for another when a link brings that task's result into it. These are the **ordering edges**:
- **A Layer link:** into a Template, Context Hint, Sublayer, Reference, or Payload Source Layer, an item's input on a Substitution Zone's end, a Stage Output, or a Viewer;
- **A File link:** from a Substitution Zone's item into a New Layer Zone, carrying the file and the context it derives.

**A value from a chain node isn't an ordering edge.** Create Prim's Prim output, for example, may feed a node in another zone. That only dirties its consumer's task when the value changes, as the note's rule 1 for a zone's own content says ([Cooking the Layers](../phase3/node-tree.md#cooking-the-layers)). It doesn't make that task wait. This works because a chain node's value outputs are computed from its own value inputs and properties, never from its zone's stage: Create Prim's Prim is its Parent joined with its Name. Every chain node with a value output must keep to that rule. A node's definition declares it, and the test of definitions against implementations checks it.

A Substitution Zone's end depends on its begin, and on which items are linked, but not on the linked zones' content. Its copies name each zone's anonymous identifier, so the copies come before the zones they name ([Cooking the Layers](../phase3/node-tree.md#cooking-the-layers)). That's possible because **a zone's anonymous layer exists before any task runs.** The graph is built first and allocates one layer per zone, kept across cooks while the zone's begin node keeps its ID. Tasks then fill in content.

So the ordering edges all follow links between tasks, and an acyclic node graph gives an acyclic task graph. Should a later node break this, the cook doesn't drop the task silently: each node of a task on a cycle of tasks gets a `cycle` error. A node whose value output needed its zone's stage, such as a later node that output a value it read, would break this. Zone A's node could feed zone B while A sublayers B: acyclic between nodes, but cyclic between tasks, since each zone cooks as one task. Such a node needs its own rule before it's added.

### Nested zones

What a zone holds is decided by its chain, not by where it's drawn ([What a Zone Holds](../phase3/node-tree.md#what-a-zone-holds)), so nesting means something different for each kind of zone:
- **A Variant Zone inside a New Layer Zone** is a stretch of its parent's chain, inside the parent's task. Its begin and end must nest as brackets on the chain.
- **A New Layer Zone inside a Substitution Zone** is a task of its own. It waits for the begin through its File link. The end's copies wait only for the begin, since they name the zone's layer and not its content. The Stage Output composing the end's copy runs last.
- **A New Layer Zone never sits inside another New Layer Zone.** Its begin has no Editable Layer input, so its begin and end are never on another zone's chain. One that feeds another through Sublayer, Reference, or Template is a separate task that runs first, and the editor draws the two side by side. It doesn't take the outer zone's stage as its context: the outer zone composes its layer, so that would be a cycle. Its context comes from its File or its Context Hint, as any zone's does.

### Order and results

- **Serial, in topological order, upstream first.** Each task reads its upstream tasks' committed results. Ties are broken by node ID, so the order, and so the result, is the same on every cook.
- **Waves:** zones whose upstream tasks have all committed form a wave, and a wave's transfers run in one `Sdf.ChangeBlock`, so each downstream stage recomposes once. Stage tasks run last, after every zone they compose has committed.
- **Upstream failures:** a task whose input produced no layer, such as a Layer from File whose file is missing, runs without that input. The node that consumes it warns once, naming the upstream node, and doesn't repeat that node's diagnostic. A Stage Output with no input layer has no stage.
- **Every task runs, linked or not,** except the Viewers other than the active one. A zone that no Stage Output composes still cooks, so it reports its errors and the Viewer can show it.

## The package

| Path | Holds |
|---|---|
| `packages/proscenium_cook/pyproject.toml` | The project, its `[tool.importlinter]` contracts, and its wheel's build hook |
| `packages/proscenium_cook/hatch_build.py` | Builds `_cook` through `tools/native_build.py` and ships it in a wheel tagged for the platform, as `proscenium_sync`'s hook does for the planner |
| `src/proscenium_cook/__init__.py` | Exports the API: `TreeCook`, `CookResult`, `NodeReport`, `NodeDiagnostic`, and the severities and codes |
| `src/proscenium_cook/node_definitions.usda` | One `class` prim per node type ([Node Definitions](../phase3/node-tree.md#the-tree-as-plain-data)) |
| `src/proscenium_cook/tree_cook/` | The C++ module `_cook`, its CMake project, its type stubs, and an `AGENTS.md` like [the planner's](../../packages/proscenium_sync/src/proscenium_sync/planner/AGENTS.md) |
| `src/proscenium_cook/tree_cook/nodes/` | One `.cpp` per node type with its generated attribute header beside it, checked in, and `node_registry.cpp` |
| `tools/node_attributes.py` | Writes the attribute headers from the definitions file (`render`), or fails when they're out of date (`check`, a pre-commit hook) |

- **All of the cook is C++, every node's behavior included.** Of PROJECT.md's criteria for a compiled component, only the second is met today: mapping a composition error to the node that authored it needs the C++ error types' fields, which Python's `pxr` doesn't expose. The rest is a judgment about the work after the first feature set ([Why C++](../phase3/node-tree.md#why-c)). For-each zones and trees of many zones multiply the authoring calls, Blender's arrays convert on every frame, and a Python cook would have to be rewritten node by node to move later. Phase 3 has no budgets yet, so the module's DECISIONS.md row records the choice as a judgment. The planner's [boundary rules](../../packages/proscenium_sync/src/proscenium_sync/planner/AGENTS.md#boundary-rules) apply. The error translation is copied from the planner at first, not shared.
- **A node reaches the tree, its zone's stage, and its layer only through its context.** The context reads the node's inputs, with definitions' defaults for unauthored ones. It reads the zone's stage through the recording reader, and authors through the Sdf API at the variant path the node is inside. It records each write in the edit table, and takes the node's diagnostics. So reads are recorded, provenance is complete, and variant paths are right because of the interface itself, not because each node remembers to do it.
- **A node type is a registered function, with one signature per role** ([Node Types in C++](#node-types-in-c)). Its typed inputs and outputs are generated from the definitions file, and the checks every node shares run once, from the definitions.

### Node types in C++

**Roles.** The node types play four roles, and each has its own function signature, so a node can do only what its role allows:

| Role | Node types | Signature |
|---|---|---|
| Value | Prim, Match Prims, Value, Convert | `const ValueInputs&` in, its outputs returned. It gets no stage and no layer, so it's pure because of its signature. |
| Authoring | Create Prim, Edit Prim, Set Attribute, Set Transform, Configure Layer, Sublayer, Reference, Payload, Set Variant Selection, Relocate | `AuthoringContext&`: one step of a chain, which reads the zone's stage and authors into its scratch layer. Its value outputs are computed from its inputs and properties alone ([Edges Between Tasks](#edges-between-tasks)). |
| Zone | New Layer Zone, Variant Zone, Substitution Zone | Hooks the task machinery calls, each null for a type that needs none: a begin's file, the layer it starts from, and an end's outputs, and as later steps need them, its context and a Variant Zone's edit target. Most of a zone's behavior is the machinery's own. |
| Task | Layer from File, Stage Output, Viewer | `TaskContext&`: a task of its own, outside any chain, and for one that reads a file, a hook naming it, so the zones' file check sees it before any task runs. |

**One registry.** `node_registry.cpp` holds the one list of node types. Each entry is a type name mapped to its role's behavior: a `std::variant` of the four. An upgrade function for older `node:version`s joins the entry with the first type whose version changes.
- The definitions test compares this list with the definitions file.
- Node types don't register themselves through static objects. If the code is ever built as a static library, the linker drops translation units that nothing references, along with their registration, and the node disappears with no error.

**No state on a node.** A function has nowhere to keep state between cooks. What a node keeps, such as an array converted from Blender's buffer, it keeps through `context.Cache<T>(key)`. That cache is the zone's task's, keyed by node ID, so reuse and the differential test see it.

**Generated attributes.** A script in `tools/` reads the definitions file through Sdf and writes a header per node type, beside its `.cpp`. It holds two structs, each naming its attributes as constants: the node's typed inputs and properties, with the reader that fills them, and its typed outputs, with the writer that commits them by name. A node commits nothing by name itself.
- **Value types:** each attribute's `SdfValueTypeName` gives its C++ type through `GetType()`.
- **Socket kinds:** the kind in `customData` gives `SdfPath`, `SdfPathExpression`, a layer handle, or `std::vector` for a multi-input. An output commits each as a linked input reads it: a layer handle, or a File's, Prim's, or Prims' string. An output left empty commits nothing, so its consumers warn that it brings nothing.
- **Three-state fields** become an `AuthoredField<T>`: unauthored or set, and, for list ops, removed, which arrives with Edit Prim (step 11), the first node to author a removal.
- **Dynamically typed inputs** stay `VtValue`, such as Set Attribute's Value, whose type follows its Type property, and the node checks them itself.
- **What this buys:** renaming or retyping an input or output in the definitions breaks the compile of the node that reads or commits it, and defaults are applied once, in the reader.
- **Checked in, not generated at build time.** The headers are checked in, and a pre-commit hook fails when they're out of date, as `proscenium-matrix check` does for the matrix. Diffs then show what changed in an interface, clang-format and clang-tidy see the generated code, and the build needs no generation step.

**Shared checks run once.** The context checks every node's inputs against its definition before the node runs, so no node repeats these checks:
- a token outside its `allowedTokens` (a warning, except in a closed menu, such as `upAxis` or a specifier);
- a Prim that isn't an absolute prim path, or names a property or a variant;
- an input or property the definition doesn't have;
- a `node:version` newer than the cook's.

Behavior stays in C++, never in the definitions file, so it lives in one place.

**Each node type has:**
- its definition;
- its generated attribute header, beside its `.cpp`;
- one `.cpp` file with its function and its helpers in an anonymous namespace;
- its diagnostic codes, in `cook_diagnostics.h` and in Python's `DiagnosticCode`, which importing the package checks against each other;
- a line in `node_registry.cpp`;
- its README entry.

Report data crosses to Python as a `VtDictionary`, so one binding carries every node type's data. A type whose data grows past a dictionary can get a binding of its own later.
- **It imports neither other package,** and neither imports it. The root contracts get its place: `proscenium_cook` beside `proscenium_sync | proscenium_ui`, and a protected contract so other packages use only its `__init__.py`'s names.
- **It's a runtime dependency,** for the temporary UI's cook tree (`src/proscenium/interface/`), a minimal front end for trying the cook in Blender: it builds a node type per definition, writes the tree as its layer, cooks it, and prints the diagnostics and stages. It hands no stage to a binding. The cook is in the root `[project] dependencies`, `tools/build_extension.py` builds its wheel with the others, and its compiled component has its DECISIONS.md row. `tests/bpy_free/test_build_extension.py` checks that the cook's wheel builds and passes the linkage audit.
- **`tools/native_build.py`** gains `COOK`, a `NativeModule` built to `build/cook/`, so the linkage audit and the pinned headers cover it.

## Tests

- **Layer:** `bpy_free/`, since the cook imports without `bpy`. A tree that could crash the module, such as a malformed connection, runs in `isolated/` ([tests/AGENTS.md](../../tests/AGENTS.md)).
- **Fixtures:** `tests/fixtures/cook/<case>/`, holding `tree.usda` and the files it reads, each `.usda` starting with a comment that says what it checks. Expected results are in `expected/`: an exported layer per zone, or a list of expected values per prim.
- **Oracles:** each node's section in the note, and USD's own APIs on the returned stages (`Usd.Prim`, `UsdGeom`, `Sdf.Layer.ExportToString`), never recorded cook output.
- **Each node's step adds:** a case per authored behavior, a case per diagnostic it reports, a muted case that checks its pass-through, and its row in the definitions-to-implementations check.
- **Determinism:** cooking one tree twice exports identical zone layers ([Cooking the Layers](../phase3/node-tree.md#cooking-the-layers)). One test covers every fixture as steps add them.

## Implementation sequence

Each step is a commit or two, passes pre-commit and the test suite on its own, and updates the READMEs, the note, and this plan's [decision log](#decision-log). The whole sequence is more than two commits, so it's done in a worktree of its own, one branch per stretch of steps. Each step names what it adds beyond its nodes. The node steps add one or two node types each.

A step's order follows what its tests need to build a tree: a node can't be tested before the nodes that feed it.

### Groundwork

1. **This plan,** and the note's [Where It Lives](../phase3/node-tree.md#where-it-lives) pointing to it, in place of its sentence that Phase 3 has no plan file.
2. **The package, empty.** `proscenium_cook` with its `pyproject.toml`, build hook, `COOK` in `tools/native_build.py`, an `_cook` that only loads, its READMEs and `AGENTS.md`, its import contracts, and a line in the root AGENTS.md's repository map. Tests: it imports without Blender's modules (`test_no_blender_imports.py`), and its wheel builds and passes the linkage audit.
3. **Reading the tree.** The node definitions file and its loader; the four roles' signatures, the registry, and the contexts ([Node Types in C++](#node-types-in-c)); `tools/node_attributes.py` and its pre-commit hook, tested on each socket kind and value-type family with a definitions file of test-only node types; the shared checks; `TreeCook` and the result types; checking the tree against the definitions (unknown node type, newer `node:version`, unknown input or property, a connection to nothing, a link between incompatible socket kinds, a cycle); decoding node IDs from prim names; the node graph and its topological order; the scheduler, which runs tasks in that order ([Evaluating the Tree](#evaluating-the-tree)); muting from each definition's pass-through. There are no node types yet, so every tree cooks to an empty result with diagnostics. Tests: malformed trees, one diagnostic each; the generator on test-only definitions; the definitions loader on malformed ones. The checks that need a node type are built here and tested in step 4, with its first types.

### Reading files

4. **Layer from File and Stage Output.** The first stage out: a Stage Output's stage composed on a file the tree reads. Adds Path properties and the `//` base directory ([The `//` Base Directory](../phase3/node-tree.md#the-tree-as-plain-data)), and the Stage Output's warning for a root layer that authors no `upAxis` or `metersPerUnit`. The Stage Output's coordinate conversion property is carried in the tree and read by the front end. The cook doesn't convert. Its tests also cover the step 3 checks that these two types can reach:
   - a newer or missing `node:version`, and a `node:version` or `node:mute` of the wrong type;
   - an unknown attribute, a wrong attribute type, and too many links;
   - a muted node, with and without an error, passing nothing, since neither type has a pass-through;
   - a node's cache, kept by its ID and type, so a new node reusing a deleted one's name starts empty.

   Neither type has a token, a Prim, a Prims, or a socket of another kind, so the rest wait for the first types that do: a Prim that isn't a path, an incompatible link, and a pass-through (also through a muted node with an error) for step 8, and a token outside its menu and a Prims that doesn't parse for step 9.
5. **Viewer, on a Layer.** Its stage composed on a finished layer, with every payload loaded, sharing the layer with any Stage Output on it. It isn't converted, so it doesn't warn of a root layer's missing metrics. The Context checkbox does nothing until zones have a context (step 12), and an Editable Layer input waits for step 8.

### Authoring layers

6. **New Layer Zone.** The begin and end pair, with the File input typed (a Substitution Zone's File comes in step 19). Each names the other's type in its definition's `customData` (`zone` and `zonePartner`), and a begin names its end with `rel zone:end`. This step adds zones:
   - the chain, and its errors: an unpaired begin or end, a branch, a broken chain, a mismatched pair, an authoring node in no chain ([What a Zone Holds](../phase3/node-tree.md#what-a-zone-holds));
   - the zone as one task, and the task graph built from the node graph, ordered by the Layer and File links between tasks, with each zone's anonymous layer made before any task runs and kept in its begin's cache ([Evaluating the Tree](#evaluating-the-tree)). Value nodes are computed first, in the node graph's order;
   - the zone's anonymous layer, cooked into a scratch layer and moved with `TransferContent`, so a returned stage keeps composing it across cooks;
   - an error in a chain stopping it: the zone gives no layer out, and its end warns, naming the node with the error ([Diagnostics](../phase3/node-tree.md#diagnostics));
   - the error for two zones with one file, each identified as USD's resolver identifies a new file, then compared with its deepest existing directory resolved through symlinks, and in lowercase on a file system that ignores case. A problem with a zone's file is its begin's error, so it stops the zone.

   An empty zone linked to a Stage Output is the test, with the chain errors that a begin and an end alone can make, two zones with one file, and a muted begin. The chain errors that need an authoring node, a node in no chain and the nodes of a broken chain, are built here and tested in step 8. The Template and Default Prim inputs come in steps 7 and 8.
7. **The Template input.** The zone's file check gains its other half ([Writing](../phase3/node-tree.md#writing)): a zone whose file a Layer from File reads is an error on both nodes, which is how a zone whose Template is its own file appears. The error stops the zone, and the Layer from File doesn't read its file. Two Layer from Files may read one file. The zone starts as a `TransferContent` copy of its Template, then one `UsdUtils.ModifyAssetPaths` pass anchors its relative asset paths to the Template's file (`layer_copies.h`). The routine is shared with the Substitution Zone's copies (steps 19 and 20). The write table starts here, for paths from a Template ([Provenance](../phase3/node-tree.md#provenance)): kept beside the zone's layer in its begin's cache, carried into a zone whose Template is another zone's layer, and reported as the begin's `anchoredPaths` report data. A Template linked to a node that brings nothing warns on the begin and stops the zone; an unlinked one starts it empty. Files compare with relative paths made absolute against the working directory, so a Layer from File's `own.usda` and a zone's `./own.usda` are one file. Its fixture is the note's Template with a relative path in each place one can live, checked against the Template's own stage and Sdf's anchoring of each path.
8. **Prim and Create Prim.** Create Prim's spec, the `over`s for missing ancestors, and its Prim output; Prim's path checks. Its tests cover three of step 3's checks: a Prim that isn't an absolute prim path, an incompatible link (a Prim into a Layer input), and a muted Create Prim passing its Editable Layer through, also with an error. A link through a muted Create Prim to a node that failed warns naming the failed node, once however many links reach it. This step also adds:
   - the New Layer Zone end's Default Prim input, and its report;
   - the Viewer on an Editable Layer partway down a chain, which copies the scratch layer as the chain passes it ([Viewer](../phase3/node-tree.md#viewer));
   - the authoring node in a chain: its scratch layer through its context, and the edit table, starting with the prim specs a zone holds ([Provenance](../phase3/node-tree.md#provenance)). Its tests cover step 6's chain errors that need one: a Create Prim in no chain, the nodes after it, which report nothing, and a broken chain's nodes, which warn that their edits never reach its end. A Create Prim with an error stops its chain;
   - the definitions' rule that a chain node's value outputs don't read its stage, with Create Prim's Prim, the first ([Edges Between Tasks](#edges-between-tasks)). A chain node's value outputs are computed with the value nodes, before any task runs, and committed where its consumers read them, so a value node fed by another zone's Create Prim gets its value;
   - a test that the nodes after a branch report nothing, since the node that branches has the error.

### Editing prims

9. **Value and Set Attribute.** Set Attribute's Value and Block modes, on Prim inputs, which convert to Prims as single-path expressions. Its tests cover the last of step 3's checks: a Mode outside its menu, and a Prims that doesn't parse. Value sockets start with the scalars, text, and vector families. Quaternions and matrices arrive with step 17, which first needs them. This step also adds:
   - the zone's stage: the zone's layer over its context, which is empty until step 12;
   - the recording reader, through which every node reads its zone's stage from here on, so reuse (step 13) has every read recorded ([Recorded Reads](../phase3/node-tree.md#cooking-the-layers)). Set Attribute's attribute-type read is its first.
10. **Match Prims.** Expressions matched against the zone's stage at the node that uses them, recorded as subtree reads at the expression's fixed prefix. A parse error is reported on Match Prims, and a warning that an expression matches nothing on the node that uses it.
11. **Edit Prim.** API schemas (apply and remove, with instance names), `active`, `kind`, `instanceable`, type name, and specifier, each with the three states ([Nodes](../phase3/node-tree.md#nodes)).

### Composing layers

12. **Sublayer and the Context Hint input.** Sublayer's appends to `subLayers`, with the zone's anonymous identifier for a linked zone. A fixture has a zone fed by another zone's Create Prim, which that zone sublayers further down its chain, so the two zones' tasks run in another order than their nodes. The Context Hint input gives a zone its context, and the Viewer's Context checkbox now composes the zone's layer over it. This step also adds two pieces that need a stack of layers to test:
    - composition errors, read from the C++ types, mapped to the node that authored the arc through the edit table: here a missing sublayer;
    - verification against each Stage Output's stage, warning where a stronger opinion hides an edit ([The Zone's Stage](../phase3/node-tree.md#the-zones-stage)).

    A department over a base is the fixture: two zones, one sublayering the other or using it as its Context Hint.
13. **Reuse.** No new node: the incremental cook, on the task graph from step 6. It adds dirty marking from `ObjectsChanged` on the tree's stage, an index of each node's downstream tasks, recooking a zone when a change reaches one of its recorded reads, and a wave's transfers in one `Sdf.ChangeBlock` ([Cooking the Layers](../phase3/node-tree.md#cooking-the-layers)). Tests:
    - the differential test: random edits to trees of base and department zones, each compared with a full cook, which must match exactly;
    - for each read kind so far, an edit that must invalidate it and one that must not;
    - a debug mode that always recooks every zone and checks the same.

    It comes here, after the first composition node, so reuse is built when the nodes that read other zones exist, and each later step adds its own reads to the differential test.
14. **Configure Layer.** Layer metadata, each field with its own toggle. The Stage Output's metrics warning from step 4 gets its first case where a zone is the root.
15. **Reference and Payload.** One step, since they share their sockets and code. External and Internal modes, the four list edits applied in chain order ([List Edits](../phase3/node-tree.md#list-edits)), the warning for an edit a later Explicit discards, and composition errors for unresolved arcs and missing target prims, including errors in a referenced zone's own arcs.

### Variants, transforms, and relocates

16. **Variant Zone and Set Variant Selection.** Edits inside a variant, at its variant path, and nested variants; the zone's stage with the variant selected; the errors for an edit outside the owner's subtree, and for layer metadata inside a variant. Set Variant Selection comes with it, so a fixture's Stage Output can show each variant. The variant path in composition errors' sites is tested here ([Provenance](../phase3/node-tree.md#provenance)).
17. **Set Transform.** Components and Matrix modes, the four placements, Reset Xform Stack, and report data: each matched prim's stack before and after, grouped by stack. This step adds the quaternion and matrix value sockets, and the warning for a value that stops an attribute's animation, which Set Attribute gains here too.
18. **Relocate and Convert.** Two small nodes: Relocate's entry in `relocates`, with its own Source checks, since USD drops some invalid relocates silently; Convert between value types of one width, as USD's casts do.

### Substitution

19. **Substitution Zone: sublayers.** The begin reads its root and offers the files the root composes as sublayers, and each item's File output gives a New Layer Zone its file and its derived context. The end copies each ancestor of a substituted file and names the zones' layers in their place ([How the End Makes Its Copies](../phase3/node-tree.md#substitution-zone)), reusing step 7's anchoring routine. The begin's and end's reports, and the warnings for a Layer from File that composes a zone's file without the zone in its place, come with it. A New Layer Zone's File linked from an item is read once the Substitution Zone's begin has committed it, so the zones' file check runs after that task rather than before every task. A File link can put a begin on a cycle, which tests that its end warns, naming it, rather than reporting itself unpaired. The fixture is the note's shot with `anim`, `lighting`, and `env`.
20. **Substitution Zone: arc targets.** Items for files that references and payloads target, at every occurrence and any depth; their derived context, the file's own sublayers, with the warning for each one the zone doesn't sublayer; a file composed both above and below another item. The fixture is the note's chair composed five ways.

### Writing

21. **Write.** The cook's `write` saves each composed zone's layer to its file, applying the write table in one `UsdUtils.ModifyAssetPaths` pass over a copy ([Writing](../phase3/node-tree.md#writing)). It refuses while a node that a Stage Output depends on has an error. The question before overwriting a file the tree hasn't written stays the front end's. Tests: a written set of files, reopened, composes as the Stage Output's stage did, and moves together.

## Open questions

For the user to settle, each before the step named:
- **Step 9:** the value socket count, one socket per stored type or a single Value socket ([Open Questions](../phase3/node-tree.md#open-questions)). The cook reads values by their USD types either way, so this mostly concerns the front end. The tree's format is fixed here, though.
- **Step 12:** whether verification runs on every cook or only on request.
- **Step 21:** whether Write is the cook's, as here, or the front end's, using a write table the cook returns.

## Decision log

- **Plan (2026-11-18).** The cook takes the tree as a stage, so the incremental cook can listen to it, and returns the stage of the one Viewer each cook names as active. It's a workspace member that ships only once a front end uses it. A full cook and an incremental one share one task graph and scheduler. A chain node's value output, such as Create Prim's Prim, dirties its consumers but doesn't order them, since it's computed from the node's own inputs, so an acyclic tree always gives an acyclic task graph. A New Layer Zone is never nested in another: its begin has no Editable Layer input, so each is a task of its own. Nodes come in one or two per step, in the order their tests need them, with reuse after the first composition node.
- **All C++ (with the user, 2026-11-18).** The whole cook, nodes included, is C++, though only the composition-error mapping meets PROJECT.md's criteria today. A Python cook with C++ helpers would iterate faster, but the work after the first feature set would grow its share of the cook, and it would split each node's behavior between two languages or need a full port. Each node works through one context, which makes recorded reads and provenance hold by construction.
- **Node types are registered functions with generated attributes (with the user, 2026-11-18).** A function per node type, with a signature per role, so value nodes are pure because of their signature, and no node can keep state outside its task's cache. A class per type would allow state on a node object, which reuse can't see. One explicit registry, since self-registering objects can vanish at link time. Typed inputs and outputs are generated from the definitions file into a header beside each node's `.cpp` and checked in, so an interface change breaks the compile of every node it affects, and no node names an attribute by hand: outputs need that as much as inputs do, and a node's files stay together. Checks every node shares run once from the definitions. Behavior isn't declared in the definitions file: most nodes need code, and declared behavior would give logic a second home that a node moves out of as it grows.
- **Reading the tree (with the user, 2026-11-18).** The API keeps this plan's names. Diagnostic codes work as the planner's do: stable strings in C++, which a Python `StrEnum` lists, and importing the package fails when the two differ. The checks that need a node type are tested from step 4, with the first types, rather than through test-only node types or a test-only API. A definition's `customData` keys are `socket`, `multiInput`, `optional`, `dynamicType`, and, on an output, `mutePassThrough`, which `node_definitions.usda` documents. A node with an error from the shared checks doesn't run, so its outputs bring nothing downstream, and a muted node doesn't run either: its consumers read through it.
- **Reading files (2026-11-18).** A link that brings nothing, because the node its tracing ends at failed, can't run, or is muted with no pass-through, warns on the node it enters, once per such node, naming it (`no-upstream-value`). The cook gives this warning for every node, so no node type repeats it, and that node's own diagnostic isn't repeated downstream. A Tf error a node raises and doesn't report itself becomes a `usd-error` on that node, so it never turns the cook into an exception. A Layer from File keeps its layer in its cache, which holds it open between cooks, so a later cook finds the process's same copy rather than reading the file again. That copy shows other tools' unsaved edits. A Stage Output keeps its stage in its cache and returns the same one while its root layer stays the same, so a binding keeps its evaluation stage and session-layer edits survive. A returned stage is owned by Python, so it outlives its cook. A Stage Output with nothing linked warns (`unlinked-input`) and has no stage. A path starting with `./`, `../`, `.\`, or `..\` warns, but a bare relative path doesn't, since it may be an identifier a custom resolver reads. The coordinate conversion property is a `bool`, off by default, as the binding's setting is ([Coordinate Conversion](../spec/support/transforms.md#coordinate-conversion)).
- **The Viewer (2026-11-18).** A Viewer composes and keeps its stage as a Stage Output does, through one shared helper, so the editor's tree keeps its stage across cooks too. With nothing linked it has no stage and reports nothing, unlike a Stage Output: the editor shows there's nothing to view, and a Viewer saves nothing, so its warning would only repeat that. It doesn't warn of missing metrics, since its stage feeds no binding and isn't converted. Context is a `bool`, on by default, as the note says.
- **New Layer Zone (with the user, 2026-11-18).** An error in a chain stops it, settling the note's open question: the zone gives no layer out, the nodes after the error don't run, and the zone's end warns, naming the node with the error, so a stage never shows a layer with an edit missing as if it were whole. A problem with a zone's file, such as two zones with one file, is its begin's error and stops the zone too. A begin and its end name each other's type in their definitions' `customData`, which the front end reads too, and the loader checks each names the other back and that only zone nodes have a zone's implementation. A zone's task holds its begin, its chain, and its end only when the chain reaches it, since a broken zone gives nothing out: with the end left out, a broken zone's task feeds none, which keeps the task graph acyclic. Each zone's layer is kept in its begin's cache, so it lasts while the begin keeps its ID and type. A zone's file is identified as USD's resolver identifies a new file, so two spellings of one path are one file. The chain errors and rules that need an authoring node are built in this step and tested with Create Prim (step 8), and the cross-zone fixture with Sublayer (step 12), since the step 3 decision rules out test-only node types; the edit table comes with the first node that fills it. A zone whose chain doesn't reach its end still runs its chain, so its nodes report their own errors while the zone is being built, and from step 8 a Viewer partway down it shows the chain so far. Two spellings of one file are one file: a symlinked directory resolves, and case folds where the file system ignores it, as macOS's and Windows' defaults do. The folding is ASCII only, so a non-ASCII letter's case, or Unicode normalization, still tells two spellings apart.
- **The Template input (with the user, 2026-11-18).** The write table is tested through the begin's report data, `anchoredPaths`, each anchored path mapped to the path as authored, which inspection can show too, rather than waiting for Write. A Template from another zone is anonymous, so its copy anchors nothing and takes that zone's entries. A linked Template that brings nothing stops the zone rather than following [Order and Results](#order-and-results)' rule that a task runs without such an input: an empty layer standing in for the Template's would reach a stage and Write as if it were whole, the case [Diagnostics](../phase3/node-tree.md#diagnostics) rules out for a chain. A Layer from File that the file check blocks keeps its cached layer, as a muted one does: it rereads only on request either way. The write table is keyed by string, as `UsdUtils.ModifyAssetPaths` maps paths, so an absolute path a Template authors as the very string a relative one anchors to is written relative too; both name one file. A path is anchored with `SdfComputeAssetPathRelativeToLayer`, so a bare path stays as authored when no file beside the Template has its name, as composition would read it, and an absolute path, an anonymous identifier, or a resolver's identifier stays as authored. A Layer from File's file comes from a Task hook that the file check calls before any task runs; its diagnostics are discarded, since the node's run reports the same ones. A generated member named for a C++ keyword takes a trailing underscore (`template_`).
- **Prim and Create Prim (2026-11-18).** The edit table is tested through the begin's report data, `primSpecs` and `layerFields`, each prim spec's path and each layer metadata field mapped to the node that wrote it, as the write table is through `anchoredPaths`: the Template's specs and fields are the begin's, marked as its copy of the Template, and an implicit `over` the node's that needed it, marked as one. The authoring context offers only what any authoring node uses (with the user): a prim spec's existence, specifier, and author, a prim spec, and a layer metadata field, which the end's Default Prim sets now and Configure Layer will. A message that needs more, such as Create Prim's naming the Template, reads it from the edit table's entry. A Create Prim on a spec the layer already holds is an error naming its author, except an implicit `over`, which it takes (with the user), so a chain may create a child before its parent; a Template's `over` and a Create Prim's own `over` are content someone authored, so they stay errors. Every ancestor that exists after the spec is created is recorded, even if creating it fails partway, so each spec has an entry. A chain node's value outputs come from its implementation's outputs hook, which gets `ValueInputs` and no stage, so it's pure because of its signature; loading checks that an authoring node has the hook exactly when its definition has value outputs. They're computed with the value nodes, only for nodes on a chain, since a node on no chain authors nothing for its Prim to name, and what it reports there, such as an invalid Name, is held, with its links, until its chain reaches it, where an error stops the chain: a node the chain stops before reports nothing, as it doesn't run. Its Prim is still given out, empty when the Name is invalid. A chain node or end whose link brings nothing doesn't run and stops the chain, as a Template does: its edit would be missing. A muted Create Prim's Prim has no pass-through, so a node using it warns that it's muted rather than editing the muted node's Parent. A specifier's menu is closed (`closedMenu`): USD takes no other value, so a token outside it is an error, as `upAxis`'s will be. A Prim path may be `/`, the parent of a root prim, and may not name a variant; the end rejects `/` as a Default Prim, which names a prim. An empty Prim Path is Prim's `missing-path` error. Default Prim may name any prim the layer has a spec for (with the user): USD 0.26 reads a deeper prim's path, which the note now allows, and a root prim is still authored by its name. An `over` or a `class` warns (`default-prim-not-def`) and is authored, since USD composes either. Create Prim warns for a Type that isn't a registered concrete schema, `unknown-prim-type` for an unregistered one and `non-concrete-prim-type` for an abstract or API schema, by [Nodes](../phase3/node-tree.md#nodes)' rule for known sets. A Viewer takes an Editable Layer through its Layer input (`takesEditableLayer`), and its copy is kept in the cache of the node it's linked after, so its stage lasts across cooks. Each cook runs only the active Viewer, which `cook` names (with the user): the editor shows one at a time, so other Viewers would only cost copies inside the zone's change block and stages nobody sees; the tree keeps them all, so switching Viewers isn't a tree edit. Other Viewers' stages and copies are dropped rather than kept for a fast switch back, since a fully loaded stage per Viewer is the memory a heavy scene can't spare. Each zone's task cooks inside one `SdfChangeBlock` (with the user), so Sdf processes its authoring, the active Viewer's copy, and its move into the zone's layer once; inside it the cook calls nothing downstream of Sdf, as the block requires, which `test_cook_change_blocks.py` checks by following the calls from every in-block entry point. So Create Prim checks its Type against the schema registry in its outputs hook, before any task, and a Viewer composes its stage in its own task, after the zone's block has closed, so a zone with a Viewer needs no second block. From step 9, a chain node's read of the zone's stage splits the zone's block at that node, and step 13's wave groups the transfers of several zones.
- **A minimal front end (with the user, 2026-11-19).** The temporary UI gets a node tree for testing the cook in Blender, so the cook ships in the zip from here on. Its node types are built from the definitions file when the extension registers, which `proscenium_cook` exports as `NODE_DEFINITIONS_PATH`, and the tree names its prims with the cook's own encoding, bound as `prim_name_from_node_id`, so the two sides never differ. A link the cook would reject is drawn red, as Blender draws an invalid link in its own editors, through the cook's own check, bound as `link_problem`, which moved beside the definitions; the link stays in the tree, and the cook reports it as `incompatible-link`. A begin names its end by the end node's name, which a rename doesn't follow. The active Viewer is the one the tree's Viewer dropdown names, by the node's name, which a rename doesn't follow either; a name no Viewer has any more is given to the cook, which warns `unknown-viewer`. Each tree's stage and `TreeCook` are kept between cooks, so the cook's state lasts as the plan's input describes; a cook prints its diagnostics, and which nodes have a stage, to the console, and shows the Viewer's stage in the scene graph and property viewer widgets below the Cook panel, the kept cook holding it; it hands no stage to a binding, which waits for Phase 2.
