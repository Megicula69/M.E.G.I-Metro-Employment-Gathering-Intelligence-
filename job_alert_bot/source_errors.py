"""Provider errors that are safe to show without exposing credentials."""


class SourceFailure(Exception):
    kind = "unavailable"


class QuotaExhausted(SourceFailure):
    kind = "quota_exhausted"


class AuthenticationFailure(SourceFailure):
    kind = "authentication_failed"


class TemporarySourceFailure(SourceFailure):
    kind = "temporary_error"

    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
