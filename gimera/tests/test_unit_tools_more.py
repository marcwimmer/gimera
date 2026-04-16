"""Additional unit tests targeting tools.py functions that operate on the
filesystem / git repos locally (no network)."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ..consts import gitcmd as git


@pytest.fixture
def main_repo(tmp_path, monkeypatch):
    repo = tmp_path / "main"
    repo.mkdir()
    subprocess.check_call(git + ["init", "-q", "--initial-branch=main"], cwd=repo)
    subprocess.check_call(git + ["config", "user.email", "t@t"], cwd=repo)
    subprocess.check_call(git + ["config", "user.name", "t"], cwd=repo)
    subprocess.check_call(git + ["config", "commit.gpgsign", "false"], cwd=repo)
    (repo / "README").write_text("x\n")
    subprocess.check_call(git + ["add", "README"], cwd=repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "init"], cwd=repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    return repo


def test_get_main_repo_finds_root(main_repo):
    from ..tools import _get_main_repo

    r = _get_main_repo()
    assert r.path == main_repo


def test_get_main_repo_from_subdir(main_repo, monkeypatch):
    from ..tools import _get_main_repo

    sub = main_repo / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    r = _get_main_repo()
    assert r.path == main_repo


def test_get_closest_gimera_returns_existing(main_repo):
    from ..tools import get_closest_gimera

    (main_repo / "gimera.yml").write_text("repos: []\n")
    inner = main_repo / "a" / "b"
    inner.mkdir(parents=True)
    assert get_closest_gimera(main_repo, inner) == main_repo


def test_get_closest_gimera_walks_up(main_repo):
    from ..tools import get_closest_gimera

    (main_repo / "gimera.yml").write_text("repos: []\n")
    (main_repo / "lvl1").mkdir()
    (main_repo / "lvl1" / "gimera.yml").write_text("repos: []\n")
    start = main_repo / "lvl1" / "deep" / "deeper"
    start.mkdir(parents=True)
    res = get_closest_gimera(main_repo, start)
    assert res == main_repo / "lvl1"


def test_get_closest_gimera_returns_root_when_not_found(main_repo):
    from ..tools import get_closest_gimera

    inner = main_repo / "x"
    inner.mkdir()
    assert get_closest_gimera(main_repo, inner) == main_repo


def test_get_missing_repos_yields_nonexistent(main_repo):
    from ..tools import _get_missing_repos
    from ..config import Config

    data = {
        "repos": [
            {
                "url": "u",
                "branch": "main",
                "path": "vendor/a",
                "type": "integrated",
            },
        ]
    }
    (main_repo / "gimera.yml").write_text(yaml.dump(data))
    config = Config()
    missing = list(_get_missing_repos(config))
    assert len(missing) == 1
    assert str(missing[0].path) == "vendor/a"


def test_get_missing_repos_yields_empty_dir(main_repo):
    from ..tools import _get_missing_repos
    from ..config import Config

    data = {
        "repos": [
            {"url": "u", "branch": "main", "path": "vendor/a", "type": "integrated"},
        ]
    }
    (main_repo / "gimera.yml").write_text(yaml.dump(data))
    (main_repo / "vendor" / "a").mkdir(parents=True)

    config = Config()
    missing = list(_get_missing_repos(config))
    assert len(missing) == 1


def test_get_missing_repos_skips_populated(main_repo):
    from ..tools import _get_missing_repos
    from ..config import Config

    data = {
        "repos": [
            {"url": "u", "branch": "main", "path": "vendor/a", "type": "integrated"},
        ]
    }
    (main_repo / "gimera.yml").write_text(yaml.dump(data))
    (main_repo / "vendor" / "a").mkdir(parents=True)
    (main_repo / "vendor" / "a" / "f").write_text("x")

    config = Config()
    missing = list(_get_missing_repos(config))
    assert missing == []


def test_get_missing_repos_skips_disabled(main_repo):
    from ..tools import _get_missing_repos
    from ..config import Config

    data = {
        "repos": [
            {
                "url": "u",
                "branch": "main",
                "path": "vendor/a",
                "type": "integrated",
                "enabled": False,
            },
        ]
    }
    (main_repo / "gimera.yml").write_text(yaml.dump(data))
    config = Config()
    assert list(_get_missing_repos(config)) == []


def test_make_sure_hidden_gimera_dir_creates_gitignore(main_repo):
    from ..tools import _make_sure_hidden_gimera_dir

    assert not (main_repo / ".gitignore").exists()
    res = _make_sure_hidden_gimera_dir(main_repo)
    assert res == main_repo / ".gimera"
    assert ".gimera" in (main_repo / ".gitignore").read_text()


def test_make_sure_hidden_gimera_dir_appends(main_repo):
    from ..tools import _make_sure_hidden_gimera_dir

    (main_repo / ".gitignore").write_text("# existing\nnode_modules/\n")
    subprocess.check_call(git + ["add", ".gitignore"], cwd=main_repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "gi"], cwd=main_repo)
    _make_sure_hidden_gimera_dir(main_repo)
    text = (main_repo / ".gitignore").read_text()
    assert ".gimera" in text
    assert "node_modules/" in text


def test_make_sure_hidden_gimera_dir_already_has(main_repo):
    from ..tools import _make_sure_hidden_gimera_dir

    (main_repo / ".gitignore").write_text(".gimera\nnode_modules/\n")
    subprocess.check_call(git + ["add", ".gitignore"], cwd=main_repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "gi"], cwd=main_repo)
    _make_sure_hidden_gimera_dir(main_repo)
    text = (main_repo / ".gitignore").read_text()
    # already had it, no duplication
    assert text.count(".gimera") == 1


def test_get_remotes_empty():
    from ..tools import _get_remotes

    class FakeRepo:
        remotes = None

    assert _get_remotes(FakeRepo()) == []


def test_get_remotes_yields():
    from ..tools import _get_remotes

    class FakeRepo:
        remotes = {"origin": "https://x/y", "upstream": "https://a/b"}.items()

    res = _get_remotes(FakeRepo())
    assert len(res) == 2
    names = sorted(r.name for r in res)
    assert names == ["origin", "upstream"]


def test_get_nearest_repo_no_submodules(main_repo):
    from ..tools import get_nearest_repo

    res = get_nearest_repo(main_repo, main_repo / "some" / "path")
    # no submodules → nearest is main_repo
    assert res == main_repo


def test_snapshot_get_repo_for_filter_paths(main_repo):
    from ..snapshot import _get_repo_for_filter_paths

    res = _get_repo_for_filter_paths(main_repo, [main_repo / "a", main_repo / "b"])
    assert res == main_repo
