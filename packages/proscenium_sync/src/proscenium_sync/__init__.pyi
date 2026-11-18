"""The synchronizer's public API, as type checkers see it: __init__.py loads each name on first use."""

from .bindings import *  # noqa: F403 - bindings' __all__, the one list of its names
from .registration import register as register
from .registration import unregister as unregister
