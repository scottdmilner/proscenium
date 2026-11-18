"""The synchronizer's public API, as type checkers see it: __init__.py loads each name on first use."""

# Each unit's __all__ is the one list of its names.
from .bindings import *  # noqa: F403
from .registration import *  # noqa: F403

__all__: list[str]  # the units' __all__ lists, joined, which __init__.py loads on first use
