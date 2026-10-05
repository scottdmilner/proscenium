# Project Overview

This project is a Blender extension for reliable, repeatable, **one-way synchronization of composed OpenUSD stages into a managed Blender display representation**.

It serves as:

- A snapshot synchronizer for supported USD content.
- The scene-display layer for a future USD-native stage editor.

**USD is authoritative.** Phases 1 and 2 do not author USD, export USD, or translate Blender edits back into USD.

## Documentation Map

Always read this file and [spec/invariants.md](spec/invariants.md). Read other files when the work touches their topic; each milestone file lists the spec files it implements.

| File | Contents |
|---|---|
| [spec/invariants.md](spec/invariants.md) | Cross-cutting guarantees every milestone must preserve |
| [spec/pipeline.md](spec/pipeline.md) | Layer boundaries (snapshot, plan, application), synchronization transaction, diagnostics |
| [spec/source-access.md](spec/source-access.md) | Bindings, source consistency and identity, copied bindings, in-memory sources, file-backed refresh |
| [spec/lifecycle.md](spec/lifecycle.md) | Ownership, lifecycle operations, detach, undo and runtime state, persistence |
| [spec/interaction.md](spec/interaction.md) | Source inspection, interaction contract, interaction testing |
| [spec/incremental.md](spec/incremental.md) | Phase 2 change discovery and affected content |
| [spec/support/](spec/support/) | Supported scene state: [transforms](spec/support/transforms.md), [geometry](spec/support/geometry.md), [instancing](spec/support/instancing.md), [materials](spec/support/materials.md), [visibility and unsupported content](spec/support/visibility.md) |
| [testing/strategy.md](testing/strategy.md) | Test layers and named contract fixtures |
| [testing/acceptance.md](testing/acceptance.md) | Acceptance criteria: bespoke fixtures, standard checks, bounds contract, ALab production-scale validation, performance |
| [milestones/](milestones/README.md) | Implementation milestones M1–M14 |
| [DECISIONS.md](DECISIONS.md) | Decision register: open decisions and chosen behavior |

This file, `spec/`, and `testing/` establish project requirements and architectural direction. The milestone files detail implementation and reference those requirements; where they conflict, the requirement files take precedence. [spec/invariants.md](spec/invariants.md) summarizes cross-cutting guarantees, and the spec section each invariant links to is authoritative for details. Milestones describe planned work, not implementation status. Inspect the repository before assuming a feature exists.

**How to read requirements.** Everything in this file, `spec/`, and `testing/` is a requirement unless it is labeled a **design note** (a suggested approach that the named milestone settles) or is plainly explanation, such as rationale or examples. "Must", "never", imperatives ("do not…"), and plain present-tense statements ("refresh does not reuse a cached stage") are equally binding. "Prefer" sets a default that holds unless a recorded decision overrides it, either in [DECISIONS.md](DECISIONS.md) or in a milestone's decision record. Terms are defined in the [Glossary](#glossary).

## Core Architecture

**The Blender display structure does not need to mirror the USD scene graph.**

Keep three concepts separate:

1. **USD scene graph:** authoritative source hierarchy and scene semantics.
2. **Source inspection and selection model:** entities users browse, inspect, select, and eventually edit.
3. **Blender display representation:** resources used to display the evaluated stage.

Requirements:

