# Proscenium

Proscenium is a Blender extension for reliable, repeatable, **one-way synchronization of composed OpenUSD stages into a managed Blender display representation**.

It serves as:

- A snapshot synchronizer for supported USD content.
- The scene-display layer for a future USD-native stage editor.

Details in `docs/PROJECT.md`

## Building

```sh
uv sync
uv run proscenium-build                  # -> dist/proscenium-<version>.zip
```

To try it, `uv run proscenium-blender` builds the zip and starts an installed Blender 5.2 with Proscenium installed and enabled, keeping its preferences and extensions in `build/blender-user/` so your own Blender setup is untouched ([tools/README.md](tools/README.md)).

The zip is the extension. Install it with Blender's *Install from Disk*, or unpack it into a repository under the user extensions directory (overridable with `$BLENDER_USER_EXTENSIONS`), e.g. `$BLENDER_USER_EXTENSIONS/user_default/proscenium/`. `uv build` produces a Python wheel that only exists so the dev environment can import `proscenium` ([tools/README.md](tools/README.md)).

## Contributing

[AGENTS.md](AGENTS.md) has the rules every change follows, and links to the rules for each part of the repository. Names follow [docs/conventions.md](docs/conventions.md).
