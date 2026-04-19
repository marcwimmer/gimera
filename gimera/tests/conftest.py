import os
import pytest


@pytest.fixture(autouse=True)
def _ensure_cwd_exists():
    """Guard against the parallel-worker footgun where a previous test
    left cwd pointing at a now-deleted tmp dir. Fixtures like
    monkeypatch.chdir internally call os.getcwd() — if cwd is gone they
    fail before the test body runs."""
    try:
        os.getcwd()
    except (FileNotFoundError, OSError):
        os.chdir("/tmp")
    yield
