# `results`

What operations on a binding report: result states and diagnostics ([Diagnostics](../../../../../docs/spec/pipeline.md#diagnostics)). The lowest tier, so it never imports `bpy`. `__init__.py` exports the names callers use; its modules are the unit's own.

| Path | Holds |
|---|---|
| `__init__.py` | The unit's exports: the public names of its two modules. |
| `diagnostics.py` | `Diagnostic`, one reported problem or state; `DiagnosticCode`, the stable codes, each with one `DiagnosticCategory` and `Severity`; `PLANNER_CODES`, the codes the planner reports; and `deduplicated_diagnostics`, which aggregates repeated problems. The binding-state records store diagnostics too. |
| `operation_results.py` | `Result`, whose state derives from its aggregated diagnostics (`result_state`) and never from its cleanup status; `ResultState`; and `DiagnosticCollector`, which gathers an operation's diagnostics as its steps run. Imports `diagnostics.py`. |
