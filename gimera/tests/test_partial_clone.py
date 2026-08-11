"""Blobless golden cache for integrated repos.

The interesting part is not the flag itself but the two boundaries: a
submodule repo must keep a full cache (you cannot clone out of a partial
clone), and a server that ignores the filter must be reported instead of
silently filling the disk.
"""

import subprocess
from pathlib import Path

from ..cachedir import _wants_partial_clone
from ..cachedir import is_partial_clone
from ..consts import REPO_TYPE_INT
from ..consts import REPO_TYPE_SUB


class FakeRepoYml:
    def __init__(self, type):
        self.type = type


def _git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        encoding="utf8",
        check=True,
    ).stdout


def _make_origin(tmp_path):
    """A tiny repo with two commits, usable as a clone source.

    Clone it via file:// - git ignores --filter for plain local paths
    ("--filter is ignored in local clones") and hardlinks everything instead,
    which would make a partial-clone test silently test nothing.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "t@t.t")
    _git(origin, "config", "user.name", "t")
    # upload-pack reads the *source* repo's config, not the client's -c
    _git(origin, "config", "uploadpack.allowFilter", "true")
    (origin / "file.txt").write_text("one")
    _git(origin, "add", "file.txt")
    _git(origin, "commit", "-qm", "one")
    (origin / "file.txt").write_text("two")
    _git(origin, "add", "file.txt")
    _git(origin, "commit", "-qm", "two")
    return origin


def _clone_partial(origin, dest):
    subprocess.run(
        ["git", "clone", "--bare", "-q", "--filter=blob:none",
         f"file://{origin}", str(dest)],
        check=True,
    )
    assert is_partial_clone(dest), "fixture did not produce a partial clone"
    return dest


def test_integrated_repos_get_the_filter():
    assert _wants_partial_clone(FakeRepoYml(REPO_TYPE_INT)) is True


def test_submodule_repos_never_get_the_filter():
    """Not a preference - a filtered cache cannot serve `git submodule update`."""
    assert _wants_partial_clone(FakeRepoYml(REPO_TYPE_SUB)) is False


def test_env_switch_turns_the_filter_off(monkeypatch):
    monkeypatch.setenv("GIMERA_FULL_CLONE", "1")
    assert _wants_partial_clone(FakeRepoYml(REPO_TYPE_INT)) is False


def test_is_partial_clone_tells_the_two_apart(tmp_path):
    origin = _make_origin(tmp_path)

    full = tmp_path / "full.git"
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(origin), str(full)], check=True
    )
    assert is_partial_clone(full) is False

    partial = tmp_path / "partial.git"
    _clone_partial(origin, partial)
    assert is_partial_clone(partial) is True


def test_is_partial_clone_on_nonsense_path_says_no(tmp_path):
    assert is_partial_clone(tmp_path / "does-not-exist") is False


def test_archive_works_on_a_partial_cache(tmp_path):
    """The path integrated.py uses: git archive against a blobless bare repo.

    The blobs are missing locally and get fetched from the promisor on the
    fly - this is what makes the small cache usable at all.
    """
    origin = _make_origin(tmp_path)
    partial = tmp_path / "partial.git"
    _clone_partial(origin, partial)
    sha = _git(partial, "rev-parse", "HEAD").strip()

    out = subprocess.run(
        ["git", "-C", str(partial), "archive", sha],
        capture_output=True,
        check=True,
    )
    assert b"file.txt" in out.stdout


def test_cloning_out_of_a_partial_cache_fails(tmp_path):
    """Pins down *why* submodule repos are excluded.

    If a future git ever makes this work, this test turns red and the
    exclusion in _wants_partial_clone can be revisited.
    """
    origin = _make_origin(tmp_path)
    partial = tmp_path / "partial.git"
    _clone_partial(origin, partial)
    # the promisor must be unreachable, otherwise the cache just refetches
    subprocess.run(
        ["git", "-C", str(partial), "remote", "set-url", "origin", "/nonexistent"],
        check=True,
    )

    result = subprocess.run(
        ["git", "clone", "-q", f"file://{partial}", str(tmp_path / "child")],
        capture_output=True,
        encoding="utf8",
    )
    assert result.returncode != 0 or not (tmp_path / "child" / "file.txt").exists()


def test_clone_falls_back_when_the_filter_is_rejected(tmp_path, monkeypatch):
    """A server that refuses --filter must not take the whole apply down."""
    from .. import cachedir

    origin = _make_origin(tmp_path)
    dest = tmp_path / "cache.git"
    calls = []

    class FakeRepo:
        def __init__(self, path):
            self.path = Path(path)

        def X(self, *params):
            calls.append(params)
            if "--filter=blob:none" in params:
                raise Exception("fatal: filtering not supported")
            subprocess.run(
                ["git", "clone", "--bare", "-q", f"file://{origin}", str(dest)],
                check=True,
            )

    monkeypatch.setattr(cachedir, "Repo", FakeRepo)
    cachedir._bare_clone(FakeRepo(tmp_path), f"file://{origin}", dest, partial=True)

    assert len(calls) == 2, "expected one filtered attempt and one fallback"
    assert "--filter=blob:none" not in calls[1]
    assert is_partial_clone(dest) is False
    assert (dest / "HEAD").exists()
