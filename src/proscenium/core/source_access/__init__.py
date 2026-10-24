"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_stages import AttachedBindingStages, BindingStages, FileBindingStages, contributing_layers, dirty_layers
from .sources import AttachedSource, FileSource, PayloadPolicy, SourceKind, SourceUnavailableError
from .stage_registry import StageRegistry

__all__ = [
    "AttachedBindingStages",
    "AttachedSource",
    "BindingStages",
    "FileBindingStages",
    "FileSource",
    "PayloadPolicy",
    "SourceKind",
    "SourceUnavailableError",
    "StageRegistry",
    "contributing_layers",
    "dirty_layers",
]
