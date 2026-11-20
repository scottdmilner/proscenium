# proscenium_sync: point-by-point solution plan

Proposal date: 2026-11-17. Source checkout: `42cf86b`.

This is the companion to the [architecture and complexity review](proscenium-sync-review.md).
It proposes implementation work, not contract changes. No product code is changed by these documents.
Paths below are relative to `packages/proscenium_sync/src/proscenium_sync/`.

## Performance promise and limits of the evidence

**Equal or better performance is an acceptance condition for these proposals, not an improvement already demonstrated.**
Keep the existing fast paths, measure each implemented change, and reject designs that miss that condition.
Correct output, ownership safety, and failure recovery are not negotiable performance optimizations.

Most changes remove work or move existing work without adding a new traversal.
Finding 1 is the exception: its straightforward correctness fix costs more in the probes below.
The proposed shared validation design needs implementation-level measurements before it can satisfy the requested performance condition.
There is not yet a verified equal-or-faster solution for that point, especially for interaction.

Use these terms throughout:

- **Unchanged path:** an operation on valid, unchanged state, including repeated refresh, selection, and already-cached times.
- **Changed path:** an operation that must change the display, including first use and full rebuild.
- **Failure path:** restoration and tracking after an injected failure. More work here can be necessary for correctness, but it must not add whole-scene snapshots to successful incremental operations.
- **Qualification:** correctness checks plus fresh-process and warm-operation measurements on the actual public entry points.

### Coverage

| Review point | Proposed change | Expected performance effect |
|---|---|---|
| 1 | Shared authoritative pointer validation and coordinated cache invalidation | Not yet qualified; standalone scans regress |
| 2 | Discover varying resource timelines before keying | Avoid repeat initialization and order-dependent backfill |
| 3 | Register restoration before writes; discard failed derived caches | Constant-size registration; keep incremental cache updates |
| 4 | Allocate, track, then populate node groups | Same allocations and node construction |
| 5 | Seed fake-user release in the existing classifier | One scalar check per candidate; no extra user-graph query |
| 6 | Materialize layer identifiers once | Same set storage; one traversal of the caller's iterable |
| 7 | Canonical diagnostic subjects and bounded ordered finalization | Resolve once per record; no global diagnostic sort |
| A | Delete unused representations, carriers, and helpers | Fewer allocations; less retained plan memory |
| B | Collect unique affected paths at notice reception | Storage follows unique paths, not event count |
| C | Reuse one instancer-wide transform computation per plan | Remove repeated point-array work across prototypes |
| D | Pass resolved state through the current operation | Fewer lookups and record decodes; no new persistent cache |
| E | Consolidate allocation records and explicit resource overlays | Fewer synchronized maps and reverse linear searches |

## Correctness findings

### 1. Pointer remapping: one validated manifest snapshot per operation

**Change:** repair `runtime/kept_manifests.py` and `bindings/shown_displays.py` together.

1. Retain decoded immutable metadata, revision checks, and incremental `PublishedPartitions` updates.
2. Validate each cached datablock against the authoritative pointer stored under its manifest entry key. Check missing, null, invalid, and remapped pointers, not just whether the old datablock is alive.
3. On disagreement, discard the cached manifest, its partitions, and any display/correspondence derived from that pointer snapshot. Decode current state before returning ownership or display data.
4. Give the validated snapshot an operation-local identity. Pass it through refresh, partition selection, and display construction so those consumers do not repeat validation during the same uninterrupted operation.
5. A shown-display cache hit must validate its relevant stored object pointers too. Generation and held-plan identity are insufficient. Fuse pointer checks with the existing object-participation check where practical, rebuilding correspondence only on a change.
6. Revalidate after callbacks that can change Blender state. Clear all related caches on load, undo, and redo as today.

Keep raw `IDPropertyGroup` handles local to an operation. Runtime indexes may retain checked datablock references, not groups or nested data inside datablocks.
Do not depend on an assumed Blender notification for `user_remap()`: the review establishes no reliable hook covering immediate calls before a dependency-graph update.

**Performance design:** replace liveness work with pointer agreement where that covers the same safety condition, rather than adding two independent full scans.
Share validation down the current call stack and combine display pointer/participation checks in one traversal.
Do not decode the whole manifest or rebuild partitions on a valid cache hit.
Implement D's redundant-lookup removal in the affected call paths, then measure the combined public operation.
Those savings are a hypothesis, not evidence that they offset pointer access.

