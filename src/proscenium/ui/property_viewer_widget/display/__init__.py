"""The property viewer widget's display: one prim's properties drawn in Blender as a virtualized UIList, for a host.

It registers no panel that shows by itself (its one panel is its settings popover) and places nothing in Blender's
editors; a host does, usually beside a scene graph whose selection it follows:

    from proscenium.ui.property_viewer_widget import display

    display.register()
    display.create_view("viewport", shows_in_region=lambda area, region: ...)
    display.set_stage("viewport", stage)
    display.show_prim("viewport", prim_path)  # as the scene graph's selection changes
    # in the host panels' draw:
    display.draw_properties(self.layout, context, "viewport")
    display.draw_metadata(self.layout, context, "viewport")

It exports the names hosts use.
"""

from .property_viewer_drawing import draw_metadata, draw_properties
from .property_viewer_hosting import (
    create_view,
    remove_view,
    select_property,
    selected_path,
    set_stage,
    set_time_code,
    show_prim,
)
from .property_viewer_properties import apply_pending
from .property_viewer_registration import is_registered, register, unregister
from .property_viewer_views import ViewNotFoundError

__all__ = [
    "ViewNotFoundError",
    "apply_pending",
    "create_view",
    "draw_metadata",
    "draw_properties",
    "is_registered",
    "register",
    "remove_view",
    "select_property",
    "selected_path",
    "set_stage",
    "set_time_code",
    "show_prim",
    "unregister",
]
