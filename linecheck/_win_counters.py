"""Network rate reader for Windows — Popen CREATE_NO_WINDOW, zero flash."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile


def read_counters() -> dict[str, dict]:
    """Read per-interface counters using PowerShell with CREATE_NO_WINDOW."""
    script = r"""
$adapters = Get-NetAdapter | Where-Object {$_.Status -eq 'Up'}
if ($adapters) {
    $results = @()
    foreach ($a in $adapters) {
        $stats = Get-NetAdapterStatistics -Name $a.Name
        $results += [PSCustomObject]@{
            Name = $a.Name
            RxBytes = $stats.ReceivedBytes
            TxBytes = $stats.SentBytes
            RxPackets = $stats.ReceivedUnicastPackets
            TxPackets = $stats.SentUnicastPackets
        }
    }
    $results | ConvertTo-Json -Compress
} else { '[]' }
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8') as f:
        f.write(script)
        script_path = f.name

    try:
        # Use Popen (not run) — CREATE_NO_WINDOW works reliably with Popen
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return {}

        if proc.returncode != 0:
            return {}

        try:
            items = json.loads(out.decode("utf-8"))
            if isinstance(items, dict):
                items = [items]
            out_dict = {}
            for item in items:
                name = item.get("Name", "Unknown")
                out_dict[name] = {
                    "rx_bytes": int(item.get("RxBytes", 0) or 0),
                    "tx_bytes": int(item.get("TxBytes", 0) or 0),
                    "rx_packets": int(item.get("RxPackets", 0) or 0),
                    "tx_packets": int(item.get("TxPackets", 0) or 0),
                    "rx_errors": 0,
                    "tx_errors": 0,
                }
            if out_dict:
                return out_dict
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

    return {}
