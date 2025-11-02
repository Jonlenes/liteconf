"""Data sources for ConfigManager."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

import yaml

try:  # pragma: no cover - Python < 3.11
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .errors import UnsupportedFormatError

SUPPORTED_SUFFIXES = {".yml", ".yaml", ".json", ".toml"}


class ConfigSource:
    """Interface describing something that can load configuration fragments."""

    name: str = "source"

    def load(self) -> Dict[str, Any]:
        raise NotImplementedError


def _assign(target: MutableMapping[str, Any], keys: Iterable[str], value: Any) -> None:
    keys_list = list(keys)
    if not keys_list:
        if isinstance(value, Mapping):
            target.update(value)  # type: ignore[arg-type]
        else:
            raise UnsupportedFormatError("Top-level config must be a mapping")
        return

    cursor: MutableMapping[str, Any] = target
    for key in keys_list[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[keys_list[-1]] = value


def _read_file(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFormatError(f"{path} is not a supported config file")

    if suffix in {".yml", ".yaml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _rel_keys(root: Path, file_path: Path) -> Iterable[str]:
    relative = file_path.relative_to(root)
    parts = list(relative.parts)
    if not parts:
        return []
    *directories, filename = parts
    return [*directories, Path(filename).stem]


@dataclass
class DirectorySource(ConfigSource):
    path: Path
    recursive: bool = False
    optional: bool = True
    name: str = "directory"

    def load(self) -> Dict[str, Any]:
        path = self.path
        if not path.exists():
            if self.optional:
                return {}
            raise FileNotFoundError(path)

        result: Dict[str, Any] = {}
        iterator = path.rglob("*") if self.recursive else path.glob("*")
        files = sorted(
            item for item in iterator if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES
        )
        for file_path in files:
            data = _read_file(file_path)
            _assign(result, _rel_keys(path, file_path), data)
        return result


@dataclass
class FileSource(ConfigSource):
    path: Path
    optional: bool = False
    name: str = "file"

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            if self.optional:
                return {}
            raise FileNotFoundError(self.path)
        data = _read_file(self.path)
        return data if isinstance(data, dict) else {"value": data}


@dataclass
class DictOverlay(ConfigSource):
    payload: Mapping[str, Any]
    name: str = "dict"

    def load(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.payload))


@dataclass
class EnvSource(ConfigSource):
    prefix: str
    delimiter: str = "__"
    infer_types: bool = True
    environ: Optional[Mapping[str, str]] = None
    name: str = "env"

    def load(self) -> Dict[str, Any]:
        env = self.environ or os.environ
        prefix_norm = f"{self.prefix.upper()}{self.delimiter}"
        result: Dict[str, Any] = {}

        for key, raw in env.items():
            if not key.upper().startswith(prefix_norm):
                continue
            stripped = key[len(prefix_norm):]
            segments = [segment.lower() for segment in stripped.split(self.delimiter)]
            value = _coerce_env_value(raw) if self.infer_types else raw
            _assign(result, segments, value)
        return result


def _coerce_env_value(value: str) -> Any:
    text = value.strip()
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        try:
            return int(text)
        except ValueError:
            pass
    try:
        return float(text)
    except ValueError:
        return value
