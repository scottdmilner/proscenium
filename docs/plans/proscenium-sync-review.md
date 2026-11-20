# proscenium_sync: architecture and complexity review

Review date: 2026-11-17. Reviewed checkout: `42cf86b`.

This document records the review findings and its validation evidence. It proposes no contract changes.
[The companion solution plan](proscenium-sync-review-solutions.md) addresses every finding and simplification.

## Overall assessment

**Keep the core layering. Simplify the bookkeeping around it.** The separation between source evaluation, immutable planning, Blender application, and live-stage inspection is sound. Most avoidable complexity comes from maintaining overlapping representations of resources and updating them incrementally.

The review found reproducible correctness issues in those areas, along with several concrete deletion opportunities. No implementation files changed during the review.

Paths below are relative to `packages/proscenium_sync/src/proscenium_sync/`.

## Correctness findings

### 1. [P1] Invalidate cached manifests when Blender remaps pointers

**Locations:** `runtime/kept_manifests.py:50–53,124–127`; `bindings/shown_displays.py:86–92,124–133`

The manifest cache validates its revision and whether referenced datablocks remain alive. Neither check detects `old.user_remap(replacement)`: Blender rewrites the persistent manifest's pointer, but the original datablock remains alive and the record revision stays unchanged.

Reproduced through synchronization:

1. Synchronize a binding.
2. Copy a managed object and remap the original's users to the replacement.
3. Change its USD transform and synchronize again.

The cached manifest still identified the original. Refresh deleted that now-unclaimed object and left the replacement linked but unclaimed, alongside the refreshed representation.

**Recommendation:** Validate cached pointers against their stored pointers, and invalidate derived partitions and shown-display mappings on disagreement. This is different from the documented trade-off for scripts directly editing record properties, because Blender performs the pointer rewrite.

### 2. [P1] Account for earlier samples within the same cache call

**Locations:** `synchronization/time_code_keying.py:86–94,150–166,335–348,403–443`

Caching creates resources lazily while walking time codes. A newly created resource is initialized for `shown_before`, but that contains only the generation's original time and previously completed calls, not earlier samples processed by the current call.

Using `F-TIME-VARIATIONS`:

```python
handle.synchronize(20)
handle.cache([0, 5, 10, 15])
```

At frames 0 and 5, the display incorrectly showed:

- two point-instance copies that should exist only later;
- Flicker's box rather than its marker.

Caching the same times in separate calls did not show the extra instances.

**Recommendation:** Determine the required resource forms across the call before writing keys, then initialize each over the complete sample set. At minimum, track already-processed samples within the call.

Architecturally, this is the strongest reason to separate **discovering required resources** from **creating and keying them**.

### 3. [P1] Register record rollback before performing the write

**Locations:** `synchronization/publication.py:84–95`; `runtime/kept_manifests.py:93–96`

Publication registers its manifest rollback only after `write_manifest_entries()` returns. That function performs a persistent write and then updates the derived partition cache. If the latter fails, the persistent manifest has changed, but publication has no registered restoration for it.

A failure injected in `PublishedPartitions.replace_entries()`, after the persistent write, made synchronization return `publication-failed`, but the stored manifest differed from its pre-attempt value.

The cache path already follows the safer pattern by registering restoration before writing.

**Recommendation:** Use write-ahead rollback registration consistently. Keep derived-cache updates disposable, so their failure cannot strand persistent state.

### 4. [P2] Track node groups at allocation, not after construction

**Locations:** `synchronization/time_code_keying.py:350–360`; `synchronization/attribute_samples.py:31–69`

`new_frames_group()` allocates a Blender node group and performs its construction before the caller tracks it. An exception during construction therefore leaves a resource that preparation cannot dispose of or record as pending cleanup.

A failure-injection probe left an untracked `Proscenium frames` node group after a failed cache call.

