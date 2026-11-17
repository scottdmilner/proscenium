"""Build the bridge module and audit its USD linkage for this platform (tools/native_build.py)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from native_build import HYDRA_BRIDGE, build_module  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HYDRA_BRIDGE.out_dir)
    parser.add_argument("--usd-library", type=Path, help="libusd_ms to link (macOS/Linux; default: the bpy wheel's)")
    args = parser.parse_args()
    built = build_module(replace(HYDRA_BRIDGE, out_dir=args.out.resolve()), args.usd_library)
    (built.module_path.parent / "build.json").write_text(json.dumps(built.build_manifest, indent=2) + "\n")
    print(json.dumps({k: v for k, v in built.build_manifest.items() if k not in {"imports", "linkage"}}, indent=2))


if __name__ == "__main__":
    main()
