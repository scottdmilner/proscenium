"""Per-platform memory counters, standard library only so the Blender binary's Python can use them too."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# macOS rusage_info_v4 as uint64 words after the 16-byte UUID (<sys/resource.h>).
RUSAGE_INFO_V4 = 4
_RESIDENT, _FOOTPRINT, _LIFETIME_MAX_FOOTPRINT = 6, 7, 28
_WORDS = 64  # more than v4 holds, so a longer struct never overruns


def _rusage(pid: int) -> list[int] | None:
    buffer = (ctypes.c_uint64 * (_WORDS + 2))()  # two words for the UUID
    libc = ctypes.CDLL(None)
    if libc.proc_pid_rusage(ctypes.c_int(pid), ctypes.c_int(RUSAGE_INFO_V4), ctypes.byref(buffer)) != 0:
        return None
    return list(buffer[2:])


def footprint(pid: int) -> int | None:
    """macOS physical footprint (Activity Monitor's Memory column) of a process, in bytes; None elsewhere."""
    if sys.platform != "darwin":
        return None
    words = _rusage(pid)
    return None if words is None else words[_FOOTPRINT]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes' own declaration form
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _MallocStatistics(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes' own declaration form
        ("blocks_in_use", ctypes.c_uint),
        ("size_in_use", ctypes.c_size_t),
        ("max_size_in_use", ctypes.c_size_t),
        ("size_allocated", ctypes.c_size_t),
    ]


class _Mallinfo2(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes' own declaration form
        (name, ctypes.c_size_t)
        for name in (
            "arena",
            "ordblks",
            "smblks",
            "hblks",
            "hblkhd",
            "usmblks",
            "fsmblks",
            "uordblks",
            "fordblks",
            "keepcost",
        )
    ]


def heap_in_use() -> int | None:
    """Bytes this process has allocated through malloc and not freed; None where it can't be read.

    Unlike resident memory or the footprint, it drops as soon as memory is freed, even when the allocator
    keeps the pages: the difference between the two is the allocator's retention."""
    try:
        libc = ctypes.CDLL(None)
        if sys.platform == "darwin":
            stats = _MallocStatistics()
            libc.malloc_zone_statistics(None, ctypes.byref(stats))  # every zone
            return stats.size_in_use
        if sys.platform.startswith("linux"):
            libc.mallinfo2.restype = _Mallinfo2  # glibc 2.33 and later
            info = libc.mallinfo2()
            return info.uordblks + info.hblkhd
    except (AttributeError, OSError):
        return None
    return None


def own_peaks() -> dict[str, int]:
    """This process's lifetime peaks, by counter name, in bytes."""
    if sys.platform == "darwin":
        import os
        import resource

        peaks = {"peak resident": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}  # bytes on macOS
        words = _rusage(os.getpid())
        if words is not None:
            peaks["peak footprint"] = words[_LIFETIME_MAX_FOOTPRINT]
        return peaks
    if sys.platform == "win32":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        windll = getattr(ctypes, "windll")  # noqa: B009 - only defined on Windows
        process = windll.kernel32.GetCurrentProcess()
        windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return {"peak resident": counters.PeakWorkingSetSize}
    import resource

    return {"peak resident": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}  # KiB on Linux
