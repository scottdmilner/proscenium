"""The scene graph widget's display: prim trees drawn in Blender as virtualized UILists, for a host to place.

It registers no panel that shows by itself (its one panel is its settings popover) and places nothing in Blender's
editors; a host does:

    from proscenium.ui.scene_graph_widget import display

    display.register()
    display.create_view("viewport", shows_in_region=lambda area, region: ...)
    display.set_stage("viewport", stage)
    # in the host panel's draw:
    display.draw_tree(self.layout, context, "viewport")

It exports the names hosts use.
"""

from .widget_drawing import draw_details, draw_tree
from .widget_hosting import create_view, remove_view, select_prim, selected_path, set_stage
from .widget_properties import apply_pending
from .widget_registration import is_registered, register, unregister
from .widget_views import ViewNotFoundError

__all__ = [
    "ViewNotFoundError",
    "apply_pending",
    "create_view",
    "draw_details",
    "draw_tree",
    "is_registered",
    "register",
    "remove_view",
    "select_prim",
    "selected_path",
    "set_stage",
    "unregister",
]
