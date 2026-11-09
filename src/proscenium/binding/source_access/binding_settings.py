"""RequestedSettings, the settings a binding's next synchronization uses (lifecycle.md#binding-state).

The binding's configuration holds them (proscenium.binding.persistence.configs), and set_settings changes them. A
record gives every field: one without the conversion and purpose settings, which configuration version 1 gained in
place (DECISIONS.md "Conversion and purpose settings"), is refused like any other invalid record.
"""

from dataclasses import dataclass

from pxr import UsdGeom

from .stages import PayloadPolicy

PURPOSES = tuple(str(purpose) for purpose in UsdGeom.Imageable.GetOrderedPurposeTokens())  # USD's: default, render, ...
# The spec's default purposes (visibility.md#visibility-and-purpose); a new binding requests them.
VIEWPORT_PURPOSES = ("default", "proxy")
RENDER_PURPOSES = ("default", "render")


@dataclass(frozen=True, slots=True)
class RequestedSettings:
    """The settings a binding's next synchronization uses; changed only through set_settings."""

    payload_policy: PayloadPolicy
    coordinate_conversion: bool  # unit and up-axis conversion together; off, the correction is the identity
    viewport_purposes: tuple[str, ...]  # USD purposes each destination shows, sorted, each once
    render_purposes: tuple[str, ...]

    def __post_init__(self) -> None:
        # A record stores the enum's plain string value and the purposes as lists. A value that isn't a member, a
        # purpose USD doesn't define, or a flag that isn't a bool raises ValueError or TypeError.
        object.__setattr__(self, "payload_policy", PayloadPolicy(self.payload_policy))
        if type(self.coordinate_conversion) is not bool:
            raise TypeError("coordinate_conversion is not a bool")
        for field in ("viewport_purposes", "render_purposes"):
            purposes = getattr(self, field)
            if isinstance(purposes, str) or not all(type(p) is str for p in purposes):
                raise TypeError(f"{field} is not a list of strings")
            if unknown := set(purposes) - set(PURPOSES):
                raise ValueError(f"{field} names purposes USD doesn't define: {sorted(unknown)}")
            object.__setattr__(self, field, tuple(sorted(set(purposes))))


def new_settings(payload_policy: PayloadPolicy) -> RequestedSettings:
    """A new binding's settings: its payload policy, conversion off, and the spec's default purposes."""
    return RequestedSettings(payload_policy, False, VIEWPORT_PURPOSES, RENDER_PURPOSES)
