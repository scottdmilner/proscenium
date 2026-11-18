"""The import-linter contracts' lists of Blender's modules are one list, written in each contract (packages/README.md).

TOML can't share a list between files, so every forbidden contract on Blender's modules repeats it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _blender_module_lists_by_contract() -> dict[str, list[str]]:
    """Each forbidden contract on Blender's modules (those that forbid bpy), by file and name, and its list."""
    lists_by_contract: dict[str, list[str]] = {}
    for configuration_path in (ROOT / "pyproject.toml", *sorted((ROOT / "packages").glob("*/pyproject.toml"))):
        configuration = tomllib.loads(configuration_path.read_text(encoding="utf-8"))
        for contract in configuration.get("tool", {}).get("importlinter", {}).get("contracts", []):
            if contract["type"] == "forbidden" and "bpy" in contract["forbidden_modules"]:
                key = f"{configuration_path.relative_to(ROOT)}: {contract['name']}"
                lists_by_contract[key] = contract["forbidden_modules"]
    return lists_by_contract


def test_blender_module_lists_are_equal() -> None:
    lists_by_contract = _blender_module_lists_by_contract()
    assert lists_by_contract, "no contract forbids Blender's modules"
    first_key, first_list = next(iter(lists_by_contract.items()))
    for key, module_list in lists_by_contract.items():
        assert sorted(module_list) == sorted(first_list), f"{key} lists other Blender modules than {first_key}"