**Measured warning:** temporary Blender-wheel probes on this host used manifests containing newly allocated objects, not ALab.
Each size had 21 alternating/rotating-order timings; maxima include first invocations.
The keyed comparison read each raw `datablock` and compared it with the cached entry.

| Entries | Existing liveness median / max, ms | Keyed pointer check median / max, ms |
|---|---:|---:|
| 100 | 0.015 / 0.032 | 0.012 / 0.018 |
| 13,358 | 1.849 / 2.005 | 2.793 / 4.184 |
| 30,006 | 4.473 / 6.299 | 7.806 / 9.012 |

A separate probe used `map(itemgetter("datablock"), group.values())` and tuple comparison to reduce Python-loop overhead:

| Entries | Liveness median / max, ms | Ordered pointer column median / max, ms |
|---|---:|---:|
| 100 | 0.015 / 0.019 | 0.007 / 0.011 |
| 13,358 | 1.752 / 2.992 | 1.381 / 2.786 |
| 30,006 | 4.385 / 5.670 | 5.063 / 6.766 |

At 30,006 entries, that probe's first liveness and ordered-column invocations took 5.110 and 6.766 ms respectively.
Building the expected tuple during validation did not establish a large-scene win either.
The ordered-column experiment also needs a proven entry-order association before it could replace keyed validation; it is not a finished correctness fix.
In the same all-object probe, adding keyed pointer validation to the hide-flag check raised median time from 4.687 to 11.064 ms.
This establishes a real interaction cost risk, not actual selection latency.

**Qualification:** reproduce the review's synchronize → copy → `user_remap()` → source edit → refresh sequence.
Assert the unclaimed original is untouched, stored claims identify the actual current resources, and there is one canonical display.
When refresh reuses the object, it must update the remapped replacement, not the original.
Also remap an object and query selection immediately with warmed display caches, before refresh or dependency-graph handlers.
Cover non-object resources, deletion, null pointers, undo/redo, and save/reopen.
Check warmed correspondence against uncached persistent reads, not against another cache.

Benchmark no-remap and remap paths separately, including first calls after publication and undo.
Require no regression in public refresh and interaction at the largest input, not merely a faster pointer microbenchmark.
**This proposal remains performance-blocked until that gate passes.** A slower standalone scan is not presented as satisfying the user's condition.

### 2. Grouped caching: discover timelines, then allocate and key

**Change:** in `synchronization/time_code_keying.py`, separate discovery of required resources from mutation using the plans the call already evaluates.

1. Retain the existing plan comparison that finds varying copies. Include copies with existing cached animation.
2. For each varying copy, derive new-time states from the available plans and preserve existing-time states from published resources and managed animation. Build a compact timeline describing presence, form, transform/shear, bounds, and visibility. Previously cached times do not require retained per-time plans or source reevaluation.
3. Determine required actions, alternative box/marker forms, shear parents, and sampling modifiers before writing their keys. Allocate each required resource once and track it immediately.
4. Initialize newly introduced channels for every earlier applicable sample, including samples in the current call. Use hidden values for absent copies/forms, identity for a not-yet-needed shear parent, and `BASE` for unchanged bounds before sampling starts.
5. Key the current state once per required channel/time. Preserve existing valid keys and rollback values. Do not let an initialization key overwrite a state key for the same channel/time.

Keep timelines operation-local and limited to varying copies.
Represent unchanged spans compactly where they do not require distinct authored keys; verify constant interpolation and extrapolation at cached and uncached frames.
New channels that did not exist at previously cached times receive their known default there; existing channels retain their authored values.
Do not build a resource-by-all-scene-times Cartesian product.
The additional discovery pass reads already available plans, never recaptures USD.

**Performance:** correctness requires some keys the broken grouped path omits, so equal key count to that incorrect output is not a valid goal.
Pay for those keys by avoiding repeated lazy initialization, repeated reverse lookups, and duplicate writes.
Use the current correct sequence of separate calls as an additional output/performance reference, but also measure the current grouped path so any latency increase is visible.
Require unchanged and already-cached calls to retain their no-write behavior.

**Qualification:** start with `F-TIME-VARIATIONS`, `synchronize(20)`, then `cache([0, 5, 10, 15])`.
At every cached frame, check authored fixture expectations for instance presence and Flicker's form, not only agreement with another implementation.
Compare grouped, separate, reversed, overlapping, and repeated requests.
Exercise a first late shear parent, a first late bounds modifier, and a resource that appears, disappears, and reappears.
Inject failures after allocation, first initialization, and partial key insertion; no times from the failed call may remain cached.
Measure first grouped calls, steady calls, keys inserted, F-curves, allocations, and peak memory with many varying and many invariant copies.