**Recommendation:** Separate allocation from population, tracking the group immediately after allocation. That matches the object and mesh creation paths and removes this exception to the resource-lifetime rule.

### 5. [P2] Honor fake users when classifying removable resources

**Location:** `synchronization/datablock_removal.py:54–64,107–119`

Removal classifies dependencies using `bpy.data.user_map()`, which does not represent a fake user as another datablock. The implementation therefore does not honor its documented promise to release fake-user-protected resources intact.

Setting `use_fake_user = True` on a published bounds mesh and requesting a full rebuild made refresh complete successfully and delete the old mesh.

**Recommendation:** Treat fake-user protection explicitly as a release condition in the shared removal classifier.

### 6. [P2] Materialize named layers once before validation and reload

**Location:** `source_access/stages.py:221–227`

`reload()` accepts an `Iterable[str]`, but consumes it first through `set(layers)` and then iterates it again to perform the reload. A generator is exhausted by validation.

Reproduced results:

| Input | Dirty layer reloaded? |
|---|---|
| Generator containing its identifier | No |
| List containing the same identifier | Yes |

**Recommendation:** Materialize the identifiers once and use that collection for both steps.

### 7. [P2] Finalize native diagnostics using canonical source identities and ordering

Two related diagnostic-pipeline issues were reproduced:

- **Duplicate subjects:** `planner/plan.cpp:194–197` canonicalizes native-instance diagnostic subjects but not equivalent point-prototype propagations. One curve used by two point instancers produced three untranslated-type diagnostics instead of one aggregated source-prim diagnostic.
- **Incorrect first-ten selection:** `planner/plan.cpp:223–235` and `planner/diagnostics.cpp:68–85` truncate source-mapped capture diagnostics in Hydra traversal order. With fourteen separately instanced curves, the retained warnings omitted earlier source paths while retaining later ones.

**Recommendation:** Map to canonical USD subjects, order by source path, and aggregate/truncate in one finalization step. This reduces special cases as well as correcting the output.

## Highest-value complexity reductions

These are simplification recommendations, separate from the defects above.

### A. Delete representations with no production reader

#### Unused native partition table

`planner/plan.h:76–79,102`; `planner/plan.cpp:388–400`

Every drawn copy stores `Partition.resourceIndices`, but no production consumer reads `Plan.partitions`. Application reconstructs the same membership from the three copy-resource buffers in `synchronization/application.py:114–120`.

Keep those buffers authoritative and remove the unused partition representation, bindings, and stubs.

#### Unused ownership-query implementation

`runtime/ownership.py:32–104`

Repository searches found no production consumers of `Claim`, `OwnershipStatus`, `Ownership`, `of()`, `manifest()`, or `set_manifest()`. Production mutation safety instead uses the Blender user graph through partition replacement and datablock removal.

Keep `set_manifest_entries()`, which caching uses. Move useful explanatory queries to test support rather than maintaining a parallel production ownership model.

#### Unused carriers and helpers

Additional small deletion candidates:

- `persistence/binding_records.py:72–85`: creation returns destination/config/index information whose production consumer reads only the binding ID; index-write return information is discarded.
- Same file, `113–115,152–154`: unused `has_config()` and `destination_collection_uids()`.
- `runtime/copy_detection.py:83`: unread `IdentityCandidates.index_entries`.
- `persistence/manifests.py:278–284`: `dependents()` is used only by its own test.

These are better initial changes than reorganizing package boundaries.

### B. Record affected paths, not notice history

**Locations:** `planner/scene_index_notices.cpp:9–28,38–53`; corresponding header fields.

The notice recorder retains individual events and copies dirty locator sets. Its sole consumer immediately discards ordering, duplicates, and locator information, reducing everything to exact paths and subtree roots.

This creates event-history-sized storage where capture needs affected-path-sized storage.

**Recommendation:** Accumulate the two required sets directly under the existing mutex and move them out on capture. This removes both unnecessary retained data and the later reduction pass.

