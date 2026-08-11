"""Unit tests for various modules: gitcommands, patches, snapshot, cachedir,
config, repo. Uses small tmpdir git repos — no remote access required.
"""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ..consts import gitcmd as git


# ------------------------------------------------------------------
# small tmp git repo fixture
# ------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(git + ["init", "-q", "--initial-branch=main"], cwd=repo)
    subprocess.check_call(git + ["config", "user.email", "t@t"], cwd=repo)
    subprocess.check_call(git + ["config", "user.name", "t"], cwd=repo)
    subprocess.check_call(git + ["config", "commit.gpgsign", "false"], cwd=repo)
    (repo / "README").write_text("hello\n")
    subprocess.check_call(git + ["add", "README"], cwd=repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "init"], cwd=repo)
    return repo


# ------------------------------------------------------------------
# gitcommands.GitCommands
# ------------------------------------------------------------------


def test_git_commands_staged_and_dirty(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    assert g.staged_files == []
    assert g.dirty_existing_files == []
    assert g.untracked_files == []
    assert g.all_dirty_files == []
    assert g.all_dirty_files_absolute == []
    assert g.untracked_files_absolute == []
    assert g.dirty is False

    # modify tracked
    (git_repo / "README").write_text("changed\n")
    assert g.dirty is True
    assert Path("README") in g.dirty_existing_files
    assert Path("README") in g.all_dirty_files

    # untracked
    (git_repo / "newfile").write_text("x\n")
    assert Path("newfile") in g.untracked_files
    assert (git_repo / "newfile") in g.untracked_files_absolute
    assert Path("newfile") in g.all_dirty_files

    # staged
    subprocess.check_call(git + ["add", "README"], cwd=git_repo)
    assert Path("README") in g.staged_files


def test_git_commands_dirty_ignores_gimera_yml(git_repo):
    from ..gitcommands import GitCommands

    (git_repo / "gimera.yml").write_text("repos: []\n")
    g = GitCommands(git_repo)
    # gimera.yml is explicitly ignored in .dirty
    assert g.dirty is False


def test_git_commands_hex(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    h = g.hex
    assert len(h) == 40
    assert all(c in "0123456789abcdef" for c in h)


def test_git_commands_simple_commit_all(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    (git_repo / "new").write_text("x\n")
    g.simple_commit_all("my msg")
    assert g.untracked_files == []
    log = subprocess.check_output(
        git + ["log", "--oneline"], cwd=git_repo, encoding="utf-8"
    )
    assert "my msg" in log


def test_git_commands_checkout(git_repo):
    from ..gitcommands import GitCommands

    # create a new branch
    subprocess.check_call(git + ["checkout", "-b", "feature"], cwd=git_repo)
    subprocess.check_call(git + ["checkout", "main"], cwd=git_repo)

    g = GitCommands(git_repo)
    g.checkout("feature")
    out = subprocess.check_output(
        git + ["branch", "--show-current"], cwd=git_repo, encoding="utf-8"
    ).strip()
    assert out == "feature"


def test_git_commands_checkout_force(git_repo):
    from ..gitcommands import GitCommands

    (git_repo / "README").write_text("dirty\n")
    g = GitCommands(git_repo)
    # force checkout should discard dirty
    g.checkout("main", force=True)
    assert (git_repo / "README").read_text() == "hello\n"


def test_git_commands_get_all_branches(git_repo):
    from ..gitcommands import GitCommands

    subprocess.check_call(git + ["checkout", "-b", "feature"], cwd=git_repo)
    subprocess.check_call(git + ["checkout", "main"], cwd=git_repo)
    g = GitCommands(git_repo)
    branches = g.get_all_branches()
    assert "main" in branches
    assert "feature" in branches


def test_git_commands_output_status(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    g.output_status()  # should not raise


def test_git_commands_configdir(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    assert g.configdir == git_repo / ".git"


def test_git_commands_combine(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    res = g._combine("sub/dir")
    assert res == git_repo / "sub" / "dir"


def test_git_commands_has_unpushed_no_remote(git_repo):
    from ..gitcommands import GitCommands

    g = GitCommands(git_repo)
    # no remote configured — should just return False gracefully
    assert g.has_unpushed_commits() is False


# ------------------------------------------------------------------
# repo.Repo
# ------------------------------------------------------------------


def test_repo_contain_commit(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    h = r.hex
    assert r.contain_commit(h)
    assert not r.contain_commit("deadbeef" * 5)


def test_repo_contains_branch(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    assert r.contains_branch("main")
    assert not r.contains_branch("nope-not-exists")


def test_repo_get_branch_and_commit(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    assert r.get_branch() == "main"
    assert len(r.get_commit()) == 40


def test_repo_is_bare_false(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    assert r.is_bare is False


def test_repo_is_bare_true(tmp_path):
    from ..repo import Repo

    bare = tmp_path / "bare"
    bare.mkdir()
    subprocess.check_call(git + ["init", "-q", "--bare", "--initial-branch=main"], cwd=bare)
    r = Repo(bare)
    assert r.is_bare is True


def test_repo_root_repo(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    assert r.root_repo.path == git_repo


def test_repo_get_submodule_missing_raises(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    with pytest.raises(ValueError):
        r.get_submodule("nope")


def test_repo_get_submodules_empty(git_repo):
    from ..repo import Repo

    assert Repo(git_repo).get_submodules() == []


def test_repo_check_ignore(git_repo):
    from ..repo import Repo

    (git_repo / ".gitignore").write_text("ignored.txt\n")
    subprocess.check_call(git + ["add", ".gitignore"], cwd=git_repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "gi"], cwd=git_repo)

    r = Repo(git_repo)
    (git_repo / "ignored.txt").write_text("x")
    assert r.check_ignore("ignored.txt") is True
    assert r.check_ignore("README") is False


def test_repo_full_clean(git_repo):
    from ..repo import Repo

    (git_repo / "README").write_text("dirty\n")
    (git_repo / "newfile").write_text("x\n")
    r = Repo(git_repo)
    r.full_clean()
    assert (git_repo / "README").read_text() == "hello\n"
    assert not (git_repo / "newfile").exists()


def test_repo_please_no_staged_files_ok(git_repo):
    from ..repo import Repo

    Repo(git_repo).please_no_staged_files()


def test_repo_please_no_staged_files_raises(git_repo, monkeypatch):
    from ..repo import Repo

    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    (git_repo / "README").write_text("dirty")
    subprocess.check_call(git + ["add", "README"], cwd=git_repo)
    with pytest.raises(Exception):
        Repo(git_repo).please_no_staged_files()


def test_repo_remotes_empty(git_repo):
    from ..repo import Repo

    assert list(Repo(git_repo).remotes) == []


def test_remote_class():
    from ..repo import Remote

    r = Remote(repo=None, name="origin", url="https://x/y")
    assert r.name == "origin"
    assert r.url == "https://x/y"


def test_repo_temporary_unignore_no_op(git_repo):
    from ..repo import Repo

    r = Repo(git_repo)
    # no .gitignore — should be noop
    with r.temporary_unignore("README"):
        pass


def test_repo_temporary_unignore_restores(git_repo):
    from ..repo import Repo

    (git_repo / ".gitignore").write_text("secret.txt\n")
    (git_repo / "secret.txt").write_text("x")
    r = Repo(git_repo)
    original = (git_repo / ".gitignore").read_text()
    with r.temporary_unignore("secret.txt"):
        # inside, .gitignore line should be removed
        assert "secret.txt" not in (git_repo / ".gitignore").read_text()
    assert (git_repo / ".gitignore").read_text() == original


# ------------------------------------------------------------------
# cachedir.py
# ------------------------------------------------------------------


def test_make_cache_path_contains_repo_name(monkeypatch, tmp_path):
    monkeypatch.setenv("GIMERA_CACHE_DIR", str(tmp_path))
    from ..cachedir import _make_cache_path

    p = _make_cache_path("https://example.com/foo/bar.git")
    assert str(p).startswith(str(tmp_path))
    # no url-unsafe chars
    for c in "?:+[]{}\\\"'":
        assert c not in p.name


def test_make_cache_path_with_git_url(monkeypatch, tmp_path):
    monkeypatch.setenv("GIMERA_CACHE_DIR", str(tmp_path))
    from ..cachedir import _make_cache_path

    p = _make_cache_path("git@github.com:foo/bar.git")
    assert str(p).startswith(str(tmp_path))


def test_get_cache_dir_tarfile():
    from ..cachedir import _get_cache_dir_tarfile

    tf = _get_cache_dir_tarfile(Path("/tmp/x"))
    assert str(tf).endswith(".tar.gz")


def test_invalidate_cache_removes_broken(tmp_path):
    from ..cachedir import _invalidate_cache_if_needed

    broken = tmp_path / "cache"
    broken.mkdir()
    # missing 'HEAD' etc → must be removed
    _invalidate_cache_if_needed(broken)
    assert not broken.exists()


def test_invalidate_cache_keeps_valid(tmp_path):
    from ..cachedir import _invalidate_cache_if_needed

    valid = tmp_path / "cache"
    valid.mkdir()
    for x in ("HEAD", "refs", "objects", "config"):
        (valid / x).mkdir() if x in ("refs", "objects") else (valid / x).write_text("x")
    _invalidate_cache_if_needed(valid)
    assert valid.exists()


def test_invalidate_cache_clear_flag(tmp_path, monkeypatch):
    from ..cachedir import _invalidate_cache_if_needed

    valid = tmp_path / "cache"
    valid.mkdir()
    for x in ("HEAD", "refs", "objects", "config"):
        (valid / x).mkdir() if x in ("refs", "objects") else (valid / x).write_text("x")
    monkeypatch.setenv("GIMERA_CLEAR_CACHE", "1")
    _invalidate_cache_if_needed(valid)
    assert not valid.exists()


def test_invalidate_zip_cache(tmp_path, monkeypatch):
    from ..cachedir import _invalidate_cache_if_needed, _get_cache_dir_tarfile

    path = tmp_path / "cache"
    tar = _get_cache_dir_tarfile(path)
    tar.write_text("x")
    monkeypatch.setenv("GIMERA_CLEAR_ZIP_CACHE", "1")
    _invalidate_cache_if_needed(path)
    assert not tar.exists()


# ------------------------------------------------------------------
# patches.py pure helpers
# ------------------------------------------------------------------


def test_remove_file_from_patch_none():
    from ..patches import remove_file_from_patch

    assert remove_file_from_patch(["x"], None) is None


def test_remove_file_from_patch_excludes_matching():
    from ..patches import remove_file_from_patch

    patch = (
        b"diff --git a/foo.txt b/foo.txt\n"
        b"+++ content\n"
        b"diff --git a/bar.txt b/bar.txt\n"
        b"+++ keepme\n"
    )
    res = remove_file_from_patch(["foo.txt"], patch)
    text = res.decode()
    assert "foo.txt" not in text
    assert "bar.txt" in text
    assert "keepme" in text


def test_remove_file_from_patch_keeps_all_when_no_match():
    from ..patches import remove_file_from_patch

    patch = b"diff --git a/foo.txt b/foo.txt\n+++ x\n"
    res = remove_file_from_patch(["other.txt"], patch)
    assert b"foo.txt" in res


# ------------------------------------------------------------------
# snapshot.py
# ------------------------------------------------------------------


def test_get_token_creates_new(monkeypatch):
    monkeypatch.delenv("GIMERA_TOKEN", raising=False)
    from ..snapshot import _get_token

    t = _get_token()
    assert t
    assert os.environ["GIMERA_TOKEN"] == t


def test_get_token_reuses(monkeypatch):
    monkeypatch.setenv("GIMERA_TOKEN", "my-token")
    from ..snapshot import _get_token

    assert _get_token() == "my-token"


def test_list_snapshots_empty(tmp_path):
    from ..snapshot import list_snapshots

    res = list_snapshots(tmp_path)
    assert res == []


def test_list_snapshots_with_entries(tmp_path):
    from ..snapshot import list_snapshots

    d = tmp_path / ".gimera" / "snapshots"
    d.mkdir(parents=True)
    (d / "snap1").mkdir()
    (d / "snap2").mkdir()
    (d / "random_file").write_text("x")  # files should be ignored
    res = list_snapshots(tmp_path)
    assert set(res) == {"snap1", "snap2"}


def test_get_snapshots_returns_names(tmp_path):
    from ..snapshot import get_snapshots

    d = tmp_path / ".gimera" / "snapshots"
    d.mkdir(parents=True)
    (d / "a").mkdir()
    (d / "b").mkdir()
    res = get_snapshots(tmp_path)
    assert set(res) == {"a", "b"}


def test_get_patch_filepath_creates_parents(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMERA_TOKEN", "tok")
    from ..snapshot import _get_patch_filepath

    root = tmp_path
    file_relpath = root / "sub" / "file"
    res = _get_patch_filepath(root, file_relpath)
    assert res.parent.exists()
    assert str(res).endswith("sub/file.patch")


def test_snapshot_cleanup_file(tmp_path, monkeypatch):
    import gimera.snapshot as snap

    f = tmp_path / "f"
    f.write_text("x")
    d = tmp_path / "d"
    d.mkdir()
    monkeypatch.setattr(snap, "to_cleanup", [f, d])
    snap.cleanup()
    assert not f.exists()
    assert not d.exists()


# ------------------------------------------------------------------
# config.py
# ------------------------------------------------------------------


@pytest.fixture
def gimera_dir(tmp_path, monkeypatch):
    repo = tmp_path / "g"
    repo.mkdir()
    subprocess.check_call(git + ["init", "-q", "--initial-branch=main"], cwd=repo)
    subprocess.check_call(git + ["config", "user.email", "t@t"], cwd=repo)
    subprocess.check_call(git + ["config", "user.name", "t"], cwd=repo)
    subprocess.check_call(git + ["config", "commit.gpgsign", "false"], cwd=repo)
    data = {
        "common": {"vars": {"VERSION": "17.0"}},
        "repos": [
            {
                "url": "https://example.invalid/a.git",
                "branch": "${VERSION}",
                "path": "vendor/a",
                "type": "integrated",
                "patches": [{"path": "patches/a", "chdir": "."}],
            },
            {
                "url": "https://example.invalid/b.git",
                "branch": "main",
                "path": "vendor/b",
                "type": "submodule",
            },
        ],
    }
    (repo / "gimera.yml").write_text(yaml.dump(data))
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "g"], cwd=repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    return repo


def test_config_loads(gimera_dir):
    from ..config import Config

    c = Config()
    assert len(c.repos) == 2
    a = [r for r in c.repos if str(r.path) == "vendor/a"][0]
    assert a.branch == "17.0"
    assert a.type == "integrated"


def test_config_repoitem_eval_unknown_var_raises(gimera_dir):
    from ..config import Config

    c = Config()
    a = c.repos[0]
    with pytest.raises(Exception):
        a.eval("prefix-${UNKNOWN}-suffix")


def test_config_get_repos_by_name(gimera_dir):
    from ..config import Config

    c = Config()
    res = c.get_repos(["vendor/a"])
    assert len(res) == 1
    assert str(res[0].path) == "vendor/a"


def test_config_get_repos_invalid_name_raises(gimera_dir):
    from ..config import Config

    c = Config()
    with pytest.raises(Exception):
        c.get_repos(["vendor/does-not-exist"])


def test_config_get_repos_none_returns_all(gimera_dir):
    from ..config import Config

    c = Config()
    assert len(c.get_repos(None)) == 2


def test_config_remove(gimera_dir):
    from ..config import Config

    c = Config()
    c.remove("vendor/b")
    data = yaml.safe_load((gimera_dir / "gimera.yml").read_text())
    paths = [r["path"] for r in data["repos"]]
    assert paths == ["vendor/a"]


def test_config_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    from ..config import Config

    with pytest.raises(Exception):
        Config()


def test_config_duplicate_path_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    data = {
        "repos": [
            {"url": "u", "branch": "b", "path": "same", "type": "integrated"},
            {"url": "u", "branch": "b", "path": "same", "type": "integrated"},
        ]
    }
    (tmp_path / "gimera.yml").write_text(yaml.dump(data))
    from ..config import Config

    with pytest.raises(Exception):
        Config()


def test_config_invalid_type_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    data = {
        "repos": [
            {"url": "u", "branch": "b", "path": "x", "type": "BOGUS"},
        ]
    }
    (tmp_path / "gimera.yml").write_text(yaml.dump(data))
    from ..config import Config

    with pytest.raises(Exception):
        Config()


def test_patchdir_as_dict(gimera_dir):
    from ..config import Config

    c = Config()
    a = [r for r in c.repos if str(r.path) == "vendor/a"][0]
    patchdir = a.patches[0]
    d = patchdir.as_dict()
    assert d["path"] == "patches/a"
    assert d["chdir"] == "."


def test_patchdir_apply_from_here_dir_chdir(gimera_dir):
    from ..config import Config

    c = Config()
    a = [r for r in c.repos if str(r.path) == "vendor/a"][0]
    # chdir is '.' → resolves to config dir
    assert a.patches[0].apply_from_here_dir == gimera_dir


def test_repoitem_as_dict(gimera_dir):
    from ..config import Config

    c = Config()
    a = [r for r in c.repos if str(r.path) == "vendor/a"][0]
    d = a.as_dict()
    assert d["type"] == "integrated"
    assert d["url"] == "https://example.invalid/a.git"


def test_repoitem_url_public(gimera_dir):
    from ..config import Config

    c = Config()
    a = c.repos[0]
    a._url = "ssh://git@github.com/foo/bar.git"
    assert a.url_public.startswith("https://")


def test_repoitem_type_force_override(gimera_dir):
    from ..config import Config

    c = Config(force_type="submodule")
    a = [r for r in c.repos if str(r.path) == "vendor/a"][0]
    # force_type overrides yaml-defined type
    assert a.type == "submodule"


# ------------------------------------------------------------------
# patches: _get_available_patchfiles
# ------------------------------------------------------------------


def test_get_available_patchfiles_empty(gimera_dir):
    from ..patches import _get_available_patchfiles

    # no patches on disk → empty
    res = _get_available_patchfiles(None, None, "")
    assert res == []


def test_get_available_patchfiles_filters(gimera_dir):
    from ..patches import _get_available_patchfiles

    patches_dir = gimera_dir / "patches" / "a"
    patches_dir.mkdir(parents=True)
    (patches_dir / "foo.patch").write_text("diff\n")
    (patches_dir / "bar.patch").write_text("diff\n")

    res = _get_available_patchfiles(None, None, "")
    assert len(res) == 2
    # filter
    res = _get_available_patchfiles(None, None, "foo")
    assert len(res) == 1
    assert "foo.patch" in res[0]