### 3. Publication: register undo before mutation

**Change:** keep the existing transaction structure in `synchronization/publication.py`.

1. Register restoration of the previous manifest before calling its writer.
2. Register restoration of the previous published-generation record before calling that writer.
3. Capture previous validated values, not a new recursive raw-record snapshot on every successful call.
4. In `runtime/kept_manifests.py`, treat derived-cache maintenance as disposable. If `replace_entries()` or cache installation raises, invalidate that destination's cache and propagate the failure so publication rolls back.
5. After restoration, invalidate dependent display/partition caches. A restored record must not reuse a partially updated cache object.

Restoration must handle an absent previous record as well as an existing one.
Retain reverse rollback ordering and the separate preparation-disposal path.
Do not introduce a generic transaction framework.

**Performance:** move existing rollback registrations earlier; do not add full partition-cache cloning or successful-path whole-record serialization.
Keep `replace_entries()` proportional to changed/removed entries and their affected partitions.
A full restoration write on failure is acceptable; a full rebuild of the derived cache on every successful write is not.

**Qualification:** warm partitions, inject the review's post-write `replace_entries()` failure, and compare uncached persistent records before/after.
Also fail after generation persistence, after partial cache maintenance, and during restoration/disposal.
Check last-attempt reporting and persistent pending cleanup independently of the unchanged published generation.
Measure successful one-partition updates and full rebuilds, with large manifests, before and after the registration change.

### 4. Node groups: allocate, track, populate

**Change:** split `attribute_samples.new_frames_group()` into allocation at the caller and a helper that populates an existing node group.

`_ensure_frames_group()` should allocate the group, immediately call `work.track()`, and only then create sockets, nodes, and links.
Keep the population helper in `synchronization/attribute_samples.py`.
Preserve the exact node interface, socket identifiers, and graph.
Do not add a callback/dependency from the helper to higher-level transaction code.

**Performance:** same Blender allocations, nodes, links, and validation.
Tracking moves earlier; no additional datablock or dependency-graph evaluation is needed.

**Qualification:** fail after allocation and at socket creation, node creation, linking, and socket-identifier validation.
Assert every created group is either removed or persistently tracked as inactive pending cleanup.
Compare successful node graphs and cached playback; count allocations and time the first cache call requiring the group.

### 5. Fake users: feed explicit protection into the existing release graph

**Change:** in `synchronization/datablock_removal.py`, include `use_fake_user` in the initial protected/released candidates.
Propagate protection to their dependencies using the classifier's existing release rules.
Remove released entries from this binding's ownership as appropriate, without deleting or modifying their protected datablocks.

Apply this shared classifier to retirement, disposal, and cleanup retry as today.
Do not add separate removal implementations per lifecycle operation.

**Performance:** perform one cheap property read during the existing candidate classification.
Retain one user-graph acquisition, dependency-level batch removal, and failure-only bisection.
Fake-user scenes intentionally retain more resources than the buggy implementation; that is required output, not a leak or a removable memory regression.

**Qualification:** reproduce fake-user protection on a bounds mesh during full rebuild.
Also protect an object and a node group with dependencies, use an external owner, and retry failed cleanup.
Clearing protection on a still-managed candidate permits normal retirement; clearing it after release must not let later cleanup claim or delete that now-unmanaged resource.
Assert released resources and dependencies remain intact and unclaimed.
Benchmark unprotected large retirements to detect classifier overhead, and mixed protected/unprotected graphs to verify no repeated `user_map()` calls.

### 6. Reload: consume the caller's iterable once

**Change:** in `source_access/stages.py`, bind `requested_identifiers = set(layers)` once.
Use that set for both unknown-identifier validation and construction of the `Sdf.Layer.ReloadLayers()` argument.
Validate the entire set before reloading anything.

**Performance:** validation already allocates a set; retain and reuse it.
This removes a second traversal of lists and permits one-shot generators without an additional collection.
Ordering is not part of the existing set-based reload argument.

**Qualification:** run the actual reload API with a list, generator, empty iterable, repeated identifiers, and a generator containing a known and unknown identifier.
Check dirty layers against their on-disk contents.
The invalid request must reload none of its known layers.
Verify that iterator exceptions also occur before any reload.

### 7. Diagnostics: canonical subjects, then bounded source-ordered summaries

#### 7a. Canonical USD subject identity

