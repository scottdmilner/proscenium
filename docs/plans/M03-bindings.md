# M3 — Binding model, source access, identity, and persistence schemas: plan

How M3 will settle its contracts and deliver tested source access, the binding model, and versioned persistence schemas, and the order of work. Requirements are in the [M3 milestone](../milestones/M03-bindings.md); where this plan and a requirement file disagree, the requirement file wins. Mechanisms named here are suggestions unless marked settled. Each phase gains a short decision log once work starts, in the style of the [M2 plan](M02-contracts.md).

M3 is the first milestone that ships product code. It delivers the matrix rows whose `delivery` is M3: the Bindings and Source Access rows (BIND-02 to BIND-10), API-01 to API-03, API-06, CONS-03, SID-03 to SID-07, COPY-01 to COPY-04, the In-Memory Sources rows (MEM-01, MEM-02, and MEM-04 to MEM-08), the File-Backed Refresh rows (FILE-01 to FILE-07), OWN-01, UNDO-06, UNDO-07, STATE-01, the Reopening rows (REOPEN-01, -02, -04, -05, -07), the Schema Versions rows (SCHEMA-02 to SCHEMA-05), ICON-07, ICON-24, and AFIX-04.

## Settled with the user (2026-10-15)

- **A file-backed binding reuses its own stage.** The binding opens one stage outside every USD stage cache (`Usd.BlockStageCaches`), keeps it, and reuses it across refreshes. It is never shared with another binding or tool. Refresh reloads the clean contributing layers that changed on disk, so the binding's Hydra chain can also persist across refreshes for Phase 2. A first synchronization, including the first after reopening a `.blend`, opens the stage.
- **The binding stage's anonymous layers are displayed.** A file-backed refresh shows the disk layers composed with the opinions in the binding stage's session layer and the anonymous layers beneath it, so a future editor can show unsaved edits through the live stage without saving and reopening. Synchronization never authors them, refresh never reloads them, and they are not saved in the `.blend`. Dirty disk layers still conflict.
- **That stage is the binding's live stage** for [live inspection](../spec/interaction-contract.md#two-layers-and-the-live-stage). For an in-memory binding, the live stage is the caller's.
- **Dirty contributing layers still fail refresh** with a source-access conflict naming them. Reloading a dirty layer discards its edits (M1 record), so refresh never reloads one.
- **The dirty check covers what the binding composes:** the layers the binding's stage uses under its payload policy (`GetUsedLayers`), excluding anonymous layers. Under load-none, a dirty layer reached only through an unloaded payload doesn't conflict, since it can't change what is displayed.
- **Source acquisition is Python `pxr`:** opening the binding's stage, the dirty check, reloads, the in-memory private stage, and runtime attachments. Every API it needs is in Python `pxr`, and Python stays the preference outside the core. The core receives a stage, takes its own reference, and releases it explicitly; it never keeps a released stage alive.
- **Persistent state is versioned ID-property records:** namespaced nested ID-property dicts on the Scene (binding records, persistent selection) and on managed IDs (ownership tags), each with a `schema_version`. Python schema code reads, migrates, and validates them, so records stay readable without registered RNA.
- **In-memory source key contract:**
  - The key is a caller-chosen string that names one in-memory source within a `.blend`. Several bindings may share it, and attaching a stage under a key attaches it to all of them (2026-10-16).
  - Reattachment requires an exact key match.
  - The root-layer identifier is informative: it is never used to find bindings.
  - Replacing the attached stage preserves stored source selections; they resolve against the next published generation.
  - Attaching a stage whose root-layer identifier differs from the stored one requires explicit confirmation from the caller.
- **Copied bindings: probe, then rule.** Phase D probes what Blender does to ID properties and ID pointers on each copy route (duplicate collection, full-copy and linked-copy scene, append from another `.blend`, a record copied through Python). The rule to settle from those results: the canonical candidate is the one whose binding record and destination still refer to each other; if more than one or none qualifies, all candidates are disabled pending repair.

