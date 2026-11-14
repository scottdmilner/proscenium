"""The temporary UI: the Source Select tool and minimal panels, which M12 replaces (M7 plan, settled 3).

Tier 10, above proscenium.ui's widget displays and below proscenium.addon: it imports only proscenium.api and
proscenium.ui's widgets, besides bpy and USD, so it can be replaced without touching the rest; it reaches the product
only through proscenium.api. It exports its modules: the Source Select tool and its sidebar panel
(source_select_tool), the binding panel (binding_panel), and its registration (interface_registration), which
proscenium.addon calls.
"""

from . import binding_panel, interface_registration, source_select_tool

__all__ = ["binding_panel", "interface_registration", "source_select_tool"]
