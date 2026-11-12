# OpenLineCheck — engineering plan

## Product promise

One-click, low-data, low-overhead *speed + latency* first; opt-in network troubleshooting when the simple result isn't enough. Free, local-first, no accounts, no background network calls. Windows 11 first, then macOS/Linux, with equal semantics.

## Personas

1. Home user: speed and latency in one click, no jargon, a clear explanation if a measurement is unavailable.
2. Gamer/streamer/remote worker: jitter, ICMP nonresponse, loaded latency and actionable troubleshooting.
3. IT / developer: deterministic CLI, JSON, comparisons, DNS routes, packet counters, reports.
4. Teacher/student: each metric includes a brief explanation and measurement method.

## UI views

- **Simple (default)**: connection indicator, Download, Upload, Latency, Jitter, server, one Start button, quick/standard selection; no packet tools exposed until Advanced opened.
- **Advanced**: separate tabs for Connectivity (DNS/ping/traceroute), Stability (latency series, loaded RTT, ICMP sample), Interface (NIC/Wi-Fi/counters), Traffic (per-interface rates and opt-in capture), History.
- **Explain this result**: never conflate HTTPS RTT with ICMP RTT, TCP timeouts with loss, or PHY link speed with throughput. Explain effect of VPN, Wi-Fi, proxy, and server.
- **Privacy**: obvious indicator when tests send traffic; raw IPs redacted in share mode.

## Milestones and acceptance criteria

### M0 — starter included in this archive
- [x] Zero dependency Python 3.10+ CLI and basic Tkinter UI
- [x] Cloudflare-compatible fixed-size GET/POST tests with bounded profiles
- [x] HTTPS RTT median/P95/jitter and clear definitions
- [x] Optional DNS, ICMP sample, interface names, kernel packet counters, traceroute
- [x] JSON output, configurable compatible endpoint, no-upload mode
- [x] Offline tests with loopback HTTP server and multi-OS CI configuration
- [ ] Validate on actual Windows 11 hardware and live Cloudflare endpoint

### M1 — correctness and resilience (before public launch)
- [ ] Run real tests on Windows 11; fix platform-specific issues
- [ ] Inspect latency implementation vs Cloudflare engine; isolate handshake/TTFB/network RTT where possible
- [ ] Improve throughput accuracy via warm-up, time-window sampling and bounded dynamic payload sizing
- [ ] Track per-stage, per-stream successes/failures and confidence; fail transparently if server refuses upload
- [ ] Test low/high bandwidth, IPv4/IPv6, proxy/VPN, flaky networks, rate limiting, offline, DNS failures, cancellation
- [ ] Add progress/cancel with propagated cancellation; avoid orphan test threads
- [x] Add initial bounded manual test server (loopback/LAN); more protocol/cancellation tests pending
- [ ] Unit/integration tests for timeouts, partial transfers, HTTP errors, test-data caps

### M2 — polished lightweight desktop app
- [ ] Refine Tkinter UI (or justify small compiled GUI tech) with live chart and accessible theme
- [ ] Separate Quick, Standard and Advanced profiles with consent/data estimates
- [ ] Add real-time packet/byte counters (rates from delta per wall-clock interval)
- [ ] Add Windows adapter properties, SSID/channel/signal via OS APIs; Linux/macOS fallbacks
- [ ] Add loaded latency / bufferbloat testing with rigorous methodology
- [ ] Local JSONL/SQLite history and CSV exports; privacy-redacted sharing
- [ ] Error and uncertainty explanations that make metrics understandable

### M3 — optional expert capabilities
- [ ] ICMP/TCP/UDP reachability modes; differentiate modes and endpoints
- [ ] DNS comparison, resolver preference and TTL-aware interpretation
- [ ] Path hop trends and root-cause hints (gateway versus external target)
- [ ] Optional explicit per-interface packet capture (metadata first, strict caps, no default payload capture; libpcap/Npcap capability detection and rights checks)
- [ ] Optional TCP retransmissions/socket stats via platform APIs, not speculative inference
- [ ] Safe device discovery only on own networks and only after explicit opt-in (not necessary for core product)
- [ ] Optional schedule/alerts with clear traffic/data budgets, fully disabled by default

### M4 — distribution / public GitHub
- [ ] Decide and document whether Python + Tkinter is small enough; consider single-binary Go core only if justified
- [ ] Windows x64 portable zip or signed installer if feasible; cross-platform binaries with integrity hashes
- [ ] GitHub Release automation, SBOM, dependency audit, reproducible tagged source
- [ ] Public demo screenshot, issue templates, CONTRIBUTING, SECURITY, changelog
- [ ] MIT notices, source-only licensing checks, no copying from LGPL code

## Product success metrics

- Default one-click run on clean Windows 11 without account or administrator rights.
- Zero automatic telemetry, packet capture, app background traffic, paid API requirements.
- CI offline tests pass on Windows/Linux/macOS.
- Clear and truthful field definitions; user can export exact methods with each result.
- Basic run bounded to <~7 MB test payload; higher-data mode clearly disclosed.
- Test network failure does not freeze UI or invent speed/packet loss results.

## Risk register

- Third-party endpoint changes or rate-limits → pluggable/self-hosted server, friendly error, never fake a result.
- Unrealistic 1 Gbps claims from short downloads → calibrated profiles, confidence/quality tags, caution labels.
- Misinterpreted packet loss → ICMP is sampled nonresponse; TCP/HTTPS errors separate.
- OS-specific command differences → feature detection and test each OS; no elevated operations by default.
- Capture privacy/consent → manual opt-in, short retention, no payloads by default.
- HTTP upload can be acknowledged before confirmed bytes consumed → use test-specific server protocol/receipts before calibrated reporting.
