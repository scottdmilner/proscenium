"""Origins, and optionally outlines, of the source selection drawn by the extension (M4 Phase F, a probe).

Blender outlines selected objects, so a source selection's highlight follows which objects show it: a batch needs
an object per selection state (D14), and a multi-mesh copy batched as one instance per mesh is never one active
object. These outlines are drawn from the source selection instead, over the display select_tool.py mirrors into
Blender's selection, which stays as it is:

- **Geometry,** shared on the GPU as Blender shares it: each mesh's triangles, an object's own or a batch's
  prototype's, are one indexed GPU batch. A change of selection only groups the selection's viewport elements by
  mesh and puts each group's world matrices, and each instance's target, in a float texture, which an instanced
  shader reads by instance; nothing is built per frame.
- **The mesh cache is bounded:** the least recently used meshes go once it holds more than CACHE_BUDGET of
  vertices and indices, but never the current selection's; one selected again is extracted again.
- **Drawing,** in the 3D view's draw handler: each group instanced into a mask the region's size, of a target id
  a pixel (`R32F`, exact to 16 million) with a depth buffer of its own, so each pixel holds the nearest selected
  target, negative for the active entry's; then the mask's edges onto the view in the theme's selected and active
  colors, the active one's where either side of an edge is the active entry's. An edge is drawn where a
  neighboring pixel holds another target, on the side of the lower id, so each selection target, a floor at the
  prim level or a group at the group level, has its own outline, a target of several elements one silhouette,
  and two that touch one line between them.
- **Origins,** always drawn, whether these outlines or Blender's are used: a dot at each selection target's
  location, from the live stage at the time code the display shows, the active entry's in the active color: the
  floor at the prim level, the kind's ancestor at a kind level, where Blender's mark objects, a batch's carriers
  among them. They are a quad each, built with the selection, which a shader projects and draws as a disc with a
  dark rim. The outlines are drawn only with `draw_outlines`, and their geometry only then built.
- **Blender's selection stays mirrored,** so its operators that read it, Frame Selected among them, work as ever;
  while Source Select is the active tool, each 3D view's origins are hidden instead, and its selection outlines
  too while these are drawn, and both restored as they were once another tool is active or the session ends.
  These follow each view's own preference: no outlines where it hides selection outlines, no origins where it
  hides origins.
- **Not occluded:** Blender's Python GPU module reaches the view's depth only by reading it back to the CPU, so
  an outline shows through what stands in front of it, and fully, where Blender's dims what is hidden. The
  readback took 11 to 20 ms a frame at the region's size (ad hoc, the Kitchen set and ALab); the code that timed
  it is commented out in `Outlines._draw`, as nothing uses the depth.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
import gpu
import numpy
from batch import TRANSFORM
from gpu_extras.batch import batch_for_shader
from pxr import Usd, UsdGeom

if TYPE_CHECKING:
    from select_tool import Session

ORIGIN = 4.0  # an origin's diameter in interface pixels, inside its dark rim
WIDTH = 2  # the outline's width in interface pixels, which the preferences' pixel size scales: Blender's own
ROWS = 16384  # instances a matrix texture holds, a row each: the GPU's smallest guaranteed texture height
CACHE_BUDGET = 256 * 2**20  # bytes of cached vertices and indices, past which unselected meshes go
_INSTANCED = """
void main()
{
    int row = gpu_InstanceIndex;
    mat4 model = mat4(texelFetch(matrices, ivec2(0, row), 0), texelFetch(matrices, ivec2(1, row), 0),
                      texelFetch(matrices, ivec2(2, row), 0), texelFetch(matrices, ivec2(3, row), 0));
    target = texelFetch(matrices, ivec2(4, row), 0).r;  // the instance's target id, negative for the active's
    gl_Position = view_projection * model * vec4(pos, 1.0);
}
"""
_EDGES = """
void main()
{
    ivec2 size = textureSize(mask, 0);
    ivec2 here = ivec2(uv * vec2(size));
    float held = texelFetch(mask, here, 0).r;
    float center = abs(held);
    bool edge = false;
    bool active = false;
    for (int x = -width; x <= width; x++) {
        for (int y = -width; y <= width; y++) {
            float near = texelFetch(mask, clamp(here + ivec2(x, y), ivec2(0), size - 1), 0).r;
            if (abs(near) > center + 0.5) {  // another target, drawn on the lower id's side
                edge = true;
                active = active || near < 0.0 || held < 0.0;  // either side the active entry's
            }
        }
    }
    if (!edge) {
        discard;
    }
    color = active ? active_color : selected_color;
}
"""
_ORIGIN_VERTEX = """
void main()
{
    vec4 clip = view_projection * vec4(center, 1.0);
    clip.xy += corner * radius * 2.0 / viewport * clip.w;  // the quad's corner, `radius` pixels out
    offset = corner;
    is_active = active;
    gl_Position = clip;
}
"""
_ORIGIN_FRAGMENT = """
void main()
{
    float r = length(offset);
    if (r > 1.0) {
        discard;
    }
    color = r > 1.0 - rim / radius ? vec4(0.0, 0.0, 0.0, 1.0) : (is_active > 0.5 ? active_color : selected_color);
}
"""
_CORNERS = numpy.array([(-1, -1), (1, -1), (1, 1), (-1, -1), (1, 1), (-1, 1)], dtype=numpy.float32)


@dataclass
class Outlines:
    """The source selection's outlines over one session's display, and what drawing them has cost."""

    session: Session
    draw_outlines: bool = False  # whether to draw outlines, besides the origins
    # By mesh pointer, its triangles' indexed GPU batch and its bytes, the most recently used last.
    _meshes: OrderedDict[int, tuple[Any, int]] = field(default_factory=OrderedDict)
    _groups: list[tuple[bool, Any, Any, int]] = field(default_factory=list)  # (is active, batch, matrices, count)
    _origins: Any = None  # the targets' origins, a quad each, or None for none
    _framebuffer: Any = None  # the mask: an id per pixel, with a depth buffer of its own
    _mask: Any = None  # its color texture
    _depth: Any = None  # and its depth texture
    _shaders: dict[str, Any] = field(default_factory=dict)  # by name, compiled once
    _quad: Any = None
    _handler: Any = None
    # By 3D view space pointer, while Blender's overlays are hidden: the space, and its own selection outlines and
    # origins settings, to restore and to follow.
    _overlays: dict[int, tuple[Any, bool, bool]] = field(default_factory=dict)
    draw_ms: list[float] = field(default_factory=list)  # the draw handler's CPU time, per frame

    def enable(self) -> None:
        if self._handler is None:
            self.session.listeners.append(self.rebuild)
            self.rebuild()
            self._handler = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")

    def disable(self) -> None:
        if self._handler is not None:
            self.hide_blender_overlays(False)
            bpy.types.SpaceView3D.draw_handler_remove(self._handler, "WINDOW")
            self._handler = None
            self.session.listeners.remove(self.rebuild)

    def hide_blender_overlays(self, hidden: bool) -> None:
        """Hide every 3D view's origins, and its selection outlines while these are drawn, or restore them.

        Each view's settings are saved when hidden, and restored as saved.
        """
        if hidden and self._overlays:
            self.hide_blender_overlays(False)  # whether outlines are drawn may have changed
        if hidden:
            manager: Any = bpy.context.window_manager
            for window in manager.windows if manager is not None else ():
                for area in window.screen.areas:
                    if area.type == "VIEW_3D":
                        overlay = area.spaces.active.overlay
                        saved = (overlay.show_outline_selected, overlay.show_object_origins)
                        self._overlays[area.spaces.active.as_pointer()] = (area.spaces.active, *saved)
                        overlay.show_object_origins = False
                        if self.draw_outlines:
                            overlay.show_outline_selected = False
        elif not hidden:
            for space, outlines, origins in self._overlays.values():
                try:
                    space.overlay.show_outline_selected, space.overlay.show_object_origins = outlines, origins
                except ReferenceError:  # its area was closed
                    pass
            self._overlays.clear()

    def _preferences(self, space: Any) -> tuple[bool, bool]:
        """Whether a 3D view shows selection outlines and origins, as its own settings say."""
        saved = self._overlays.get(space.as_pointer())
        if saved is not None:
            return saved[1], saved[2]
        return space.overlay.show_outline_selected, space.overlay.show_object_origins

    def rebuild(self) -> None:
        """Group the selection's elements by mesh, each group's matrices in a texture, and build its origins."""
        session = self.session
        # By element, its selection target's id, so each target has its own outline; negative for the active's.
        ids: dict[int, float] = {}
        for index, target in enumerate(session.targets):
            sign = -1.0 if target == session.active else 1.0
            for element in session.interaction.highlight_targets([target]):
                ids.setdefault(element, sign * (index + 1))
        active = {element for element, id_ in ids.items() if id_ < 0}
        self._groups = []
        used = set()
        for is_active, elements in ((False, ids.keys() - active), (True, active)) if self.draw_outlines else ():
            for mesh, worlds, targets in self._instances(elements, ids):
                batch = self._mesh(mesh)
                used.add(mesh.as_pointer())
                for first in range(0, len(worlds), ROWS):
                    part = slice(first, first + ROWS)
                    self._groups.append((is_active, batch, _matrices(worlds[part], targets[part]), len(worlds[part])))
        self._evict(used)
        self._origins = self._origin_quads()
        # Blender redraws a view when its data changes, which a source selection alone doesn't, as Blender's
        # selection may be off: so ask for it.
        manager: Any = bpy.context.window_manager
        for window in manager.windows if manager is not None else ():
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def _instances(self, elements: set[int], ids: dict[int, float]) -> list[tuple[Any, numpy.ndarray, numpy.ndarray]]:
        """`elements` by the mesh they show: each group's world matrices (column-vector), and target ids."""
        display = self.session.display
        grouped: dict[int, tuple[Any, list[numpy.ndarray], list[numpy.ndarray]]] = {}
        for element in elements & display.objects.keys():
            obj = display.objects[element]
            data: Any = obj.data  # an element's object shows a mesh
            group = grouped.setdefault(data.as_pointer(), (data, [], []))
            group[1].append(numpy.array(obj.matrix_world)[None])
            group[2].append(numpy.array([ids[element]]))
        for batch in display.batches:
            points = [p for p, e in enumerate(batch.elements) if e in elements]
            carriers = [c for c in batch.carriers.values() if not c.hide_viewport]
            if not points or not carriers:
                continue
            transforms = numpy.empty((len(batch.elements), 4, 4), dtype=numpy.float32)
            held: Any = batch.points.attributes[TRANSFORM]  # a FLOAT4X4 attribute
            held.data.foreach_get("value", transforms.ravel())
            # A point's transform is USD's row-vector matrix, under its carriers' shared parent.
            worlds = numpy.array(carriers[0].matrix_world) @ transforms[points].transpose(0, 2, 1)
            mesh: Any = batch.prototype.data  # a prototype shows a mesh
            group = grouped.setdefault(mesh.as_pointer(), (mesh, [], []))
            group[1].append(worlds)
            group[2].append(numpy.array([ids[batch.elements[p]] for p in points]))
        return [(mesh, numpy.concatenate(w), numpy.concatenate(t)) for mesh, w, t in grouped.values()]

    def _mesh(self, mesh: Any) -> Any:
        """A mesh's triangles as an indexed GPU batch, in the mesh's own space, cached by mesh."""
        key = mesh.as_pointer()
        if key in self._meshes:
            self._meshes.move_to_end(key)
        else:
            mesh.calc_loop_triangles()
            corners = numpy.empty(len(mesh.loop_triangles) * 3, dtype=numpy.int32)
            mesh.loop_triangles.foreach_get("vertices", corners)
            positions = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float32)
            mesh.vertices.foreach_get("co", positions)
            # Row-major arrays: batch_for_shader reads the buffers' memory as rows, whatever their strides.
            content: Any = {"pos": positions.reshape(-1, 3)}  # the stubs list no numpy arrays
            indices: Any = corners.reshape(-1, 3)
            batch = batch_for_shader(self._shader("instanced"), "TRIS", content, indices=indices)
            self._meshes[key] = (batch, positions.nbytes + corners.nbytes)
        return self._meshes[key][0]

    def _evict(self, used: set[int]) -> None:
        """Drop the least recently used meshes not in `used` while the cache holds more than its budget."""
        held = sum(size for _, size in self._meshes.values())
        for key in [k for k in self._meshes if k not in used]:  # the least recently used first
            if held <= CACHE_BUDGET:
                break
            held -= self._meshes.pop(key)[1]

    @property
    def cached_bytes(self) -> int:
        """The cached meshes' vertices and indices, in bytes."""
        return sum(size for _, size in self._meshes.values())

    def _origin_quads(self) -> Any:
        """A quad about each selection target's world origin, for the origin shader; None for none."""
        session = self.session
        if session.stage is None or not session.targets:
            return None
        cache = UsdGeom.XformCache(Usd.TimeCode.Default() if session.time is None else session.time)
        centers, actives = [], []
        for path in session.targets:
            prim = session.stage.GetPrimAtPath(path)
            if prim:
                at = cache.GetLocalToWorldTransform(prim).ExtractTranslation()
                centers.append((at[0], at[1], at[2]))
                actives.append(1.0 if path == session.active else 0.0)
        if not centers:
            return None
        count = len(centers)
        content: Any = {  # row-major, as batch_for_shader reads them; the stubs list no numpy arrays
            "center": numpy.ascontiguousarray(numpy.repeat(numpy.array(centers, numpy.float32), 6, axis=0)),
            "corner": numpy.ascontiguousarray(numpy.tile(_CORNERS, (count, 1))),
            "active": numpy.repeat(numpy.array(actives, numpy.float32), 6),
        }
        return batch_for_shader(self._shader("origin"), "TRIS", content)

    def _shader(self, name: str) -> Any:
        """The instanced mask, edge, or origin shader, compiled once."""
        if name in self._shaders:
            return self._shaders[name]
        info = gpu.types.GPUShaderCreateInfo()
        info.fragment_out(0, "VEC4", "color")
        if name == "instanced":
            info.push_constant("MAT4", "view_projection")
            info.sampler(0, "FLOAT_2D", "matrices")
            interface = gpu.types.GPUStageInterfaceInfo("proscenium_mask")
            interface.flat("FLOAT", "target")
            info.vertex_in(0, "VEC3", "pos")
            info.vertex_out(interface)
            info.vertex_source(_INSTANCED)
            info.fragment_source("void main() { color = vec4(target, 0.0, 0.0, 1.0); }")
        elif name == "edges":
            info.push_constant("VEC4", "selected_color")
            info.push_constant("VEC4", "active_color")
            info.push_constant("INT", "width")
            info.sampler(0, "FLOAT_2D", "mask")
            interface = gpu.types.GPUStageInterfaceInfo("proscenium_outline")
            interface.smooth("VEC2", "uv")
            info.vertex_in(0, "VEC2", "pos")
            info.vertex_out(interface)
            info.vertex_source("void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }")
            info.fragment_source(_EDGES)
        else:
            info.push_constant("MAT4", "view_projection")
            info.push_constant("VEC4", "selected_color")
            info.push_constant("VEC4", "active_color")
            info.push_constant("VEC2", "viewport")
            info.push_constant("FLOAT", "radius")
            info.push_constant("FLOAT", "rim")
            interface = gpu.types.GPUStageInterfaceInfo("proscenium_origin")
            interface.smooth("VEC2", "offset")
            interface.flat("FLOAT", "is_active")
            info.vertex_in(0, "VEC3", "center")
            info.vertex_in(1, "VEC2", "corner")
            info.vertex_in(2, "FLOAT", "active")
            info.vertex_out(interface)
            info.vertex_source(_ORIGIN_VERTEX)
            info.fragment_source(_ORIGIN_FRAGMENT)
        self._shaders[name] = gpu.shader.create_from_info(info)
        if name == "edges":
            self._quad = batch_for_shader(self._shaders[name], "TRIS", {"pos": _CORNERS.tolist()})
        return self._shaders[name]

    def _draw(self) -> None:
        start = time.perf_counter()
        context: Any = bpy.context
        region, view = context.region, context.region_data
        if not (self._groups or self._origins) or region is None or view is None:
            return
        show_outlines, show_origins = self._preferences(context.space_data)
        show_outlines = show_outlines and self.draw_outlines
        if not (show_outlines or show_origins):
            return
        # The view's depth read back to the CPU, once, to time it; nothing uses it, so it doesn't run.
        # if self.depth_readback is None:
        #     framebuffer = gpu.state.active_framebuffer_get()
        #     begin = time.perf_counter()
        #     framebuffer.read_depth(0, 0, region.width, region.height)
        #     self.depth_readback = (time.perf_counter() - begin) * 1000
        size = (region.width, region.height)
        if self._mask is None or (self._mask.width, self._mask.height) != size:
            # A target id a pixel, as a float, exact to 16 million, and a float depth buffer: 8 bytes a pixel.
            # Not DEPTH_COMPONENT24, which Blender 5.2 deprecates: it didn't tell apart depths 1e-4 apart near
            # the far end, as a large scene's are (ad hoc, Metal), so selected targets showed through each other.
            self._mask = gpu.types.GPUTexture(size, format="R32F")
            self._depth = gpu.types.GPUTexture(size, format="DEPTH_COMPONENT32F")
            self._framebuffer = gpu.types.GPUFrameBuffer(depth_slot=self._depth, color_slots=self._mask)
        framebuffer: Any = self._framebuffer  # its bind() is a context manager the stubs don't declare
        projection = view.perspective_matrix
        with framebuffer.bind():
            framebuffer.viewport_set(0, 0, *size)
            # Depth writes on before the clear: Blender leaves them off in a draw callback, and a clear then
            # leaves the depth buffer as the last frame left it.
            gpu.state.depth_mask_set(True)
            framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
            mask = self._shader("instanced")
            mask.uniform_float("view_projection", projection)
            # Every target hides those behind it, the active entry's too, so each pixel holds the nearest.
            gpu.state.depth_test_set("LESS_EQUAL")
            for _, batch, matrices, count in self._groups:
                mask.uniform_sampler("matrices", matrices)
                batch.draw_instanced(mask, instance_start=0, instance_count=count)
            gpu.state.depth_test_set("NONE")
            gpu.state.depth_mask_set(False)
        theme: Any = context.preferences.themes[0].view_3d
        selected, active = _linear(theme.object_selected), _linear(theme.object_active)
        scale = context.preferences.system.pixel_size
        edges = self._shader("edges")
        edges.uniform_float("selected_color", selected)
        edges.uniform_float("active_color", active)
        edges.uniform_int("width", max(1, round(WIDTH * scale)))
        edges.uniform_sampler("mask", self._mask)
        gpu.state.blend_set("ALPHA")
        if show_outlines:
            self._quad.draw(edges)
        if self._origins is not None and show_origins:
            origin = self._shader("origin")
            origin.uniform_float("view_projection", projection)
            origin.uniform_float("selected_color", selected)
            origin.uniform_float("active_color", active)
            origin.uniform_float("viewport", (region.width, region.height))
            origin.uniform_float("radius", (ORIGIN / 2 + 1) * scale)  # the dot and its rim
            origin.uniform_float("rim", scale)
            self._origins.draw(origin)
        gpu.state.blend_set("NONE")
        self.draw_ms.append((time.perf_counter() - start) * 1000)


def _linear(color: Any) -> tuple[float, float, float, float]:
    """A theme color, which is sRGB, as the 3D view's linear color buffer takes it, opaque."""
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in color[:3]]
    return (channels[0], channels[1], channels[2], 1.0)


def _matrices(worlds: numpy.ndarray, targets: numpy.ndarray) -> Any:
    """A float texture of instances, a row each, as the instanced shader reads them.

    A row's first four texels are a world matrix's columns, and its fifth the instance's target id.
    """
    rows = numpy.zeros((len(worlds), 5, 4), dtype=numpy.float32)
    rows[:, :4] = worlds.transpose(0, 2, 1)
    rows[:, 4, 0] = targets
    values: Any = rows.ravel()  # a sequence of floats, which the stubs don't take numpy's for
    data = gpu.types.Buffer("FLOAT", rows.size, values)
    return gpu.types.GPUTexture((5, len(worlds)), format="RGBA32F", data=data)
