"""Tests for `gimera cache` (issue #25).

The point of the command is disk that nobody can account for, so the tests
care about two things above all: that it never deletes an entry the user did
not agree to, and that it does delete the things that are provably dead.
"""

import time

import pytest

from ..cachemaint import clean
from ..cachemaint import format_size
from ..cachemaint import iter_entries
from ..cachemaint import stray_tarballs


def _entry(root, name, size=10, with_tar=0):
    path = root / name
    (path / "objects").mkdir(parents=True)
    (path / "objects" / "pack").write_bytes(b"x" * size)
    if with_tar:
        (root / f"{name}.tar.gz").write_bytes(b"y" * with_tar)
    return path


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    return root


class TestListing:
    def test_reports_size_and_tarball(self, cache):
        _entry(cache, "github.com-odoo-odoo", size=100, with_tar=50)

        entries = list(iter_entries(cache))

        assert len(entries) == 1
        assert entries[0]["size"] == 100
        assert entries[0]["tar_size"] == 50

    def test_a_loose_file_is_not_an_entry(self, cache):
        (cache / "stray.txt").write_text("x")

        assert list(iter_entries(cache)) == []


class TestStrayTarballs:
    def test_found_when_the_directory_is_gone(self, cache):
        (cache / "gone.tar.gz").write_bytes(b"x" * 20)

        assert [x.name for x in stray_tarballs(cache)] == ["gone.tar.gz"]

    def test_not_reported_while_the_directory_exists(self, cache):
        _entry(cache, "still-here", with_tar=20)

        assert stray_tarballs(cache) == []


class TestClean:
    def test_removes_tarballs_but_keeps_the_cache(self, cache):
        path = _entry(cache, "github.com-odoo-odoo", size=100, with_tar=50)
        (cache / "orphan.tar.gz").write_bytes(b"z" * 7)

        freed = clean(cache)

        assert freed == 57
        assert path.exists(), "the cache itself must survive"
        assert not (cache / "github.com-odoo-odoo.tar.gz").exists()
        assert not (cache / "orphan.tar.gz").exists()

    def test_keeps_everything_without_unused_for(self, cache):
        old = _entry(cache, "ancient", size=10)
        long_ago = time.time() - 400 * 86400
        import os

        os.utime(old, (long_ago, long_ago))

        clean(cache)

        assert old.exists(), "age alone must not delete anything"

    def test_idle_entry_is_removed_when_asked(self, cache, monkeypatch):
        old = _entry(cache, "ancient", size=10)
        fresh = _entry(cache, "recent", size=10)
        now = time.time()
        _age(old, now - 400 * 86400)
        _age(fresh, now)

        freed = clean(cache, unused_for=90, force=True, now=now)

        assert not old.exists()
        assert fresh.exists(), "a recently used entry must stay"
        assert freed == 10

    def test_declining_the_prompt_keeps_it(self, cache, monkeypatch):
        old = _entry(cache, "ancient", size=10)
        now = time.time()
        _age(old, now - 400 * 86400)
        monkeypatch.setattr("click.confirm", lambda *a, **kw: False)
        monkeypatch.delenv("GIMERA_NON_INTERACTIVE", raising=False)

        freed = clean(cache, unused_for=90, now=now)

        assert old.exists()
        assert freed == 0

    def test_one_undeletable_entry_does_not_stop_the_rest(
        self, cache, monkeypatch
    ):
        """tools.rmtree exits the process on failure - this must not."""
        bad = _entry(cache, "bad", size=10)
        good = _entry(cache, "good", size=10)
        now = time.time()
        _age(bad, now - 400 * 86400)
        _age(good, now - 400 * 86400)

        real = __import__("shutil").rmtree

        def _fail_on_bad(path, *args, **kwargs):
            if str(path).endswith("bad"):
                raise OSError("nope")
            return real(path, *args, **kwargs)

        monkeypatch.setattr("gimera.cachemaint.shutil.rmtree", _fail_on_bad)

        freed = clean(cache, unused_for=90, force=True, now=now)

        assert bad.exists()
        assert not good.exists()
        assert freed == 10


def _age(path, when):
    import os

    for target in [path, path / "objects", path / "objects" / "pack"]:
        os.utime(target, (when, when))


class TestFormatSize:
    @pytest.mark.parametrize(
        "value,expected",
        [(0, "0 B"), (2048, "2.0 KB"), (5 * 1024**3, "5.0 GB")],
    )
    def test_readable(self, value, expected):
        assert format_size(value) == expected
