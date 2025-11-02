class LiteConfError(RuntimeError):
    """Base exception for LiteConf errors."""


class ConfigNotFoundError(LiteConfError):
    """Raised when no configuration files could be located."""
