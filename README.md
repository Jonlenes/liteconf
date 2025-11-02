# simpleconf

`simpleconf` is a lightweight configuration loader focused on deterministic override rules, explicit layering, and ergonomic access patterns. It embraces boring tooling (plain YAML/JSON/TOML) while solving the painful parts typical projects hit:

- predictable ordering across `base/`, `local/`, environment, and runtime overrides
- structure-preserving deep merge (lists replace, dicts merge)
- attribute and dict access via a single `ConfigView`
- environment interpolation with type coercion
- opt-in validation hooks without mandating a heavyweight framework

## Why another config loader?

Existing Python options shine in specific niches but often trade simplicity for power:

- `dynaconf`, `hydra`, `omegaconf` ship large abstraction layers, CLIs, or plugin registries
- `pydantic-settings` and `environs` center on `.env` files and type validation, not layered YAML
- `configparser` and `ConfigObj` struggle with nested structures

`simpleconf` keeps the learning curve flat while covering the 90% case of layered application configs.

## Install

```bash
pip install simpleconf
```

## Quick start

```python
from pathlib import Path
from simpleconf import ConfigManager, DirectorySource, EnvSource, DictOverlay

manager = ConfigManager(
    sources=[
        DirectorySource(Path("conf/base")),
        DirectorySource(Path("conf/local")),
        EnvSource(prefix="APP", delimiter="__", infer_types=True),
        DictOverlay({"runtime": {"feature_flag": True}}),
    ]
)

cfg = manager.load()

print(cfg.get("messaging.transport.primary"))
# -> "smtp"

cfg.save("debug_config.yml")
```

## Features

- deterministic source ordering; later sources override earlier ones
- automatic parsing for `.yml/.yaml`, `.json`, and `.toml`
- `${ENV_VAR:default}` interpolation inside string values
- environment overlays with case-insensitive prefix matching
- `ConfigView` offering `.get()` with dotted paths, `.to_dict()`, `.as_dataclass()`
- stateless loader: creating a new manager or calling `reload()` rereads from disk

## Project layout

```text
simpleconf/
|-- pyproject.toml
|-- README.md
|-- src/
|   \-- simpleconf/
|       |-- __init__.py
|       |-- core.py
|       |-- errors.py
|       |-- exceptions.py
|       |-- loader.py
|       |-- manager.py
|       |-- merger.py
|       |-- namespaces.py
|       \-- sources.py
\-- tests/
    |-- conftest.py
    |-- fixtures/
    |   |-- base/
    |   |   \-- messaging.yml
    |   |-- local/
    |   |   \-- messaging.yml
    |   \-- prod/
    |       |-- messaging.json
    |       \-- messaging.yml
    |-- test_loader.py
    \-- test_manager.py
```

## License

MIT — do anything you want, just keep the notice.

