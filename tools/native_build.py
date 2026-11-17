"""Build a Python module against Blender's USD with CMake and Ninja from the dev group, and audit its linkage.

The repository's compiled modules are here: the planner, which proscenium_sync's build hook and
build_extension.py build through sync_module, and the feasibility bridge (feasibility/hydra_bridge/build.py).
clang_tidy.py checks both with their builds' compile commands. The CMake project receives BLENDER_DEPS, the headers
of the locked Blender release (blender_deps.py), and on macOS and Linux USD_LIBRARY, the bpy wheel's libusd_ms to
link. Each platform's audit checks that the module binds only to Blender's usd_ms and loads wherever that Blender
does.
"""

from __future__ import annotations

import hashlib
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from blender_deps import (
    LIBS,
    Platform,
    blender_version,
    current_platform,
    deps_dir,
    ensure_dependency_checkout,
    release,
)
from blender_release import blender_tag

ROOT = Path(__file__).resolve().parents[1]
# The dev group's cmake and ninja, installed beside this interpreter.
SCRIPTS = Path(sysconfig.get_path("scripts"))

# Blender 5.2.2's usd_ms.dll was linked with MSVC 14.44; the CRT it ships must cover our toolset.
MSVC_TOOLSET = "14.44"
MAX_MSVC_LINKER = (14, 44)
# manylinux_2_28, which matches the glibc 2.28 floor of Blender's Linux libraries.
MAX_GLIBC = (2, 28)
MAX_GLIBCXX = (3, 4, 25)
MACOS_MIN = "11.2"


@dataclass(frozen=True)
class NativeModule:
    """A compiled module: its CMake project, and the directory its builds go to."""

    name: str  # the module's name before its extension suffix, as its CMake project installs it
    source_dir: Path  # the CMake project
    out_dir: Path  # the build's results: the built module and its build record

    @property
    def cmake_dir(self) -> Path:
        """The CMake build directory: beside out_dir, which holds only results."""
        return self.out_dir.with_name(self.out_dir.name + "-cmake")


PLANNER = NativeModule(
    "_planner", ROOT / "packages/proscenium_sync/src/proscenium_sync/planner", ROOT / "build/planner"
)
HYDRA_BRIDGE = NativeModule("_hydra_bridge", ROOT / "tools/feasibility/hydra_bridge", ROOT / "build/hydra-bridge")
# What sync_module hashes to tell whether a module is current: its project's sources, and these build tools.
SOURCE_PATTERNS = ("*.cpp", "*.h", "CMakeLists.txt")
BUILD_TOOLS = (Path(__file__), Path(__file__).with_name("blender_deps.py"))


def wheel_tag() -> str:
    """The tag of a wheel holding a module built here: this interpreter's, and the floor the linkage audit holds to."""
    python = f"cp{sys.version_info.major}{sys.version_info.minor}"
    platform = {
        Platform.MACOS_ARM64: f"macosx_{MACOS_MIN.split('.')[0]}_0_arm64",  # tags spell macOS 11 and later as N_0
        Platform.LINUX_X64: f"manylinux_{MAX_GLIBC[0]}_{MAX_GLIBC[1]}_x86_64",
        Platform.WINDOWS_X64: "win_amd64",
    }[current_platform()]
    return f"{python}-{python}-{platform}"


def sync_module(module: NativeModule, *, write: bool = True) -> Path:
    """Build the module into its source directory, where its package imports it, unless it's current; returns it.

    It's current when its build record (out_dir/build.json) names this platform, the locked Blender release, the hash
    of its sources and the build tools, and the module's own hash. With write=False nothing is built: it fails unless
    the module is already current.
    """
    inputs = _build_inputs(module.source_dir)
    current = _current_module(module, inputs)
    if current is not None:
        return current
    if not write:
        raise SystemExit(f"{module.source_dir}: {module.name} is missing or out of date; run tools/build_extension.py")
    built = build_module(module)
    for stale in _installed_modules(module):
        stale.unlink()
    installed = Path(shutil.copy2(built.module_path, module.source_dir / built.module_path.name))
    build = {k: v for k, v in built.build_manifest.items() if k not in {"imports", "linkage"}}
    record = {**inputs, "module_sha256": _sha256(installed), "build": build}
    (module.out_dir / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"built {installed}")
    return installed


