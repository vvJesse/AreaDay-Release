"""Dependency-free memory metrics for AreaDay extraction."""
from __future__ import annotations

import json
import multiprocessing
import os
import platform
import resource
import time
from pathlib import Path
from typing import Any

FIELDS = (
    "phase", "pid", "ppid", "rss_bytes", "peak_rss_bytes",
    "cgroup_current_bytes", "cgroup_peak_bytes", "cgroup_swap_current_bytes",
    "mem_total_bytes", "mem_available_bytes", "swap_total_bytes",
    "swap_free_bytes", "timestamp",
)


def _parse_bytes(value: str) -> int | None:
    parts = value.strip().split()
    try:
        number = int(parts[0])
    except (IndexError, TypeError, ValueError):
        return None
    return number * 1024 if len(parts) > 1 and parts[1].lower() == "kb" else number


def parse_status(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"VmRSS", "VmHWM"}:
            parsed = _parse_bytes(value)
            if parsed is not None:
                result[key] = parsed
    return result


def parse_smaps_rollup(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"Rss", "Pss"}:
            parsed = _parse_bytes(value)
            if parsed is not None:
                result[key] = parsed
    return result


def parse_meminfo(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            parsed = _parse_bytes(value)
            if parsed is not None:
                result[key] = parsed
    return result


def parse_cgroup_events(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return result


def unified_cgroup_path(cgroup_text: str, mount: Path = Path("/sys/fs/cgroup")) -> Path | None:
    for line in cgroup_text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1] == "":
            return mount / parts[2].lstrip("/")
    return None


def read_cgroup_events(root: Path | None = None) -> dict[str, int]:
    if root is None:
        try:
            content = Path("/proc/self/cgroup").read_text()
        except OSError:
            return {}
        root = unified_cgroup_path(content)
    if root is None:
        return {}
    try:
        return parse_cgroup_events((root / "memory.events").read_text())
    except OSError:
        return {}


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def sample(phase: str) -> dict[str, Any]:
    system = platform.system()
    status = parse_status(_read(Path("/proc/self/status")) or "") if system == "Linux" else {}
    rollup = parse_smaps_rollup(_read(Path("/proc/self/smaps_rollup")) or "") if system == "Linux" else {}
    meminfo = parse_meminfo(_read(Path("/proc/meminfo")) or "") if system == "Linux" else {}
    cgroup: dict[str, int] = {}
    if system == "Linux":
        root = unified_cgroup_path(_read(Path("/proc/self/cgroup")) or "")
        if root is not None:
            for filename, field in (
                ("memory.current", "cgroup_current_bytes"),
                ("memory.peak", "cgroup_peak_bytes"),
                ("memory.swap.current", "cgroup_swap_current_bytes"),
            ):
                value = _read(root / filename)
                if value is not None:
                    try:
                        cgroup[field] = int(value.strip())
                    except ValueError:
                        pass
    rss = rollup.get("Rss", status.get("VmRSS"))
    peak = status.get("VmHWM")
    if system == "Darwin":
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = int(usage.ru_maxrss) if usage.ru_maxrss else None
        peak = rss
    return {
        "phase": phase, "pid": os.getpid(), "ppid": os.getppid(),
        "rss_bytes": rss, "peak_rss_bytes": peak,
        "cgroup_current_bytes": cgroup.get("cgroup_current_bytes"),
        "cgroup_peak_bytes": cgroup.get("cgroup_peak_bytes"),
        "cgroup_swap_current_bytes": cgroup.get("cgroup_swap_current_bytes"),
        "mem_total_bytes": meminfo.get("MemTotal"),
        "mem_available_bytes": meminfo.get("MemAvailable"),
        "swap_total_bytes": meminfo.get("SwapTotal"),
        "swap_free_bytes": meminfo.get("SwapFree"),
        "timestamp": time.time(),
    }


def append_sample(workspace: Path, phase: str, filename: str = "process-memory.jsonl") -> dict[str, Any]:
    row = sample(phase)
    try:
        path = workspace / "analysis" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    except (OSError, TypeError, ValueError):
        pass
    return row


def _monitor_main(workspace: str, interval: float, ready: Any) -> None:
    append_sample(Path(workspace), "monitor", "system-memory.jsonl")
    ready.set()
    while True:
        time.sleep(interval)
        append_sample(Path(workspace), "monitor", "system-memory.jsonl")


class SystemMemoryMonitor:
    """Independent OS process sampler with bounded idempotent shutdown."""

    def __init__(self, workspace: Path, interval: float = 2.0) -> None:
        self.workspace = workspace
        self.interval = min(5.0, max(0.1, interval))
        self._process: multiprocessing.Process | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> "SystemMemoryMonitor":
        if self._process is not None and self._process.is_alive():
            return self
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        self._process = context.Process(
            target=_monitor_main,
            args=(str(self.workspace), self.interval, ready),
            name="areaday-memory-monitor",
            daemon=True,
        )
        self._process.start()
        ready.wait(timeout=1.0)
        return self

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.is_alive():
            process.terminate()
        process.join(timeout=max(1.0, self.interval + 1.0))
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)
        self._process = None
