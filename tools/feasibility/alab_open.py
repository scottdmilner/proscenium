"""Open ALab once in a fresh process, for probe_disk_view's timing comparison.

    python alab_open.py <normal|view> <entry.usda> <out.json>

Runs without bpy, so the in-process layer registry starts empty for each open.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main(mode: str, entry: Path, out: Path) -> None:
    from pxr import Usd

    import probe_disk_view

    start = time.perf_counter()
    if mode == "view":
        stage = probe_disk_view._anonymous_view(entry)  # noqa: SLF001
        layers = len(stage._proscenium_copies)  # noqa: SLF001
    else:
        stage = probe_disk_view._open(str(entry))  # noqa: SLF001
        layers = len(stage.GetUsedLayers())
    seconds = time.perf_counter() - start
    prims = Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate))
    result = {
        "seconds": seconds,
        "layers": layers,
        "inventory": {str(prim.GetPath()): str(prim.GetTypeName()) for prim in prims},
        "unresolved": sorted(probe_disk_view._UNRESOLVED),  # noqa: SLF001
    }
    out.write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
