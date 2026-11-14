"""Instancing's color, as the scene graph marks instances and their proxies in it, the instance badge's color.

Instancing takes one of the theme's collection colors. Mixed toward the list's text color, it reads on rows in light
and dark themes alike; an instance proxy's mix is closer to the text, fainter than its instance's, since it's shared
from the prototype.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...widget_resources import badge_icons, theme_colors

if TYPE_CHECKING:
    from ...widget_resources.theme_colors import RGB

# Instancing's color, the instance badge's (badge_icons.INSTANCE_BADGE_LOOK). How much of a row mark's color is the
# text's.
INSTANCING_COLOR = badge_icons.INSTANCE_BADGE_LOOK.color
INSTANCE_TEXT_WEIGHT = 0.6
INSTANCE_PROXY_TEXT_WEIGHT = 0.75


def instance_color() -> RGB:
    """The color an instance's row marks it in."""
    instancing_color = theme_colors.last_read_theme_colors().collection_color(INSTANCING_COLOR)
    return theme_colors.saturated_text_mix(instancing_color, INSTANCE_TEXT_WEIGHT)


def instance_proxy_color() -> RGB:
    """The color an instance proxy's row marks it in: fainter, for what it shares from its prototype."""
    instancing_color = theme_colors.last_read_theme_colors().collection_color(INSTANCING_COLOR)
    return theme_colors.text_mix(instancing_color, INSTANCE_PROXY_TEXT_WEIGHT)
