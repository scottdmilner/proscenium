"""Bindings: their records, runtime state, source access, and results, apart from the compiled core.

Its subpackages and results module are its API: code outside this package imports runtime, persistence,
source_access, and results, and uses what each exports, never the modules inside them (checked by
tests/bpy_free/test_import_tiers.py). This package imports none of them, so it imports without bpy.
"""
