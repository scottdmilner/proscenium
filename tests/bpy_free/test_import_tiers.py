"""Each tier imports only the tiers below it (docs/plans/source-tiers-and-names.md#tiers, AGENTS.md#layout).

Imports are read from each module's source with ast, without importing it, so type-only imports count too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import proscenium

PACKAGE = Path(proscenium.__file__).parent

# What each tier may import from proscenium; modules at the package's top level, such as addon, may import any.
ALLOWED = {
    "core": {"core"},
    "persistence": {"persistence", "core"},
    "runtime": {"runtime", "persistence", "core"},
    "api": {"api", "runtime", "persistence", "core"},
}


def _module_name(path: Path) -> list[str]:
    parts = ["proscenium", *path.relative_to(PACKAGE).with_suffix("").parts]
    return parts[:-1] if parts[-1] == "__init__" else parts


def _imported(path: Path) -> list[tuple[int, str]]:
    """The proscenium modules path imports, with their line numbers, relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module[:-1]
    found = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            target = ".".join([*base, *([node.module] if node.module else [])])
            if node.module:
                found.append((node.lineno, target))
            else:  # "from . import x" names submodules
                found += [(node.lineno, f"{target}.{alias.name}") for alias in node.names]
    return [(line, name) for line, name in found if name.split(".")[0] == "proscenium"]


def _violations(path: Path, tier: str) -> list[str]:
    allowed = ALLOWED[tier]
    return [
        f"{path.relative_to(PACKAGE)}:{line} imports {name}"
        for line, name in _imported(path)
        if len(name.split(".")) > 1 and name.split(".")[1] not in allowed
    ]


def _tier(path: Path) -> str | None:
    parts = path.relative_to(PACKAGE).parts
    return parts[0] if len(parts) > 1 and parts[0] in ALLOWED else None


def test_tiers_import_only_below() -> None:
    found = [v for path in sorted(PACKAGE.rglob("*.py")) if (tier := _tier(path)) for v in _violations(path, tier)]
    assert not found, "\n".join(found)


def test_every_module_is_in_a_tier_or_at_the_top() -> None:
    # A new subpackage gets a row in ALLOWED, so the test above checks it.
    stray = [p for p in PACKAGE.rglob("*.py") if len(p.relative_to(PACKAGE).parts) > 1 and _tier(p) is None]
    assert not stray, stray


def test_a_wrong_way_import_is_found() -> None:
    # Guards the tests above: the API module, read as if it were in persistence, imports above that tier.
    api = PACKAGE / "api" / "synchronization.py"
    assert any("imports proscenium.runtime" in v for v in _violations(api, "persistence"))