def _build_inputs(source_dir: Path) -> dict[str, Any]:
    sources = hashlib.sha256()
    files = {p for pattern in SOURCE_PATTERNS for p in source_dir.rglob(pattern)}
    for path in sorted(files, key=lambda p: p.relative_to(source_dir).as_posix()):
        sources.update(path.relative_to(source_dir).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    for path in BUILD_TOOLS:
        sources.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return {"platform": str(current_platform()), "blender_tag": blender_tag(), "sources_sha256": sources.hexdigest()}


def _current_module(module: NativeModule, inputs: dict[str, Any]) -> Path | None:
    """The module installed in its source directory, if its build record matches inputs and the module itself."""
    record = module.out_dir / "build.json"
    if not record.is_file():
        return None
    recorded = json.loads(record.read_text(encoding="utf-8"))
    installed = _installed_modules(module)
    if any(recorded.get(k) != v for k, v in inputs.items()) or len(installed) != 1:
        return None
    return installed[0] if _sha256(installed[0]) == recorded.get("module_sha256") else None


def _installed_modules(module: NativeModule) -> list[Path]:
    return sorted(p for p in module.source_dir.glob(f"{module.name}.*") if p.suffix in {".so", ".pyd"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class NativeModuleBuildResult:
    """The native module's output path and build and linkage-audit manifest."""

    module_path: Path  # the module, moved into the output directory
    build_manifest: dict[str, Any]  # platform, Blender release, dependency revision, command, and audit


def build_module(module: NativeModule, usd_library: Path | None = None) -> NativeModuleBuildResult:
    """Configure, build, and install the module's CMake project, then move the module into its out_dir and audit it."""
    key = current_platform()
    module.out_dir.mkdir(parents=True, exist_ok=True)
    blender = release()
    command = configure(module, usd_library)
    deps = deps_dir(key)
    env = build_env(key)
    subprocess.run([command[0], "--build", str(module.cmake_dir)], check=True, env=env)
    with tempfile.TemporaryDirectory(prefix=f"{module.name}-install-") as tmp:
        subprocess.run([command[0], "--install", str(module.cmake_dir), "--prefix", tmp], check=True, env=env)
        built = _take_module(Path(tmp), module.out_dir, module.name)
    audits = {
        Platform.MACOS_ARM64: _audit_macos,
        Platform.LINUX_X64: _audit_linux,
        Platform.WINDOWS_X64: _audit_windows,
    }
    manifest = {
        "platform": key,
        "blender_tag": blender["tag"],
        "blender_commit": blender["commit"],
        "dependency_repo": LIBS[key].repository_name,
        "dependency_revision": _git(deps, "rev-parse", "HEAD"),
        "command": command,
        "module": str(built),
        **audits[key](built),
    }
    return NativeModuleBuildResult(built, manifest)


def configure(module: NativeModule, usd_library: Path | None = None) -> list[str]:
    """Configure the module's CMake project in its cmake_dir, and return the command.

    Also writes compile_commands.json there, which clang-tidy reads (tools/clang_tidy.py).
    """
    source, build = module.source_dir, module.cmake_dir
    key = current_platform()
    _check_installed_bpy(release())
    deps = ensure_dependency_checkout(key)
    command = [
        tool("cmake"), "-S", str(source), "-B", str(build), "-G", "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={tool('ninja')}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        # Configures for this interpreter's SOABI; the headers come from Blender's lib repo.
        f"-DPython_EXECUTABLE={sys.executable}",
        f"-DBLENDER_DEPS={deps.as_posix()}",
    ]  # fmt: skip
    if key != Platform.WINDOWS_X64:
        command.append(f"-DUSD_LIBRARY={(usd_library or _wheel_usd_library(key)).resolve()}")
    if _cached_source(build) not in (None, source.resolve()):
        command.append("--fresh")  # CMake refuses a cache made from another source directory, as before a move
    subprocess.run(command, check=True, env=build_env(key))
    return command


def _cached_source(build: Path) -> Path | None:
    """The source directory build's CMake cache was made from, if it has one."""
    cache = build / "CMakeCache.txt"
    text = cache.read_text(encoding="utf-8", errors="replace") if cache.is_file() else ""
    found = re.search(r"^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$", text, re.MULTILINE)
    return Path(found.group(1)).resolve() if found else None


def _check_installed_bpy(blender: dict[str, str]) -> None:
    """The installed bpy wheel must be the locked release, read from its metadata."""
    installed = importlib.metadata.version("bpy")
    if installed != blender_version():
        raise RuntimeError(f"The installed bpy is {installed}, not the locked {blender['tag']}; run uv sync")


def tool(name: str) -> str:
    """A dev-group tool installed beside this interpreter."""
    found = shutil.which(name, path=str(SCRIPTS))
    if found is None:
        raise RuntimeError(f"{name} not found in {SCRIPTS}; run uv sync")
    return found


def build_env(key: Platform) -> dict[str, str]:
    """The environment the platform's native build runs in."""
    if key == Platform.WINDOWS_X64:
        # Ninja uses the compiler from this environment; the Visual Studio generator would pick its own.
        return msvc_env()
    # The CMake project sets the macOS deployment target; the environment variable would override it.
    return {k: v for k, v in os.environ.items() if k != "MACOSX_DEPLOYMENT_TARGET"}


def msvc_env() -> dict[str, str]:
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
    marker = "__NATIVE_BUILD_ENV__"
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
        raise RuntimeError("The bpy wheel is not installed; run uv sync or pass a USD library")
    name = "libusd_ms.dylib" if key == Platform.MACOS_ARM64 else "libusd_ms.so"
    library = Path(spec.origin).parent / "lib" / name
    if not library.is_file():
        raise RuntimeError(f"Blender's USD library is missing from the bpy wheel: {library}")
    return library


def _take_module(installed: Path, out: Path, name: str) -> Path:
    """Move the installed module into out; the install must hold only the module, no USD or other library."""
    files = [p for p in installed.rglob("*") if p.is_file()]
    if len(files) != 1 or files[0].parent != installed or not files[0].name.startswith(f"{name}."):
        raise RuntimeError(f"Expected only a top-level {name} module in the install, found {files}")
    for stale in out.glob(f"{name}.*"):
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
    env = msvc_env()
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
