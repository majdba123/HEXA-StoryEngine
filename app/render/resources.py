"""Bound FFmpeg beat concurrency by observed memory demand."""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

from app.config import RenderResourceSettings

_GIB = 1 << 30
# Sprint 5.1 measured four real 1080p beat encodes from Script Kiddie, Black Hat,
# and Insider Threat at 1/2/4 workers. Maximum observed private memory was 2.78
# GiB for four workers; a single Black Hat encode reached 1.03 GiB. Budget 1.5
# GiB per worker (above either observed per-worker peak) and leave 2 GiB for the
# parent process, OS, and transient encoder allocations. This is a concurrency
# admission budget, not a guarantee against unrelated machine-wide pressure.
_WORKER_BUDGET_BYTES = 3 * _GIB // 2
_HEADROOM_BYTES = 2 * _GIB
_REFERENCE_PIXELS = 1920 * 1080


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def available_memory_bytes() -> int | None:
    """Use the tighter physical/commit slack on Windows, free pages elsewhere."""
    try:
        if os.name == "nt":
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return min(int(status.ullAvailPhys), int(status.ullAvailPageFile))
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size if pages > 0 and page_size > 0 else None
    except (AttributeError, OSError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class RenderConcurrencyPolicy:
    settings: RenderResourceSettings

    def workers(self, *, width: int, height: int, cpu_count: int | None = None,
                available_bytes: int | None = None) -> int:
        # Preserve the legacy explicit override contract, including its 1..8 bounds.
        if self.settings.workers_override is not None:
            return max(1, min(8, self.settings.workers_override))
        cpus = os.cpu_count() if cpu_count is None else cpu_count
        cpu_limit = max(1, min(4, (cpus or 2) // 2))
        free = available_memory_bytes() if available_bytes is None else available_bytes
        if free is None or free <= _HEADROOM_BYTES:
            return 1
        # Larger frames need more filter/overlay buffers. Smaller frames retain the
        # measured 1080p allowance; reducing it would be unmeasured optimism.
        pixel_factor = max(1.0, width * height / _REFERENCE_PIXELS)
        memory_limit = int((free - _HEADROOM_BYTES) // (_WORKER_BUDGET_BYTES * pixel_factor))
        return max(1, min(cpu_limit, memory_limit))
