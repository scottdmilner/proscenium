"""proscenium_sync's lazy API loads its units' names, and only those (packages/README.md#public-apis)."""

from __future__ import annotations

import pytest

import proscenium_sync
from proscenium_sync import bindings, registration


def test_all_is_the_units_names() -> None:
    assert proscenium_sync.__all__ == [*bindings.__all__, *registration.__all__]


def test_each_name_is_its_units() -> None:
    for unit in (bindings, registration):
        for name in unit.__all__:
            assert getattr(proscenium_sync, name) is getattr(unit, name), name


def test_other_names_are_not_attributes() -> None:
    # registration's own names, outside its __all__, are not the package's.
    for name in ("Missing", "CLASSES"):
        with pytest.raises(AttributeError, match=f"no attribute '{name}'"):
            getattr(proscenium_sync, name)
