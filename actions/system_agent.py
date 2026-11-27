"""
system_agent.py — VINCEVISION PC health & system monitor
────────────────────────────────────────────────────────
Voice-queryable system status: CPU, RAM, disk, battery, uptime, network,
and the top processes. Uses psutil (already a dependency); imported lazily
so the module loads even where psutil is absent.

Actions: status / cpu / memory / disk / battery / network / processes / uptime
"""

import sys
import time
from pathlib import Path

psutil = None  # lazily populated; tests may inject a fake


def _get_psutil():
    global psutil
    if psutil is None:
        import psutil as _p
        psutil = _p
    return psutil


# ── pure formatting helpers (unit-tested) ───────────────────────

def format_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} PB"


def format_uptime(seconds: float) -> str:
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def format_overview(d: dict) -> str:
    lines = ["🖥️  SYSTEM STATUS"]
    lines.append(f"  CPU:    {d.get('cpu_percent', 0):.0f}%  ({d.get('cpu_count', '?')} cores)")
    mem = d.get("memory", {})
    lines.append(f"  RAM:    {mem.get('percent', 0):.0f}%  "
                 f"({format_bytes(mem.get('used', 0))} / {format_bytes(mem.get('total', 0))})")
    disk = d.get("disk", {})
    lines.append(f"  Disk:   {disk.get('percent', 0):.0f}%  "
                 f"({format_bytes(disk.get('free', 0))} free)")
    bat = d.get("battery")
    if bat:
        plug = "plugged in" if bat.get("power_plugged") else "on battery"
        lines.append(f"  Battery:{bat.get('percent', 0):.0f}%  ({plug})")
    else:
        lines.append("  Battery: n/a (desktop / no sensor)")
    lines.append(f"  Uptime: {format_uptime(d.get('uptime_seconds', 0))}")
    return "\n".join(lines)


def format_processes(procs: list) -> str:
    if not procs:
        return "No process data available, sir."
    lines = ["Top processes:"]
    for p in procs:
        lines.append(f"  {p.get('pid', '?'):>7}  {p.get('name', '?')[:24]:<24} "
                     f"CPU {p.get('cpu', 0):.0f}%  RAM {p.get('mem', 0):.1f}%")
    return "\n".join(lines)


# ── data gathering (psutil; mockable) ───────────────────────────

def gather_overview() -> dict:
    p = _get_psutil()
    vm = p.virtual_memory()
    try:
        disk = p.disk_usage(str(Path.home()))
        disk_d = {"percent": disk.percent, "free": disk.free, "total": disk.total}
    except Exception:
        disk_d = {"percent": 0, "free": 0, "total": 0}
    battery = None
    try:
        b = p.sensors_battery()
        if b is not None:
            battery = {"percent": b.percent, "power_plugged": b.power_plugged}
    except Exception:
        pass
    return {
        "cpu_percent": p.cpu_percent(interval=0.3),
        "cpu_count": p.cpu_count(),
        "memory": {"percent": vm.percent, "used": vm.used, "total": vm.total},
        "disk": disk_d,
        "battery": battery,
        "uptime_seconds": max(0, time.time() - p.boot_time()),
    }


def top_processes(n: int = 5, sort: str = "cpu") -> list:
    p = _get_psutil()
    procs = []
    for proc in p.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            procs.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "?",
                "cpu": info.get("cpu_percent") or 0.0,
                "mem": info.get("memory_percent") or 0.0,
            })
        except Exception:
            continue
    key = "mem" if sort == "memory" else "cpu"
    procs.sort(key=lambda x: x[key], reverse=True)
    return procs[:max(1, n)]


# ── entry point ─────────────────────────────────────────────────

def system_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    try:
        _get_psutil()
    except Exception:
        return "System monitoring needs psutil. Install it with: pip install psutil"

    try:
        if action in ("status", "overview", "health", "all"):
            data = gather_overview()
            text = format_overview(data)
            if speak:
                speak(f"CPU at {data['cpu_percent']:.0f} percent, "
                      f"memory at {data['memory']['percent']:.0f} percent, sir.")
            return text

        if action == "cpu":
            p = _get_psutil()
            pct = p.cpu_percent(interval=0.5)
            if speak: speak(f"CPU is at {pct:.0f} percent, sir.")
            return f"CPU: {pct:.0f}% across {p.cpu_count()} cores."

        if action in ("memory", "ram"):
            vm = _get_psutil().virtual_memory()
            if speak: speak(f"Memory is at {vm.percent:.0f} percent, sir.")
            return (f"RAM: {vm.percent:.0f}% used "
                    f"({format_bytes(vm.used)} / {format_bytes(vm.total)}).")

        if action == "disk":
            d = _get_psutil().disk_usage(str(Path.home()))
            return (f"Disk: {d.percent:.0f}% used, {format_bytes(d.free)} free "
                    f"of {format_bytes(d.total)}.")

        if action == "battery":
            b = _get_psutil().sensors_battery()
            if b is None:
                return "No battery detected (desktop or no sensor), sir."
            plug = "plugged in" if b.power_plugged else "on battery"
            if speak: speak(f"Battery at {b.percent:.0f} percent, {plug}, sir.")
            return f"Battery: {b.percent:.0f}% ({plug})."

        if action == "uptime":
            up = format_uptime(max(0, time.time() - _get_psutil().boot_time()))
            return f"Uptime: {up}, sir."

        if action in ("processes", "top", "tasks"):
            n = int(params.get("count", 5) or 5)
            sort = "memory" if str(params.get("sort", "cpu")).lower() in ("memory", "ram") else "cpu"
            return format_processes(top_processes(n, sort))

        if action == "network":
            io = _get_psutil().net_io_counters()
            return (f"Network I/O: {format_bytes(io.bytes_sent)} sent, "
                    f"{format_bytes(io.bytes_recv)} received.")

        return ("❌ Unknown system action. Try: status, cpu, memory, disk, "
                "battery, network, processes, uptime.")
    except Exception as e:
        return f"System check failed: {e}"
