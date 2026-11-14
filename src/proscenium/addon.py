"""Blender registration. Imports bpy, so no bpy-free module imports this one."""

import bpy
from bpy.app.handlers import persistent

from .api import bindings
from .binding.persistence import id_property_records
from .interface import interface_registration


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
    bindings.BINDINGS.drop_all_stages()  # loading a .blend releases every attachment (source-access.md) and plan
    bindings.BINDINGS.clear_shown_displays()  # whose objects the load freed


@persistent
def _undone_or_redone(*_args: object) -> None:
    bindings.BINDINGS.prune_stages()  # at once, so an undone binding's stages are freed without waiting
    bindings.BINDINGS.clear_shown_displays()  # before any other handler reads one: undo may free its objects


@persistent
def _frame_changed(scene: bpy.types.Scene, *_args: object) -> None:
    bindings.BINDINGS.mirror_after_frame_change(scene)  # hide flags keyed at cached time codes deselect objects


# The owner of the message-bus subscriptions to what windows show.
_WINDOW_SUBSCRIBER = object()


def _window_shows_another_view_layer() -> None:
    # A window showing another view layer, or another scene, mirrors that scene's source selection into it (ICON-39).
    window_manager = bpy.context.window_manager
    for window in window_manager.windows if window_manager is not None else ():
        bindings.BINDINGS.mirror_source_selection(window.scene, window.view_layer)


def _subscribe_to_windows() -> None:
    bpy.msgbus.clear_by_owner(_WINDOW_SUBSCRIBER)
    for shown in ("view_layer", "scene"):
        bpy.msgbus.subscribe_rna(
            # Blender's documented (type, property name) key, for every window; the stubs type only an instance.
            key=(bpy.types.Window, shown),  # ty: ignore[invalid-argument-type]
            owner=_WINDOW_SUBSCRIBER,
            args=(),
            notify=_window_shows_another_view_layer,
        )


@persistent
def _file_loaded_subscribe(*_args: object) -> None:
    _subscribe_to_windows()  # a file load clears message-bus subscriptions


def register() -> None:
    """Register the record types, the handlers that drop or prune the bindings' stages, and those that mirror."""
    global _registered
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for id_type in RECORD_TYPES:
        setattr(id_type, id_property_records.NAMESPACE, bpy.props.PointerProperty(type=ProsceniumRecords))
    bpy.app.handlers.load_post.append(_file_loaded)
    bpy.app.handlers.undo_post.append(_undone_or_redone)
    bpy.app.handlers.redo_post.append(_undone_or_redone)
    bpy.app.handlers.frame_change_post.append(_frame_changed)
    bpy.app.handlers.load_post.append(_file_loaded_subscribe)
    _subscribe_to_windows()
    interface_registration.register()
    _registered = True


def unregister() -> None:
    """Remove what register() added."""
    global _registered
    interface_registration.unregister()
    bpy.app.handlers.load_post.remove(_file_loaded)
    bpy.app.handlers.undo_post.remove(_undone_or_redone)
    bpy.app.handlers.redo_post.remove(_undone_or_redone)
    bpy.app.handlers.frame_change_post.remove(_frame_changed)
    bpy.app.handlers.load_post.remove(_file_loaded_subscribe)
    bpy.msgbus.clear_by_owner(_WINDOW_SUBSCRIBER)
    for id_type in RECORD_TYPES:
        delattr(id_type, id_property_records.NAMESPACE)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _registered