**Change:** use a canonical diagnostic subject from immutable evaluated-source provenance, separately from each drawn copy's source entity identity.

Resolve native prototypes and point-prototype propagations to the original USD definition that produced them.
Use `PrimRecord.originPath` with its documented context, not as an unconditionally absolute USD path.
If the current frozen records omit the needed provenance, carry an explicit canonical diagnostic subject through snapshot capture and prim-record decoding.
Do not parse synthetic `ForInstancer` names or query a live stage during planning/application.

Feed this subject into `DrawnCopyDiagnosticAggregator`.
Combine equivalent reports from the original and propagated prototypes while counting each drawn copy once and retaining the smallest source-entity path.
Keep distinct USD definitions distinct even if their type and message match.

**Performance:** resolve provenance once per evaluated prim that needs it, not once per drawn copy.
Reuse existing frozen origin/context facts where sufficient.
No extra source traversal, Blender operation, or persistent cache is needed.

**Qualification:** one unsupported curve drawn directly and twice by each of two point instancers must produce one canonical-subject report with five drawn copies.
Also cover nested/native instances, prototype-relative origins, distinct same-type prims, masks, and missing provenance.
Compare canonical subjects and counts with the authored USD fixture, not with Hydra namespace spellings.

#### 7b. Deterministic first-ten selection

**Change:** pass all source-mapped capture diagnostics through the same finalization rules.
Preserve the existing problem-group key, including code, message, property, asset, and fallback distinctions.
Keep drawn-copy context out of that key until equivalent reports are combined.

For each problem group, count all eligible subjects but retain only the ten smallest source-ordered reports.
A bounded heap or sorted buffer of size ten is sufficient.
Use a stable tie-breaker for equal source paths and preserve defined handling of diagnostics without a source path.
Sort only the retained reports before emitting them.

**Performance:** no global sort of all diagnostics.
Selection costs at most `O(D log 10)` for `D` candidates, in addition to existing grouping; retained summary storage is `O(10G)` for `G` problem groups.
This does not remove the separate canonical-subject aggregation storage.
Avoid copying long messages repeatedly by retaining report indices until final output.

**Qualification:** the fourteen-instance curve fixture must retain the expected first ten source paths, including `/World/I01`, regardless of Hydra traversal order.
Permute creation order, add repeated messages on different properties, and include source-less warnings.
Check exact remaining counts and that each diagnostic is counted once.
Benchmark no diagnostics, one diagnostic, and large warning storms, including all-distinct problem groups.
Do not assume better asymptotics than the current linear truncation; bounded storage and fewer duplicate reports must justify any extra comparisons.

## Complexity reductions

### A. Delete representations with no production reader

Re-search all callers at implementation time, including bindings, stubs, package exports, tools, and tests.
These are internal implementation deletions, not permission to silently remove a supported external API.

| Item | Concrete change | Preserved authority / validation |
|---|---|---|
| Native `Partition`, `Plan.partitions` | Delete vector/type construction, Python binding/stub exposure, and tests asserting that unused representation | Keep copy-resource buffers, resource dependencies, actual replacement partitions, and application behavior |
| Ownership query types/functions | Remove `Claim`, `OwnershipStatus`, `Ownership`, `of()`, `manifest()`, and `set_manifest()` after caller confirmation | Keep the production `set_manifest_entries()` path and user-graph-based mutation/removal safety |
| Useful ownership test queries | Move only useful independent oracles to test support | Test actual stored claims and Blender users, not one production implementation against itself |
| `CreatedBinding` | Return the binding ID directly; update the production caller that currently reads `.binding_id` | Binding creation and persisted index remain unchanged |
| `WrittenIndex` | Make write/restore return `None` where results are discarded | Preserve the internal Text/index pair where `_index()` actually needs both |
| `has_config()` / `destination_collection_uids()` | Delete after confirming no callers | Preserve binding discovery and damaged-record behavior |
| `IdentityCandidates.index_entries` | Delete the unread field and its argument construction | Keep evidence used to choose or disable canonical candidates |
| `manifests.dependents()` | Remove from production; retain an independent test helper only if useful | Keep manifest dependency validation and all production dependency users |

**Performance:** less construction and retained memory; no added runtime abstraction.
Removing native partitions should save one vector per drawn copy across every retained plan, including undo-held plans.
Keep the measured manifest, partition, and correspondence caches that production consumes.

