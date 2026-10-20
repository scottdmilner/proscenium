"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_source import BindingSource, contributing_layers
from .registry import SourceRegistry
from .sources import AttachedSource, FileSource, SourceKind, SourceUnavailable

__all__ = [
    "AttachedSource",
    "BindingSource",
    "FileSource",
    "SourceKind",
    "SourceRegistry",
    "SourceUnavailable",
    "contributing_layers",
]
