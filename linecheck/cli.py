"""Command-line entrypoint: python -m linecheck"""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .diagnostics import run_diagnostics
from .errors import CancelledError
from .measure import DEFAULT_ORIGIN, run_speed_test


def _number(value: float | None, unit: str) -> str:
    return "unavailable" if value is None else f"{value:.2f} {unit}"


def _format_quality(quality: str | None) -> str:
    """Format a quality/confidence tag."""
    if quality is None:
        return ""
    labels = {"high": "✓ high confidence", "medium": "~ medium confidence", "low": "! low confidence"}
    return labels.get(quality, quality)


def format_report(record: dict) -> str:
    speed = record["speed"]
    latency = speed["latency"]
    lines = [
        "OpenLineCheck • Network check",
        "=" * 40,
        f"Server      : {speed['origin']}",
        f"Profile     : {speed['profile']}",
        f"Download    : {_number(speed['download']['mbps'], 'Mbps')} {_format_quality(speed['download'].get('quality'))}",
        f"Upload      : {_number(speed['upload']['mbps'], 'Mbps') if speed['upload'] else 'skipped'} {_format_quality(speed['upload'].get('quality') if speed['upload'] else None)}",
        f"HTTPS RTT   : {_number(latency['median_ms'], 'ms')} (median; includes TLS/setup)",
        f"Jitter      : {_number(latency['jitter_ms'], 'ms')} (HTTPS request variation)",
        f"Probe errors: {latency['attempts']-latency['successful']}/{latency['attempts']} (NOT packet loss)",
    ]
    data = speed.get("data_usage", {})
    if data:
        dl_mb = data.get("download_bytes", 0) / 1_000_000
        ul_mb = data.get("upload_bytes", 0) / 1_000_000
        lines.append(f"Data used   : {dl_mb:.1f} MB down / {ul_mb:.1f} MB up")
    for direction in ("download", "upload"):
        value = speed[direction]
        if value and value.get("message"):
            lines.append(f"{direction.title()} warning: {value['message']}")
    advanced = record.get("advanced")
    if advanced:
        lines.append("\nAdvanced diagnostics")
        lines.append("-" * 40)
        dns = advanced["dns"]
        icmp = advanced["icmp"]
        lines.append(f"DNS lookup  : {_number(dns.get('lookup_ms'), 'ms')}")
        if icmp.get("available"):
            lines.append(f"ICMP loss   : {icmp['observed_icmp_loss_percent']:.1f}% ({icmp['sent']} attempts)")
            lines.append(f"ICMP RTT    : {_number(icmp['median_icmp_rtt_ms'], 'ms')}")
        else:
            lines.append(f"ICMP        : unavailable ({icmp.get('reason')})")
        lines.append(f"Interfaces  : {', '.join(advanced['interfaces'].get('names', [])) or 'unavailable'}")
        counters = advanced.get("packet_counters", {})
        lines.append(f"Packet stats: {len(counters.get('interfaces', {}))} interfaces (see JSON for details)" if "interfaces" in counters else "Packet stats: platform details available in JSON")
        if "traceroute" in advanced:
            trace = advanced["traceroute"]
            lines.append("Traceroute  : " + ("collected (see JSON)" if trace.get("available") else str(trace.get("reason", "unavailable"))))
    lines.append("\nNote: Results depend on server and route; HTTPS RTT is not ICMP ping.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linecheck", description="Lightweight free network speed test and read-only diagnostics"
    )
    parser.add_argument("--origin", default=DEFAULT_ORIGIN, help="Cloudflare-compatible test origin (default: speed.cloudflare.com)")
    parser.add_argument("--profile", choices=("quick", "standard"), default="quick", help="Trade data usage for accuracy")
    parser.add_argument("--latency-samples", type=int, default=5, metavar="N", help="1..20 HTTPS RTT probes")
    parser.add_argument("--no-upload", action="store_true", help="Skip upload traffic")
    parser.add_argument("--advanced", action="store_true", help="Add DNS, ICMP, interface names, packet counters")
    parser.add_argument("--trace", action="store_true", help="Add optional system traceroute (implies --advanced)")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--output", type=Path, metavar="FILE", help="Write JSON report to this local file")
    parser.add_argument("--version", action="version", version=f"OpenLineCheck {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cancelled = False

    def _sigint_handler(signum, frame):
        nonlocal cancelled
        cancelled = True

    # Register SIGINT handler for graceful cancellation
    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except (OSError, ValueError):
        # signal.signal not available on all platforms (e.g., some embedded)
        pass

    cancel = lambda: cancelled

    try:
        speed = run_speed_test(
            origin=args.origin,
            profile=args.profile,
            attempts=args.latency_samples,
            no_upload=args.no_upload,
            progress=(lambda msg: print(f"  {msg}...", file=sys.stderr)) if not args.json else None,
            cancel=cancel,
        )
        report = {"speed": speed.as_dict()}
        if args.advanced or args.trace:
            if not args.json:
                print("  Collecting optional diagnostics...", file=sys.stderr)
            host = urlsplit(args.origin).hostname
            report["advanced"] = run_diagnostics(host, include_trace=args.trace)
        json_text = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_text + "\n", encoding="utf-8")
        print(json_text if args.json else format_report(report))
        if cancelled:
            print("\nTest cancelled.", file=sys.stderr)
            return 130  # Standard SIGINT exit code
        return 0 if speed.download.mbps is not None or speed.latency.median_ms is not None else 1
    except CancelledError:
        print("\nTest cancelled.", file=sys.stderr)
        return 130
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
