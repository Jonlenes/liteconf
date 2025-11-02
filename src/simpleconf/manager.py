"""High-level orchestrator for the lightweight ConfigView API."""
from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, Sequence

from .errors import InterpolationError, ValidationError
from .merger import deep_merge
from .namespaces import ConfigView
from .sources import ConfigSource

PLACEHOLDER_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::(?P<default>[^}]*))?\}")


class ConfigManager:
    """Compose a configuration from ordered sources with optional validation."""

    def __init__(self,
                 sources: Sequence[ConfigSource],
                 *,
                 validators: Optional[Sequence[Callable[[ConfigView], None]]] = None,
                 interpolate_env: bool = True,
                 environ: Optional[Mapping[str, str]] = None) -> None:
        self._sources = list(sources)
        self._validators = list(validators or [])
        self._interpolate_env = interpolate_env
        self._environ = environ or os.environ

    @property
    def sources(self) -> Sequence[ConfigSource]:
        return tuple(self._sources)

    def load(self) -> ConfigView:
        payload: Dict[str, Any] = {}
        for source in self._sources:
            fragment = source.load()
            if not isinstance(fragment, Mapping):
                raise ValidationError(
                    f"Config source '{source.name}' returned non-mapping payload: {type(fragment).__name__}"
                )
            payload = deep_merge(payload, fragment)

        if self._interpolate_env:
            resolved = _resolve_placeholders(payload, self._environ)
        else:
            resolved = deepcopy(payload)

        view = ConfigView(resolved)

        for validator in self._validators:
            try:
                validator(view)
            except Exception as exc:  # pragma: no cover - user validator failure
                raise ValidationError(str(exc)) from exc

        return view

    def reload(self) -> ConfigView:
        return self.load()


def _resolve_placeholders(data: Mapping[str, Any],
                          environ: Mapping[str, str]) -> Dict[str, Any]:
    cloned: Dict[str, Any] = deepcopy(dict(data))
    _resolve_inplace(cloned, environ)
    return cloned


def _resolve_inplace(node: MutableMapping[str, Any],
                     environ: Mapping[str, str]) -> None:
    for key, value in list(node.items()):
        if isinstance(value, dict):
            _resolve_inplace(value, environ)
            continue
        if isinstance(value, list):
            node[key] = [_resolve_nested(item, environ) for item in value]
            continue
        node[key] = _resolve_value(value, environ)


def _resolve_nested(value: Any, environ: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        nested = deepcopy(value)
        _resolve_inplace(nested, environ)
        return nested
    if isinstance(value, list):
        return [_resolve_nested(item, environ) for item in value]
    return _resolve_value(value, environ)


def _resolve_value(value: Any, environ: Mapping[str, str]) -> Any:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        if name in environ:
            return environ[name]
        if default is not None:
            return default
        raise InterpolationError(f"Environment variable '{name}' not found")

    return PLACEHOLDER_PATTERN.sub(replace, value)
