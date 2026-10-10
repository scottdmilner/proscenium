# Proscenium

Proscenium is a Blender extension for reliable, repeatable, **one-way synchronization of composed OpenUSD stages into a managed Blender display representation**.

It serves as:

- A snapshot synchronizer for supported USD content.
- The scene-display layer for a future USD-native stage editor.

Details in `docs/PROJECT.md`

## Building

```sh
uv sync
uv run python tools/build_extension.py   # -> dist/proscenium-<version>.zip
```

The zip is the extension. Install it with Blender's *Install from Disk*, or unpack it into a repository under the user extensions directory (overridable with `$BLENDER_USER_EXTENSIONS`), e.g. `$BLENDER_USER_EXTENSIONS/user_default/proscenium/`. `uv build` produces a Python wheel that only exists so the dev environment can import `proscenium`. Don't distribute it.

## Style Guide

- PEP8
- Type annotate all function signatures
- Prefer shorter docstrings + inline code comments over very long docstrings
- Files should generally not exceed ~600 lines of code, and rarely exceed ~1000 lines. Split long files into appropriately organized submodules.
