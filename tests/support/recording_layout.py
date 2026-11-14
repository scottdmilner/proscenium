"""A stand-in for a Blender UI layout that records what a panel's draw function gives it, to check headless.

A panel draws into a UILayout only in a window. Draw functions written to take a layout (the temporary UI's
draw_source_selection and draw_bindings) draw into this instead, and a test reads back what they drew, in order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, override


@dataclass
class DrawnOperator:
    """An operator button, with the properties the draw function set on it."""

    idname: str
    icon: str
    properties: dict[str, Any] = field(default_factory=dict)

    @override
    def __setattr__(self, name: str, value: object) -> None:
        if name in {"idname", "icon", "properties"}:
            object.__setattr__(self, name, value)
        else:
            self.properties[name] = value


@dataclass
class RecordingLayout:
    """What was drawn, shared by the layout and the rows and boxes made from it."""

    labels: list[tuple[str, str, bool]] = field(default_factory=list)  # each label's text, icon, and row enabled
    props: list[str] = field(default_factory=list)  # each property drawn, by name
    operators: list[DrawnOperator] = field(default_factory=list)
    boxes: int = 0
    enabled: bool = True
    _root: RecordingLayout | None = None

    def _shared(self) -> RecordingLayout:
        return self._root or self

    def _child(self) -> RecordingLayout:
        root = self._shared()
        return RecordingLayout(root.labels, root.props, root.operators, 0, True, root)

    def prop(self, _data: object, name: str, **_kwargs: object) -> None:
        self._shared().props.append(name)

    def label(self, *, text: str, icon: str = "NONE") -> None:
        self._shared().labels.append((text, icon, self.enabled))

    def operator(self, idname: str, *, text: str = "", icon: str = "NONE") -> DrawnOperator:
        del text
        drawn = DrawnOperator(idname, icon)
        self._shared().operators.append(drawn)
        return drawn

    def row(self) -> RecordingLayout:
        return self._child()

    def box(self) -> RecordingLayout:
        self._shared().boxes += 1
        return self._child()
