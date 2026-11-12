"""Custom exception hierarchy for OpenLineCheck."""


class LineCheckError(Exception):
    """Base exception for all OpenLineCheck errors."""


class MeasurementError(LineCheckError):
    """A measurement stage failed (server error, timeout, etc.)."""


class ServerError(MeasurementError):
    """The test server returned an unexpected response."""


class TimeoutError(LineCheckError):
    """A measurement timed out."""


class NetworkError(LineCheckError):
    """No network connectivity or DNS failure."""


class CancelledError(LineCheckError):
    """The user cancelled the test."""


class DiagnosticError(LineCheckError):
    """An optional diagnostic tool failed."""
