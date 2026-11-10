"""Tiny /proc based CPU and memory sampler (no psutil dependency).

CPU% is relative to ONE core (100% = one full vCPU), like `top`.
"""
from __future__ import annotations

import os
import time

_CLK = os.sysconf("SC_CLK_TCK")
_PAGE = os.sysconf("SC_PAGE_SIZE")


def _read(pid: int) -> tuple[float, int] | None:
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().rsplit(")", 1)[1].split()
        cpu_s = (int(parts[11]) + int(parts[12])) / _CLK  # utime + stime
        rss = int(parts[21]) * _PAGE
        return cpu_s, rss
    except (FileNotFoundError, ProcessLookupError, IndexError):
        return None


class ProcSampler:
    def __init__(self) -> None:
        self.pids: dict[str, int] = {}
        self._last: dict[str, tuple[float, float]] = {}

    def track(self, name: str, pid: int) -> None:
        self.pids[name] = pid
        r = _read(pid)
        if r:
            self._last[name] = (time.monotonic(), r[0])

    def sample(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        now = time.monotonic()
        for name, pid in self.pids.items():
            r = _read(pid)
            if not r:
                continue
            cpu_s, rss = r
            t0, c0 = self._last.get(name, (now, cpu_s))
            dt = now - t0
            pct = 100.0 * (cpu_s - c0) / dt if dt > 0 else 0.0
            self._last[name] = (now, cpu_s)
            out[name] = {"cpu_pct": round(pct, 1), "rss_mb": round(rss / 1048576, 1)}
        return out


def host_stats() -> dict[str, float]:
    load1, load5, _ = os.getloadavg()
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
    return {
        "cpus": os.cpu_count() or 0,
        "load1": round(load1, 2),
        "load5": round(load5, 2),
        "mem_total_mb": round(mem["MemTotal"] / 1024),
        "mem_available_mb": round(mem["MemAvailable"] / 1024),
    }
