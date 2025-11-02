"""Config view utilities used by ConfigManager."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Type, TypeVar, Union

import yaml


T = TypeVar("T")


class ConfigView:
    """Lightweight wrapper around nested dictionaries with attribute access."""

    __slots__ = ("_data", "_path")

    def __init__(self, data: Dict[str, Any], path: str = "") -> None:
        self._data = data
        self._path = path

    def __repr__(self) -> str:  # pragma: no cover - repr is for debugging
        return f"ConfigView(path='{self._path}', data={self._data!r})"

    def __getattr__(self, item: str) -> Any:
        if item in self._data:
            return self._wrap_child(item, self._data[item])
        raise AttributeError(f"No configuration value named '{item}'")

    def __getitem__(self, item: str) -> Any:
        value = self._data[item]
        return self._wrap_child(item, value)

    # ------------------------------------------------------------------
    def _wrap_child(self, key: str, value: Any) -> Any:
        if isinstance(value, dict):
            next_path = f"{self._path}.{key}" if self._path else key
            return ConfigView(value, next_path)
        if isinstance(value, list):
            return [
                self._wrap_child(f"{key}[{index}]", element)  # type: ignore[arg-type]
                if isinstance(element, dict) else element
                for index, element in enumerate(value)
            ]
        return value

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self._data)

    def get(self,
            dotted_path: str,
            default: Optional[Any] = None,
            *,
            coerce: Optional[Type[T]] = None) -> Union[Any, T]:
        if not dotted_path:
            raise ValueError("dotted_path must be provided")

        current: Any = self._data
        for part in dotted_path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default

        if coerce is not None:
            try:
                if coerce is bool:
                    return _coerce_bool(current)
                return coerce(current)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default
        return current

    def as_dataclass(self, cls: Type[T]) -> T:
        if not is_dataclass(cls):
            raise TypeError("cls must be a dataclass")

        payload: Dict[str, Any] = {}
        for field in fields(cls):
            if field.name in self._data:
                payload[field.name] = self._data[field.name]
        return cls(**payload)

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(
            yaml.safe_dump(self._data, sort_keys=False, default_flow_style=False),
            encoding="utf-8")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Cannot coerce {value!r} to bool")
