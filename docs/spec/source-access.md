# Source Access

Bindings and how they acquire USD sources. Cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Bindings and Source Access

A synchronization binding associates a source with a dedicated managed destination collection and settings. Each binding stores an explicit target scene and its own units and up-axis conversion settings. Together with the target scene's unit scale, these drive coordinate conversion.

Support:

- Root-layer files: `.usd`, `.usda`, `.usdc`.
- Caller-supplied in-memory stages without requiring file reopening.
- Load-all or load-no-payload policy.
- Explicit evaluation time code, including the USD default time code.
- Coordinate-conversion and purpose/display settings.
- Multiple independent bindings, including bindings using the same source.

The default scope is the entire available stage. Subtree selection and individual payload selection are not required.

Consume existing composition and variant selections. Do not author composition arcs or variant selections.

Binding configuration must not cross-contaminate other bindings. Opening or synchronizing must not save or modify source USD files.

## Synchronization API

Callers reach a binding through a **binding handle**: an immutable value that holds only the binding's persistent identifier, never a Blender datablock or cached binding state. Each method looks the binding up when it is called, and two handles are equal when their identifiers are.

- `synchronize(time_code)` synchronizes the binding at an explicit USD time code, which may be the default time code. The time code is the attempt's, not a setting of the binding: the caller derives it at each synchronization, and the attempt uses the binding's requested settings.
- The requested settings (payload policy, conversion, purpose) change only through `set_settings(...)`, which records them without synchronizing.
- `reload(layers=None)` rereads the binding's source layers from disk on request ([Layer State and Reloading](#layer-state-and-reloading)) without synchronizing; the next synchronization displays them.
- `synchronize` returns an immutable result: its result state and deduplicated diagnostics ([Diagnostics](pipeline.md#diagnostics)). An expected failure, such as an unavailable source, is a result, not an exception.
- A handle whose binding no longer exists, for example after undo or binding removal, raises when used.
- Exceptions report misuse only, such as a call made during another synchronization.

Operations that span bindings belong to the process's synchronization, not to a handle: creating a binding, finding a scene's bindings, reporting copied bindings ([Copied Bindings](#copied-bindings)), and attaching a stage under a source key or releasing it ([Source Identity](#source-identity), [Source Stages](#source-stages)).

Design note (settled by M3; M5 settles the result's fields): the API is `proscenium.api.synchronization`. The process's synchronization is `SYNCHRONIZATION`, a `Synchronization` whose methods keyed by binding identifier the handle's methods delegate to, and which tests exercise on a fresh instance.

## Source Consistency

- Synchronization is synchronous and non-reentrant.
- The caller must not mutate an attached stage or its contributing layers during a synchronization.
- Where a source change during evaluation can be detected, the attempt is discarded before publication.

## Source Identity

Source identity is persisted separately from source availability. A binding's source is a **file source**, named by the path of its root-layer file, or an **attached source**, named by a **source key**: a string the caller chooses when it creates the binding, under which it attaches the source stage ([Source Stages](#source-stages)). A binding with an attached source also stores the root-layer identifier of the stage last attached to it.

- A source key names one attached source within a `.blend`. Several bindings may share a key; attaching a stage under a key attaches it to every binding with that key.
- Reattachment requires an exact key match.
- The root-layer identifier is informative only: it is never used to find the bindings for a stage.
- Attaching a stage whose root-layer identifier differs from the stored one requires explicit confirmation from the caller. Without it, the attachment fails and the bindings are unchanged.
- Replacing the attached stage preserves stored source selections; they resolve against the next published generation.

The key is the reattachment contract because the root-layer identifier of an anonymous or unsaved source does not survive the session.

## Copied Bindings

Custom properties can be copied by duplication; do not assume they guarantee uniqueness. A binding can be copied by duplicating its destination collection or scene, appending managed content from another `.blend`, or copying a binding record together with its manifest. The bindings in a `.blend` that share one binding identity are its **candidates**: each scene's binding record for it, and each destination collection tagged with it that no binding record names, as a collection duplicated on its own is. A binding's identity is not unique when it has two or more candidates, or two or more binding indexes name it.

- A binding whose identity is not unique is **disabled pending repair**: it keeps its display, does not refresh, and reports the ambiguity until the user makes it a new binding or detaches it.
- A deterministic, documented rule decides which candidate remains canonical. If the rule cannot decide, all candidates are disabled.
- Copies are never automatically claimed, merged, or deleted.
- A binding's handle reaches its canonical candidate. A scene lists the bindings whose canonical candidate is on it and, for a binding with none, those with a candidate on it. Every candidate of an identity that isn't unique is reported, with which one is canonical, or that none is.
- A binding with no canonical candidate refuses synchronization, reloading, and settings changes with a fatal diagnostic naming its candidates, before accessing its source.
- Whether a candidate is disabled is derived from the records whenever they are read, never stored, so it survives save/reopen and no copy carries it. Detection writes nothing.
- Detection runs when a `.blend` is loaded, after undo and redo, when scenes are added or removed, and before each synchronization.

### Canonical Candidate

Each `.blend` holds a **binding index**, with one entry per binding identity naming that binding's destination. The index is held outside every binding's own datablocks, and nothing in a binding refers to it, so copying a binding's datablocks does not copy the index.

- Creating a binding adds its index entry. Removing a binding removes its entry.
- A candidate is canonical when the index names its destination and its binding record and destination refer to each other.
- If the index has no entry for the identity, or its entry names no destination, then the one candidate whose binding record and destination refer to each other is canonical.
- Otherwise the rule cannot decide, and all candidates are disabled. This includes:
  - more than one index naming the identity;
  - a binding index that can't be read, for an identity with two or more candidates;
  - an index naming a destination whose binding record does not refer back;
  - with no usable index entry, two or more candidates whose binding record and destination refer to each other, or none.
- A write to the canonical candidate's binding records restores its missing index entry, when its record and destination refer to each other. An entry naming no destination is kept.
- A binding linked from another `.blend` is not a candidate. It is library data, read-only in the linking file, and its identity belongs to its library, so it never makes a local binding's identity non-unique.

## Source Stages

Every binding has a **source stage**: the stage its source is composed on. A binding with a file source opens its source stage itself; for an attached source, the caller supplies it. The source stage is also the binding's live stage ([Two Layers and the Live Stage](interaction-contract.md#two-layers-and-the-live-stage)). In USD, layers hold opinions and exist once per process, while each stage has its own settings stored in no layer: load set, population mask, muted layers, interpolation type, and edit target.

Requirements:

- A binding with a file source opens its source stage outside every USD stage cache, at its first synchronization, including the first after a `.blend` is reopened, and keeps and reuses it across synchronizations. It never takes the stage from a stage cache, places it in one, or shares it with other bindings or tools.
- The binding holds the attached stage until the caller releases it with `release(key)`, which releases it from every binding with that key, or attaches another stage under the key; loading a `.blend` releases it too. The caller dropping its own references doesn't release it: until then the stage stays alive with its layers and their unsaved edits, which a stage opened on the same files sees. A released binding is unattached. A binding that no longer exists, as after undo of its creation, keeps its attachment until then, so redo brings it back attached, and `release(key)` still releases it; its other runtime stages are dropped. Replacing the stage follows the [Source Identity](#source-identity) rules.
- After a `.blend` is reopened, a binding with an attached source reports its source as unavailable until the caller attaches a stage. Refreshing an unattached binding produces a diagnostic and preserves the saved display.
- Do not author changes to an attached stage's layers or change its stage settings, including load state, population mask, layer muting, and edit target. A reload the caller requests is the one change to its layers ([Layer State and Reloading](#layer-state-and-reloading)).
- Evaluate the source stage's composed content as the source stage presents it, including the opinions in its session layer and the anonymous layers beneath it, except that the binding's payload policy replaces the source stage's load rules.
- Each binding evaluates an **evaluation stage**, which composes the source stage's root and session layers and is opened outside every USD stage cache with the source stage's resolver context. Because the layers are shared, the source stage's unsaved layer edits and session-layer opinions are seen live.
- At each synchronization, the evaluation stage's population mask, muted layers, and interpolation type match the source stage's. The source stage's edit target does not affect composition and is not reproduced.
- Multiple bindings on the same source may use different payload policies without affecting each other or the source stage.

Tools may author in the source stage's session layer and the anonymous layers beneath it, through the live stage, to show unsaved edits; synchronization never does. A source stage the binding opened, and the attachment of a caller's stage, are runtime state: neither is saved in the `.blend`, and the opened stage starts with an empty session layer. USD shares opened layers across the whole process, so bindings on the same files can see each other's layer state.

Design note (settled by M3): when the binding opened its source stage itself, there are no caller's settings to protect, so its evaluation stage is the source stage, under the binding's payload policy. For an attached source, the binding keeps its evaluation stage across synchronizations while the attached stage's root and session layers stay the same, and opens a new one otherwise.

Design note (suggested, settled by M3): persist the kind of source, its path or source key, and the root-layer identifier.

## Layer State and Reloading

A binding evaluates its source's layers as they are loaded in the process. USD loads each layer once per process and shares it with every stage that composes it, so a binding sees the same layer state as every other tool using those layers.

Requirements:

- A binding displays its source's layers as they are loaded, including unsaved in-process edits in dirty layers and the content a layer had when it was read, even if its file has changed since. Synchronization never reloads a layer.
- When a synchronization displays dirty layers, it reports an informational source-state diagnostic naming them.
- Layers are reloaded only on request, through the binding's `reload` ([Synchronization API](#synchronization-api)). It rereads the contributing layers whose files changed since they were read, and every dirty one, which discards its unsaved edits. Saving edits first is the caller's responsibility.
- The contributing layers are the non-anonymous layers the binding's evaluation stage composes under its payload policy. A layer reached only through an unloaded payload does not contribute, and anonymous layers are never reloaded.
- `reload(layers)` rereads only the named layers, each of which must be a contributing layer of the binding. Naming any other layer is misuse: the call raises and reloads nothing.
- Every stage that composes a reloaded layer sees its new content, including an attached stage. This is the only effect source access may have that other stages can observe, apart from holding an attached stage until the caller releases it ([Source Stages](#source-stages)).
- After a reload, a binding's reused evaluation stage displays the same result as a stage newly opened from the same files with the same anonymous layers.

Design note (settled by M3): reload uses USD's non-forced layer reload, which rereads a clean layer only when its file's modification time differs from the one USD stored when it read the layer, and always rereads a dirty one. USD stores whole seconds on Windows, so there a rewrite within the same second as the last read isn't reloaded. That is expected and matches USD's own behavior ([feasibility record](../feasibility/runtime-record.md#dirty-layers-and-fresh-stages)). A forced reload would notify every stage using each layer even when its file is unchanged.

Design note (suggested, settled by M5): the source-state diagnostic may also name layers whose files changed on disk since they were read, if that can be detected cheaply.
