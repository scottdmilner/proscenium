"""Throwaway extension for probe_packaging: records register/unregister calls
and inspects a stage handed over by caller code after installation.

probe_packaging copies stubs/callee_ext.py into the source dir as
stage_inspect.py before building, so both exchange checks share one inspector.
"""

# stage_inspect.py is copied in by probe_packaging; receive_stage is called by the probe.
from .stage_inspect import inspect as receive_stage  # noqa: F401  # ty: ignore[unresolved-import]

events: list[str] = []


def register() -> None:
    events.append("register")


def unregister() -> None:
    events.append("unregister")
