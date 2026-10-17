import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# Imports under test must not create bytecode beside existing repository files.
sys.dont_write_bytecode = True


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    cache_dir = Path(__file__).parent / ".pytest_cache"
    config.inicfg["cache_dir"] = str(cache_dir)
    if hasattr(config, "cache"):
        config.cache._cachedir = cache_dir


@pytest.fixture
def sample():
    def load(name):
        path = Path(__file__).parent / "fixtures" / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return load
