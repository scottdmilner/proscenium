"""Layered USD scenes shared by the source-access probes.

The layer files live in scenes/ and are copied to a temp dir per probe. Every
composed value is 1.0 on disk; probes make in-memory edits that set values to
99.0, so the disk view and the in-process view are easy to tell apart.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

SCENES = Path(__file__).parent / "scenes"

# Layer name -> (composed prim path, attribute that layer authors).
VALUES: dict[str, tuple[str, str]] = {
    "root": ("/World", "rootValue"),
    "sub": ("/World", "subValue"),
    "ref": ("/World/Ref", "refValue"),
    "pay": ("/World/Pay", "payValue"),
    "nested": ("/World/Pay", "nestedValue"),
    "var_b": ("/World/Var/Inner", "varValue"),
    "abs": ("/World/Abs", "absValue"),
}


def build_layered(dest: Path) -> tuple[Path, Path]:
    """Copy the layered scene into dest and add the absolute-path reference.

    Returns (scene dir, abs dir); the root layer is scene dir / root.usda.
    """
    from pxr import Sdf

    scene_dir = dest / "layered"
    abs_dir = dest / "abs"
    shutil.copytree(SCENES / "layered", scene_dir)
    shutil.copytree(SCENES / "abs", abs_dir)
    root = Sdf.Layer.FindOrOpen(str(scene_dir / "root.usda"))
    spec = root.GetPrimAtPath("/World/Abs")
    spec.referenceList.Prepend(Sdf.Reference((abs_dir / "abs.usda").as_posix()))
    root.Save()
    return scene_dir, abs_dir


def layer_path(scene_dir: Path, abs_dir: Path, name: str) -> Path:
    return (abs_dir if name == "abs" else scene_dir) / f"{name}.usda"


def read_values(stage: Any) -> dict[str, float | None]:
    """Composed value for each entry in VALUES (None when absent)."""
    out: dict[str, float | None] = {}
    for name, (prim_path, attr) in VALUES.items():
        prim = stage.GetPrimAtPath(prim_path)
        out[name] = prim.GetAttribute(attr).Get() if prim else None
    return out


def dirty_edit(layer: Any, name: str, value: float = 99.0) -> None:
    """Change the layer's authored value in memory, without saving."""
    from pxr import Sdf

    prim_path = "/World" if name in ("root", "sub") else "/Asset"
    attr = VALUES[name][1]
    layer.GetAttributeAtPath(Sdf.Path(prim_path).AppendProperty(attr)).default = value


def rewrite_on_disk(path: Path, name: str, value: float) -> None:
    """Change a layer's value on disk without going through the open layer."""
    text = path.read_text(encoding="utf-8")
    attr = VALUES[name][1]
    lines = [
        line.rsplit("=", 1)[0] + f"= {value:g}" if f"double {attr} =" in line else line for line in text.splitlines()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
