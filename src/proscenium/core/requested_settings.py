"""RequestedSettings, the settings a binding's next synchronization uses (lifecycle.md#binding-state).

The binding's configuration holds them (proscenium.persistence.binding_records), and set_settings changes them.
"""

from dataclasses import dataclass

from .source_access import PayloadPolicy


@dataclass(frozen=True, slots=True)
class RequestedSettings:
    """The settings a binding's next synchronization uses; changed only through set_settings."""

    payload_policy: PayloadPolicy

    def __post_init__(self) -> None:
        # A record stores the enum's plain string value. One that isn't a member raises ValueError.
        object.__setattr__(self, "payload_policy", PayloadPolicy(self.payload_policy))
