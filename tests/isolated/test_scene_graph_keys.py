"""The scene graph widget's Left and Right keys in Blender's window, from simulated mouse moves and key presses.

The bodies (bodies/scene_graph_keys.py) host views in the 3D View's sidebar on scenes/scene_graph/prim_kinds.usda,
whose first row is /_Crate: Right with nothing selected expands that row and selects it.
"""

from __future__ import annotations

from pathlib import Path

from fixtures.scenes import Scene, copy_scene

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"
TIMEOUT_SECONDS = 120  # the sweep down the sidebar takes a few seconds; a window that never draws times out


def _stage_path(tmp_path: Path) -> str:
    return str(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")


def test_right_steps_the_view_whose_list_is_under_the_cursor(windowed_binary: Runtime, tmp_path: Path) -> None:
    observed = run_isolated(
        windowed_binary,
        BODIES / "scene_graph_keys.py",
        "keys_step_the_hovered_view",
        tmp_path,
        timeout=TIMEOUT_SECONDS,
        stage_path=_stage_path(tmp_path),
    )
    crate = observed["first_row_path"]
    # Over the second list, below the first in the same editor: the second view steps, and only its host hears.
    assert observed["after_second"] == {
        "selected": {"first": None, "second": crate},
        "expanded": {"first": [], "second": [crate]},
        "heard": {"first": [], "second": [crate]},
    }
    assert observed["after_first"] == {
        "selected": {"first": crate, "second": crate},
        "expanded": {"first": [crate], "second": [crate]},
        "heard": {"first": [crate], "second": [crate]},
    }
    # Below both panels, where no list is under the cursor, the key passes on to Blender, which steps the frame.
    assert observed["below"] == {"selected": {"first": crate, "second": crate}, "frame_change": 1}


def test_right_steps_a_view_after_the_widget_is_registered_again(windowed_binary: Runtime, tmp_path: Path) -> None:
    # Unregistering ends each window's watcher; registering again must start another.
    observed = run_isolated(
        windowed_binary,
        BODIES / "scene_graph_keys.py",
        "keys_step_after_registering_again",
        tmp_path,
        timeout=TIMEOUT_SECONDS,
        stage_path=_stage_path(tmp_path),
    )
    # Expanded, not only selected: with nothing selected, the list's own Right would select the first row too.
    stepped = {"selected": {"only": "/_Crate"}, "expanded": {"only": ["/_Crate"]}}
    assert observed["before"] == stepped
    assert observed["after"] == stepped
    assert observed["heard"] == {"only": ["/_Crate", "/_Crate"]}  # once by each registration's view
