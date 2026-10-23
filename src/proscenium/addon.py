"""Blender registration. Imports bpy; never import from proscenium.core code."""

import bpy
from bpy.app.handlers import persistent

from . import runtime
from .api import bindings
from .persistence import records


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
    bindings.BINDINGS.drop_all_stages()
    runtime.invalidate()


@persistent
def _data_changing(*_args: object) -> None:
    # Before a load, undo, or redo, so that another extension's handler running ahead of _file_loaded
    # or _undone_or_redone rebuilds the state from the data that results.
    runtime.invalidate()


@persistent
def _undone_or_redone(*_args: object) -> None:
    runtime.invalidate()  # undo and redo restore records, and re-read the datablocks the step changed
    bindings.BINDINGS.prune_stages()  # at once, so an undone binding's stages are freed without waiting


def register() -> None:
    """Register the record types, and the handlers that keep the bindings' state current."""
    global _registered
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for id_type in RECORD_TYPES:
        setattr(id_type, records.NAMESPACE, bpy.props.PointerProperty(type=ProsceniumRecords))
    for pre in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        pre.append(_data_changing)
    bpy.app.handlers.load_post.append(_file_loaded)
    bpy.app.handlers.undo_post.append(_undone_or_redone)
    bpy.app.handlers.redo_post.append(_undone_or_redone)
    runtime.start()
    _registered = True


def unregister() -> None:
    """Remove what register() added, and stop the bindings' state."""
    global _registered
    runtime.stop()
    bpy.app.handlers.load_post.remove(_file_loaded)
    bpy.app.handlers.undo_post.remove(_undone_or_redone)
    bpy.app.handlers.redo_post.remove(_undone_or_redone)
    for pre in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        pre.remove(_data_changing)
    for id_type in RECORD_TYPES:
        delattr(id_type, records.NAMESPACE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _registered
