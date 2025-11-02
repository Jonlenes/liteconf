from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from keyword import iskeyword
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .exceptions import LiteConfError

PLACEHOLDER_PATTERN = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<fallback>[^}]*))?\}")


def _sanitize_attribute(name: str) -> str:
    clean = name.replace("-", "_").replace(" ", "_")
    if clean and clean[0].isdigit():
        clean = f"_{clean}"
    if iskeyword(clean):
        clean = f"{clean}_"
    return clean or name


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return ConfigNode(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def _unwrap(value: Any) -> Any:
    if isinstance(value, ConfigNode):
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    return value


@dataclass(frozen=True)
class MissingEnvVar:
    name: str

    def __str__(self) -> str:
        return f"${{{self.name}}}"


class ConfigNode(Mapping[str, Any]):
    """
    Immutable mapping with attribute-style access.
    Nested dictionaries are converted recursively into ConfigNode instances.
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self._data: Dict[str, Any] = {}
        self._aliases: Dict[str, str] = {}

        if data:
            for key, value in data.items():
                alias = _sanitize_attribute(key)
                if alias != key and alias not in self._aliases:
                    self._aliases[alias] = key
                self._data[key] = _wrap(value)

    def __getattr__(self, item: str) -> Any:
        if item in self._data:
            return self._data[item]
        if item in self._aliases:
            return self._data[self._aliases[item]]
        raise AttributeError(f"ConfigNode has no attribute '{item}'") from None

    def __getitem__(self, item: str) -> Any:
        if item in self._data:
            return self._data[item]
        if item in self._aliases:
            return self._data[self._aliases[item]]
        raise KeyError(item)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        payload = json.dumps(self.to_dict(), indent=2, default=str, ensure_ascii=False)
        return f"ConfigNode({payload})"

    def get(self, dotted_path: str, default: Any = None) -> Any:
        try:
            return self.select(dotted_path)
        except KeyError:
            return default

    def select(self, dotted_path: str) -> Any:
        """
        Return the value at ``dotted_path``, raising KeyError if missing.
        """
        current: Any = self
        for part in dotted_path.split("."):
            current = _dotted_get(current, part)
        return current

    def to_dict(self) -> Dict[str, Any]:
        return {key: _unwrap(value) for key, value in self._data.items()}

    def dump(self, path: Path, *, format_hint: Optional[str] = None) -> None:
        """
        Persist the configuration to disk.

        Args:
            path: Destination path.
            format_hint: Optional override for format (``json`` or ``yaml``).
        """
        suffix = (format_hint or path.suffix.lstrip(".") or "json").lower()
        payload = self.to_dict()

        if suffix in {"yaml", "yml"}:
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover - dependency missing
                raise LiteConfError("PyYAML is required to dump YAML files") from exc
            with path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        elif suffix == "json":
            with path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        else:  # pragma: no cover - user error
            raise LiteConfError(f"Unsupported dump format: {suffix}")

    def merge_overrides(self, overrides: Mapping[str, Any]) -> "ConfigNode":
        """
        Return a new ConfigNode with overrides applied.
        """
        cloned = copy.deepcopy(self.to_dict())
        apply_overrides(cloned, overrides)
        return ConfigNode(cloned)


def _dotted_get(value: Any, key: str) -> Any:
    if isinstance(value, ConfigNode):
        return value[key]
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        alias = _sanitize_attribute(key)
        if alias in value:
            return value[alias]
    raise KeyError(key)


def apply_overrides(target: MutableMapping[str, Any], overrides: Mapping[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, Mapping):
            section = target.setdefault(key, {})
            if not isinstance(section, MutableMapping):
                raise LiteConfError(
                    f"Cannot override non-mapping config section '{key}' with a mapping."
                )
            apply_overrides(section, value)
        else:
            if "." in key:
                _assign_dotted(target, key, value)
            else:
                target[key] = value


def _assign_dotted(target: MutableMapping[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    current: MutableMapping[str, Any] = target
    for part in parts[:-1]:
        part_alias = _sanitize_attribute(part)
        for candidate in (part, part_alias):
            if candidate in current and isinstance(current[candidate], MutableMapping):
                current = current[candidate]  # type: ignore[assignment]
                break
        else:
            current = current.setdefault(part, {})  # type: ignore[assignment]
    current[parts[-1]] = value


def ensure_config_node(value: Any, ref: str) -> None:
    if not isinstance(value, ConfigNode):
        raise LiteConfError(f"Expected ConfigNode at '{ref}', got {type(value).__name__}")


def resolve_placeholders(data: Any, *, env_lookup: Optional[Mapping[str, str]] = None) -> Any:
    """
    Expand ``${VAR}`` and ``${VAR:-fallback}`` placeholders recursively.
    """
    env_lookup = env_lookup or {}

    if isinstance(data, ConfigNode):
        return ConfigNode({k: resolve_placeholders(v, env_lookup=env_lookup) for k, v in data.items()})
    if isinstance(data, dict):
        return {k: resolve_placeholders(v, env_lookup=env_lookup) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_placeholders(item, env_lookup=env_lookup) for item in data]
    if isinstance(data, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group("name")
            fallback = match.group("fallback")
            if name in env_lookup:
                return env_lookup[name]
            if fallback is not None:
                return fallback
            raise LiteConfError(f"Environment variable '{name}' is required but not set.")

        return PLACEHOLDER_PATTERN.sub(repl, data)
    return data


def deep_merge(base: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> MutableMapping[str, Any]:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], MutableMapping) and isinstance(value, Mapping):
            deep_merge(base[key], value)  # type: ignore[arg-type]
        else:
            base[key] = copy.deepcopy(value)
    return base
