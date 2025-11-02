from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from liteconf import load
from liteconf.core import ConfigNode
from liteconf.errors import InterpolationError, UnsupportedFormatError, ValidationError
from liteconf.exceptions import ConfigNotFoundError, LiteConfError
from liteconf.loader import LayeredConfigLoader
from liteconf.manager import ConfigManager
from liteconf.namespaces import ConfigView
from liteconf.sources import (
    DictOverlay,
    DirectorySource,
    EnvSource,
    FileSource,
    _assign,
)
from liteconf.core import ensure_config_node, resolve_placeholders, _dotted_get  # type: ignore
from liteconf.sources import _read_file as _read_source_file, _rel_keys  # type: ignore
from liteconf.sources import ConfigSource  # type: ignore


def test_confignode_dump_json_yaml_and_invalid(tmp_path: Path) -> None:
    node = ConfigNode({"a": 1, "b": {"c": 2}})

    json_path = tmp_path / "out.json"
    yaml_path = tmp_path / "out.yaml"

    node.dump(json_path)
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"a": 1, "b": {"c": 2}}

    node.dump(yaml_path, format_hint="yaml")
    assert "a: 1" in yaml_path.read_text(encoding="utf-8")

    with pytest.raises(LiteConfError):
        node.dump(tmp_path / "bad.txt", format_hint="txt")


def test_attribute_aliases_and_dotted(tmp_path: Path) -> None:
    data = {
        "with-dash": {"inner-key": 1},
        "class": True,
    }
    node = ConfigNode(data)
    assert node.with_dash.inner_key == 1
    # original keys still work
    assert node["with-dash"]["inner-key"] == 1
    # keyword attribute is available via alias, and original key still accessible
    assert getattr(node, "class") is True
    assert getattr(node, "class_") is True


def test_loader_missing_env_raises(tmp_path: Path) -> None:
    base = tmp_path / "conf" / "base"
    (base / "svc.yml").parent.mkdir(parents=True, exist_ok=True)
    (base / "svc.yml").write_text("token: ${MUST_SET}", encoding="utf-8")
    with pytest.raises(LiteConfError):
        LayeredConfigLoader(layers=[base]).load()


def test_loader_txt_only_and_keypath_empty(tmp_path: Path) -> None:
    # directory with only unsupported files triggers no files found
    d = tmp_path / "cfg"
    d.mkdir(parents=True, exist_ok=True)
    (d / "readme.txt").write_text("ignore", encoding="utf-8")
    with pytest.raises(ConfigNotFoundError):
        LayeredConfigLoader(layers=[d]).load()
    # derive_key_path empty tuple branch
    assert LayeredConfigLoader._derive_key_path(d, d) == ()
    # Force empty ordered_dirs to hit guard
    loader = LayeredConfigLoader(layers=[d])
    loader.layers = tuple()  # type: ignore[assignment]
    with pytest.raises(ConfigNotFoundError):
        loader.load()


def test_loader_no_layers_and_no_files(tmp_path: Path) -> None:
    # No layers specified
    with pytest.raises(ConfigNotFoundError):
        LayeredConfigLoader(layers=[]).load()

    # Layer exists but contains no config files
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ConfigNotFoundError):
        LayeredConfigLoader(layers=[empty_dir]).load()


def test_loader_private_helpers_cover_branches() -> None:
    # _inject with root mapping and non-mapping
    target: dict[str, object] = {}
    LayeredConfigLoader._inject(target, (), {"k": 1})
    assert target == {"k": 1}
    with pytest.raises(ValueError):
        LayeredConfigLoader._inject({}, (), 123)

    # _load_file unsupported extension
    with pytest.raises(ValueError):
        LayeredConfigLoader._load_file(Path("/tmp/config.ini"))


