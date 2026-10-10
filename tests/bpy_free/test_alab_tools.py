"""The ALab tools: the checksum pin and its comparison, and (with ALab) the committed outputs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import alab_checksums
import alab_inventory


def test_manifest_lists_files_but_not_dotfiles(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "entry.usda").write_text("a")
    (tmp_path / "sub" / "x.usda").write_text("b")
    (tmp_path / ".DS_Store").write_text("ignored")
    lines = alab_checksums.manifest(tmp_path).splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["entry.usda", "sub/x.usda"]
    # sha256 of "a", as sha256sum prints it
    assert lines[0] == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb  entry.usda"


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def _pin(root: Path) -> dict[str, tuple[str, str]]:
    """subtree -> (digest, file count)"""
    text = alab_checksums.subtrees(alab_checksums.manifest(root))
    return {name: (digest, count) for digest, count, name in (line.split("  ") for line in text.splitlines())}


def test_subtrees_split_fragment_by_child(tmp_path: Path) -> None:
    _tree(tmp_path, {"entry.usda": "e", "entity/a/a.usda": "a", "entity/b.usda": "b",
                     "fragment/geo/x.usdc": "x", "fragment/look/y.usda": "y", "fragment/top.usda": "t"})  # fmt: skip
    pin = _pin(tmp_path)
    assert list(pin) == [".", "entity", "entry.usda", "fragment", "fragment/geo", "fragment/look"]
    assert pin["."][1] == "6" and pin["entity"][1] == "2" and pin["fragment"][1] == "1"  # fragment/ itself: top.usda


def test_a_change_reaches_only_its_subtree_and_the_root(tmp_path: Path) -> None:
    _tree(tmp_path, {"entry.usda": "e", "fragment/geo/x.usdc": "x", "fragment/look/y.usda": "y"})
    before = alab_checksums.subtrees(alab_checksums.manifest(tmp_path))
    assert alab_checksums.differences(before, before) == []

    (tmp_path / "fragment/geo/x.usdc").rename(tmp_path / "fragment/geo/z.usdc")  # same bytes, new path
    (tmp_path / "fragment/look/y.usda").unlink()
    _tree(tmp_path, {"fragment/texture/t.exr": "t"})
    after = alab_checksums.subtrees(alab_checksums.manifest(tmp_path))
    assert alab_checksums.differences(before, after) == [
        "missing: fragment/look",
        "added: fragment/texture",
        "changed: .",
        "changed: fragment/geo",
    ]


@pytest.mark.alab
def test_committed_alab_files_match_the_tree() -> None:
    root = Path(os.environ["PROSCENIUM_ALAB_ROOT"])
    pin = alab_checksums.subtrees(alab_checksums.manifest(root))
    assert alab_checksums.differences(alab_checksums.PIN.read_text(encoding="utf-8"), pin) == []
    current = alab_inventory.summary(alab_inventory.inventories(root / "entry.usda"))
    assert current == alab_inventory.SUMMARY.read_text(encoding="utf-8"), "run tools/alab_inventory.py"
