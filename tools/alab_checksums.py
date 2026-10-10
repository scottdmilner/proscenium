"""Write or verify the SHA-256 pin of the ALab tree that acceptance runs use.

    PROSCENIUM_ALAB_ROOT=/path/to/ALab uv run python tools/alab_checksums.py [--check]

The root is the directory holding entry.usda, with techvar assets installed into
it (docs/testing/alab/README.md). Every file below it except dotfiles (e.g.
.DS_Store) is listed as `sha256  relative/posix/path`, sorted, like sha256sum.
That per-file manifest goes to build/alab/sha256sums.txt (not committed).

The committed pin, docs/testing/alab/subtrees.sha256, has one line per subtree:
`sha256  files  subtree`, where the hash is over that subtree's manifest lines.
Subtrees are the top-level entries, with fragment/ split into its children,
since the optional ALab packages install there. The `.` line hashes all the
subtree lines, so it pins the whole tree. --check fails on any added, missing,
or changed subtree.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "docs" / "testing" / "alab" / "subtrees.sha256"
FULL = ROOT / "build" / "alab" / "sha256sums.txt"  # gitignored
SPLIT = {"fragment"}  # top-level directories pinned per child


def _files(root: Path) -> list[str]:
    """Every file below root except dotfiles, as sorted POSIX paths relative to root."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]  # prune hidden dirs from the walk
        out += [(Path(dirpath) / f).relative_to(root).as_posix() for f in filenames if not f.startswith(".")]
    # Sorted by code point, not locale, and with "/" separators, so every platform lists files the same way.
    return sorted(out)


def _digest(path: Path) -> str:
    """The SHA-256 of one file, read in chunks."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def manifest(root: Path) -> str:
    """The per-file manifest text for the tree at root."""
    files = _files(root)
    with ThreadPoolExecutor(max_workers=16) as pool:  # hashing releases the GIL; this is I/O bound
        digests = pool.map(lambda rel: _digest(root / rel), files)
    return "".join(f"{d}  {rel}\n" for d, rel in zip(digests, files, strict=True))


def _subtree(rel: str) -> str:
    """The pinned subtree a file belongs to.

    "entity/a/a.usda" -> "entity"; "fragment/geo/x.usdc" -> "fragment/geo";
    "fragment/top.usda" (directly in a split directory) -> "fragment"; "entry.usda" -> itself.
    """
    parts = rel.split("/")
    return "/".join(parts[:2]) if parts[0] in SPLIT and len(parts) > 2 else parts[0]


def subtrees(full: str) -> str:
    """The pin text for a per-file manifest: the whole tree as `.` first, then one line per subtree."""
    # Hashing whole manifest lines (digest and path) means a rename or move changes the
    # subtree's hash even when no file's bytes change.
    groups: dict[str, list[str]] = {}
    for line in full.splitlines(keepends=True):
        groups.setdefault(_subtree(line.split("  ", 1)[1].rstrip("\n")), []).append(line)
    lines = [
        f"{hashlib.sha256(''.join(group).encode()).hexdigest()}  {len(group)}  {name}\n"
        for name, group in sorted(groups.items())
    ]
    # The root line hashes the subtree lines, so it changes whenever any subtree does.
    total = sum(len(group) for group in groups.values())
    return f"{hashlib.sha256(''.join(lines).encode()).hexdigest()}  {total}  .\n" + "".join(lines)


def _entries(text: str) -> dict[str, str]:
    """Pin text as subtree -> digest; the file counts are informational and not compared."""
    return {name: digest for digest, _count, name in (line.split("  ", 2) for line in text.splitlines())}


def differences(expected: str, actual: str) -> list[str]:
    """Missing, added, and changed subtrees between two pins."""
    want, have = _entries(expected), _entries(actual)
    problems = [f"missing: {p}" for p in sorted(want.keys() - have.keys())]
    problems += [f"added: {p}" for p in sorted(have.keys() - want.keys())]
    problems += [f"changed: {p}" for p in sorted(want.keys() & have.keys()) if want[p] != have[p]]
    return problems


def main() -> int:
    """Write the pin, or with --check compare against it; the per-file manifest is written either way."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help=f"verify against {PIN.relative_to(ROOT)}")
    args = parser.parse_args()
    if not (alab := os.environ.get("PROSCENIUM_ALAB_ROOT")):
        raise SystemExit("set PROSCENIUM_ALAB_ROOT to the directory holding entry.usda")
    root = Path(alab)
    if not (root / "entry.usda").is_file():
        raise SystemExit(f"{root}: no entry.usda")

    full = manifest(root)
    FULL.parent.mkdir(parents=True, exist_ok=True)
    FULL.write_text(full, encoding="utf-8")
    pin = subtrees(full)
    if not args.check:
        PIN.write_text(pin, encoding="utf-8")
        print(f"wrote {PIN.relative_to(ROOT)} ({len(full.splitlines())} files) and {FULL.relative_to(ROOT)}")
        return 0

    problems = differences(PIN.read_text(encoding="utf-8"), pin)
    if problems:
        problems.append(f"per-file manifest for comparison: {FULL.relative_to(ROOT)}")
    print("\n".join(problems) or f"{root} matches {PIN.relative_to(ROOT)} ({len(full.splitlines())} files)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
