"""Throwaway extension for probe_packaging: records register/unregister calls
and inspects a stage handed over by caller code after installation.

probe_packaging copies stubs/callee_ext.py into the source dir as
stage_inspect.py before building, so both exchange checks share one inspector.
"""

from .stage_inspect import inspect as receive_stage  # noqa: F401 - called by the probe

events: list[str] = []


def register() -> None:
    events.append("register")


def unregister() -> None:
    events.append("unregister")
