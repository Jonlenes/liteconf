"""
LiteConf public API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

from .core import ConfigNode, ensure_config_node
from .errors import (
    LiteConfError,
    InterpolationError,
    UnsupportedFormatError,
    ValidationError,
)
from .loader import LayeredConfigLoader
from .manager import ConfigManager
from .namespaces import ConfigView
from .sources import DictOverlay, DirectorySource, EnvSource, FileSource

LayerLike = Union[str, Path]
OverrideMapping = Mapping[str, object]
Validator = Union[Callable[[ConfigNode], None], Tuple[str, Callable[[ConfigNode], None]]]


def load(
    layers: Optional[Sequence[LayerLike]] = None,
    *,
    env: Optional[str] = None,
    env_var: str = "APP_ENV",
    overrides: Optional[Union[OverrideMapping, MutableMapping[str, object]]] = None,
    validators: Optional[Iterable[Validator]] = None,
) -> ConfigNode:
    """
    Load configuration data from layered folders.
    """
    loader = LayeredConfigLoader(
        layers=layers,
        env=env,
        env_var=env_var,
    )
    config = loader.load(overrides=overrides)

    if validators:
        for validator in validators:
            if isinstance(validator, tuple):
                selector, func = validator
                sub = config.select(selector)
                ensure_config_node(sub, selector)
                func(sub)
            else:
                validator(config)

    return config


__all__ = [
    "ConfigManager",
    "ConfigNode",
    "ConfigView",
    "DictOverlay",
    "DirectorySource",
    "EnvSource",
    "LiteConfError",
    "FileSource",
    "InterpolationError",
    "LayeredConfigLoader",
    "UnsupportedFormatError",
    "ValidationError",
    "ensure_config_node",
    "load",
]
