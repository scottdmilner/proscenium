"""Shared helpers for runtime feasibility probes.

Probes record two kinds of evidence:
- checks: a behavior later milestones depend on, with an expected value.
- facts: observations recorded as-is (versions, paths, undocumented behavior).
"""

from __future__ import annotations

import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = [jsonable(v) for v in value]
        return sorted(items, key=str) if isinstance(value, set | frozenset) else items
    if isinstance(value, Path):
        return str(value)
    return repr(value)


class Probe:
    """Collects checks and facts for one topic."""

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.checks: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}
        self._tmp = tempfile.TemporaryDirectory(prefix=f"proscenium-{topic}-")
        self.tmp = Path(self._tmp.name)

    def check(self, name: str, fn: Callable[[], Any], expect: Any = True) -> Any:
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 - probes record every failure
            self.checks.append(_error(name, exc))
            return None
        status = "pass" if value == expect else "fail"
        self.checks.append(
            {
                "name": name,
                "status": status,
                "value": jsonable(value),
                "expected": jsonable(expect),
            }
        )
        return value

    def fact(self, name: str, fn: Callable[[], Any]) -> Any:
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001
            self.facts[name] = {"error": f"{type(exc).__name__}: {exc}"}
            return None
        self.facts[name] = jsonable(value)
        return value

    def result(self) -> dict[str, Any]:
        self._tmp.cleanup()
        return {"topic": self.topic, "checks": self.checks, "facts": self.facts}


def _error(name: str, exc: BaseException) -> dict[str, Any]:
    return {
        "name": name,
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(limit=6),
    }


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
