"""Run the feasibility probes inside one runtime and write JSON results.

Usage, from either runtime:
    python probe_main.py <out.json> [topic ...]
    blender -b --factory-startup --python probe_main.py -- <out.json> [topic ...]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TOPICS = ["env", "exchange", "handlers", "undo", "inmemory", "layers", "disk_view", "packaging"]


def main(argv: list[str]) -> int:
    import importlib

    out = Path(argv[0])
    topics = argv[1:] or TOPICS
    results = []
    for topic in topics:
        try:
            results.append(importlib.import_module(f"probe_{topic}").run())
        except Exception:  # noqa: BLE001 - a crashing probe is itself a finding
            results.append({"topic": topic, "crashed": traceback.format_exc()})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


def _argv() -> list[str]:
    # Blender passes script arguments after "--".
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]


if __name__ == "__main__":
    sys.exit(main(_argv()))
