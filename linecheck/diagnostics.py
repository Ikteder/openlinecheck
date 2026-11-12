"""Read-only network diagnostics using standard-library and local system tools."""
from __future__ import annotations

import platform
import re
import shutil
import socket
import statistics
import subprocess
import time
from typing import Any


def dns_lookup(host: str) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        addresses = sorted({item[4][0] for item in answers})
        return {"host": host, "lookup_ms": elapsed, "addresses": addresses, "note": "System resolver lookup; caching may affect latency."}
    except OSError as exc:
        return {"host": host, "error": str(exc)}


def _ping_command(host: str, timeout_seconds: float) -> list[str]:
    if platform.system() == "Windows":
        return ["ping", "-n", "1", "-w", str(int(timeout_seconds * 1000)), host]
    if platform.system() == "Darwin":
        return ["ping", "-c", "1", "-W", str(int(timeout_seconds * 1000)), host]
    return ["ping", "-c", "1", "-W", str(max(1, int(timeout_seconds))), host]


def icmp_ping(host: str, count: int = 4, timeout_seconds: float = 2.0) -> dict[str, Any]:
    if not 1 <= count <= 20:
        raise ValueError("ICMP count must be 1..20")
    if not shutil.which("ping"):
        return {"target": host, "available": False, "reason": "System ping command not installed"}
    success = 0
    latencies = []
    for _ in range(count):
        try:
            completed = subprocess.run(
                _ping_command(host, timeout_seconds), capture_output=True, text=True,
                timeout=timeout_seconds + 3, check=False, errors="replace",
            )
            if completed.returncode == 0:
                success += 1
                # Locale-dependent optional extraction; loss is based on exit status only.
                match = re.search(r"(?:time|zeit|temps)[=<]\s*([\d.,]+)\s*ms", completed.stdout, flags=re.IGNORECASE)
                if match:
                    try:
                        latencies.append(float(match.group(1).replace(",", ".")))
                    except ValueError:
                        pass
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "target": host,
        "available": True,
        "sent": count,
        "replied": success,
        "observed_icmp_loss_percent": round((count - success) * 100 / count, 1),
        "median_icmp_rtt_ms": round(statistics.median(latencies), 2) if latencies else None,
        "note": "A small ICMP sample. Firewalls/ICMP filtering can appear as loss; not proof of network packet loss.",
    }


def network_interfaces() -> dict[str, Any]:
    try:
        names = [name for _, name in socket.if_nameindex()]
        return {"names": names, "note": "Names only. Extended interface counters are OS-specific."}
    except OSError as exc:
        return {"error": str(exc)}


def packet_counters() -> dict[str, Any]:
    """Counters are kernel OS data; NOT packet capture/sniffing."""
    system = platform.system()
    if system == "Linux":
        try:
            out = {}
            with open("/proc/net/dev", encoding="utf-8") as handle:
                lines = handle.read().splitlines()[2:]
            for line in lines:
                interface, values = line.rsplit(":", 1)
                nums = [int(value) for value in values.split()]
                if len(nums) >= 16:
                    out[interface.strip()] = {
                        "rx_bytes": nums[0], "rx_packets": nums[1], "rx_errors": nums[2], "rx_drops": nums[3],
                        "tx_bytes": nums[8], "tx_packets": nums[9], "tx_errors": nums[10], "tx_drops": nums[11],
                    }
            return {"platform": system, "interfaces": out, "note": "Cumulative interface counters since boot, not a rate."}
        except OSError as exc:
            return {"platform": system, "error": str(exc)}
    # Cross-platform safe fallback. Do not pretend to parse localized outputs.
    cmd = ["netstat", "-e"] if system == "Windows" else ["netstat", "-ib"]
    if not shutil.which("netstat"):
        return {"platform": system, "available": False, "reason": "netstat unavailable"}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6, errors="replace", check=False)
        return {"platform": system, "available": proc.returncode == 0, "raw_output": proc.stdout[:12000], "note": "Cumulative OS counters; raw platform output, not individual captured packets."}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"platform": system, "error": str(exc)}


