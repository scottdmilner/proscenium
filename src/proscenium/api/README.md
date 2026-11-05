# `proscenium.api`

What callers use to reach bindings ([Synchronization API](../../../docs/spec/source-access.md#synchronization-api)). Not a tier: it may import `proscenium.synchronization`, `proscenium.binding.runtime`, `proscenium.binding.persistence`, and the bpy-free code (`proscenium.core`, `proscenium.binding.source_access`, `proscenium.binding.results`), using what each package exports.

| File | Holds |
|---|---|
| `__init__.py` | The package. |
| `bindings.py` | `BindingHandle`, the immutable value of a binding's identifier that callers hold, and `Bindings`, the process's bindings, of which `BINDINGS` is the one instance. Also `BindingNotFoundError`, and `RequestedSettings`, from `proscenium.binding.source_access`. |

## `bindings.py`

- **The handle** holds only the binding's identifier, never a datablock or cached state, so undo, redo, and file loads can't leave it stale. Its methods (`attach`, `release`, `synchronize`, `set_settings`, `reload`, `requested_settings`, `live_stage`) delegate to the methods of `BINDINGS` keyed by that identifier, which tests call on a fresh `Bindings`.
- **Operations that span bindings** are `Bindings`' own: creating an unattached binding (`create_binding(scene, ...)`), listing a scene's bindings (`in_scene`), and reporting copied bindings (`copied`). Callers open source stages and resolve file paths.
- **Results and refusals:** an operation returns a `Result` (`proscenium.binding.results`) whose diagnostics say why it failed: an unavailable source, a configuration that can't be read, a removed destination, or a binding with copies and no canonical candidate. A query raises instead, and methods needing records raise `BindingNotFoundError` for a binding that doesn't exist. `release()` is an idempotent runtime operation that remains valid after undo or removal.
- **Runtime stages:** each binding's source and evaluation stages are in `Bindings.stages`, a `CurrentStages` (`proscenium.binding.runtime`), created unattached on first use and compared with the bindings before any use once the bindings' state was rebuilt. `addon.py` drops them all when a file is loaded (`drop_all_stages`).

`synchronize` finds the binding and refuses one that isn't usable, and `proscenium.synchronization` runs the transaction. It acquires only so far; M5 adds evaluation, planning, application, and publication.

## Caller workflow

With the extension enabled in Blender, the caller opens a stage and attaches it through the returned handle:

```python
import bpy
from pxr import Usd

from proscenium.api.bindings import BINDINGS

stage = Usd.Stage.Open("/absolute/path/to/shot.usda")
handle = BINDINGS.create_binding(bpy.context.scene, name="Shot")
attachment = handle.attach(stage)
if attachment.is_success:
    result = handle.synchronize(Usd.TimeCode.Default())
    print(result)
```

Each handle attaches and releases independently. A different stored root-layer identifier produces a fatal `source confirmation required` diagnostic and leaves the binding unchanged; the caller can explicitly choose `handle.attach(stage, confirm=True)`. Callers resolve file paths before opening, including Blender-relative paths through `bpy.path.abspath`. The default destination name is `USD Display`.

After reopening a `.blend`, find existing handles with `BINDINGS.in_scene(scene)` or reconstruct a `BindingHandle` from its persistent identifier, then call `handle.attach(stage)` for each binding to restore. Until attached, bindings retain their saved display and report the source unavailable. `handle.live_stage()` exposes the supplied stage immediately.

To give bindings separate source opinions over shared layers, create an anonymous root for each stage and sublayer the shared source:

```python
from pxr import Sdf

overlay = Sdf.Layer.CreateAnonymous()
overlay.subLayerPaths.append(stage.GetRootLayer().identifier)
independent_stage = Usd.Stage.Open(overlay)
other = BINDINGS.create_binding(bpy.context.scene)
other.attach(independent_stage)
```

Release each binding's attachment when finished, including after undo removes the binding:

```python
handle.release()
other.release()
del stage, independent_stage
```

The binding holds a strong stage reference until release, replacement, or file load. Releasing clears its source and evaluation stages; the caller's own references keep the source alive until they are dropped too.

## Measuring source access

Time the caller's stage opening, the binding's first evaluation-stage acquisition, and subsequent acquisitions separately. The first acquisition composes a second stage over the source's loaded root and session layers; later acquisitions reuse it while those layers match. Record the payload policy, host, fixture, and cache conditions with each result. A retained evaluation stage also retains its composed layers, so include both held stages when measuring memory.

The direct source-access boundary can be measured independently of Blender's records and diagnostics:

```python
from time import perf_counter

from pxr import Usd

from proscenium.binding.source_access import BindingStages, PayloadPolicy

started = perf_counter()
stage = Usd.Stage.Open("/absolute/path/to/shot.usda")
opened = perf_counter()
stages = BindingStages()
stages.attach(stage)
attached = perf_counter()
evaluation = stages.acquire(PayloadPolicy.LOAD_ALL)
acquired = perf_counter()
reused = stages.acquire(PayloadPolicy.LOAD_ALL)
finished = perf_counter()
assert reused == evaluation
print(
    {
        "caller stage open": opened - started,
        "first evaluation acquisition": acquired - attached,
        "reused evaluation acquisition": finished - acquired,
    }
)
stages.release()
```

M4's feasibility bridge times its own source opening and bridge construction. It evaluates its supplied stage directly; measurements of the product's source access use `BindingStages` as above to include its evaluation-stage construction.
