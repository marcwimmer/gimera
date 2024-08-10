import os
import shutil
import pytest
import tempfile
from pathlib import Path


@pytest.fixture(autouse=True)
def set_env_vars():
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"


@pytest.fixture(autouse=True)
def python():
    return sys.executable


@pytest.fixture(autouse=True)
def temppath():
    path = Path(tempfile.mktemp(suffix=""))
    path = Path("/tmp/gimeratest")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(exist_ok=True)
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


from . import tools
from . import test_gimera
from . import test_snapshots
from . import test_git