**Qualification:** run native plan/application, copied-binding, ownership, lifecycle, cache, and import-contract tests.
Measure large-plan construction, retained-plan memory across undo history, and synchronization output/resource sharing.
Update source README inventories, exports, stubs, and CMake inputs for any removed/moved files.

### B. Notices: retain affected paths, not event history

**Change:** replace the recorder's event vector with exact-path and subtree-root sets.

- Added/dirtied notices contribute exact paths.
- Removed notices contribute subtree roots.
- Renames contribute both old and new subtree roots.
- Drop unused dirty locator storage.
- Under the existing mutex, record into the sets; capture takes them by swap/move.

Preserve drop-next-capture hooks, invalidation semantics, and concurrent notice/capture behavior.
Do not turn a subtree removal into an exact-path invalidation or eagerly enumerate descendants.

**Performance:** retained memory follows unique affected paths `U`, not event count `E`.
Expected hash insertion work is `O(E)` with `O(U)` storage; avoid repeated reduction and locator copying.
Hash insertion moves work into the locked callback, so lower memory does not establish lower notice latency.

**Qualification:** compare captured output with the existing recorder for added, dirtied, removed, renamed, and overlapping paths.
Test notices arriving during capture and a deliberately dropped capture.
Measure callback latency and end-to-end capture for one event, all-unique events, and repeated-event storms; reject a single-event/common-case regression.

### C. Instancers: compute point arrays once per resolver

**Change:** add a narrow per-instancer result inside `InstanceResolver`.
Key it by the instancer's Hydra path and store the inferred point count and complete local point-transform vector.
Populate it once from masks, prototype index arrays, and transform primvars.
Each prototype expansion selects its indices from the same const result.

Keep the existing prototype-root copy cache; it answers a different question.
The new result belongs to one resolver/plan and needs no revision flags or cross-plan invalidation.

**Performance:** for `P` used prototypes and `N` points, remove repeated `O(PN)` transform construction and index-extent scans.
Compute the instancer-wide arrays in `O(N + I)` once, where `I` is the total prototype-index input size, then perform the existing selected-copy expansion.
Avoid copying cached vectors and release them with the resolver.
Retaining vectors for multiple instancers can increase peak memory compared with successive temporaries, so qualify that explicitly.

**Qualification:** compare exact transforms, masks, IDs, hierarchy resets, malformed indices, and nested instancing with fixture/USD expectations.
Count point-transform computations: one per used instancer, not per prototype.
Benchmark one prototype and many prototypes, sparse/large arrays, and many separate instancers.
Measure peak memory as well as planning time; no single-prototype slowdown is assumed away.

### D. Resolve and decode state once within each operation

#### D1. Binding status

Extract narrow internal queries accepting the already found binding, generation, and stage tracker.
Status enumeration passes its resolved values; public single-binding queries still look up current state before calling the same implementation.
Do not add a generic operation context or widen import-layer dependencies.

**Gate:** two-binding status enumeration must eliminate the four additional individual lookups observed in the review while preserving live-stage and out-of-date results.
Exercise missing, copied, removed, and unavailable bindings; measure many-binding status latency.

#### D2. Scene selection and shown displays

Pass the `FoundBinding` and already read generation through `_displays`, shown-display lookup, and validation.
Do not re-run `find_binding()` through both `live_stage()` and `_builds_from()` when the caller has just resolved the same binding.
Combine this work with finding 1 so pointer validity is not bypassed.

**Gate:** count lookups and record reads for the actual scene selection API, with warmed and rebuilt correspondence.
Retain freshness after callbacks, record edits between calls, undo, and destination removal.
Do not persist the resolved operation state across calls.

#### D3. Binding-index Text discovery

Replace `stored()`'s recursive conversion used only for presence detection with a non-decoding presence/value-shape check.
Reuse the namespace-shape logic but preserve the current handling of damaged namespace values.
Do not substitute `has()` blindly: it currently rejects a non-group namespace, whereas `stored(...) is not None` can expose damage even when that malformed value is falsey.

**Gate:** cover missing namespace, null/missing record, valid record, malformed group/non-group namespace, falsey malformed values, newer schema, and linked Texts.
Discovery must not decode valid records; callers decode each needed record once.
Measure index discovery with many unrelated Texts and large index records.

#### D4. Pending-cleanup ledger preflight

Have the update's preflight return the trackable Text and its validated loaded ledger, then apply the delta to that same loaded value.
Retain the independent early `check_trackable()` used before preparation.
Do not reuse that earlier value after callbacks or intervening work; the eventual update must read current state.
Preserve preflight refusal on empty updates and avoid unnecessary writes.

