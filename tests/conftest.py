from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def base_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "base"


@pytest.fixture
def local_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "local"


@pytest.fixture
def prod_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "prod"
