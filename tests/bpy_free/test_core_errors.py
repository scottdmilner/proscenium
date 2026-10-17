"""The compiled core turns Tf errors and C++ exceptions into Python exceptions (AGENTS.md "Compiled core")."""

from __future__ import annotations

import pytest
from pxr import Tf

from proscenium.core import _core


def test_tf_error_raises_tf_error_exception() -> None:
    with pytest.raises(Tf.ErrorException, match="posted by the test"):
        _core._post_tf_error("posted by the test")


def test_cpp_exception_raises_python_exception() -> None:
    # The StageHandle constructor throws std::invalid_argument for a null stage.
    with pytest.raises(ValueError, match="valid USD stage"):
        _core.StageHandle(None)
