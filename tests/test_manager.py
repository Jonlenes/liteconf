from dataclasses import dataclass
from pathlib import Path

import pytest

from simpleconf import ConfigManager, DictOverlay, DirectorySource, EnvSource
from simpleconf.errors import InterpolationError


def test_base_only_load(base_dir: Path) -> None:
    manager = ConfigManager([DirectorySource(base_dir, optional=False)])
    cfg = manager.load()

    assert cfg.get("messaging.transport.primary") == "smtp"
    assert cfg.get("messaging.transport.backup") == "sms"
    assert cfg.get("messaging.channels.email") is True
    assert cfg.get("messaging.channels.sms") is False
    assert cfg.get("messaging.limits.daily") == 1000
    assert cfg.get("messaging.webhook") is None


def test_base_and_local_merge(base_dir: Path, local_dir: Path,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MESSAGING_WEBHOOK", "https://hooks.test/special")

    manager = ConfigManager(
        sources=[
            DirectorySource(base_dir, optional=False),
            DirectorySource(local_dir, optional=False),
        ])

    cfg = manager.load()

    assert cfg.get("messaging.transport.primary") == "slack"
    assert cfg.get("messaging.transport.backup") == "sms"  # retained from base
    assert cfg.get("messaging.transport.features.digest") is True
    assert cfg.get("messaging.transport.features.attachments") is True
    assert cfg.get("messaging.transport.features.emoji") == ":party_parrot:"
    assert cfg.get("messaging.channels.sms") is True  # overridden
    assert cfg.get("messaging.channels.email") is True  # untouched
    assert cfg.get("messaging.channels.push") is True  # new key from local
    assert cfg.get("messaging.webhook") == "https://hooks.test/special"
    assert cfg.get("messaging.limits.daily") == 1000  # missing in local


def test_directory_order_changes_precedence(base_dir: Path, local_dir: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MESSAGING_WEBHOOK", raising=False)

    forward = ConfigManager([
        DirectorySource(base_dir, optional=False),
        DirectorySource(local_dir, optional=False),
    ]).load()

    reversed_cfg = ConfigManager([
        DirectorySource(local_dir, optional=False),
        DirectorySource(base_dir, optional=False),
    ]).load()

    assert forward.get("messaging.transport.primary") == "slack"
    assert reversed_cfg.get("messaging.transport.primary") == "smtp"
    assert forward.get("messaging.channels.push") is True
    assert forward.get("messaging.transport.features.digest") is True
    assert reversed_cfg.get("messaging.transport.features.digest") is False


def test_environment_overlay(monkeypatch: pytest.MonkeyPatch,
                              base_dir: Path) -> None:
    monkeypatch.setenv("APP__MESSAGING__TRANSPORT__RETRIES", "9")
    monkeypatch.setenv("APP__MESSAGING__TRANSPORT__FEATURES__DIGEST", "false")

    manager = ConfigManager(
        sources=[
            DirectorySource(base_dir, optional=False),
            EnvSource(prefix="APP"),
        ])

    cfg = manager.load()
    assert cfg.get("messaging.transport.retries", coerce=int) == 9
    assert cfg.get("messaging.transport.features.digest", coerce=bool) is False


def test_dataclass_projection(base_dir: Path) -> None:
    manager = ConfigManager([DirectorySource(base_dir, optional=False)])
    cfg = manager.load().messaging

    @dataclass
    class Messaging:
        transport: dict
        limits: dict

    projection = cfg.as_dataclass(Messaging)
    assert projection.transport["primary"] == "smtp"
    assert projection.limits["daily"] == 1000


def test_missing_interpolation_raises(base_dir: Path) -> None:
    path = base_dir / "requires_env.yml"
    path.write_text("token: ${MISSING_VAR}", encoding="utf-8")

    manager = ConfigManager([DirectorySource(base_dir, optional=False)])
    try:
        with pytest.raises(InterpolationError):
            manager.load()
    finally:
        path.unlink()


def test_dict_overlay(base_dir: Path) -> None:
    manager = ConfigManager([
        DirectorySource(base_dir, optional=False),
        DictOverlay({"messaging": {
            "transport": {
                "primary": "sms"
            },
            "timeout": 10
        }}),
    ])

    cfg = manager.load()
    assert cfg.get("messaging.transport.primary") == "sms"
    assert cfg.get("messaging.timeout") == 10