## Phases

Each phase ends with a review by the user before the next starts. Each phase lists its commits in order. Every commit is one feature and passes `pre-commit` and the test suite on its own:

- A spec change lands with its matrix rows, its `invariants.md` bullet, and its DECISIONS.md row.
- A new fixture lands with its registry entry, its Named Contract Fixtures row, its mention in the M3 Tests section, and a row that uses it.
- Code lands with its tests.
- A decision lands with its line in the phase's decision log.

If a commit grows past one feature, it splits, and this list is updated in the same commit.

### Phase A — Contracts in the spec and matrix

1. **The M3 plan:** this file.
2. **File-backed refresh contract.**
   - [source-access.md](../spec/source-access.md) File-Backed Refresh: replace the design note with the settled contract above.
   - FILE-04 says "Refresh does not reuse a cached stage", which read literally forbids reusing the binding's own stage. New wording: the binding's stage never comes from a USD stage cache (`UsdUtils.StageCache`, or a `Usd.StageCacheContext` another tool set up), and is never shared with another binding or tool. The binding may keep and reuse a stage it opened itself. Clean-layer reloads stay the only effect other stages can observe.
   - Updated together: the FILE rows, the file-backed bullet in [invariants.md](../spec/invariants.md), the DECISIONS.md rows "Strictness of the file-backed refresh contract" and "Dirty contributing layers on file-backed refresh", and the `F-DIRTY-LAYER` and `F-CACHED-STAGE` descriptions in [strategy.md](../testing/strategy.md).
