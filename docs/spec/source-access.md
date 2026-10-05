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

## Source Consistency

- Synchronization is synchronous and non-reentrant.
- The caller must not mutate an attached stage or its contributing layers during a synchronization.
- Where a source change during evaluation can be detected, the attempt is discarded before publication.

## Source Identity

Source identity is persisted separately from source availability. M3 defines the in-memory source key contract:

- Its uniqueness scope.
- Whether reattachment requires an exact key match.
- Whether the root-layer identifier is authoritative or only informative. A root-layer identifier alone cannot be the reattachment contract for anonymous or unsaved sources.
- Whether replacing the attached stage preserves existing source selections.
- Whether attaching a different stage under an existing key requires explicit confirmation.

## Copied Bindings

Custom properties can be copied by duplication; do not assume they guarantee uniqueness. A binding can be copied by duplicating its destination collection or scene, appending managed content from another `.blend`, or copying a binding record together with its manifest.

- A binding whose identity is not unique is **disabled pending repair**: it keeps its display, does not refresh, and reports the ambiguity until the user makes it a new binding or detaches it.
- A deterministic, documented rule decides which candidate remains canonical. If the rule cannot decide, all candidates are disabled.
- Copies are never automatically claimed, merged, or deleted.

## In-Memory Sources

Requirements:

- Do not author changes to a caller-supplied stage's layers or change its stage settings, including load state, population mask, layer muting, and edit target.
- Evaluate the caller's composed content as the caller's stage presents it, except that the binding's payload policy replaces the caller's load rules. M3 settles how each piece of stage-level state is reproduced: muted layers, population mask, resolver context, interpolation settings, and session-layer opinions.
- Multiple bindings on the same in-memory source may use different payload policies without affecting each other or the caller.
- If the caller releases the attached stage, the binding becomes unattached. Replacing it follows the [Source Identity](#source-identity) rules.
- After a `.blend` is reopened, an in-memory binding reports its source as unavailable until the caller attaches a stage. Refreshing an unattached binding produces a diagnostic and preserves the saved display.

Design note (suggested, not settled): open a private stage per binding over the caller's root and session layers, using the binding's payload policy. Shared layers would make unsaved caller edits visible without reopening files. Persist the source kind, a caller-chosen source key, and the root-layer identifier.

## File-Backed Refresh

Requirements:

- A file-backed refresh displays the source as it exists on disk.
- Refresh must not discard unsaved in-process edits made by other tools to layers it shares.
- **If any contributing layer has unsaved in-process edits, refresh fails** with a source-access conflict naming those layers and preserves the previous display.
- Refresh does not reuse a cached stage or otherwise share stage state with other bindings.
- Refresh may reload clean shared layers from disk. Other stages using those layers then see the current disk content. This is the only effect synchronization may have that other stages can observe.

USD shares opened layers across the whole process, so file-backed and in-memory bindings on the same files can see each other's layer state.

Design note (suggested, not settled): open the stage at each refresh outside any stage-cache context, check contributing layers for unsaved edits before evaluation, and reload the clean ones. If M1 shows that a private disk view can be built reliably without touching shared layers, M3 may replace the conflict failure with that view. That change only turns failures into successes.
