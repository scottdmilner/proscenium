"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_source import AttachedBindingSource, BindingSource, FileBindingSource, contributing_layers, dirty_layers
from .registry import SourceRegistry
from .sources import AttachedSource, FileSource, PayloadPolicy, SourceKind, SourceUnavailable

__all__ = [
    "AttachedBindingSource",
    "AttachedSource",
    "BindingSource",
    "FileBindingSource",
    "FileSource",
    "PayloadPolicy",
    "SourceKind",
    "SourceRegistry",
    "SourceUnavailable",
    "contributing_layers",
    "dirty_layers",
]
