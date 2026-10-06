"""Runs every probe inside a pytest session (the "wheel-pytest" runtime).

Invoked by run_all.py; the output path comes from PROSCENIUM_FEASIBILITY_OUT.
Not collected by the project test suite.
"""

import os
from pathlib import Path

import probe_main


def test_probes_under_pytest() -> None:
    out = Path(os.environ["PROSCENIUM_FEASIBILITY_OUT"])
    assert probe_main.main([str(out)]) == 0
