# M1 — Runtime feasibility, workspace, and test infrastructure: decision log

What M1 produced, where each result is documented, and why it was done that way. The linked docs are authoritative; this file records only the reasoning they don't. Requirements are in the [M1 milestone](../milestones/M01-runtime.md).

## Phase A — Runtime feasibility

Produced the probes in `tools/feasibility/` and the [runtime feasibility record](../feasibility/runtime-record.md); macOS arm64 is a go.

- **Three runtimes per probe** (bpy wheel, wheel under pytest, Blender binary). The binary is what users run, so its results are authoritative. The wheel and pytest runs show which findings hold in the test environment.
- **Findings, not mechanisms.** The record states observed behavior; where a finding suggests a design, the milestone that owns it decides. Example: the private disk view works but is too slow as built, so DECISIONS.md keeps the conflict failure and leaves a cheaper view to M3.
- **Review gate after Phase A**, before any tooling, so a failed feasibility result could change the strategy before more was built on it.

## Phase B — Workspace, tooling, CI

Produced the extension skeleton in `src/proscenium/`, the build script, the lint hooks, [AGENTS.md](../../AGENTS.md), and the CI and feasibility workflows in `.github/`.

- **Packaging with the wheel's extension CLI** instead of a Blender binary, because Phase A showed its archive matches the binary's file for file. Building needs no Blender install.
- **Runtime wheels come only from the runtime lock.** That keeps dev packages out of the zip by construction, so the build needs no separate leak check.
- **Windows and Linux through GitHub Actions**, as agreed with the user. The feasibility workflow runs by hand, and its uploaded results are copied into the record.

## Phase C — Test infrastructure

Produced the three test layers, shared helpers, the fixture registry and scenes, the generated CI fixture, and smoke tests; [tests/README.md](../../tests/README.md) documents them.

- **Reused, reset processes rather than fresh ones.** On the development machine, a reset cost about 30 ms against 0.85 s for a fresh wheel process and 1.2 s for the binary, and forking a process with bpy loaded aborts. So pytest-xdist workers each reuse one process, with a reset and a clean-baseline assertion before every test. Fresh processes (`tests/isolated/`) are kept for what a reset can't make clean.
- **Layers named for the runtime** (`bpy_free`, `blender`, `isolated`), not for test granularity, because unit and integration tests both occur in every layer.
- **Blender modules blocked by origin** in the bpy-free layer (where a module loads from), not by a hard-coded name list that would need maintaining.
- **Static scenes as `.usda` files with purpose comments**, copied into `tmp_path` before use, so parallel tests never share or modify repository files.
- **Fixture cases are left to M3.** acceptance.md requires every case to declare its operation, outcome, requirement IDs, and phase, but the right schema depends on real cases. M3 writes the first ones.

## Phase D — Acceptance details, ALab, matrix

Produced the acceptance details in [acceptance.md](../testing/acceptance.md), the metamorphic-test section in [strategy.md](../testing/strategy.md), the [ALab pin and inventory](../testing/alab/README.md), and the [requirement-to-test matrix](../testing/requirements-matrix.md) with its checker, `tools/matrix.py`.

- **Acceptance details in acceptance.md, not a separate specification.** What M1 can settle (time-code rules, the ALab pin, the reference hardware) is short, and keeping it next to the requirements avoids a second file to maintain.
- **The bounds comparison contract belongs to M4.** Everything beyond "compare in Blender world space, using visibility and purpose as specified" depends on the display representation. The one M1 finding, that `BBoxCache` bounds are looser than the points' box under rotation, is kept in the DECISIONS.md row.
- **ALab pinned per subtree.** A composite hash is as tamper-evident as a per-file list. Splitting by top-level entry, and by child of `fragment/` where the optional packages install, still names the package when a tree differs. The 14,150-line per-file manifest is written to `build/alab/` for comparing machines, not committed.
- **Only the ALab summary is committed.** The inventory is deterministic for a given tree, USD version, and script. `inventory.md` shows any change in review and is readable without a 12 GB download; the per-prototype JSON can be regenerated.
- **Matrix rows quote the spec.** A quote that must appear in its section, plus a check that every block is quoted or excluded, catches drift in both directions: a changed requirement and an untraced one.
- **Rows are filled in by their delivering milestone.** Fixtures and oracles for M3–M14 would encode designs those milestones haven't made. A milestone fills in its rows and adds itself to `started` before implementing; the checker then requires them. M4 marks high-risk rows from its risk matrix.
- **Only requirements with an outcome to check get rows:** behavior checked by tests, contracts by decision records, and process rules by tooling. Permissions, scope limits, design guidance, and statements true by construction are excluded, with the milestone they guide, because checking them would show nothing.
- **In-memory sources are Phase 2**, because PROJECT.md lists them under Phase 2, even though M3 delivers them. File-backed refresh is Phase 1.
- **Invariants name their rows**, so each cross-cutting guarantee points at testable requirements, and the checker confirms those rows sit in the sections the invariant links.
- **Metamorphic tests** were added for results that are hard to state fully but whose change under an input change the spec defines, such as translating a root or toggling instancing. The delivering milestone chooses its relations.

## M1b — Hydra bridge

A side investigation after Phase C showed that a compiled module can link to Blender's bundled USD on macOS and read Hydra scene indices, which Blender's Python `pxr` doesn't expose ([record](../feasibility/runtime-record.md#compiled-hydra-bridge--macos-arm64)). The choice of evaluation front end and core language became a separate gate, [M1b](../milestones/M01b-evaluation-gate.md), between M1 and M3: M3 defines identifier schemes and the inspection snapshot format, which belong to the core, so the core's language is settled first. The bridge's Windows and Linux results are M1b work and do not gate M1's exit. Until M1b decides, `proscenium/core/` is provisional, and the matrix accepts M1b as a delivery milestone.

## Working agreements

- Work happens on branch `m01-runtime`, committed at phase boundaries. The user makes the commits and pushes.
- Planning docs state requirements; mechanisms are suggestions for the milestone that settles them.
- Windowed (UI-mode) testing is out of scope and recorded only as future work.
