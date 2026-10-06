"""Run the feasibility probes in every available runtime and summarize.

    uv run python tools/feasibility/run_all.py [--out build/feasibility]

Runtimes:
- wheel:         the bpy wheel in the uv environment
- wheel-pytest:  the same, inside a pytest session
- binary:        the Blender binary (BLENDER env var or platform default), plus a
                 comparison of `blender --command extension build` with the
                 wheel's standalone CLI

Each runtime gets an isolated BLENDER_USER_RESOURCES so probes never touch the
real user configuration. Set PROSCENIUM_ALAB_ROOT to include the ALab check.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parents[1]

sys.path.insert(0, str(HERE.parent))  # tools/, for blender_paths
from blender_paths import find_blender, wheel_extension_cli  # noqa: E402


def _env(user_dir: Path) -> dict[str, str]:
    return {**os.environ, "BLENDER_USER_RESOURCES": str(user_dir), "PYTHONPATH": str(HERE)}


def run_runtime(name: str, out: Path, blender: str | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="proscenium-user-") as user_dir:
        env = _env(Path(user_dir))
        if name == "wheel":
            cmd = [sys.executable, str(HERE / "probe_main.py"), str(out)]
        elif name == "wheel-pytest":
            env["PROSCENIUM_FEASIBILITY_OUT"] = str(out)
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(HERE / "test_under_pytest.py")]
        else:
            assert blender
            cmd = [
                blender,
                "-b",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python",
                str(HERE / "probe_main.py"),
                "--",
                str(out),
            ]
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    return {"runtime": name, "returncode": proc.returncode, "log_tail": (proc.stdout + proc.stderr)[-3000:]}


def compare_binary_cli(blender: str) -> dict[str, Any]:
    """Build the probe extension with both CLIs and compare the archives."""
    sys.path.insert(0, str(HERE))
    with tempfile.TemporaryDirectory(prefix="proscenium-cli-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "src"
        _prepare_source(src)
        results: dict[str, Any] = {}
        for label, prefix in {
            "binary": [blender, "--factory-startup", "--command", "extension"],
            "wheel": [sys.executable, str(wheel_extension_cli())],
        }.items():
            dist = tmp_path / label
            dist.mkdir()
            validate = subprocess.run([*prefix, "validate", str(src)], capture_output=True, text=True, check=False)
            build = subprocess.run(
                [*prefix, "build", "--source-dir", str(src), "--output-dir", str(dist)],
                capture_output=True,
                text=True,
                check=False,
            )
            archives = sorted(dist.glob("*.zip"))
            results[label] = {
                "validate_returncode": validate.returncode,
                "build_returncode": build.returncode,
                "archives": [a.name for a in archives],
                "contents": {
                    n: zipfile.ZipFile(archives[0]).read(n).decode() for n in zipfile.ZipFile(archives[0]).namelist()
                }
                if archives
                else {},
            }
        results["identical_archive_contents"] = results["binary"]["contents"] == results["wheel"]["contents"]
        for label in ("binary", "wheel"):
            results[label]["files"] = sorted(results[label].pop("contents"))
        return results


def _prepare_source(dest: Path) -> None:
    from probe_packaging import prepare_source

    prepare_source(dest)


def summarize(path: Path) -> list[str]:
    lines = []
    for topic in json.loads(path.read_text()):
        if "crashed" in topic:
            lines.append(f"  {topic['topic']}: CRASHED")
            continue
        bad = [c["name"] for c in topic["checks"] if c["status"] != "pass"]
        lines.append(
            f"  {topic['topic']}: {len(topic['checks']) - len(bad)}/{len(topic['checks'])} pass"
            + (f"; not passing: {bad}" if bad else "")
        )
    return lines


def all_pass(path: Path) -> bool:
    topics = json.loads(path.read_text())
    return all("crashed" not in t and all(c["status"] == "pass" for c in t["checks"]) for t in topics)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "feasibility")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 unless every check passes in every runtime, including the binary (for CI)",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    plat = f"{platform.system().lower()}-{platform.machine().lower()}"
    blender = find_blender()
    runtimes = ["wheel", "wheel-pytest"] + (["binary"] if blender else [])
    meta: dict[str, Any] = {"platform": plat, "blender": blender, "runs": []}
    ok = True
    for name in runtimes:
        out = args.out / f"{plat}-{name}.json"
        out.unlink(missing_ok=True)
        run = run_runtime(name, out, blender)
        meta["runs"].append(run)
        print(f"{name}: exit {run['returncode']}")
        if out.exists():
            print("\n".join(summarize(out)))
            ok = ok and (all_pass(out) or not args.strict)
        else:
            ok = False
            print(run["log_tail"])
    if blender:
        meta["cli_comparison"] = compare_binary_cli(blender)
        print("cli comparison: identical archives =", meta["cli_comparison"]["identical_archive_contents"])
        ok = ok and (meta["cli_comparison"]["identical_archive_contents"] or not args.strict)
    else:
        print("binary: skipped (no Blender found; set BLENDER)")
        ok = ok and not args.strict
    (args.out / f"{plat}-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
