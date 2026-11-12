# Contributing

OpenLineCheck is an MIT-licensed, privacy-first network diagnostics prototype. Issues and code contributions are welcome once the repository is published.

Please preserve the key promise: minimal dependencies, bounded network traffic, transparent measurement methodology, and optional (never automatic) advanced probes.

## Before opening a pull request

1. Run `python -m unittest discover -s tests -v` from the repository root.
2. Add an offline test for changes to the measurement engine; tests should never depend on the public Internet.
3. Describe your platform, Python version, expected data use and how a metric was measured.
4. For Windows changes, include actual Windows 11 command output (redact identifying addresses).
5. Never add third-party telemetry, unsafe default network capture, or privileged operations without explicit opt-in and a reviewed design.

External code must be appropriately licensed; do not copy LGPL or proprietary source into this MIT starter.
