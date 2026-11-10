"""The constant keyframes of a cached display (M4 Phase E, E3): each object's keys, and the samples it shows.

Every key holds until the next. An object's action is made at its first key, with a slot for it. A mesh's
objects key the sample their frames modifier shows (attribute_samples.py), and with blending the next sample and
both their time codes; each object's timeline holds the sample it is keyed to at each time code.
"""

from __future__ import annotations

from typing import Any, Literal

import bpy
from attribute_samples import MODIFIER, NEXT, NEXT_TIME, SAMPLE, TIME, input_path
from bpy_extras import anim_utils

TRANSFORM_PATHS = ("location", "rotation_euler", "scale")


class AnimationKeyWriter:
    """The keys of a cached display's objects, and the timeline of the samples each shows."""

    blend: bool  # whether a time between samples mixes them
    _channels: dict[int, Any]  # by object session_uid, its action's channelbag
    _timelines: dict[int, dict[float, int]]  # by object session_uid, the sample keyed at each time

    def __init__(self, blend: bool) -> None:
        self.blend = blend
        self._channels = {}
        self._timelines = {}

    def insert(  # noqa: PLR0913 - the property keyed, and its key
        self,
        owner: Any,
        path: str,
        index: int,
        time: float,
        value: float,
        interpolation: Literal["CONSTANT", "LINEAR"] = "CONSTANT",
    ) -> None:
        """A key on an object or another ID, constant by default, so it holds until the next."""
        channels = self._channels.get(owner.session_uid)
        if channels is None:
            action = bpy.data.actions.new(f"{owner.name} frames")
            slot = action.slots.new(id_type=owner.id_type, name=owner.name)
            animation = owner.animation_data_create()
            animation.action, animation.action_slot = action, slot
            channels = self._channels[owner.session_uid] = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        curve = channels.fcurves.find(path, index=index) or channels.fcurves.new(path, index=index)
        point = curve.keyframe_points.insert(time, value, options={"FAST"})
        point.interpolation = interpolation

    def insert_transform(self, obj: bpy.types.Object, time: float) -> None:
        """Key `obj`'s transform as it is."""
        for path in TRANSFORM_PATHS:
            for index, value in enumerate(getattr(obj, path)):
                self.insert(obj, path, index, time, value)

    def timeline(self, obj: bpy.types.Object) -> dict[float, int]:
        """The sample `obj` is keyed to show at each time code; empty if none."""
        return self._timelines.get(obj.session_uid, {})

    def key_sample(self, obj: bpy.types.Object, time: float, sample: int) -> None:
        """Key `obj` to show `sample` from `time`, and with blending, to mix it with the next as time passes."""
        timeline = self._timelines.setdefault(obj.session_uid, {})
        timeline[time] = sample
        self.insert(obj, input_path(SAMPLE), 0, time, sample)
        if not self.blend:
            return
        later = [t for t in timeline if t > time]
        after = min(later) if later else time
        self.insert(obj, input_path(TIME), 0, time, time)
        self.insert(obj, input_path(NEXT), 0, time, timeline[after])
        self.insert(obj, input_path(NEXT_TIME), 0, time, after)
        earlier = [t for t in timeline if t < time]
        if earlier:  # the sample before now mixes into this one
            self.insert(obj, input_path(NEXT), 0, max(earlier), sample)
            self.insert(obj, input_path(NEXT_TIME), 0, max(earlier), time)

    def unkey_inputs(self, obj: bpy.types.Object) -> None:
        """Remove the keys of `obj`'s modifier inputs, which an attribute cache keyed, and its timeline."""
        channels = self._channels.get(obj.session_uid)
        curves = channels.fcurves if channels is not None else []
        for curve in [c for c in curves if c.data_path.startswith(f'modifiers["{MODIFIER}"]')]:
            curves.remove(curve)
        self._timelines.pop(obj.session_uid, None)


def frames_modifier(obj: bpy.types.Object) -> Any:
    """`obj`'s frames modifier, made first in its stack if it has none, so it acts before any other."""
    modifier = obj.modifiers.get(MODIFIER)
    if modifier is None:
        modifier = obj.modifiers.new(MODIFIER, "NODES")
        if len(obj.modifiers) > 1:
            obj.modifiers.move(len(obj.modifiers) - 1, 0)
    return modifier
