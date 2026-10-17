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

- `synchronize(time_code)` synchronizes the binding at an explicit USD time code, which may be the default time code. The time code becomes the binding's requested time code, and the attempt uses the binding's requested settings.
- The other requested settings (payload policy, conversion, purpose) change only through `set_settings(...)`, which records them without synchronizing.
- `synchronize` returns an immutable result: its result state and deduplicated diagnostics ([Diagnostics](pipeline.md#diagnostics)). An expected failure, such as a source-access conflict or an unavailable source, is a result, not an exception.
- A handle whose binding no longer exists, for example after undo or binding removal, raises when used.
- Exceptions report misuse only, such as a call made during another synchronization.

Operations that span bindings are module functions: creating a binding, finding a scene's bindings, and attaching a stage under a source key ([Source Identity](#source-identity)).

Design note (suggested, settled by M3 and M5): the module, exact names, and the result's fields are settled with the implementation. The handle's methods delegate to functions keyed by binding identifier, which are what tests exercise.

## Source Consistency

- Synchronization is synchronous and non-reentrant.
- The caller must not mutate an attached stage or its contributing layers during a synchronization.
- Where a source change during evaluation can be detected, the attempt is discarded before publication.

## Source Identity

Source identity is persisted separately from source availability. An in-memory binding's source identity is its **source key**, a string the caller chooses when it creates the binding. The binding also stores the root-layer identifier of the stage last attached to it.

- A source key names one in-memory source within a `.blend`. Several bindings may share a key; attaching a stage under a key attaches it to every binding with that key.
- Reattachment requires an exact key match.
- The root-layer identifier is informative only: it is never used to find the bindings for a stage.
- Attaching a stage whose root-layer identifier differs from the stored one requires explicit confirmation from the caller. Without it, the attachment fails and the bindings are unchanged.
- Replacing the attached stage preserves stored source selections; they resolve against the next published generation.

The key is the reattachment contract because the root-layer identifier of an anonymous or unsaved source does not survive the session.

## Copied Bindings

Custom properties can be copied by duplication; do not assume they guarantee uniqueness. A binding can be copied by duplicating its destination collection or scene, appending managed content from another `.blend`, or copying a binding record together with its manifest.

- A binding whose identity is not unique is **disabled pending repair**: it keeps its display, does not refresh, and reports the ambiguity until the user makes it a new binding or detaches it.
- A deterministic, documented rule decides which candidate remains canonical. If the rule cannot decide, all candidates are disabled.
- Copies are never automatically claimed, merged, or deleted.

## In-Memory Sources

The **caller's stage** is the stage a caller attaches to an in-memory binding. The binding's **private stage** is a separate stage the binding opens over the same root and session layer objects. In USD, layers hold opinions and exist once per process, while each stage has its own settings stored in no layer: load set, population mask, muted layers, interpolation type, and edit target. The two stages therefore share every opinion, but not each other's settings.

Requirements:

- Do not author changes to a caller-supplied stage's layers or change its stage settings, including load state, population mask, layer muting, and edit target.
- Evaluate the caller's composed content as the caller's stage presents it, except that the binding's payload policy replaces the caller's load rules.
- Each in-memory binding evaluates a private stage over the caller's root and session layers, opened outside every USD stage cache with the caller's resolver context. Because the layers are shared, the caller's unsaved layer edits and session-layer opinions are seen live.
- At each synchronization, the private stage's population mask, muted layers, and interpolation type match the caller's stage. The caller's edit target does not affect composition and is not reproduced.
- Multiple bindings on the same in-memory source may use different payload policies without affecting each other or the caller.
- If the caller releases the attached stage, the binding becomes unattached. Replacing it follows the [Source Identity](#source-identity) rules.
- After a `.blend` is reopened, an in-memory binding reports its source as unavailable until the caller attaches a stage. Refreshing an unattached binding produces a diagnostic and preserves the saved display.

Design note (suggested, settled by M3): the binding keeps its private stage across synchronizations while the same caller stage stays attached, as a file-backed binding keeps its own. Persist the source kind, a caller-chosen source key, and the root-layer identifier.

## File-Backed Refresh

Requirements:

- A file-backed refresh displays the source as it exists on disk, composed with the opinions in the binding stage's anonymous layers: its session layer and the anonymous layers beneath it. Tools may author there through the live stage to show unsaved edits; synchronization never does.
- Refresh must not discard unsaved in-process edits made by other tools to layers it shares.
- **If any contributing layer has unsaved in-process edits, refresh fails** with a source-access conflict naming those layers and preserves the previous display.
- The contributing layers are the non-anonymous layers the binding's stage composes under its payload policy. A layer reached only through an unloaded payload does not contribute.
- Each file-backed binding keeps its own stage and reuses it across refreshes. The binding opens it outside every USD stage cache; refresh never takes a stage from a stage cache or otherwise shares stage state with other bindings or tools.
- Refresh reloads the clean contributing layers that changed on disk, never a dirty or anonymous one, so a refresh that reuses the binding's stage displays the same result as a stage newly opened from the same files with the same anonymous layers.
- Refresh may reload clean shared layers from disk. Other stages using those layers then see the current disk content. This is the only effect synchronization may have that other stages can observe.

The binding's stage is runtime state. The first synchronization opens it, including the first after a `.blend` is reopened, with an empty session layer: edits in anonymous layers are not saved in the `.blend`. USD shares opened layers across the whole process, so file-backed and in-memory bindings on the same files can see each other's layer state.

Design note (suggested, settled by M3): a non-forced layer reload compares modification times, which miss a rewrite within the same second on Windows ([feasibility record](../feasibility/runtime-record.md#dirty-layers-and-fresh-stages)). Refresh needs a change check that does not.
