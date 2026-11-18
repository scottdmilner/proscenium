"""The temporary UI: the Source Select tool and minimal panels, which M12 replaces (M7 plan, settled 3).

The extension's lowest tier, below proscenium.addon: it imports only the packages' public APIs, proscenium_sync's
names and proscenium_ui's widgets and widget_updates, besides bpy and USD, so it can be replaced without touching the
rest. It exports its modules: the Source Select tool and its sidebar panel
(source_select_tool), the binding panel (binding_panel), the source inspector (source_inspector), and its
registration (interface_registration), which proscenium.addon calls.
"""

from . import binding_panel, interface_registration, source_inspector, source_select_tool

__all__ = ["binding_panel", "interface_registration", "source_inspector", "source_select_tool"]
