from .fixtures import *  # required for all
import itertools
import yaml
from ..repo import Repo
import os
import subprocess
import shutil
import os
from pathlib import Path
from .tools import gimera_apply
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git


def test_recursive_gimeras_2_levels(temppath):
    workspace = temppath / "workspace_tree_dirty_files"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = None
    repo_sub = None
    repo_subsub = None

    gimera_main = None
    gimera_sub = None

    # region prepare repos
    def prepare_repos(ttype_sub, ttype_subsub):
        if workspace_main.exists():
            shutil.rmtree(workspace_main)
        nonlocal repo_main, repo_sub, repo_subsub, gimera_main, gimera_sub
        if repo_main:
            shutil.rmtree(repo_main)
        if repo_sub:
            shutil.rmtree(repo_sub)
        if repo_subsub:
            shutil.rmtree(repo_subsub)
        repo_main = _make_remote_repo(temppath / "mainrepo")
        repo_sub = _make_remote_repo(temppath / "sub1")
        repo_subsub = _make_remote_repo(temppath / "subsub1")
        path = Path(os.path.expanduser("~/.cache/gimera"))
        if path.exists():
            shutil.rmtree(path)

        # region gimera config
        gimera_main = {
            "repos": [
                {
                    "url": f"file://{repo_sub}",
                    "branch": "main",
                    "path": "sub",
                    "patches": [],
                    "type": ttype_sub,
                },
            ]
        }
        gimera_sub = {
            "repos": [
                {
                    "url": f"file://{repo_subsub}",
                    "branch": "main",
                    "path": "subsub",
                    "patches": [],
                    "type": ttype_subsub,
                },
            ]
        }
        # endregion

        with clone_and_commit(repo_main, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_main))
            (repopath / "main.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub))
            (repopath / "sub.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_subsub, "main") as repopath:
            (repopath / "subsub.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        subprocess.check_output(
            git + ["clone", "file://" + str(repo_main), workspace_main],
            cwd=workspace,
        )

    # endregion

    repo = Repo(workspace_main)

    # region: case 1: all integrated
    prepare_repos("integrated", "integrated")
    os.chdir(workspace_main)
    gimera_apply([], None, recursive=True, strict=True)

    assert (workspace_main / "sub" / "sub.txt").exists()
    assert (workspace_main / "sub" / "gimera.yml").exists()
    assert (workspace_main / "sub" / "subsub" / "subsub.txt").exists()
    dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
    assert not dirty
    # endregion

    # region: case 2: submodule then integrated
    prepare_repos("submodule", "integrated")
    os.chdir(workspace_main)
    gimera_apply([], update=None, recursive=True, strict=True)

    assert (workspace_main / "sub" / "sub.txt").exists()
    assert (workspace_main / "sub" / "gimera.yml").exists()
    assert (workspace_main / "sub" / "subsub" / "subsub.txt").exists()
    dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
    assert not dirty
    # endregion

    # region: case 3: integrated then submodule
    prepare_repos("integrated", "submodule")
    os.chdir(workspace_main)
    gimera_apply([], update=None, recursive=True, strict=True)

    assert (workspace_main / "sub" / "sub.txt").exists()
    assert (workspace_main / "sub" / "gimera.yml").exists()
    assert (workspace_main / "sub" / "subsub" / "subsub.txt").exists()
    dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
    assert not dirty
    # endregion

    # region: case 4: submodule submodule
    prepare_repos("submodule", "submodule")
    os.chdir(workspace_main)
    gimera_apply([], update=None, recursive=True, strict=True)

    assert (workspace_main / "sub" / "sub.txt").exists()
    assert (workspace_main / "sub" / "gimera.yml").exists()
    assert (workspace_main / "sub" / "subsub" / "subsub.txt").exists()
    dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
    assert not dirty
    # endregion


def test_recursive_gimeras_3_levels(temppath):
    workspace = temppath / "workspace_tree_dirty_files_3"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = None
    repo_sub1 = None
    repo_sub2 = None
    repo_sub3 = None

    gimera_main = None
    gimera_sub = None

    # region prepare repos
    def prepare_repos(ttype_sub1, ttype_sub2, ttype_sub3):
        if workspace_main.exists():
            shutil.rmtree(workspace_main)
        nonlocal repo_main, repo_sub1, repo_sub2, repo_sub3, gimera_main, gimera_sub
        if repo_main:
            shutil.rmtree(repo_main)
        if repo_sub1:
            shutil.rmtree(repo_sub1)
        if repo_sub2:
            shutil.rmtree(repo_sub2)
        if repo_sub3:
            shutil.rmtree(repo_sub3)
        repo_main = _make_remote_repo(temppath / "mainrepo")
        repo_sub1 = _make_remote_repo(temppath / "sub1")
        repo_sub2 = _make_remote_repo(temppath / "sub2")
        repo_sub3 = _make_remote_repo(temppath / "sub3")
        path = Path(os.path.expanduser("~/.cache/gimera"))
        if path.exists():
            shutil.rmtree(path)

        # region gimera config
        gimera_main = {
            "repos": [
                {
                    "url": f"file://{repo_sub1}",
                    "branch": "main",
                    "path": "sub1",
                    "patches": [],
                    "type": ttype_sub1,
                },
            ]
        }
        gimera_sub = {
            "repos": [
                {
                    "url": f"file://{repo_sub2}",
                    "branch": "main",
                    "path": "sub2",
                    "patches": [],
                    "type": ttype_sub2,
                },
            ]
        }
        gimera_sub2 = {
            "repos": [
                {
                    "url": f"file://{repo_sub3}",
                    "branch": "main",
                    "path": "sub3",
                    "patches": [],
                    "type": ttype_sub3,
                },
            ]
        }
        # endregion

        with clone_and_commit(repo_main, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_main))
            (repopath / "main.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub1, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub))
            (repopath / "sub1.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub2, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub2))
            (repopath / "sub2.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub3, "main") as repopath:
            (repopath / "sub3.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        subprocess.check_output(
            git + ["clone", "file://" + str(repo_main), workspace_main],
            cwd=workspace,
        )

    # endregion

    permutations = list(sorted(set(itertools.permutations("000111", 3))))

    for i, permutation in enumerate(permutations):

        def ttype(x):
            return "integrated" if int(x) else "submodule"

        prepare_repos(*tuple(map(ttype, permutation)))
        os.chdir(workspace_main)
        gimera_apply([], update=None, recursive=True, strict=True)

        repo = Repo(workspace_main)
        assert (workspace_main / "sub1" / "sub1.txt").exists()
        assert (workspace_main / "sub1" / "gimera.yml").exists()
        assert (workspace_main / "sub1" / "sub2" / "sub2.txt").exists()
        assert (workspace_main / "sub1" / "sub2" / "sub3" / "sub3.txt").exists()
        dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
        assert not dirty


def test_recursive_gimeras_5_levels(temppath):
    workspace = temppath / "test_recursive_gimeras_4_levels"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = None
    repo_sub1 = None
    repo_sub2 = None
    repo_sub3 = None
    repo_sub4 = None
    repo_sub5 = None

    gimera_main = None
    gimera_sub = None

    # region prepare repos
    def prepare_repos(ttype_sub1, ttype_sub2, ttype_sub3, ttype_sub4, ttype_sub5):
        if workspace_main.exists():
            shutil.rmtree(workspace_main)
        nonlocal repo_main, repo_sub1, repo_sub2, repo_sub3, repo_sub4, repo_sub5, gimera_main, gimera_sub
        if repo_main:
            shutil.rmtree(repo_main)
        if repo_sub1:
            shutil.rmtree(repo_sub1)
        if repo_sub2:
            shutil.rmtree(repo_sub2)
        if repo_sub3:
            shutil.rmtree(repo_sub3)
        if repo_sub4:
            shutil.rmtree(repo_sub4)
        if repo_sub5:
            shutil.rmtree(repo_sub5)
        repo_main = _make_remote_repo(temppath / "mainrepo")
        repo_sub1 = _make_remote_repo(temppath / "sub1")
        repo_sub2 = _make_remote_repo(temppath / "sub2")
        repo_sub3 = _make_remote_repo(temppath / "sub3")
        repo_sub4 = _make_remote_repo(temppath / "sub4")
        repo_sub5 = _make_remote_repo(temppath / "sub5")
        path = Path(os.path.expanduser("~/.cache/gimera"))
        if path.exists():
            shutil.rmtree(path)

        # region gimera config
        gimera_main = {
            "repos": [
                {
                    "url": f"file://{repo_sub1}",
                    "branch": "main",
                    "path": "sub1",
                    "patches": [],
                    "type": ttype_sub1,
                },
            ]
        }
        gimera_sub = {
            "repos": [
                {
                    "url": f"file://{repo_sub2}",
                    "branch": "main",
                    "path": "sub2",
                    "patches": [],
                    "type": ttype_sub2,
                },
            ]
        }
        gimera_sub2 = {
            "repos": [
                {
                    "url": f"file://{repo_sub3}",
                    "branch": "main",
                    "path": "sub3",
                    "patches": [],
                    "type": ttype_sub3,
                },
            ]
        }
        gimera_sub3 = {
            "repos": [
                {
                    "url": f"file://{repo_sub4}",
                    "branch": "main",
                    "path": "sub4",
                    "patches": [],
                    "type": ttype_sub4,
                },
            ]
        }
        gimera_sub4 = {
            "repos": [
                {
                    "url": f"file://{repo_sub5}",
                    "branch": "main",
                    "path": "sub5",
                    "patches": [],
                    "type": ttype_sub5,
                },
            ]
        }
        # endregion

        with clone_and_commit(repo_main, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_main))
            (repopath / "main.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub1, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub))
            (repopath / "sub1.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub2, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub2))
            (repopath / "sub2.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub3, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub3))
            (repopath / "sub3.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub4, "main") as repopath:
            (repopath / "gimera.yml").write_text(yaml.dump(gimera_sub4))
            (repopath / "sub4.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        with clone_and_commit(repo_sub5, "main") as repopath:
            (repopath / "sub5.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

        subprocess.check_output(
            git + ["clone", "file://" + str(repo_main), workspace_main],
            cwd=workspace,
        )

    # endregion

    permutations = list(sorted(set(itertools.permutations("0000011111", 5))))

    for i, permutation in enumerate(permutations):

        def ttype(x):
            return "integrated" if int(x) else "submodule"

        prepare_repos(*tuple(map(ttype, permutation)))
        os.chdir(workspace_main)
        gimera_apply([], update=None, recursive=True, strict=True)

        repo = Repo(workspace_main)
        assert (workspace_main / "sub1" / "sub1.txt").exists()
        assert (workspace_main / "sub1" / "gimera.yml").exists()
        assert (workspace_main / "sub1" / "sub2" / "sub2.txt").exists()
        assert (workspace_main / "sub1" / "sub2" / "sub3" / "sub3.txt").exists()
        assert (
            workspace_main / "sub1" / "sub2" / "sub3" / "sub4" / "sub4.txt"
        ).exists()
        assert (
            workspace_main / "sub1" / "sub2" / "sub3" / "sub4" / "sub5" / "sub5.txt"
        ).exists()
        dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
        assert not dirty
