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
