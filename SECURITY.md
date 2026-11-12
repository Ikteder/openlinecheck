# Security and privacy

The starter runs network tests only when invoked. It does not install a service or monitor background traffic. The bundled test server binds to loopback by default. Do not expose it on public interfaces without authentication, rate limiting and other controls.

A configured external speed-test endpoint will see network requests and your source IP. The app does not send your stored results to an analytics service. Advanced diagnostics may include identifying interface names, addresses, gateway information and routing hops, so redact reports before publishing.

No packet sniffing is included. Any future capture functionality must be opt-in, bounded, metadata-only by default, with permissions and a visible recording indicator.

If a security issue is discovered after repository publication, report it privately to the maintainers rather than posting exploit details publicly. The owner should configure GitHub private vulnerability reporting before release.
