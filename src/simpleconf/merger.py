"""Utility helpers for deterministic deep merges."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from typing import Any


def deep_merge(base: Mapping[str, Any],
               override: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Return a deep merged mapping without mutating inputs."""
    merged: MutableMapping[str, Any] = deepcopy(dict(base))
    for key, value in override.items():
        if key in merged and isinstance(merged[key], MutableMapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = deepcopy(value)
    return merged
