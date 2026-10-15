"""Build the module with CMake and Ninja from the dev group, and audit its USD linkage for this platform."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Any

from prepare_deps import LIBS, Platform, blender_version, current_platform, prepare, release

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
# The dev group's cmake and ninja, installed beside this interpreter.
SCRIPTS = Path(sysconfig.get_path("scripts"))

# Blender 5.2.2's usd_ms.dll was linked with MSVC 14.44; the CRT it ships must cover our toolset.
MSVC_TOOLSET = "14.44"
MAX_MSVC_LINKER = (14, 44)
# manylinux_2_28, which matches the glibc 2.28 floor of Blender's Linux libraries.
MAX_GLIBC = (2, 28)
MAX_GLIBCXX = (3, 4, 25)
MACOS_MIN = "11.2"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge")
    parser.add_argument("--usd-library", type=Path, help="libusd_ms to link (macOS/Linux; default: the bpy wheel's)")
    args = parser.parse_args()
    key = current_platform()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    blender = release()
    _check_installed_bpy(blender)
    deps = prepare(key)
    build = out.with_name(out.name + "-cmake")  # beside out, which holds only results
    command = [
        _tool("cmake"), "-S", str(HERE), "-B", str(build), "-G", "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={_tool('ninja')}",
        "-DCMAKE_BUILD_TYPE=Release",
        # Configures for this interpreter's SOABI; the headers come from Blender's lib repo.
        f"-DPython_EXECUTABLE={sys.executable}",
    ]  # fmt: skip
    if key != Platform.WINDOWS_X64:
        usd_library = (args.usd_library or _wheel_usd_library(key)).resolve()
        command.append(f"-DUSD_LIBRARY={usd_library}")
    env = _build_env(key)
    subprocess.run(command, check=True, env=env)
    subprocess.run([command[0], "--build", str(build)], check=True, env=env)
    with tempfile.TemporaryDirectory(prefix="hydra-bridge-install-") as tmp:
        subprocess.run([command[0], "--install", str(build), "--prefix", tmp], check=True, env=env)
        module = _take_module(Path(tmp), out)
    audits = {
        Platform.MACOS_ARM64: _audit_macos,
        Platform.LINUX_X64: _audit_linux,
        Platform.WINDOWS_X64: _audit_windows,
    }
    audit = audits[key](module)
    manifest = {
        "platform": key,
        "blender_tag": blender["tag"],
        "blender_commit": blender["commit"],
        "dependency_repo": LIBS[key].repo,
        "dependency_revision": _git(deps, "rev-parse", "HEAD"),
        "command": command,
        "module": str(module),
        **audit,
    }
    (out / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k not in {"imports", "linkage"}}, indent=2))


def _check_installed_bpy(blender: dict[str, str]) -> None:
    """The installed bpy wheel must be the locked release, read from its metadata."""
    installed = importlib.metadata.version("bpy")
    if installed != blender_version():
        raise RuntimeError(f"The installed bpy is {installed}, not the locked {blender['tag']}; run uv sync")


def _tool(name: str) -> str:
    found = shutil.which(name, path=str(SCRIPTS))
    if found is None:
        raise RuntimeError(f"{name} not found in {SCRIPTS}; run uv sync")
    return found


def _build_env(key: Platform) -> dict[str, str]:
    if key == Platform.WINDOWS_X64:
        # Ninja uses the compiler from this environment; the Visual Studio generator would pick its own.
        return _msvc_env()
    # CMakeLists.txt sets the macOS deployment target; the environment variable would override it.
    return {k: v for k, v in os.environ.items() if k != "MACOSX_DEPLOYMENT_TARGET"}


def _msvc_env() -> dict[str, str]:
    """The pinned MSVC toolset's developer environment, from Microsoft's vswhere and vcvarsall."""
    if os.environ.get("VCToolsVersion", "").startswith(MSVC_TOOLSET + "."):
        return dict(os.environ)  # already in a developer prompt for the pinned toolset
    program_files = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise RuntimeError(f"vswhere not found at {vswhere}: install Visual Studio or its Build Tools")
    installs = subprocess.check_output(
        [str(vswhere), "-all", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
         "-property", "installationPath"],
        text=True,
    ).splitlines()  # fmt: skip
    marker = "__HYDRA_BRIDGE_ENV__"
    for install in installs:
        vcvars = Path(install) / "VC/Auxiliary/Build/vcvarsall.bat"
        # vcvarsall fails, and `&&` stops, when this installation lacks the toolset.
        result = subprocess.run(
            f'"{vcvars}" x64 -vcvars_ver={MSVC_TOOLSET} >nul && echo {marker} && set',
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and marker in result.stdout:
            lines = result.stdout.split(marker, 1)[1].splitlines()
            env = dict(line.split("=", 1) for line in lines if "=" in line)
            if env.get("VCToolsVersion", "").startswith(MSVC_TOOLSET + "."):
                return env
    raise RuntimeError(f"No Visual Studio installation provides MSVC toolset {MSVC_TOOLSET}: {installs}")


def _wheel_usd_library(key: Platform) -> Path:
    # Found without importing bpy, which would load USD into the build process.
    spec = importlib.util.find_spec("bpy")
    if spec is None or spec.origin is None:
        raise RuntimeError("The bpy wheel is not installed; run uv sync or pass --usd-library")
    name = "libusd_ms.dylib" if key == Platform.MACOS_ARM64 else "libusd_ms.so"
    library = Path(spec.origin).parent / "lib" / name
    if not library.is_file():
        raise RuntimeError(f"Blender's USD library is missing from the bpy wheel: {library}")
    return library


def _take_module(installed: Path, out: Path) -> Path:
    """Move the installed module into out; the install must hold only the module, no USD or other library."""
    files = [p for p in installed.rglob("*") if p.is_file()]
    if len(files) != 1 or files[0].parent != installed or not files[0].name.startswith("_hydra_bridge."):
        raise RuntimeError(f"Expected only a top-level bridge module in the install, found {files}")
    for stale in out.glob("_hydra_bridge.*"):
        stale.unlink()
    return Path(shutil.move(files[0], out / files[0].name))


def _audit_macos(module: Path) -> dict[str, Any]:
    linkage = _run("otool", "-L", str(module))
    load_commands = _run("otool", "-l", str(module))
    imports = _run("nm", "-m", "-u", str(module))
    usd_imports = [line for line in imports.splitlines() if "pxrBlender" in line]
    if not usd_imports or any("(from libusd_ms)" not in line for line in usd_imports):
        raise RuntimeError("USD symbols must bind to libusd_ms, not dynamic lookup")
    if "@rpath/libusd_ms.dylib" not in linkage:
        raise RuntimeError("The module must load USD through @rpath/libusd_ms.dylib")
    if "LC_RPATH" in load_commands:
        raise RuntimeError("The module must not embed an rpath")
    minos = re.findall(r"minos (\S+)", load_commands)
    if minos != [MACOS_MIN]:
        raise RuntimeError(f"Expected minimum macOS {MACOS_MIN}, found {minos}")
    return {"linkage": linkage, "usd_import_count": len(usd_imports), "minos": minos[0], "imports": imports}


def _audit_linux(module: Path) -> dict[str, Any]:
    dynamic = _run("readelf", "-d", str(module))
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", dynamic)
    if "libusd_ms.so" not in needed:
        raise RuntimeError(f"The module must need libusd_ms.so, found {needed}")
    if "RPATH" in dynamic or "RUNPATH" in dynamic:
        raise RuntimeError("The module must not embed an rpath or runpath")
    if any(name.startswith("libpython") for name in needed):
        raise RuntimeError("The module must not link libpython; Blender provides Python symbols")
    symbols = _run("objdump", "-T", str(module))
    usd_imports = [line for line in symbols.splitlines() if "*UND*" in line and "pxrBlender" in line]
    if not usd_imports:
        raise RuntimeError("Expected undefined pxrBlender symbols resolved from libusd_ms.so")
    glibc = _max_version(symbols, "GLIBC")
    glibcxx = _max_version(symbols, "GLIBCXX")
    if glibc > MAX_GLIBC or glibcxx > MAX_GLIBCXX:
        raise RuntimeError(f"Symbol versions too new for Blender's floor: GLIBC {glibc}, GLIBCXX {glibcxx}")
    return {
        "needed": needed,
        "usd_import_count": len(usd_imports),
        "max_glibc": ".".join(map(str, glibc)),
        "max_glibcxx": ".".join(map(str, glibcxx)),
        "linkage": dynamic,
    }


def _audit_windows(module: Path) -> dict[str, Any]:
    env = _msvc_env()
    dependents = _run("dumpbin", "/nologo", "/dependents", str(module), env=env)
    dlls = sorted({m.lower() for m in re.findall(r"^\s+(\S+\.dll)\s*$", dependents, re.MULTILINE | re.IGNORECASE)})
    for required in ("usd_ms.dll", "python313.dll"):
        if required not in dlls:
            raise RuntimeError(f"The module must import {required}, found {dlls}")
    debug = [d for d in dlls if re.search(r"(msvcp\d+d|vcruntime\d+d|ucrtbased|_debug)\.dll$", d)]
    if debug:
        raise RuntimeError(f"Debug runtime imports found; build Release with /MD: {debug}")
    headers = _run("dumpbin", "/nologo", "/headers", str(module), env=env)
    match = re.search(r"(\d+)\.(\d+) linker version", headers)
    if match is None:
        raise RuntimeError("Linker version not found in dumpbin /headers")
    linker = (int(match.group(1)), int(match.group(2)))
    if linker > MAX_MSVC_LINKER:
        raise RuntimeError(f"Linker {linker} is newer than Blender's CRT supports {MAX_MSVC_LINKER}")
    return {
        "dependents": dlls,
        "linker_version": f"{linker[0]}.{linker[1]}",
        "msvc_tools_version": env.get("VCToolsVersion", ""),
        "linkage": dependents,
    }


def _max_version(symbols: str, prefix: str) -> tuple[int, ...]:
    found = [tuple(map(int, v.split("."))) for v in re.findall(rf"\b{prefix}_([\d.]+)\b", symbols)]
    return max(found, default=(0,))


def _run(*command: str, env: dict[str, str] | None = None) -> str:
    # Resolve the program on the given environment's PATH: dumpbin lives in the toolset's bin directory.
    # Windows' `set` spells it "Path".
    path = (env.get("PATH") or env.get("Path")) if env is not None else None
    program = shutil.which(command[0], path=path) or command[0]
    return subprocess.check_output([program, *command[1:]], text=True, env=env)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


if __name__ == "__main__":
    main()
