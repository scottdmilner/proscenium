"""The application layer reads no USD (APP-08): its modules import nothing that reaches a stage.

Imports are read from each module's source with ast, without importing it. Imports under `if TYPE_CHECKING:` are
skipped, since they name types only: the plan's type is the core's.
"""

from __future__ import annotations

import ast
from pathlib import Path

import proscenium

SYNCHRONIZATION = Path(proscenium.__file__).parent / "synchronization"
APPLICATION_MODULES = ("application",)  # the application layer's, in synchronization/
# What reaches a stage: USD itself, the compiled core that captures one, and the binding's stages.
STAGE_READERS = ("pxr", "proscenium.core", "proscenium.binding.source_access")


def _runtime_imports(path: Path, package: list[str]) -> list[tuple[int, str]]:
    """Each module path, in package, imports when it runs, with its line; relative imports resolved."""
    found = []

    def visit(statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                visit(node.orelse)
            elif isinstance(node, ast.Import):
                found.extend((node.lineno, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = package[: len(package) - node.level + 1] if node.level else []
                target = ".".join([*base, *([node.module] if node.module else [])])
                found.extend((node.lineno, f"{target}.{alias.name}") for alias in node.names)
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):
                    visit([s for s in getattr(node, field, []) if isinstance(s, ast.stmt | ast.ExceptHandler)])

    visit(ast.parse(path.read_text(), str(path)).body)
    return found


def test_the_application_layer_imports_nothing_that_reads_a_stage() -> None:
    found = [
        f"{name}.py:{line} imports {imported}"
        for name in APPLICATION_MODULES
        for line, imported in _runtime_imports(SYNCHRONIZATION / f"{name}.py", ["proscenium", "synchronization"])
        if any(imported == reader or imported.startswith(f"{reader}.") for reader in STAGE_READERS)
    ]
    assert not found, "\n".join(found)


def test_the_check_finds_a_stage_reader(tmp_path: Path) -> None:
    # The check itself: each way of importing one is found, and a type-only import isn't.
    module = tmp_path / "module.py"
    module.write_text(
        "from typing import TYPE_CHECKING\n"
        "import pxr.Usd\n"
        "from pxr import Sdf\n"
        "if TYPE_CHECKING:\n"
        "    from pxr import Gf\n"
        "def f() -> None:\n"
        "    from pxr import Vt\n"
        "from ..core import _core\n"
    )
    found = [name for _, name in _runtime_imports(module, ["proscenium", "synchronization"])]
    assert found == ["typing.TYPE_CHECKING", "pxr.Usd", "pxr.Sdf", "pxr.Vt", "proscenium.core._core"]
