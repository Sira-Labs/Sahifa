"""Exceptions raised by the core. Messages never contain credentials."""


class SahifaError(Exception):
    """Base class for errors the core reports to its caller."""


class SourceError(SahifaError):
    """A source could not be opened, listed or queried."""


class UsageError(SahifaError):
    """The caller passed something the core cannot work with (a bad path, an unknown scheme)."""


class UnsafeValueError(SahifaError):
    """A value cannot be rendered as an SQL literal safely (for example it contains NUL)."""
