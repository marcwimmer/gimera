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
    dt = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    path = Path(f"/tmp/gimeratest/{dt}{str(uuid.uuid4())[:5]}")
    path = Path(f"/tmp/gimeratest")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(exist_ok=True, parents=True)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(autouse=True)
def cleangimera_cache():
    cache_dir = Path(os.path.expanduser("~")) / ".cache/gimera"
    backup_dir = cache_dir.parent / f"{cache_dir.name}_backup"
    if cache_dir.exists():
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.move(cache_dir, backup_dir)
    yield
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    if backup_dir.exists():
        shutil.move(backup_dir, cache_dir)