def network_rates() -> dict[str, Any]:
    """Read cumulative interface counters and return per-interface rates.

    Reads counters twice with a short interval, then computes bytes/sec deltas.
    Returns a dict keyed by interface name with rx_bps, tx_bps, rx_packets, tx_packets.
    """
    system = platform.system()
    counters = _read_counters()
    if not counters:
        return {"error": "Could not read interface counters"}

    # Wait briefly for a second sample
    time.sleep(1.0)
    counters_after = _read_counters()

    if not counters_after:
        return {"error": "Could not read interface counters on second sample"}

    rates = {}
    for name, prev in counters.items():
        curr = counters_after.get(name)
        if not curr:
            continue
        interval = 1.0  # seconds
        rates[name] = {
            "rx_bps": round((curr["rx_bytes"] - prev["rx_bytes"]) * 8 / interval, 0),
            "tx_bps": round((curr["tx_bytes"] - prev["tx_bytes"]) * 8 / interval, 0),
            "rx_packets": curr["rx_packets"] - prev["rx_packets"],
            "tx_packets": curr["tx_packets"] - prev["tx_packets"],
            "rx_errors": curr["rx_errors"] - prev["rx_errors"],
            "tx_errors": curr["tx_errors"] - prev["tx_errors"],
        }
    return {"interfaces": rates, "note": "Rates are per-second deltas from cumulative kernel counters."}


def _read_counters() -> dict[str, dict]:
    """Read cumulative counters from the OS. Returns dict keyed by interface name."""
    system = platform.system()
    if system == "Linux":
        try:
            out = {}
            with open("/proc/net/dev", encoding="utf-8") as handle:
                lines = handle.read().splitlines()[2:]
            for line in lines:
                interface, values = line.rsplit(":", 1)
                nums = [int(v) for v in values.split()]
                if len(nums) >= 16:
                    out[interface.strip()] = {
                        "rx_bytes": nums[0], "rx_packets": nums[1], "rx_errors": nums[2], "rx_drops": nums[3],
                        "tx_bytes": nums[8], "tx_packets": nums[9], "tx_errors": nums[10], "tx_drops": nums[11],
                    }
            return out
        except OSError:
            return {}
    # Windows: use ctypes GetIfEntry2 — no subprocess, no console window
    if system == "Windows":
        try:
            from ._win_counters import read_counters as _win_read
            out = _win_read()
            if out:
                return out
        except Exception:
            pass
        # Fallback: netstat -e gives total only
        cmd = ["netstat", "-e"]
        if not shutil.which("netstat"):
            return {}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6, errors="replace", check=False)
            if proc.returncode != 0:
                return {}
            lines = proc.stdout.strip().splitlines()
            for line in reversed(lines):
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        return {"Total": {
                            "rx_bytes": int(parts[1]), "rx_packets": int(parts[2]),
                            "tx_bytes": int(parts[5]), "tx_packets": int(parts[6]),
                            "rx_errors": 0, "tx_errors": 0,
                        }}
                    except (ValueError, IndexError):
                        continue
        except (OSError, subprocess.TimeoutExpired):
            pass
        return {}
    # macOS: use netstat -ib
    if system == "Darwin":
        cmd = ["netstat", "-ib"]
        if not shutil.which("netstat"):
            return {}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6, errors="replace", check=False)
            if proc.returncode != 0:
                return {}
            out = {}
            lines = proc.stdout.strip().splitlines()[2:]  # skip header
            for line in lines:
                parts = line.split()
                if len(parts) >= 12:
                    name = parts[0]
                    try:
                        out[name] = {
                            "rx_bytes": int(parts[3]), "rx_packets": int(parts[1]),
                            "tx_bytes": int(parts[9]), "tx_packets": int(parts[7]),
                            "rx_errors": int(parts[4]), "tx_errors": int(parts[10]),
                        }
                    except (ValueError, IndexError):
                        continue
            return out
        except (OSError, subprocess.TimeoutExpired):
            return {}
    return {}


def trace_route(host: str, max_hops: int = 10) -> dict[str, Any]:
    if not 1 <= max_hops <= 30:
        raise ValueError("max_hops must be 1..30")
    if platform.system() == "Windows":
        cmd = ["tracert", "-d", "-h", str(max_hops), "-w", "500", host]
    else:
        cmd = ["traceroute", "-n", "-m", str(max_hops), "-w", "1", host]
    if not shutil.which(cmd[0]):
        return {"target": host, "available": False, "reason": f"{cmd[0]} is not installed"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=35, check=False)
        return {"target": host, "available": True, "exit_code": result.returncode, "raw_output": result.stdout[:16000], "note": "Routers may not respond; missing hops are not definitive packet loss."}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"target": host, "available": False, "reason": str(exc)}


def run_diagnostics(host: str, include_trace: bool = False) -> dict[str, Any]:
    result = {"dns": dns_lookup(host), "icmp": icmp_ping(host), "interfaces": network_interfaces(), "packet_counters": packet_counters()}
    if include_trace:
        result["traceroute"] = trace_route(host)
    return result
