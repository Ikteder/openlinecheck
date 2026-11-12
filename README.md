# OpenLineCheck

**Fast answers about your internet connection. Detailed diagnostics only when you need them.**

OpenLineCheck is a lightweight, open-source network speed test and monitoring toolkit for Windows. It provides a CLI speed test, a floating real-time network monitor widget, and optional advanced diagnostics — all in pure Python with zero external dependencies.

![OpenLineCheck Monitor](docs/screenshot.png)

## Features

### 🚀 Speed Test (CLI)
- **HTTPS download/upload** via Cloudflare's speed endpoints
- **Latency & jitter** measurement (median, P95, MAD)
- **Quick** and **Standard** profiles (bounded traffic)
- **JSON output** for scripting
- **Local test server** for LAN/loopback measurements

### 📊 Floating Network Monitor
- **Real-time rates** for every interface (Wi-Fi, Ethernet, VPN, etc.)
- **Zero console flash** — runs silently in the background
- **Draggable** — click and drag to reposition
- **Red/Black/White** minimal design, always-on-top
- **No dependencies** — pure Python with Tkinter

### 🔍 Advanced Diagnostics
- ICMP ping sampling
- DNS lookup timing
- Network interface names & cumulative packet counters
- Traceroute (optional)
- Per-interface statistics

## Install / Run

**Requirements:** Python 3.10+ · No external packages · Windows 10/11

### Quick Start

```powershell
# Speed test
py -m linecheck

# Advanced diagnostics
py -m linecheck --advanced

# JSON output
py -m linecheck --json

# Floating monitor (silent, no console)
wscript Start-Monitor.vbs
```

### Editable Install

```powershell
python -m pip install -e .
linecheck
```

## Commands

| Command | Description |
| --- | --- |
| `py -m linecheck` | Quick speed/latency test |
| `py -m linecheck --profile standard` | Higher-data multi-stage measurement |
| `py -m linecheck --advanced` | ICMP, DNS, interfaces, packet counters |
| `py -m linecheck --advanced --trace` | Add traceroute |
| `py -m linecheck --no-upload` | Skip upload test |
| `py -m linecheck --json` | JSON to stdout |
| `py -m linecheck --output reports/check.json` | Write local JSON report |
| `py -m linecheck.server --port 8765` | Start local test server |
| `py -m linecheck --origin http://127.0.0.1:8765` | Test local server |
| `python -m unittest discover -s tests -v` | Offline tests |

## Project Layout

```text
openlinecheck/
  linecheck/              Core CLI, measurement engine & server
    __main__.py           python -m linecheck
    cli.py                Argument parsing, human/JSON output
    measure.py            HTTPS speed/latency engine
    diagnostics.py        DNS, ICMP, interface, counter, route tools
    server.py             Optional bounded local test server
    _win_counters.py      Windows network counter reader
  monitor.py              Floating real-time network monitor widget
  Start-Monitor.vbs       Silent launcher (no console window)
  tests/                  Offline unit & loopback tests
  docs/                   Roadmap & screenshots
  pyproject.toml          Package config
  .github/workflows/      CI on Windows, Linux, macOS
```

## How It Works

### Speed Test Engine
- **HTTPS Latency:** 5 zero-byte GET requests → median, P95, MAD
- **Download:** 1–3 concurrent requests to exact-size payloads → fastest stage
- **Upload:** Bounded fixed-size payloads → acknowledged-request estimate
- **Jitter:** Variation of successful HTTPS timings

### Network Monitor
- Reads cumulative kernel counters via PowerShell (`Get-NetAdapterStatistics`)
- Computes per-second deltas for live Mbps/KBps display
- Runs hidden via `subprocess.CREATE_NO_WINDOW` — zero console flash
- Updates every 2 seconds via Tkinter's `after()` loop

## Accuracy Notes

- Results vary by server, route, and protocol — not a calibrated instrument
- HTTP transfer speed includes DNS, TLS, and request overhead
- ICMP non-response may be firewall policy, not packet loss
- No telemetry, no auto-update, no background daemon

## Security & Privacy

- Local-first, no account, no telemetry
- Default profile sends ≤7 MB of test traffic
- No test results uploaded automatically
- Never use for scanning networks you don't own

## Development

```powershell
python -m unittest discover -s tests -v
```

CI runs on Windows, Linux, and macOS across multiple Python versions.

## License

Apache-2.0. Copyright (c) 2026 OpenLineCheck contributors.
