"""Minimal, bounded HTTP network measurements. No third-party dependencies."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
import statistics
import threading
import time
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

DEFAULT_ORIGIN = "https://speed.cloudflare.com"
MAX_WORKERS = 3
MAX_BYTES_PER_REQUEST = 16_000_000
MAX_TOTAL_DOWNLOAD_BYTES = 50_000_000  # 50 MB hard cap
MAX_TOTAL_UPLOAD_BYTES = 20_000_000    # 20 MB hard cap
Progress = Callable[[str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class ProbeSummary:
    method: str
    target: str
    attempts: int
    successful: int
    median_ms: float | None
    p95_ms: float | None
    jitter_ms: float | None
    failed_probe_percent: float
    samples_ms: list[float]


@dataclass(frozen=True)
class TransferSummary:
    mbps: float | None
    bytes_transferred: int
    successful_requests: int
    failed_requests: int
    message: str | None
    quality: str = "unknown"  # low | medium | high confidence


@dataclass(frozen=True)
class SpeedResult:
    version: str
    timestamp_utc: str
    origin: str
    profile: str
    latency: ProbeSummary
    download: TransferSummary
    upload: TransferSummary | None
    notes: list[str]
    data_usage: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Origin must be an http(s) URL, e.g. https://speed.cloudflare.com")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Origin must be a bare origin with no credentials/path/query/fragment")
    # Limit unnecessary traffic on accidentally supplied service URLs.
    return origin.rstrip("/")


def _down_url(origin: str, size: int) -> str:
    # Unique query busts shared intermediate caches without generating user identifiers.
    return f"{origin}/__down?{urlencode({'bytes': size, 'ts': time.time_ns()})}"


def _check_cancel(cancel: CancelCallback | None) -> None:
    """Raise CancelledError if the cancel callback returns True."""
    if cancel is not None and cancel():
        raise CancelledError("Measurement cancelled by user")


class CancelledError(Exception):
    """Raised when the user cancels an in-progress measurement."""


def _request_download(
    origin: str,
    size: int,
    timeout: float,
    cancel: CancelCallback | None = None,
) -> tuple[int, float]:
    """Download exactly *size* bytes in streaming chunks.

    Returns (bytes_received, elapsed_seconds).
    Raises IOError if the server returns a different byte count.
    """
    if not 0 <= size <= MAX_BYTES_PER_REQUEST:
        raise ValueError("Download request size is outside safe bounds")
    _check_cancel(cancel)
    request = Request(
        _down_url(origin, size),
        headers={"Cache-Control": "no-store", "Accept-Encoding": "identity", "User-Agent": "OpenLineCheck/0.1"},
    )
    start = time.perf_counter()
    received = 0
    with urlopen(request, timeout=timeout) as response:
        # Streaming: do not retain entire transfer in memory.
        while True:
            _check_cancel(cancel)
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            received += len(chunk)
    elapsed = time.perf_counter() - start
    if received != size:
        raise IOError(f"Server returned {received} bytes; requested {size} bytes")
    return received, max(elapsed, 1e-9)


def _request_upload(
    origin: str,
    size: int,
    timeout: float,
    cancel: CancelCallback | None = None,
) -> tuple[int, float, Optional[int]]:
    """Upload *size* bytes and return (bytes_sent, elapsed_s, received_bytes_or_None).

    received_bytes comes from X-Received-Bytes header when the server supports it.
    HTTP 2xx acknowledges the request but cannot prove every byte was processed.
    """
    if not 0 <= size <= MAX_BYTES_PER_REQUEST:
        raise ValueError("Upload request size is outside safe bounds")
    _check_cancel(cancel)
    # Small bounded payload; for high-end bandwidth testing use a streaming client in v2.
    payload = b"x" * size
    request = Request(
        f"{origin}/__up",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "Cache-Control": "no-store", "User-Agent": "OpenLineCheck/0.1"},
    )
    start = time.perf_counter()
    received_bytes = None
    with urlopen(request, timeout=timeout) as response:
        response.read()  # consume response body
        received_header = response.headers.get("X-Received-Bytes")
        if received_header is not None:
            try:
                received_bytes = int(received_header)
            except (ValueError, TypeError):
                received_bytes = None
            if received_bytes != size:
                raise IOError(f"Server receipt mismatch: expected {size}, acknowledged {received_bytes}")
    elapsed = time.perf_counter() - start
    return size, max(elapsed, 1e-9), received_bytes


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * q
    low = math.floor(index)
    high = math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def measure_https_latency(
    origin: str,
    attempts: int = 5,
    timeout: float = 5.0,
    cancel: CancelCallback | None = None,
) -> ProbeSummary:
    """Measure HTTPS round-trip latency via zero-byte GET requests.

    Each probe measures DNS + TCP handshake + TLS handshake + TTFB.
    This is NOT ICMP RTT.
    Returns partial results if cancelled.
    """
    origin = validate_origin(origin)
    if not 1 <= attempts <= 20:
        raise ValueError("Latency attempts must be between 1 and 20")
    samples: list[float] = []
    for i in range(attempts):
        try:
            _check_cancel(cancel)
        except CancelledError:
            # Return partial results on cancellation
            break
        try:
            _, elapsed = _request_download(origin, 0, timeout, cancel)
            samples.append(round(elapsed * 1000, 3))
        except CancelledError:
            break
        except (OSError, HTTPError, URLError, ValueError):
            pass
    jitter = statistics.mean(abs(b - a) for a, b in zip(samples, samples[1:])) if len(samples) > 1 else None
    return ProbeSummary(
        method="HTTPS request completion time (includes DNS/TCP/TLS; not ICMP ping)",
        target=origin,
        attempts=attempts,
        successful=len(samples),
        median_ms=round(statistics.median(samples), 2) if samples else None,
        p95_ms=round(_percentile(samples, .95), 2) if samples else None,
        jitter_ms=round(jitter, 2) if jitter is not None else None,
        failed_probe_percent=round((attempts - len(samples)) * 100 / attempts, 1),
        samples_ms=samples,
    )


def _transfer_stage(
    origin: str,
    direction: str,
    size: int,
    workers: int,
    timeout: float,
    cancel: CancelCallback | None = None,
) -> tuple[int, float, int, int, str | None]:
    """Run one transfer stage with concurrent workers.

    Returns (bytes_transferred, wall_time_s, succeeded, failed, first_error_or_None).
    """
    task = _request_download if direction == "download" else _request_upload
    transferred = 0
    succeeded = 0
    failed = 0
    errors: list[str] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: list[Future] = []
        for _ in range(workers):
            _check_cancel(cancel)
            if direction == "download":
                futures.append(pool.submit(task, origin, size, timeout, cancel))
            else:
                futures.append(pool.submit(task, origin, size, timeout, cancel))
        for future in as_completed(futures):
            try:
                result = future.result()
                count = result[0]  # bytes_sent/received
                transferred += count
                succeeded += 1
            except CancelledError:
                raise
            except (OSError, HTTPError, URLError, ValueError) as exc:
                failed += 1
                errors.append(f"{type(exc).__name__}: {exc}")
    wall = max(time.perf_counter() - started, 1e-9)
    return transferred, wall, succeeded, failed, errors[0] if errors else None


def measure_transfer(
    origin: str,
    direction: str,
    profile: str = "quick",
    timeout: float = 8.0,
    progress: Progress | None = None,
    cancel: CancelCallback | None = None,
    total_cap: int = MAX_TOTAL_DOWNLOAD_BYTES,
) -> TransferSummary:
    """Measure throughput for one direction across multiple stages.

    Uses a warm-up stage (single small request) before reporting best speed.
    Applies a hard cap on total bytes transferred.
    """
    origin = validate_origin(origin)
    if direction not in ("download", "upload") or profile not in ("quick", "standard"):
        raise ValueError("Invalid transfer direction or profile")
    plans = {
        "download": {"quick": [(512_000, 1), (2_000_000, 2)], "standard": [(1_000_000, 1), (4_000_000, 2), (8_000_000, 3)]},
        "upload": {"quick": [(256_000, 1), (1_000_000, 2)], "standard": [(256_000, 1), (1_000_000, 2), (2_000_000, 3)]},
    }
    total_bytes = total_successes = total_failures = 0
    best_mbps: float | None = None
    last_error = None
    stage_list = plans[direction][profile]

    # Warm-up stage: single small request to prime connections
    if progress:
        progress(f"{direction.title()} warm-up")
    _check_cancel(cancel)
    try:
        _transfer_stage(origin, direction, 256_000, 1, timeout, cancel)
    except CancelledError:
        raise
    except Exception:
        pass  # Warm-up failures are non-fatal

    for index, (size, workers) in enumerate(stage_list, start=1):
        _check_cancel(cancel)
        # Enforce hard cap on total bytes
        if total_bytes + size > total_cap:
            if progress:
                progress(f"{direction.title()} stage {index}/{len(stage_list)} (capped)")
            remaining = total_cap - total_bytes
            if remaining <= 0:
                break
            size = remaining
        if progress:
            progress(f"{direction.title()} stage {index}/{len(stage_list)} ({workers} stream{'s' if workers != 1 else ''})")
        amount, wall, succeeded, failed, error = _transfer_stage(origin, direction, size, workers, timeout, cancel)
        total_bytes += amount
        total_successes += succeeded
        total_failures += failed
        if error:
            last_error = error
        if succeeded:
            mbps = (amount * 8) / (wall * 1_000_000)
            best_mbps = max(best_mbps or 0.0, mbps)
        if failed:
            # Never imply a healthy/saturated line when a stage is partially failing.
            break

    # Determine quality tag based on stage success ratio
    total_stages_attempted = total_successes + total_failures
    if total_stages_attempted == 0:
        quality = "low"
    elif total_failures == 0:
        quality = "high" if total_stages_attempted >= 2 else "medium"
    elif total_failures < total_stages_attempted:
        quality = "medium"
    else:
        quality = "low"

    return TransferSummary(
        mbps=round(best_mbps, 2) if best_mbps is not None else None,
        bytes_transferred=total_bytes,
        successful_requests=total_successes,
        failed_requests=total_failures,
        message=last_error,
        quality=quality,
    )


def run_speed_test(
    origin: str = DEFAULT_ORIGIN,
    profile: str = "quick",
    attempts: int = 5,
    no_upload: bool = False,
    progress: Progress | None = None,
    cancel: CancelCallback | None = None,
) -> SpeedResult:
    """Run a complete speed test with download, upload, and latency measurements.

    Supports cancellation via *cancel* callback. Raises CancelledError if cancelled.
    """
    origin = validate_origin(origin)
    if profile not in ("quick", "standard"):
        raise ValueError("Profile must be quick or standard")
    if progress:
        progress("Measuring idle HTTPS latency")
    latency = measure_https_latency(origin, attempts, cancel=cancel)
    download = measure_transfer(
        origin, "download", profile, progress=progress, cancel=cancel,
    )
    upload = None
    if not no_upload:
        if progress:
            progress("Measuring upload speed")
        upload = measure_transfer(
            origin, "upload", profile, progress=progress, cancel=cancel,
            total_cap=MAX_TOTAL_UPLOAD_BYTES,
        )
    total_dl = download.bytes_transferred if download else 0
    total_ul = upload.bytes_transferred if upload else 0
    return SpeedResult(
        version="0.1.0",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        origin=origin,
        profile=profile,
        latency=latency,
        download=download,
        upload=upload,
        notes=[
            "HTTPS latency includes DNS, connection setup and TLS; it is NOT ICMP ping.",
            "Jitter is the mean absolute difference of successive successful HTTPS probes.",
            "HTTPS probe failures are NOT packet loss. Use --advanced for ICMP loss estimates.",
            "Throughput is best completed HTTP stage using application bytes / wall time, not line-rate capacity.",
            "Speeds depend on server, path, Wi-Fi and protocol overhead; results may differ from other testers.",
        ],
        data_usage={"download_bytes": total_dl, "upload_bytes": total_ul},
    )
