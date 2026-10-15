"""ALab's entry point for Phase E: a root layer over entry.usda that deactivates what the prototype doesn't translate.

Both sides then import the same content: lights, cameras, curves, points, point instancers, volumes and
ALab's audio prims would otherwise be translated by the importer and only marked with placeholders by the
prototype. The pinned ALab tree is untouched; the layer is written under the output directory.

Opinions on instance proxies are ignored, so prims inside native-instance prototypes can't be deactivated
from here. What remains of each type there is counted and recorded.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from pxr import Sdf, Usd, UsdGeom, UsdLux, UsdVol

if TYPE_CHECKING:
    from pathlib import Path

# Types the prototype turns into objects, or groups that hold them.
TRANSLATED = {"Mesh", "Cube", "Sphere", "Cone", "Cylinder", "Capsule", "Plane", "Xform", "Scope", ""}
# Typed prims outside UsdGeom that the importer reads and the prototype doesn't.
UNTRANSLATED_OTHER = {"ALAudio"}
# Root-layer metadata the stage reads from its root layer only, copied so timing and units are unchanged.
STAGE_METADATA = (
    "startTimeCode",
    "endTimeCode",
    "timeCodesPerSecond",
    "framesPerSecond",
    "metersPerUnit",
    "upAxis",
    "defaultPrim",
)


def untranslated(prim: Usd.Prim) -> bool:
    type_name = str(prim.GetTypeName())
    if type_name in UNTRANSLATED_OTHER:
        return True
    # HasAPI and IsA also take a schema class, which the stubs don't declare.
    lights = prim.HasAPI(UsdLux.LightAPI)  # ty: ignore[no-matching-overload]
    imageable = prim.IsA(UsdGeom.Imageable) or prim.IsA(UsdVol.Volume)  # ty: ignore[no-matching-overload]
    return lights or (imageable and type_name not in TRANSLATED)


def write(entry: Path, out: Path) -> dict[str, Any]:
    """Writes the layer; returns what it deactivated and what remains inside prototypes."""
    stage = Usd.Stage.Open(str(entry), Usd.Stage.LoadAll)
    deactivated: list[Usd.Prim] = []
    iterator = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in iterator:
        if untranslated(prim):
            deactivated.append(prim)
            iterator.PruneChildren()
    remaining = Counter(
        str(prim.GetTypeName())
        for prototype in stage.GetPrototypes()
        for prim in Usd.PrimRange(prototype)
        if untranslated(prim)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    layer = Sdf.Layer.CreateNew(str(out))
    source = Sdf.Layer.FindOrOpen(str(entry))
    for key in STAGE_METADATA:
        if source.pseudoRoot.HasInfo(key):
            layer.pseudoRoot.SetInfo(key, source.pseudoRoot.GetInfo(key))
    layer.documentation = (
        "Phase E measurement entry point for ALab: entry.usda with every prim of a type the Hydra prototype "
        "doesn't translate deactivated (tools/feasibility/hydra_bridge/measure/alab_entry.py)."
    )
    layer.subLayerPaths.append(str(entry.resolve()))
    with Sdf.ChangeBlock():
        for prim in deactivated:
            Sdf.CreatePrimInLayer(layer, prim.GetPath()).active = False
    layer.Save()
    return {
        "entry": str(entry),
        "deactivated": len(deactivated),
        "deactivated by type": dict(Counter(str(p.GetTypeName()) for p in deactivated)),
        "deactivated paths": [str(p.GetPath()) for p in deactivated],
        "remaining in prototypes": dict(remaining),
    }
