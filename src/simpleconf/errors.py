"""Exception types for the LiteConf API."""
from __future__ import annotations

from .exceptions import LiteConfError


class UnsupportedFormatError(LiteConfError):
    """Raised when a configuration file format is not supported."""


class InterpolationError(LiteConfError):
    """Raised when environment interpolation cannot resolve a placeholder."""


class ValidationError(LiteConfError):
    """Raised when a user-supplied validator fails."""


__all__ = [
    "LiteConfError",
    "UnsupportedFormatError",
    "InterpolationError",
    "ValidationError",
]
