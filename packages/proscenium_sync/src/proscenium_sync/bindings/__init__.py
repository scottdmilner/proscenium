"""What callers use: the binding handle and the process's bindings (source-access.md#synchronization-api).

It exports caller operations and types; its implementation modules stay within this unit.
"""

from .binding_service import (
    BINDINGS,
    BindingHandle,
    BindingNotFoundError,
    Bindings,
    BindingStatus,
    PersistentSelection,
    PickedEntity,
    ReentrantCallError,
    RequestedSettings,
    Result,
    ResultState,
    SelectionEntry,
    SelectionMode,
    SelectionResolution,
    SourceUnavailableError,
    TargetSelection,
)

__all__ = [
    "BINDINGS",
    "BindingHandle",
    "BindingNotFoundError",
    "BindingStatus",
    "Bindings",
    "PersistentSelection",
    "PickedEntity",
    "ReentrantCallError",
    "RequestedSettings",
    "Result",
    "ResultState",
    "SelectionEntry",
    "SelectionMode",
    "SelectionResolution",
    "SourceUnavailableError",
    "TargetSelection",
]
