"""Blender registration. Imports bpy, so no bpy-free module imports this one."""

import bpy
from bpy.app.handlers import persistent

from .api import bindings
from .binding.persistence import id_property_records


class ProsceniumRecords(bpy.types.PropertyGroup):
    """The records' namespace, registered so Blender's Custom Properties panel hides it.

    The panel lists every custom property except those the Python API defines, unless Developer
    Extras is on. Records stay raw ID properties inside it, readable with the extension disabled.
    """


# Classes registered with Blender, in registration order.
CLASSES = (ProsceniumRecords,)
# The datablock types that carry records: the persistent selection, a destination's binding records, the binding index.
RECORD_TYPES = (bpy.types.Scene, bpy.types.Collection, bpy.types.Text)

_registered = False


@persistent
def _file_loaded(*_args: object) -> None:
    bindings.BINDINGS.drop_all_stages()  # loading a .blend releases every attachment (source-access.md)


@persistent
def _undone_or_redone(*_args: object) -> None:
    bindings.BINDINGS.prune_stages()  # at once, so an undone binding's stages are freed without waiting


def register() -> None:
    """Register the record types, and the handlers that drop or prune the bindings' stages."""
    global _registered
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for id_type in RECORD_TYPES:
        setattr(id_type, id_property_records.NAMESPACE, bpy.props.PointerProperty(type=ProsceniumRecords))
    bpy.app.handlers.load_post.append(_file_loaded)
    bpy.app.handlers.undo_post.append(_undone_or_redone)
    bpy.app.handlers.redo_post.append(_undone_or_redone)
    _registered = True


def unregister() -> None:
    """Remove what register() added."""
    global _registered
    bpy.app.handlers.load_post.remove(_file_loaded)
    bpy.app.handlers.undo_post.remove(_undone_or_redone)
    bpy.app.handlers.redo_post.remove(_undone_or_redone)
    for id_type in RECORD_TYPES:
        delattr(id_type, id_property_records.NAMESPACE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _registered