3. **Live stage per binding.** [interaction-contract.md](../spec/interaction-contract.md#two-layers-and-the-live-stage) names the live stage for both source kinds, with ICON-07 and the live-stage notes in the DECISIONS.md rows "Browsing universe and inspection metadata set" and "Inspection layer".
4. **Stage-level state for in-memory sources (MEM-07, MEM-08).**
   - A private stage over the caller's root and session layers.
   - Muted layers, population mask, resolver context, and interpolation are copied.
   - The binding's payload policy replaces the caller's load rules.
   - Session-layer opinions are shared live.
   - The edit target is irrelevant to reading and isn't copied.
   - Updated together: In-Memory Sources and the DECISIONS.md row "Stage-level state reproduced for in-memory sources".
5. **In-memory source key contract.** Source Identity, the SID rows (SID-03 to SID-07), and the DECISIONS.md row "In-memory source key contract".
6. **Synchronization API signature.** A Synchronization API section in source-access.md (API-01 to API-06) and a DECISIONS.md row. M3 implements source acquisition behind it and `set_settings`; M5 builds the transaction.
7. **Fixture case schema (AFIX-04).** The schema M1 left to M3's first cases: operation, expected outcome, requirement IDs, and phase. It goes into `tests/fixtures/registry.py`, with its test and the row's oracle.
8. **Oracles on rows whose fixtures already exist:** the FILE, MEM, COPY, OWN-01, REOPEN, and SCHEMA-05 rows.
9. **New fixtures, with the rows they cover,** in one commit. These are stubs; their generators land with the code that uses them.
   1. `F-MULTI-BINDING`: independent bindings on one source, including a file-backed and an in-memory binding on the same file (BIND-02 to BIND-10).
   2. `F-SOURCE-CHANGE`: a source layer changed while the binding evaluates (CONS-03).
   3. `F-REATTACH`: in-memory release and reattachment (MEM-05, MEM-06, UNDO-06, ICON-07, SID-03 to SID-07).
   4. `F-SCHEMA-VERSIONS`: older, failed-migration, and newer records (SCHEMA-02 to SCHEMA-04).
   5. `F-BINDING-STATE`: binding handles, configuration, live stage, and persistent selection (API-01 to API-03, API-06, STATE-01, UNDO-07, REOPEN-02, ICON-24, ICON-32, ICON-33).
   6. M3 co-owns `F-OFFLINE`, which its reopening rows already use, and writes its generator in Phase D.
10. **Start M3:** add it to `started`, then `tools/matrix.py render`.

#### Phase A log

- **A2, file-backed refresh.** FILE-04 now rules out stage caches and shared stages, not reuse of the binding's own stage. Two new rows: FILE-06, the dirty check's scope, and FILE-07, that a reused stage displays what a newly opened one would. FILE-01 adds the opinions in the binding stage's anonymous layers to what refresh displays, for a future editor's unsaved edits (with the user). The binding's stage is listed in [Binding State](../spec/lifecycle.md#binding-state) as runtime state. The same-second change check is a design note that Phase C settles.
- **A3, live stage.** The contract names each binding's live stage (ICON-32, ICON-07). A file-backed binding has none until its first synchronization, including after reopening (ICON-33), since the extension opens sources only when asked to synchronize. Tools need the live stage to author into its anonymous layers, so they get it from the binding, which never places it in a stage cache (ICON-34).
- **A4, in-memory stage-level state.** The design note's private stage becomes the contract (MEM-07, MEM-08), as M1 tested it; MEM-03 is retired. The caller's settings are matched at each synchronization, not only on attach, because the caller may change them between synchronizations. Whether the binding keeps its private stage across synchronizations, as a file-backed binding keeps its own, is a design note for Phase C.
- **A5, in-memory source key.** The key names a source (with the user), so bindings with different payload policies on one caller stage share it and one attach call serves them all. The settled contract replaces the open questions (SID-03 to SID-07); SID-02 is retired. A root-layer mismatch needs confirmation, and without it the attachment fails.
- **A6, synchronization API** (with the user). A binding handle holds only the binding's persistent identifier, so it gives methods without holding a datablock or state across operator calls (UNDO-07); operations that span bindings, such as attaching under a source key, stay module functions. `synchronize(time_code)` takes only the time code, as PROJECT.md requires it as a parameter; other settings change through `set_settings`. Expected failures are results, since a completed-with-issues result needs a return value anyway. M3 delivers API-01 to API-03 and API-06; the result and exception rows (API-04, API-05) are M5's.
- **A7, fixture case schema.** A case is a name, an operation, an outcome, the rows it checks, and its phase, declared on the fixture in the registry. The phase is derived from the rows rather than chosen, and a test checks it. The source-access fixtures get their first cases, covering every row that lists them. Their operation is synchronization, though M3 runs only the acquisition step; M5 runs the same cases through the whole transaction. Once M3 starts, the coverage test requires a case for each of its rows on every fixture with cases.
- **A8, oracles on rows with fixtures.** The FILE, MEM, COPY, REOPEN, SCHEMA-05, and ICON-34 rows state what a test asserts, in terms of the generators' fields where a generator exists. OWN-01 is a contract, so its oracle is Phase D's ownership format. The F-OFFLINE and F-PREPARATION-CLEANUP-FAILURE oracles wait on those fixtures' owning milestones for their generators.
- **A9, new fixtures.** Every remaining M3 behavior row gets a fixture: `F-MULTI-BINDING` for the BIND rows, so one scene checks both what each binding reads and that it leaves the others alone; `F-SOURCE-CHANGE` for CONS-03; `F-REATTACH` for the key contract and attachment; `F-SCHEMA-VERSIONS` for migration; and `F-BINDING-STATE` for handles, configuration, the live stage, and persistent selection. BIND-05 is checked as what `synchronize` records, since M3 implements only acquisition. M3 co-owns `F-OFFLINE` (with the user), whose reopening rows it delivers; M9 extends it with materials and textures.
- **A10, M3 started.** Every M3 row now has an oracle, and every behavior row a fixture, so the checker holds them to it from here on, and the case test requires each fixture with cases to cover its M3 rows. Phase A is complete: the contracts are settled in the spec, and the rows Phases B to D implement are traced.

### Phase B — Compiled core bring-up

1. **Shared build code out of `tools/feasibility/`.** The toolsets, dependency preparation, and linkage audit from the bridge's `build.py` and `prepare_deps.py` move to `tools/`, and the bridge builds through them unchanged.
2. **`tools/build_extension.py` builds the core** from `src/proscenium/core/` as an empty module. The build links Blender's `usd_ms`, the manifest gains its `platforms` key, and the linkage audit runs on the module. CI gets the toolchain on macOS, Windows, and Linux in the same commit, so it never breaks between commits.
3. **clang-format and clang-tidy pre-commit hooks.**
4. **Error translation and the stage handle.** Error translation covers every entry point. The handle takes the caller's stage, adds its own reference, and has an explicit `release()`. Test: releasing the caller's in-memory stage leaves the binding unattached (MEM-05), in `isolated/` since native code is involved.

#### Phase B log

- **B1, shared build code.** `tools/blender_deps.py` (the pins and the dependency checkout) and `tools/native_build.py` (toolsets, the CMake build, and the linkage audit) come from the bridge's `prepare_deps.py` and `build.py`. The bridge's `build.py` is now a caller that names its module and writes `build.json`. The build script passes `BLENDER_DEPS` to CMake, so a CMake project doesn't locate the checkout itself. The dependency cache moves to `build/blender-deps/`, shared by the core and the bridge. Compiler flags stay in each CMakeLists.txt; the core's copies the bridge's in B2.
- **B2, the core in the extension build.** The module is `proscenium.core._core`, with one function, `usd_version()`, so tests can check it was built against the host's USD. `build_extension.py` builds it into `src/proscenium/core/` (ignored by that directory's `.gitignore`), the way it syncs `wheels/`, and skips the build when `build/core/build.json` records this platform, the locked release, and the current hashes of the sources, the build tools, and the module. Only a temporary copy of the manifest gets `platforms` and `blender_version_max`, so the checked-in manifest is the same on every platform and release. Each zip supports only the locked release's minor version (5.2.x): the maximum is the next minor (`5.3.0`, the first unsupported version), and the build fails unless the hand-written `blender_version_min` is in that minor. Linux's module is built in CI's manylinux_2_28 job and the Linux test job reuses it through that record, since the manylinux image can't run bpy. The module has no rpath, so it loads only once Blender's `usd_ms` is in the process, which Blender and an imported bpy guarantee. For processes without bpy, such as the bpy-free tests, `proscenium.core` imports `pxr.Tf` first.
- **B3, clang-format and clang-tidy.** Both come from PyPI in the dev group, so `uv.lock` pins them like the other hooks. They cover `src/proscenium/core/` only; the bridge is evidence and keeps its own style. The format is Google's with 120 columns. clang-tidy runs the bugprone, clang-analyzer, misc, modernize, and performance checks, without trailing return types (a style choice) and include-cleaner (it can't follow pxr's umbrella headers), and every warning fails. It reads the compile commands of the core's CMake build, which `tools/clang_tidy.py` configures first through `native_build.configure`, so it parses the core with the build's flags and Blender's headers. On macOS it names the SDK, which AppleClang's commands leave implicit. CI's lint job restores the dependency cache for those headers.
- **B4, error translation and the stage handle.** The bindings use `pxr_boost::python` (DECISIONS.md row "Python bindings for the compiled core", with the user). Each entry point opens a `TfErrorMark` and raises the Tf errors posted since as `pxr.Tf.ErrorException` (`errors.h`). C++ exceptions use pxr_boost::python's own translation (`std::invalid_argument` is `ValueError`, any other `std::exception` is `RuntimeError`), so the core adds no translator. `_core.StageHandle(stage)` takes a weak stage pointer and adds its own reference, since Tf's converter for a `TfRefPtr` argument moves ownership out of the caller's Python object (M1b Phase C). `release()` drops that reference; `stage()` then returns the stage only while someone else holds it. `proscenium.core` imports `pxr.Usd`, not only `pxr.Tf`: the core's stage arguments need pxr.Usd's Python converters, which a process with bpy may not have registered either. `_core.pyi` gives the module's types, so ty checks callers where it isn't built. Tests: in `isolated/`, a stage the caller dropped stays alive while held and expires after `release()`, which is the core's part of MEM-05, and releasing a handle leaves a caller-held stage alive. In `bpy_free/`, a posted Tf error and a C++ exception each raise their Python exception.
- **Source-entity identifiers (with the user, 2026-10-17).** A source entity's identifier is its prim path in the composed stage: the instance-proxy path inside native-instance contents, which carries its instance context, as M2's oracle names entities. It is never a Hydra-generated path or an instancer index, and is persisted as the path string. The instance context and the floor are computed from a stage when needed, during synchronization or on the live stage, never stored: without a live stage no interaction function runs, and a stored context would go stale when the source's instancing changes, while a path resolves against the next published generation (SID-07). The identifier arrives with its first user, the persistent selection schema (D7); the correspondence layer that derives floors is M4's.

