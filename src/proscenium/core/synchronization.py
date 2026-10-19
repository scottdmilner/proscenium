"""Synchronization keyed by binding identifier, behind the binding handle (source-access.md#synchronization-api).

M3 implements source acquisition: a synchronization records the requested time code, acquires
the binding's evaluation stage under its requested settings, and reports the source's state. M5
adds evaluation, planning, application, and publication, and the guard against reentrant calls.
Requested settings are runtime state here until the binding records exist (M3 Phase D).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pxr import Usd

from .source_access import AttachResult, SourceRegistry, SourceUnavailable

if TYPE_CHECKING:
    import os
    from collections.abc import Iterable


class BindingNotFound(LookupError):  # noqa: N818 (misuse, raised like KeyError)
    """No binding has this identifier: it was removed, or never created."""


class ResultState(StrEnum):
    SUCCESS = "success"
    COMPLETED_WITH_ISSUES = "completed with issues"
    FATAL_FAILURE = "fatal failure"


class Category(StrEnum):
    """Diagnostic categories source access reports (pipeline.md#diagnostics)."""

    UNAVAILABLE_SOURCE = "unavailable source"
    SOURCE_STATE = "source state"  # informational: it doesn't change the result state


class Severity(StrEnum):
    INFO = "info"
    ERROR = "error"


@dataclass(frozen=True)
class Diagnostic:
    category: Category
    severity: Severity
    message: str
    layers: tuple[str, ...] = ()  # layer identifiers it concerns, sorted


@dataclass(frozen=True)
class Result:
    """What a synchronization or a reload did. Expected failures are results, never exceptions."""

    state: ResultState
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass
class RequestedSettings:
    """The settings a binding's next synchronization uses (lifecycle.md#binding-state)."""

    time_code: Usd.TimeCode | None  # None until the first synchronize
    payload_policy: Usd.Stage.InitialLoadSet


@dataclass(frozen=True)
class BindingHandle:
    """How callers reach a binding: its persistent identifier, never a datablock or cached state.

    Each method looks the binding up when it is called, and raises BindingNotFound once the
    binding is gone. Two handles are equal when their identifiers are.
    """

    binding_id: str

    def synchronize(self, time_code: Usd.TimeCode | float) -> Result:
        return SYNCHRONIZATION.synchronize(self.binding_id, time_code)

    def set_settings(self, *, payload_policy: Usd.Stage.InitialLoadSet | None = None) -> None:
        SYNCHRONIZATION.set_settings(self.binding_id, payload_policy=payload_policy)

    def reload(self, layers: Iterable[str] | None = None) -> Result:
        return SYNCHRONIZATION.reload(self.binding_id, layers)

    def requested_settings(self) -> RequestedSettings:
        return SYNCHRONIZATION.requested_settings(self.binding_id)

    def live_stage(self) -> Usd.Stage | None:
        return SYNCHRONIZATION.live_stage(self.binding_id)


class Synchronization:
    """The process's bindings: their sources and requested settings, by binding identifier."""

    sources: SourceRegistry
    _requested: dict[str, RequestedSettings]

    def __init__(self) -> None:
        self.sources = SourceRegistry()
        self._requested = {}

    def create_file_binding(
        self, root: str | os.PathLike[str], payload_policy: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll
    ) -> BindingHandle:
        binding_id = _new_identifier()
        self.sources.add_file(binding_id, root, payload_policy)
        self._requested[binding_id] = RequestedSettings(None, payload_policy)
        return BindingHandle(binding_id)

    def create_attached_binding(
        self, key: str, payload_policy: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll
    ) -> BindingHandle:
        binding_id = _new_identifier()
        self.sources.add_attached(binding_id, key, payload_policy)
        self._requested[binding_id] = RequestedSettings(None, payload_policy)
        return BindingHandle(binding_id)

    def attach(self, key: str, stage: Usd.Stage, *, confirm: bool = False) -> AttachResult:
        """Attach stage under a source key (source-access.md#source-identity)."""
        return self.sources.attach(key, stage, confirm=confirm)

    def remove(self, binding_id: str) -> None:
        self._known(binding_id)
        self.sources.remove(binding_id)
        del self._requested[binding_id]

    def requested_settings(self, binding_id: str) -> RequestedSettings:
        return self._known(binding_id)

    def set_settings(self, binding_id: str, *, payload_policy: Usd.Stage.InitialLoadSet | None = None) -> None:
        """Record requested settings without synchronizing."""
        requested = self._known(binding_id)
        if payload_policy is not None:
            requested.payload_policy = payload_policy

    def synchronize(self, binding_id: str, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code, which becomes the requested one; acquisition only (M3)."""
        requested = self._known(binding_id)
        requested.time_code = Usd.TimeCode(time_code)
        source = self.sources.get(binding_id)
        source.payload_policy = requested.payload_policy
        try:
            dirty = source.dirty_layers()  # acquires the evaluation stage
        except SourceUnavailable as error:
            return _unavailable(error)
        diagnostics = ()
        if dirty:
            message = "Displaying layers with unsaved in-process edits"
            diagnostics = (Diagnostic(Category.SOURCE_STATE, Severity.INFO, message, tuple(sorted(dirty))),)
        return Result(ResultState.SUCCESS, diagnostics)

    def reload(self, binding_id: str, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request, without synchronizing.

        Raises ValueError, and reloads nothing, if layers names one that isn't a contributing layer.
        """
        self._known(binding_id)
        try:
            self.sources.get(binding_id).reload(layers)
        except SourceUnavailable as error:
            return _unavailable(error)
        return Result(ResultState.SUCCESS)

    def live_stage(self, binding_id: str) -> Usd.Stage | None:
        self._known(binding_id)
        return self.sources.get(binding_id).live_stage

    def _known(self, binding_id: str) -> RequestedSettings:
        try:
            return self._requested[binding_id]
        except KeyError:
            raise BindingNotFound(binding_id) from None


def _new_identifier() -> str:
    # Stands in for the persistent identifier the binding records assign (M3 Phase D).
    return uuid.uuid4().hex


def _unavailable(error: SourceUnavailable) -> Result:
    return Result(ResultState.FATAL_FAILURE, (Diagnostic(Category.UNAVAILABLE_SOURCE, Severity.ERROR, str(error)),))


SYNCHRONIZATION = Synchronization()  # the process's bindings, which handles use