### C. Compute instancer-wide transforms once

**Location:** `planner/instancing.cpp:269–274`

Each prototype expansion scans all prototype-index arrays and constructs transforms for all points. Because resolution is cached by prototype root, an instancer with multiple used prototypes repeats this instancer-wide work for each prototype.

**Recommendation:** Cache point count and transforms per instancer within the resolver's lifetime. Prototype expansion should select its indices from that result. No persistent invalidation machinery is necessary.

This is an algorithmic duplication finding; the review measured no wall-clock improvement.

### D. Resolve state once within each operation

**Locations:** `bindings/binding_status.py:41–56`; `bindings/scene_source_selection.py:88–96`; `persistence/binding_records.py:157–165`; `runtime/pending_cleanup.py:67–72,85–92`

Several paths resolve or decode information that their caller just obtained:

- Status enumeration finds bindings, then calls query methods that look each binding up again. With two bindings, one status request made four additional individual binding lookups.
- Index discovery recursively converts index records merely to detect their presence, after which callers decode them again.
- Ledger update preflight loads the ledger, then the update immediately loads it again.

**Recommendation:** Pass already-resolved values down the current call stack. Have preflight return the validated state its caller needs.

This does not require another cross-operation cache and does not weaken the requirement to read current records on each API call.

### E. Reduce the number of coordinated resource maps

**Locations:** `synchronization/preparation_resources.py:45–56`; `synchronization/time_code_keying.py:100–121,224–238`

Prepared resources are represented across separate datablock, role, and manifest-entry dictionaries. Caching adds identity-to-key mappings and manifest changes layered over the published manifest.

Partial construction explains some of this separation, but callers repeatedly implement the same questions:

- Does this resource exist already?
- Was it created in this call?
- Which entry describes it now?
- Which dependencies should that entry contain?

**Recommendation:** Consider one operation-local resource overlay with explicit incomplete/complete entries, rather than synchronizing several parallel maps. Keep it narrow. A generalized transaction framework or another persistent registry would add complexity rather than remove it.

## Data-flow assessment

The intended flow is coherent:

```text
Caller-owned source stage
    → binding-owned evaluation stage
    → retained Hydra chain
    → frozen snapshot
    → plain prim records
    → immutable plan
    → preparation and local updates
    → publication
    → retirement / pending cleanup
```

Interaction correctly takes a different route:

```text
Published manifest + current Blender participation
    → display elements
    → correspondence
    → live-stage inspection and selection
```

The difficult part is the transition between the plan and published Blender state. Resource identities, partition membership, dependency relationships, and current entry values are reconstructed or overlaid in several places. Simplification should concentrate there.

Preserve these distinctions:

- source stage versus evaluation stage;
- snapshot versus plan versus application;
- requested settings versus published generation versus last attempt;
- manifest ownership versus pending cleanup;
- source selection identity versus display representation.

Those are meaningful boundaries, not accidental duplication. Likewise, the measured manifest and correspondence caches should be repaired, not removed indiscriminately.

## Suggested order of work

1. Correct remapping invalidation and grouped-cache initialization.
2. Standardize write-ahead rollback and allocation-time resource tracking.
3. Delete unused partition, ownership-query, and carrier code.
4. Remove repeated notice storage, decoding, and instancer-wide calculations.
5. Simplify the resource overlay only after those smaller changes clarify what remains.

## Validation

Focused suites passed during the review:

| Area | Result |
|---|---:|
| Synchronization, caching, incremental updates, selection | 63 passed |
| API and source access | 157 passed |
| Native planner | 142 passed |
| Persistence, runtime, results, ownership and cleanup | 230 passed |

Additional temporary-process probes reproduced the findings described above. One initial test invocation referenced a nonexistent test file and collected no tests; the corrected invocation passed.

The full suite, ALab qualification, and Blender-binary validation were not run. Git status remained clean at the end of the review.
