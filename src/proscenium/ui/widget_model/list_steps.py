"""The steps a widget's Left and Right keys take through its list, whichever widget's: into a row, or out of it."""

from __future__ import annotations

import enum


class StepDirection(enum.Enum):
    """Which way a key moves through a list's rows."""

    INTO = "into"  # Right: expand the row, or step into its first child
    OUT_OF = "out of"  # Left: collapse the row, or step out to its parent
