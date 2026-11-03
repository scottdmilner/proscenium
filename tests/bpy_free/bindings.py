"""Binding stages attached to a caller-supplied stage (source-access.md#source-stages)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proscenium.source_access import BindingStages

if TYPE_CHECKING:
    from pxr import Usd


def binding(caller: Usd.Stage) -> BindingStages:
    """A binding with caller attached through its handle."""
    stages = BindingStages()
    stages.attach(caller)
    return stages
