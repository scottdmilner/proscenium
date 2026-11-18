# Conventions

How code is named, across the repository. [AGENTS.md](../AGENTS.md) has the other style rules, and ruff and ty enforce the rest.

## Names

- These rules cover types, functions, methods, parameters, dataclass fields, other attributes, and file and module names. They apply in product code, tests, fixtures, tools, and prototypes, and to their C++ equivalents. Review names where they are called and where their fields are read: their meaning should be clear without reading the implementation or finding a comment elsewhere.
- One concept per word, the [Glossary](PROJECT.md#glossary)'s word where it has one. Never use a bare generic word such as `index`, `source`, or `binding` where it could mean more than one thing. Write `binding_index` and `ownership_index`, and `candidate` for one record or copy of a binding identity.
- Spec terms keep their meaning:
  - A *generation* is a published generation.
  - A *layer* is a USD layer or a pipeline layer.
  - A *synchronization* is one attempt.
  - A *claim* and a *candidate* are what the spec defines.

  None of these words names anything else. The source's levels of units, which import-linter's `layers` contracts list, are always *import layers*, never bare layers or tiers.
- Don't call primvar value types, Blender attribute types, or interpolation modes "kinds". Name their actual role, so they can't be confused with USD model kinds.
- Prefer familiar, precise words, such as `index` for a position.
  - Spell out domain distinctions that affect how a value is used.
  - Avoid unexplained abbreviations, and generic names such as `data`, `kind`, `place`, or `previous`, when the reader must reconstruct what they hold.
  - Keep names concise where the enclosing type or module already makes the domain clear.
- Exceptions end in `Error`, so they aren't mistaken for values (ruff's N818 enforces it).
- A type names its domain and responsibility: `DiagnosticCategory`, `DecisionReason`, `PostgresConnectionPool`. Avoid abstract labels such as `Category`, `Reason`, or `DataManager`, which require reading their implementation to understand.
- A function is named for its effect:
  - One that decodes or encodes a stored record is `read_*` or `write_*`.
  - One that changes held state and writes it through to the record is `set_*`.
  - Any other function is named for what it returns (`config(binding_id)`, `index_texts()`).
  - An operation the spec defines takes the spec's verb (`synchronize`, `reload`).
- Name side effects explicitly: creating a resource, installing a handler, registering a holder, and clearing a cache use those verbs. Use `ensure_*` or `get_or_create_*` only when an existing suitable value is reused. A name must not imply reuse when every call creates a new value.
- Members distinguish values from their references: `object_resource_index` for a plan index, `manifest_entry_key` for a stored key, `source_path` for a path, `module_path` for a file path, and `candidate_count` for a count.
  - Name the indexed collection when several are in scope.
  - Boolean names read as predicates (`is_canonical`, `visible_in_viewport`). A predicate name must not hold an index or a count.
- Collection names say what their elements represent: `resource_indices`, `source_entity_paths`, `dependency_entry_keys`.
  - When a mapping's keys or direction need context, name them too (`prim_index_by_path`, `previous_mesh_indices_by_holder`).
  - Don't name a collection of indices as though it contained the objects themselves.
- Include units, coordinate space, or lifecycle state when they change the interpretation: `stage_durations_seconds`, `world_matrix`, `local_bounds`, `requested_settings`, `applied_settings`, `attempted_settings`. Distinguish observed results from predictions, and counts from the collections counted.
- Corresponding Python and C++ members use the same domain words and meaning, each in its language's spelling convention (`object_resource_index` / `objectResourceIndex`).
  - Keep declarations, Python bindings, type stubs, and callers aligned.
  - Keep external API spellings where an override or protocol requires them.
- A persisted field name is part of its storage schema.
  - A schema that has not shipped may be edited in place, without a version bump or migration.
  - Once a schema has shipped, renaming a field includes the schema version and the migrations needed to read existing records, with compatibility checks.
  - Review other serialized keys and externally consumed names for compatibility before changing them.
- Files and modules name their responsibility, so imports and editor tabs identify what they contain: `stage_registry.py`, `frame_capture.py`, `loaded_usd_libraries.cpp`.
  - Avoid catch-all names such as `common.py` or `data.py`.
  - Distinguish implementation modules from their probes and benchmarks.
  - Keep conventional entry and configuration filenames (`__init__.py`, `conftest.py`, `CMakeLists.txt`).
- Module names are unique across `src/proscenium/` and `packages/`. They name what the module holds, so a use doesn't repeat itself (`binding_records.BindingConfig`, `binding_settings.PayloadPolicy`).
- Rename tracked files with `git mv`. In the same change, update imports, package exports, CMake inputs, script paths, README inventories, documentation references, and affected requirement-matrix rows. Preserve the import layers and the unique module names.