**Gate:** one ledger decode within an uninterrupted ledger update, with unchanged empty-update behavior.
Test malformed/newer ledgers, failure tracking, additions/removals, and a ledger changed between preparation and update.
Measure large-ledger updates and assert the decode count directly.

### E. Use one allocation record, with an explicit overlay

**Change:** make this the last refactor, after the concrete fixes and deletions.

1. Replace the prepared datablock/role/completed-entry parallel maps with one slotted operation-local allocation record per manifest entry key.
2. Each record holds its datablock, role, and optional completed manifest metadata. Distinguish allocated-but-incomplete from complete resources explicitly.
3. Track immediately on allocation. Only resources actually created by this operation enter its disposal set.
4. Retain a narrow changed-entry overlay for reused published resources. Resolve current metadata in the explicit order changed → newly created → published.
5. Keep the identity-to-entry-key map: it is a useful secondary index, not another ownership authority.
6. Replace repeated `key_of()` scans with an operation-local inverse datablock-identity-to-entry-key index, built once or lazily when needed.
7. Produce persistence deltas once at commit. Do not materialize merged dictionaries on every lookup or replace immutable manifests with mutable shared state.

**Performance:** reduce map synchronization and repeated reverse searches without wrapping every field access in a heavy abstraction.
The inverse index trades bounded operation-local memory for removal of repeated linear scans.
Reuse existing entry keys and metadata; avoid eagerly copying all published records into the overlay.
If the proposed record increases measured time or memory without offsetting savings, keep the existing representation for that path.

**Qualification:** test allocation, tracking, completion, reuse, dependency updates, partial keying, publication, and every rollback transition.
Assert a reused published resource is never disposed as if newly allocated.
Measure invariant-heavy and highly varying caches, one-copy updates, full rebuilds, allocation counts, dictionary materialization, and peak memory.
This refactor is optional if it cannot meet the equal-or-better gate; the correctness fixes do not depend on it.

## Implementation order and shared validation

1. Add reproductions for findings 1–7, keeping raw persistence and fixture-authored expectations as independent oracles.
2. Address 1 with D1/D2 and measure before accepting the design; fix grouped caching in 2.
3. Apply the small transaction/allocation/protection/iterable fixes in 3–6.
4. Correct diagnostic identity and finalization in 7.
5. Delete A, then implement and measure B, C, and the remaining D items independently.
6. Attempt E only after the smaller changes establish the remaining need.

Keep each change independently testable. Update contract/matrix documents only if an actual contract decision is made; these proposals request no relaxation.
Do not merge requested settings, published generation, last attempt, or pending cleanup.
Preserve source/evaluation stage separation, immutable snapshot/plan buffers, source-selection identity, and undo-bounded held plans.

### Performance protocol for implementation

- Record the unchanged checkout, host, supported Blender/USD versions, payload policy, resource counts, and call sequence.
- Use fresh processes for first-call measurements, count any required build/startup work when the applicable budget includes it, and also measure warm repeated calls.
- Test existing contract fixtures and ALab under every required payload policy. Synthetic 100-, 13,358-, and 30,006-entry manifests supplement, never replace, production-scale tests.
- Include unchanged refresh, one-copy edits, full rebuild, first/repeated/overlapping cache calls, playback, status enumeration, picking, selection, rollback, and cleanup retry.
- Compare equivalent correct outputs. Also report timings against the original buggy entry point so added correctness work is not hidden by changing the baseline.
- Report median, p95, first-call time, observed maximum, and peak memory per scenario, not an average across scenarios. Alternate baseline/candidate order and repeat fresh-process trials.
- Keep existing numeric budgets and churn gates unchanged. Check the heaviest input and first calls, with headroom under hard limits.
- Check USD captures, plan computations, record decodes, user-graph queries, key writes, Blender allocations, and dependency-graph updates directly.
- Treat repeatable regressions as failures. Do not infer parity from overlapping noisy timings; gather enough samples to resolve uncertainty.
- Re-run the decisive checks against the final implementation, not an earlier variant.

### Status of evidence for these documents

The [review](proscenium-sync-review.md#validation) records its completed focused suites and reproductions.
Those results establish the reviewed behavior, not the correctness or speed of these unimplemented solutions.
The pointer-validation timings above are additional planning probes in temporary Blender-wheel processes with isolated Blender user resources.
They are not ALab, packaged-extension, cross-platform, or Blender-binary qualification.
No implementation performance claim should be promoted to established evidence until the corresponding public-path gate passes.