### Phase C — Source access

All of this goes in a bpy-free source-access package. Tests are synchronization cases on the existing generators in `tests/fixtures/source_access.py`.

1. **The binding's own uncached stage,** opened under `Usd.BlockStageCaches`, with the `F-CACHED-STAGE` cases.
2. **The scoped dirty check** and its source-access conflict, with the `F-DIRTY-LAYER` cases.
3. **Reloading clean changed layers.** Reloading must not miss a change on disk. M1 found that a non-forced reload misses a rewrite within the same second on Windows, and this commit settles how refresh detects such changes. Test, a metamorphic relation: after a refresh, the binding's reused stage evaluates the same as a freshly opened stage of the same files on disk.
4. **Payload-policy changes on the owned stage.**
5. **The in-memory private stage,** with the `F-PRIVATE-STAGE` cases.
6. **The runtime attachment registry and key contract.** The registry is keyed by binding identity and unaffected by undo (UNDO-06). Covers exact-key reattachment, the root-layer mismatch warning, and confirmation for a different stage.
7. **Isolation** between a file-backed binding and an in-memory stage on the same file.
8. **The synchronization API entry point,** acquisition only.

### Phase D — Binding model and persistence

1. **Copy-route probe,** with its section in the [feasibility record](../feasibility/runtime-record.md).
2. **The canonical-candidate rule,** in Copied Bindings, the COPY rows, and the DECISIONS.md row "Copied bindings".
3. **The versioned record framework.** ID-property records, validation, and migration hooks. Tests: loading older, failed-migration, and newer-schema records.
4. **Binding configuration schema.**
5. **Ownership metadata format (OWN-01).** It is representation-independent and keeps resource identity, ownership, source coverage, representation role, and usage separate.
6. **Published-generation, last-attempt, and pending-cleanup schemas,** as far as M3 can define them. M5 fills in the published generation and chooses the pending-cleanup mechanism.
7. **Source-entity identifiers and the persistent selection schema (ICON-24).** The identifier is the entity's path in the composed stage, as the Phase B log describes. Tests: compatibility of source-entity identifiers and persisted selection with M2's fixtures and oracle (`tests/support/interaction_oracle.py`).
8. **Runtime indexes,** keyed by persistent identifiers and guarded by a generation counter. They are rebuilt after file load, undo, and redo. Test: indexes survive save and reopen.
9. **Reopening:** no automatic synchronization, an unavailable source, and a deleted destination.
10. **Copied-binding detection and the disabled-pending-repair state,** with `F-OWNERSHIP-AMBIGUITY`.

### Phase E — Close

1. **Notes for M4 and M5.** M4 reviews identifiers and schemas against the finalized contract. M5 settles the pending-cleanup mechanism and the published generation's contents.
2. **Close the decision log,** render the matrix, and confirm the exit condition.

## Working agreements

- Each phase has its own branch (`m03-phase-a`, `m03-phase-b`, …). The user stages, commits, and pushes.
- Commits are small and single-feature, as listed under each phase.
- Planning docs state requirements; mechanisms are suggestions for the milestone that settles them.