def test_manager_interpolate_toggle_and_validators(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "conf"
    (cfg_dir / "base").mkdir(parents=True, exist_ok=True)
    (cfg_dir / "base" / "service.yml").write_text(
        "url: ${SERVICE_URL:-http://default}\nflag: ${REQUIRED}", encoding="utf-8"
    )

    # Interpolation disabled preserves placeholders
    cfg = ConfigManager([DirectorySource(cfg_dir / "base")], interpolate_env=False).load()
    assert cfg.get("service.url").startswith("${SERVICE_URL")

    # Validator as tuple (selector, func)
    events: list[str] = []

    def validate_service(svc: ConfigView) -> None:
        assert svc.get("url") is not None
        events.append("tuple_ran")

    os.environ["REQUIRED"] = "ok"
    cfg2 = load(layers=[cfg_dir / "base"], validators=[("service", validate_service), lambda root: None])
    assert "tuple_ran" in events

    # Validator raising error is wrapped as ValidationError
    def bad_validator(_: ConfigView) -> None:
        raise RuntimeError("nope")

    with pytest.raises(ValidationError):
        ConfigManager([DirectorySource(cfg_dir / "base")], validators=[bad_validator]).load()


def test_namespaces_wrapping_get_save(tmp_path: Path) -> None:
    view = ConfigView({
        "items": [{"a": 1}, {"a": 2}],
        "nested": {"on": "true"},
    })
    # Lists of dicts are wrapped
    assert view.items[0].a == 1
    # .get with coerce=bool works and invalid returns default
    assert view.get("nested.on", coerce=bool) is True
    assert view.get("nested.off", default=False, coerce=bool) is False

    out = tmp_path / "dump.yml"
    view.save(out)
    assert out.exists()


def test_additional_core_paths_and_overrides(tmp_path: Path) -> None:
    # numeric-leading and space keys become safe attribute aliases
    node = ConfigNode({"1alpha": 10, "has space": 20})
    assert getattr(node, "_1alpha") == 10
    assert node.has_space == 20
    # len and repr
    assert len(node) == 2
    assert "ConfigNode" in repr(node)
    # missing attribute and item
    with pytest.raises(AttributeError):
        _ = node.missing_attr
    with pytest.raises(KeyError):
        _ = node["missing"]
    # get default
    assert node.get("missing", default=7) == 7
    # merge_overrides returns new ConfigNode
    merged = node.merge_overrides({"extra": True, "has space": 21})
    assert isinstance(merged, ConfigNode)
    assert merged.extra is True and merged.has_space == 21
    # apply_overrides error when overriding scalar with mapping
    with pytest.raises(LiteConfError):
        from liteconf.core import apply_overrides as _apply

        target = {"scalar": 1}
        _apply(target, {"scalar": {"nested": 2}})
    # dotted assign creates missing parents
    target2: dict[str, object] = {}
    _apply(target2, {"new.parent.key": 3})
    assert target2 == {"new": {"parent": {"key": 3}}}
    # ensure_config_node raising
    with pytest.raises(LiteConfError):
        ensure_config_node(123, "ref")
    # resolve_placeholders on ConfigNode and list
    cn = ConfigNode({"x": "${X:-1}"})
    resolved = resolve_placeholders(cn)
    assert isinstance(resolved, ConfigNode)
    assert resolved.x == "1"  # fallback applied
    lst = resolve_placeholders(["${Y:-ok}"])
    assert lst == ["ok"]
    # _dotted_get alias path on plain mapping
    assert _dotted_get({"inner_key": 1}, "inner-key") == 1


def test_manager_sources_property_reload_and_bad_source(tmp_path: Path) -> None:
    # Prepare a minimal directory
    base = tmp_path / "conf" / "base"
    (base / "x.yml").parent.mkdir(parents=True, exist_ok=True)
    (base / "x.yml").write_text("a: 1", encoding="utf-8")

    class BadSource:
        name = "bad"

        def load(self):  # type: ignore[override]
            return [1, 2, 3]

    m = ConfigManager([DirectorySource(base)])
    assert isinstance(tuple(m.sources), tuple)
    v1 = m.load()
    v2 = m.reload()
    assert v1.to_dict() == v2.to_dict()

    with pytest.raises(ValidationError):
        ConfigManager([BadSource()]).load()
    # env resolution through nested list
    payload = {"arr": [{"url": "${URL:http://a}"}]}
    cfg = ConfigManager([DictOverlay(payload)]).load()
    assert cfg.get("arr")[0]["url"] == "http://a"
    # also handle nested lists
    cfg2 = ConfigManager([DictOverlay({"nest": [["${N:ok}"]]})]).load()
    assert cfg2.get("nest")[0][0] == "ok"


def test_sources_files_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "srcs"
    root.mkdir(parents=True, exist_ok=True)

    # FileSource with mapping
    f_yaml = root / "cfg.yml"
    f_yaml.write_text("foo: 1", encoding="utf-8")
    assert FileSource(f_yaml).load() == {"foo": 1}

    # FileSource with non-mapping returns {"value": data}
    f_json = root / "list.json"
    f_json.write_text("[1,2,3]", encoding="utf-8")
    assert FileSource(f_json).load() == {"value": [1, 2, 3]}

    # Optional file missing yields {}
    assert FileSource(root / "missing.yml", optional=True).load() == {}

    # DirectorySource recursive and ignores unsupported files
    sub = root / "sub"
    sub.mkdir()
    (sub / "a.yml").write_text("x: 1", encoding="utf-8")
    (sub / "note.txt").write_text("ignore", encoding="utf-8")
    d = DirectorySource(root, recursive=True, optional=False).load()
    assert d["sub"]["a"]["x"] == 1
    assert "note" not in d.get("sub", {})

    # EnvSource coercion
    monkeypatch.setenv("APP__FOO__COUNT", "10")
    monkeypatch.setenv("APP__FOO__RATE", "0.5")
    e = EnvSource(prefix="APP").load()
    assert e["foo"]["count"] == 10
    assert e["foo"]["rate"] == 0.5

    # _assign root non-mapping raises
    with pytest.raises(UnsupportedFormatError):
        _assign({}, [], 5)
    # _assign with mapping at root updates
    target: dict[str, object] = {}
    _assign(target, [], {"ok": True})
    assert target == {"ok": True}

    # FileSource toml handling
    t = root / "cfg.toml"
    t.write_text("x=1\n[y]\nz=2\n", encoding="utf-8")
    loaded = FileSource(t).load()
    assert loaded == {"x": 1, "y": {"z": 2}}
    # _read_file unsupported suffix
    with pytest.raises(UnsupportedFormatError):
        _read_source_file(root / "x.ini")
    # _rel_keys empty parts when file equals root (edge case)
    assert list(_rel_keys(root, root)) == []
    # DirectorySource missing optional and required
    assert DirectorySource(root / "nope", optional=True).load() == {}
    with pytest.raises(FileNotFoundError):
        DirectorySource(root / "nope", optional=False).load()
    # FileSource required missing raises
    with pytest.raises(FileNotFoundError):
        FileSource(root / "nope.json").load()
    # EnvSource leaves unknown types as string
    monkeypatch.setenv("APP__RAW__VALUE", "abc")
    env_loaded = EnvSource(prefix="APP").load()
    assert env_loaded["raw"]["value"] == "abc"
    monkeypatch.setenv("APP__BOOL__FLAG", "on")
    assert EnvSource(prefix="APP").load()["bool"]["flag"] is True


def test_configsource_base_class_notimplemented() -> None:
    with pytest.raises(NotImplementedError):
        ConfigSource().load()


def test_namespaces_more_paths_and_errors(tmp_path: Path) -> None:
    view = ConfigView({"a": 1})
    with pytest.raises(AttributeError):
        _ = view.missing
    with pytest.raises(ValueError):
        view.get("")
    # as_dataclass type check
    with pytest.raises(TypeError):
        view.as_dataclass(dict)  # type: ignore[arg-type]
    # getitem path and coercions
    assert view["a"] == 1
    assert ConfigView({"v": "abc"}).get("v", default=0, coerce=int) == 0
    from liteconf.namespaces import _coerce_bool  # type: ignore

    assert _coerce_bool("on") is True
    assert _coerce_bool("off") is False
    with pytest.raises(ValueError):
        _coerce_bool("maybe")


def test_more_core_paths_covering_lists_and_helpers() -> None:
    node = ConfigNode({"l": [{"a": 1}, {"a": 2}]})
    assert node.l[0].a == 1 and node.l[1].a == 2
    assert node.to_dict() == {"l": [{"a": 1}, {"a": 2}]}
    # MissingEnvVar string form
    from liteconf.core import MissingEnvVar

    assert str(MissingEnvVar("X")) == "${X}"
    # _dotted_get missing key raises
    with pytest.raises(KeyError):
        _dotted_get({}, "nope")
    # apply_overrides recursion branch
    from liteconf.core import apply_overrides as _apply

    target: dict[str, object] = {"a": {"x": 1}}
    _apply(target, {"a": {"y": 2}})
    assert target == {"a": {"x": 1, "y": 2}}
    # __getitem__ via alias and _dotted_get present-key path
    node2 = ConfigNode({"class": True})
    assert node2["class_"] is True
    assert _dotted_get({"key": 1}, "key") == 1
