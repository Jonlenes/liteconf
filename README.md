# simpleconf

[![PyPI version](https://img.shields.io/pypi/v/simpleconf.svg)](https://pypi.org/project/simpleconf/)
[![Python versions](https://img.shields.io/pypi/pyversions/simpleconf.svg)](https://pypi.org/project/simpleconf/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Build](https://github.com/jonlenes/simpleconf/actions/workflows/tests.yml/badge.svg)](https://github.com/jonlenes/simpleconf/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/jonlenes/simpleconf/branch/main/graph/badge.svg)](https://codecov.io/gh/jonlenes/simpleconf)

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

## Quick Start (Practical)

Consider this minimal layout (two folders + one JSON):

```text
conf/
  base/
    service.yml
  local/
    service.yml
extra.json
```

`conf/base/service.yml`

```yaml
service:
  url: https://api.base
  retries: 2
  features:
    cache: false
    logging: warn   # defined only in base
```

`conf/local/service.yml`

```yaml
service:
  url: https://api.local          # overrides base
  retries: 3                      # overrides base; later overridden by extra.json
  features:
    cache: true                   # overrides base
    tracing: true                 # added by local
  webhook: "${SERVICE_WEBHOOK:https://hooks.local/notify}"  # env placeholder with default
```

`extra.json`

```json
{
  "service": {
    "retries": 5,                 
    "timeout": 10,                
    "endpoint": { "health": "/health" }  
  }
}
```

Load everything with explicit source order (later wins):

```python
from pathlib import Path
from simpleconf import ConfigManager, DirectorySource, FileSource, EnvSource

manager = ConfigManager([
    DirectorySource(Path("conf/base"), optional=False),
    DirectorySource(Path("conf/local"), optional=True),
    FileSource(Path("extra.json"), optional=True),
    # Optional: environment overlay, e.g. APP__SERVICE__TIMEOUT=30
    EnvSource(prefix="APP", delimiter="__", infer_types=True),
])

cfg = manager.load()

# Value defined only in base
assert cfg.get("service.features.logging") == "warn"

# Values overridden by local
assert cfg.service.url == "https://api.local"
assert cfg.service.features.cache is True

# Value added by local
assert cfg.get("service.features.tracing") is True

# Overridden by local, then by extra.json (final)
assert cfg.service.retries == 5  # base=2 -> local=3 -> extra.json=5

# Values provided only by extra.json
assert cfg.service.timeout == 10
assert cfg.service.endpoint.health == "/health"

# You can use attribute-style or dotted lookups interchangeably
assert cfg.service.url == cfg.get("service.url")

# Save a copy if useful for debugging
cfg.save("debug_config.yml")
```

Notes:
- The filename forms the first key: `service.yml` becomes top-level key `service`.
- Attribute access (`cfg.service.url`) and dotted lookups (`cfg.get("service.url")`) both work.
- Source order matters: items from later sources override earlier ones.

## Features

- deterministic source ordering; later sources override earlier ones
- automatic parsing for `.yml/.yaml`, `.json`, and `.toml`
- `${ENV_VAR:default}` interpolation inside string values
- environment overlays with case-insensitive prefix matching
- `ConfigView` offering `.get()` with dotted paths, `.to_dict()`, `.as_dataclass()`
- stateless loader: creating a new manager or calling `reload()` rereads from disk

## Environment Overrides (Two Ways)

1) Inline placeholders inside files (resolved at load time):

```yaml
# in conf/local/service.yml
service:
  webhook: "${SERVICE_WEBHOOK:https://hooks.local/notify}"
```

- If `SERVICE_WEBHOOK` is set in the environment, its value is used.
- Otherwise, the default `https://hooks.local/notify` is used.

2) Environment overlay with a prefix (no file edits needed):

```bash
# Let’s suppose you want to raise the timeout via an env var
export APP__SERVICE__TIMEOUT=30
pytest  # or run your app; the manager will pick it up
```

With `EnvSource(prefix="APP", delimiter="__", infer_types=True)`, keys map as:
- `APP__SERVICE__TIMEOUT=30` -> `service.timeout = 30` (int)
- `APP__SERVICE__FEATURES__CACHE=false` -> `service.features.cache = False` (bool)

## Loading: One-Call vs Explicit Sources

- Quick one-call loader for folders only:

  ```python
  from simpleconf import load
  cfg = load(layers=[Path("conf/base"), Path("conf/local")])
  # Recursively loads .yml/.yaml/.json/.toml; later folders override earlier
  ```

- Explicit sources for full control (files, env, dict overlays, optional flags):

  ```python
  from simpleconf import ConfigManager, DirectorySource, FileSource, EnvSource, DictOverlay
  manager = ConfigManager([
      DirectorySource(Path("conf/base")),
      DirectorySource(Path("conf/local")),
      FileSource(Path("extra.json")),
      EnvSource(prefix="APP"),
      DictOverlay({"runtime": {"feature_flag": True}}),
  ])
  cfg = manager.load()
  ```

Use `load(...)` when you just need layered folders; use `ConfigManager` when you want to precisely choose and order different kinds of sources.

## File Precedence and Duplicate Stems

- Across sources: later sources override earlier ones.
- Within a single folder: files are applied in lexicographic filename order.
- If both `messaging.json` and `messaging.yml` exist in the same folder:
  - One-call `load(...)` (LayeredConfigLoader): both are merged; later filename wins for overlapping keys (usually YAML after JSON).
  - Explicit `DirectorySource` (ConfigManager): later filename replaces the earlier file’s subtree at that key entirely.

Recommendation: avoid keeping two files with the same stem (e.g., `messaging.*`) in the same folder. Prefer a single file per logical key per layer to keep intent crystal clear.

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

