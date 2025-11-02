from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from simpleconf import ConfigNode, load


def _write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False)


def _write_toml(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def test_local_overrides_base(tmp_path: Path) -> None:
    base = tmp_path / "conf" / "base"
    local = tmp_path / "conf" / "local"

    _write_yaml(
        base / "messaging.yml",
        {"transport": {"primary": "smtp", "retries": 2}},
    )
    _write_yaml(
        local / "messaging.yml",
        {"transport": {"primary": "slack"}},
    )

    config = load(layers=[base, local])

    assert isinstance(config, ConfigNode)
    assert config.messaging.transport.primary == "slack"
    assert config.messaging.transport.retries == 2


def test_environment_folder_is_used(tmp_path: Path) -> None:
    base = tmp_path / "conf" / "base"
    local = tmp_path / "conf" / "local"

    _write_yaml(base / "service.yml", {"url": "https://api.dev", "retries": 1})
    _write_yaml(local / "service.yml", {"retries": 3})
    _write_yaml(base / "prod" / "service.yml", {"url": "https://api.prod"})

    config = load(layers=[base, local], env="prod")

    assert config.service.url == "https://api.prod"
    assert config.service.retries == 3


def test_placeholders_are_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local = tmp_path / "conf" / "local"

    monkeypatch.setenv("MESSAGING_PASSWORD", "secret")
    monkeypatch.delenv("MESSAGING_USER", raising=False)

    _write_yaml(
        local / "messaging.yml",
        {
            "credentials": {
                "user": "${MESSAGING_USER:-guest}",
                "password": "${MESSAGING_PASSWORD}",
            }
        },
    )

    config = load(layers=[local])

    assert config.messaging.credentials.user == "guest"
    assert config.messaging.credentials.password == "secret"


def test_dotted_overrides(tmp_path: Path) -> None:
    base = tmp_path / "conf" / "base"
    _write_yaml(base / "trainer.yml", {"epochs": 5, "optimizer": {"lr": 0.001}})

    config = load(layers=[base], overrides={"trainer.optimizer.lr": 0.01, "trainer.name": "baseline"})

    assert config.trainer.optimizer.lr == 0.01
    assert config.trainer.name == "baseline"
    assert config.trainer.epochs == 5


def test_mixed_formats(tmp_path: Path) -> None:
    base = tmp_path / "conf" / "base"
    local = tmp_path / "conf" / "local"

    _write_yaml(base / "model.yml", {"name": "resnet", "version": 1})
    _write_toml(local / "model.toml", 'version = 2\n[metrics]\naccuracy = 0.9\n')

    config = load(layers=[base, local])

    assert config.model.name == "resnet"
    assert config.model.version == 2
    assert config.model.metrics.accuracy == 0.9


def test_fixture_base_only_load(base_dir: Path) -> None:
    config = load(layers=[base_dir])

    assert config.messaging.transport.primary == "smtp"
    assert config.messaging.transport.backup == "sms"
    assert config.messaging.channels.email is True
    assert config.messaging.channels.sms is False


def test_fixture_base_and_local_merge(base_dir: Path, local_dir: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MESSAGING_WEBHOOK", "https://hooks.fixture/notify")
    config = load(layers=[base_dir, local_dir])

    assert config.messaging.transport.primary == "slack"
    assert config.messaging.transport.backup == "sms"
    assert config.messaging.transport.features.emoji == ":party_parrot:"
    assert config.messaging.channels.sms is True
    assert config.messaging.channels.push is True
    assert config.messaging.channels.email is True
    assert config.messaging.limits.daily == 1000
    assert config.messaging.webhook == "https://hooks.fixture/notify"


def test_fixture_with_prod_layer(base_dir: Path, local_dir: Path, prod_dir: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MESSAGING_WEBHOOK", raising=False)
    config = load(layers=[base_dir, local_dir, prod_dir])

    assert config.messaging.transport.retries == 6  # overridden by prod json
    assert config.messaging.transport.backup == "pagerduty"
    assert config.messaging.alerts.priority == "high"
    assert config.messaging.alerts.pager is True
    assert config.messaging.channels.voice is True
    assert config.messaging.limits.daily == 1000
    assert config.messaging.limits.burst == 50


def test_fixture_layer_order_changes_result(base_dir: Path, local_dir: Path,
                                            prod_dir: Path) -> None:
    forward = load(layers=[base_dir, local_dir, prod_dir])
    reversed_config = load(layers=[prod_dir, local_dir, base_dir])

    assert forward.messaging.transport.primary == "slack"
    assert reversed_config.messaging.transport.primary == "smtp"
    assert forward.messaging.transport.backup == "pagerduty"
    assert reversed_config.messaging.transport.backup == "sms"
