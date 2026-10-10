"""The built extension zip installs, registers on enable, and unregisters on disable.

Built from src/proscenium in check mode (sync=False), which only reads the source dir,
so the test never writes into the repository and workers can build concurrently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from build_extension import ROOT, build

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


@pytest.fixture(scope="session")
def extension_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The extension built by tools/build_extension.py into a temporary dir, without touching src/."""
    return build(ROOT / "src" / "proscenium", tmp_path_factory.mktemp("dist"), sync=False)


def test_install_enable_disable(runtime: Runtime, extension_zip: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    result = run_isolated(
        runtime,
        BODIES / "extension.py",
        "install_enable_disable",
        tmp_path,
        archive=str(extension_zip),
        repo_dir=str(repo),
    )
    assert repo in Path(result["module_file"]).parents  # the installed copy, not src/
    assert result["enabled_after_install"]
    assert result["registered_after_install"]
    assert not result["enabled_after_disable"]
    assert not result["registered_after_disable"]
