"""Unit tests for gimera.filelock.FileLock."""
import os
import time
from pathlib import Path

import pytest

from ..filelock import FileLock, FileLockException


@pytest.fixture
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_acquire_and_release(chdir_tmp):
    lock = FileLock("a", timeout=1, delay=0.01)
    lock.acquire()
    try:
        assert lock.is_locked
        assert Path(lock.lockfile).exists()
    finally:
        lock.release()
    assert not lock.is_locked
    assert not Path(lock.lockfile).exists()


def test_context_manager(chdir_tmp):
    with FileLock("b", timeout=1, delay=0.01) as lock:
        assert lock.is_locked
        assert Path(lock.lockfile).exists()
    assert not Path(lock.lockfile).exists()


def test_second_acquire_times_out(chdir_tmp):
    first = FileLock("c", timeout=1, delay=0.01)
    first.acquire()
    try:
        second = FileLock("c", timeout=0.1, delay=0.01)
        with pytest.raises(FileLockException):
            second.acquire()
    finally:
        first.release()


def test_none_timeout_raises_immediately(chdir_tmp):
    first = FileLock("d", timeout=1, delay=0.01)
    first.acquire()
    try:
        second = FileLock("d", timeout=None, delay=0.01)
        with pytest.raises(FileLockException):
            second.acquire()
    finally:
        first.release()


def test_timeout_without_delay_raises():
    with pytest.raises(ValueError):
        FileLock("e", timeout=1, delay=None)


def test_release_when_not_locked_is_noop(chdir_tmp):
    lock = FileLock("f", timeout=1, delay=0.01)
    lock.release()
    assert not lock.is_locked


def test_del_releases(chdir_tmp):
    lock = FileLock("g", timeout=1, delay=0.01)
    lock.acquire()
    lockfile = Path(lock.lockfile)
    assert lockfile.exists()
    del lock
    assert not lockfile.exists()


def test_failed_construction_leaves_a_usable_object():
    """__del__ runs on half-built objects too.

    FileLock("e", delay=None) raises before __init__ finishes. Python still
    calls __del__ on the wreck, which called release() -> self.is_locked and
    died with AttributeError. Exceptions from __del__ are swallowed, so this
    only ever surfaced as a pytest warning -- but on an object that already
    held the lock the same path means the lockfile stays behind.
    """
    lock = FileLock.__new__(FileLock)
    with pytest.raises(ValueError):
        lock.__init__("e", timeout=1, delay=None)

    lock.release()  # must not raise AttributeError
    assert lock.is_locked is False


def test_lockfile_name_is_what_wait_git_lock_watches(tmp_path, monkeypatch):
    """The stale-lock recovery has to target the file that really appears.

    FileLock appends ".lock", so handing it ".../gimera.lock" produces
    ".../gimera.lock.lock". wait_git_lock used to watch the undoubled name,
    which nothing creates -- so a lock from a killed process was never
    cleaned up.
    """
    monkeypatch.chdir(tmp_path)
    given = tmp_path / "gimera.lock"
    lock = FileLock(given, timeout=1, delay=0.01)

    assert Path(lock.lockfile) != given
    lock.acquire()
    try:
        assert Path(lock.lockfile).exists()
        assert not given.exists(), "the undoubled name is never created"
    finally:
        lock.release()


def test_stale_lock_is_cleaned_up_instead_of_blocking(tmp_path, monkeypatch):
    """End to end: a leftover lock older than the timeout must not block."""
    from ..tools import wait_git_lock

    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    index_lock = repo / ".git" / "index.lock"
    index_lock.write_text("")
    stale = Path(
        FileLock(repo / ".git" / "gimera.lock", timeout=1, delay=0.01).lockfile
    )
    stale.write_text("")

    long_ago = time.time() - 7200  # MAX_TIMEOUT is 3600
    for f in (index_lock, stale):
        os.utime(f, (long_ago, long_ago))

    started = time.time()
    with wait_git_lock(repo):
        pass

    assert time.time() - started < 30, "blocked on a lock it should have cleared"
    assert not index_lock.exists()
