# Docs: agent instructions

[PROJECT.md](PROJECT.md#documentation-map) maps these files, and says which of them are requirements.

## Superseded documents

`archive/` holds superseded documents, kept for history. Don't read them unless the user asks. They describe intentions that were later changed, and would mislead current work. Never treat them as requirements or guidance, and don't update them.

## Keep invariants in sync with the spec

- Any change to a guarantee in a spec file updates its statement in `spec/invariants.md` in the same change, and the reverse.
- `invariants.md` stays a summary that links to and defers to the authoritative spec section. It never gains detail of its own. Each bullet ends with the IDs of the matrix rows it summarizes.

## Keep the requirement matrix in sync

- [testing/requirements.yaml](testing/requirements.yaml) has a row for every requirement in PROJECT.md, `spec/`, and `testing/`, quoting its text.
- Any change to those docs updates the affected rows (or the `excluded` list) in the same change. Then regenerate the view with `uv run python tools/matrix.py render`.
- Contract decisions update their rows before implementation.
- Before a milestone implements anything, it fills in the fixtures and oracle of the rows it delivers, and adds itself to `started`.
- `tools/matrix.py check` fails on drift. It runs as a pre-commit hook and as a bpy_free test.
- Retired IDs are never reused.

## Writing docs

- Docs and decision logs state the current decision and its reasons, not how it was reached. Don't describe earlier drafts, revisions, or options that were never decided on ("revised four times", "three, not four", "no longer", "rather than X" where X was never adopted). Name a rejected alternative only when its reason still guides later work.
- Evidence docs (feasibility records, decision rows) claim only what a check actually tested.