- The USD hierarchy must remain accessible through source inspection, within the browsing universe defined in [Source Inspection and Interaction](spec/interaction.md#source-inspection-and-interaction).
- Blender objects, collections, and parenting need not reproduce that hierarchy.
- One source prim may produce multiple display elements.
- Multiple source prims may share a display representation.
- Organizational prims need not have individual Blender objects.
- Supported descendants must receive the correct ancestor state, including beneath unsupported ancestors.
- Source hierarchy and selection identities are independent of display partitioning.

The central architectural rule:

> **Tools address USD entities through the source selection model. The display layer resolves those entities to Blender resources; tools do not infer USD structure from Blender parenting or object names.**

That preserves freedom to optimize the display later without redesigning the editor's hierarchy, selection, or authoring model.

Objects, collection instancing, Geometry Nodes, batching, or a hybrid are implementation options. Geometry Nodes is not mandatory, and one large graph is not a goal in itself. Prefer the simplest representation that satisfies correctness, interaction, and performance needs. Keep the performance tests around for later so that we can adapt to updates to Blender's performance.

## Delivery Phases

### Phase 1 — Correct Snapshot Synchronization

Synchronize supported content at an **explicit USD time code supplied as a function parameter**. The USD default time code is permitted.

- Manual refresh is required.
- Full traversal and rebuilding are acceptable.
- Blender object identities need not survive refresh.
- Geometry is deduplicated wherever sharing preserves correct display, under the [Geometry Sharing](spec/support/instancing.md#geometry-sharing) contract.
- Binding lifecycle, persistence, diagnostics, and failure safety are required.
- The acceptance suite must pass, as defined in [Acceptance Criteria](testing/acceptance.md): bespoke fixture cases and assertions covering every Phase 1 requirement, as assigned by the requirement-to-test matrix, plus a production-scale check on ALab (ALab v2.3.0, techvar assets v2.2.0, `entry.usda`) at any time code under every payload policy.

### Phase 2 — Incremental Synchronization

Preserve Phase 1 correctness while avoiding unnecessary work.

- Update affected representations and their dependencies.
- Leave unaffected representations untouched during ordinary incremental refresh, as defined in [Affected Content](spec/incremental.md#affected-content).
- Preserve source selections where their source identities remain valid.
- Maintain sharing and reclaim obsolete managed resources without breaking sharing or other owners.
- Establish and meet representative performance targets for synchronization and the required interaction operations.
- Support manual file-backed refresh and in-memory sources.

See [Incremental Synchronization](spec/incremental.md) for detailed requirements.

**Phase 2 must be complete before Phase 3 begins.**

### Phase 3 — USD Stage Editor

Tools author USD changes and use the synchronizer as their display layer. Actual USD authoring tools are outside Phases 1 and 2.

Automatic timeline synchronization is a stretch goal. The evaluation time code may change between any two synchronizations.

## Compatibility and Development

- Minimum Blender version: **5.2 LTS**.
- Use the OpenUSD version bundled with the supported Blender distribution.
- Support macOS, Windows, and Linux.
- Prefer Python-only implementation. Whether performance requires compiled components is decided from measurements, starting in M4, and recorded in [DECISIONS.md](DECISIONS.md).
- Do not require externally installed custom resolvers or schema plugins.
- If additional compiled components become necessary, all three platforms remain required.

Verify actual runtime capabilities rather than assuming Blender's embedded Python behaves like a normal `uv` environment. "Blender has USD support" and "the required USD Python API is available and can exchange stages with callers" are separate assumptions.

Planned tooling includes `uv`, `ruff`, `ty`, pre-commit hooks, extension packaging, and pytest-based tests. Keep development dependencies separate from distributable runtime dependencies; do not inadvertently bundle another OpenUSD build.

## Glossary

Each entry links to the section that defines the term in full.

| Term | Meaning |
|---|---|
| **Binding** | The association of one USD source with a managed destination collection, a target scene, and settings. See [Bindings and Source Access](spec/source-access.md#bindings-and-source-access). |
| **Managed / unmanaged content** | Managed content is Blender content that a binding's ownership records claim. Everything else, including detached content, is unmanaged. See [Ownership and Lifecycle](spec/lifecycle.md#ownership-and-lifecycle). |
| **Source entity** | A USD prim, plus its instance context where applicable, as addressed by the source selection model. |
| **Instance context** | The chain of native-instance roots through which a prim inside shared instance contents is reached. It distinguishes the separate uses of the same shared contents. |
| **Correspondence** | The two-way mapping between source entities and the display resources that represent them. See [Source Inspection and Interaction](spec/interaction.md#source-inspection-and-interaction). |
| **Source coverage** | The set of source entities a display resource represents. It may contain many entities. |
| **Representation role** | Why a display resource exists, such as shared geometry, a placeholder, or a material. Roles are defined in M5. |
| **Canonical** | The single authoritative instance among duplicates: of a representation (same source coverage and role) or of a copied binding. Noncanonical resources are still tracked but excluded from the active display and correspondence. |
| **Partition** | The unit of display replacement chosen in M4. A partition owns a set of display resources and is replaced as a whole. |
| **Evaluated source snapshot** | The resolved USD semantics for one synchronization, with no Blender references. See [Evaluated Source Snapshot](spec/pipeline.md#evaluated-source-snapshot). |
| **Display plan** | The description of how a snapshot will be represented in Blender. See [Display Plan](spec/pipeline.md#display-plan). |
| **Planning context** | The immutable plain values, such as the target scene's unit scale, that planning depends on besides the snapshot and binding settings. See [Display Plan](spec/pipeline.md#display-plan). |
| **Generation** | The complete display resources and metadata produced by one synchronization. The **published generation** is the one currently active. See [Binding State](spec/lifecycle.md#binding-state). |
| **Publication** | The step that makes a prepared generation the published one, switching all of its parts together. See [Synchronization Transaction](spec/pipeline.md#synchronization-transaction). |
| **Retirement** | Removing the previous generation's obsolete resources after publication. A retirement that fails leaves **pending cleanup**. |
| **Requested settings / last attempt** | The settings the user has asked for, and the record of the most recent synchronization attempt and its result. Both are kept separate from the published generation. See [Binding State](spec/lifecycle.md#binding-state). |
| **Payload policy** | Load-all or load-no-payload. |
| **Contributing layer** | Any layer that contributes opinions to the composed stage, whether through its layer stack or through composition arcs. |
| **Dirty layer** | A layer with unsaved in-process edits. |
| **Detach** | Releasing a whole binding's surviving managed content as-is into unmanaged Blender content, removing binding-specific metadata and controls. See [Detach As-Is](spec/lifecycle.md#detach-as-is). |
| **Materialize** | Turning display content that depends on managed shared resources or extension-specific mechanisms into standalone Blender data. |
| **Browsing universe** | The set of source entities that source inspection exposes, defined in M2. |
| **Bespoke fixture** | A small, code-generated USD test scene built to exercise specific requirements. See [Bespoke Fixtures](testing/acceptance.md#bespoke-fixtures). |
| **Production-scale fixture** | A real production scene, currently ALab, used to check integration and performance at scale. |
