"""Run the same compiled module in the bpy wheel and installed Blender."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from blender_paths import find_blender  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE.parents[2] / "build/hydra-bridge")
    parser.add_argument(
        "--blender", default=find_blender(), help="Blender binary (default: BLENDER or the platform default)"
    )
    args = parser.parse_args()
    if not args.blender:
        parser.error("no Blender binary found: set BLENDER or pass --blender")
    out = args.out.resolve()
    passed = True
    for runtime, prefix in (
        ("wheel", [sys.executable, str(HERE / "probe.py")]),
        (
            "binary",
            [
                args.blender,
                "--background",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python",
                str(HERE / "probe.py"),
                "--",
            ],
        ),
    ):
        result_path = out / f"{runtime}.json"
        result_path.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="hydra-bridge-user-") as user_dir:
            env = {**os.environ, "BLENDER_USER_RESOURCES": user_dir}
            command = [*prefix, str(out), str(result_path)]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=300, check=False)
        (out / f"{runtime}.log").write_text(result.stdout + result.stderr)
        (out / f"{runtime}-process.json").write_text(
            json.dumps({"command": command, "returncode": result.returncode}, indent=2) + "\n"
        )
        print(f"{runtime}: exit {result.returncode}")
        print((result.stdout + result.stderr)[-5000:])
        passed = passed and result.returncode == 0 and result_path.exists()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
