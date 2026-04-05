import uuid
from datetime import datetime
import pytest
import os
import sys
import shutil
import tempfile
from pathlib import Path


@pytest.fixture(autouse=True)
def set_env_vars():
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"
    os.environ["GIMERA_FORCE"] = "0"
    os.environ["GIMERA_NON_INTERACTIVE"] = "0"
    # otherwise test2 submodules fails; repos are fetched in threads;
    # just happens at tests; perhaps because of pytest - not in real world 
    # (test in console)
    os.environ["GIMERA_NON_THREADED"] = "1"


@pytest.fixture(autouse=True)
def python():
    return sys.executable


@pytest.fixture(autouse=True)
def temppath():
    path = Path(f"/tmp/gimeratest/{uuid.uuid4().hex[:8]}").resolve()
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(exist_ok=True, parents=True)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(autouse=True)
def cleangimera_cache(tmp_path):
    cache_dir = tmp_path / "gimera_cache"
    cache_dir.mkdir()
    os.environ["GIMERA_CACHE_DIR"] = str(cache_dir)
    yield
    os.environ.pop("GIMERA_CACHE_DIR", None)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
