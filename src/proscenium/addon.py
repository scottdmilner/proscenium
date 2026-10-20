"""Blender registration. Imports bpy; never import from proscenium.core code."""

import bpy
from bpy.app.handlers import persistent

from . import records, synchronization


class ProsceniumRecords(bpy.types.PropertyGroup):
    """The records' namespace, registered so Blender's Custom Properties panel hides it.

    The panel lists every custom property except those the Python API defines, unless Developer
    Extras is on. Records stay raw ID properties inside it, readable with the extension disabled.
    """


# Classes registered with Blender, in registration order.
CLASSES = (ProsceniumRecords,)
# The datablock types that carry records: binding configuration, destination tags, the binding index.
RECORD_TYPES = (bpy.types.Scene, bpy.types.Collection, bpy.types.Text)

_registered = False


@persistent
def _file_loaded(*_args: object) -> None:
    synchronization.SYNCHRONIZATION.file_loaded()


def register() -> None:
    global _registered
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for id_type in RECORD_TYPES:
        setattr(id_type, records.NAMESPACE, bpy.props.PointerProperty(type=ProsceniumRecords))
    bpy.app.handlers.load_post.append(_file_loaded)
    _registered = True


def unregister() -> None:
    global _registered
    bpy.app.handlers.load_post.remove(_file_loaded)
    for id_type in RECORD_TYPES:
        delattr(id_type, records.NAMESPACE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False


def is_registered() -> bool:
    return _registered
