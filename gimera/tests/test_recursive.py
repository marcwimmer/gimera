from .fixtures import *  # required for all
import itertools
import yaml
from ..repo import Repo
import os
import subprocess
import shutil
from pathlib import Path
from .tools import gimera_apply
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git


def _prepare_recursive_repos(temppath, workspace, workspace_main, sub_names, types):
    """
    Generic setup for recursive gimera tests with N levels.

    sub_names: list of names like ["sub1", "sub2", "sub3"]
    types: list of types like ["integrated", "submodule", "integrated"]
    """
    assert len(sub_names) == len(types)

    if workspace_main.exists():
        shutil.rmtree(workspace_main)

    # Clean up old repos
    for name in ["mainrepo"] + list(sub_names):
        p = temppath / name
        if p.exists():
            shutil.rmtree(p)

    # Create remote repos
    repo_main = _make_remote_repo(temppath / "mainrepo")
    repos = [_make_remote_repo(temppath / name) for name in sub_names]

    # Clear cache
    cache_path = Path(os.environ["GIMERA_CACHE_DIR"])
    if cache_path.exists():
        shutil.rmtree(cache_path)
    cache_path.mkdir(parents=True, exist_ok=True)

    # Build gimera config chain: main -> sub[0] -> sub[1] -> ... -> sub[N-1]
    gimera_main = {
        "repos": [{
            "url": f"file://{repos[0]}",
            "branch": "main",
            "path": sub_names[0],
            "patches": [],
            "type": types[0],
        }]
    }
    gimera_subs = []
    for i in range(len(repos) - 1):
        gimera_subs.append({
            "repos": [{
                "url": f"file://{repos[i + 1]}",
                "branch": "main",
                "path": sub_names[i + 1],
                "patches": [],
                "type": types[i + 1],
            }]
        })

    # Commit main repo
    with clone_and_commit(repo_main, "main") as repopath:
        (repopath / "gimera.yml").write_text(yaml.dump(gimera_main))
        (repopath / "main.txt").write_text("This is a new function")
        Repo(repopath).simple_commit_all()

    # Commit sub repos (each with gimera.yml pointing to next, except last)
    for i, repo_path in enumerate(repos):
        with clone_and_commit(repo_path, "main") as repopath:
            if i < len(gimera_subs):
                (repopath / "gimera.yml").write_text(yaml.dump(gimera_subs[i]))
            (repopath / f"{sub_names[i]}.txt").write_text("This is a new function")
            Repo(repopath).simple_commit_all()

    # Clone main to workspace
    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace,
    )


def _assert_recursive_structure(workspace_main, sub_names):
    """Assert that all nested repos exist and workspace is clean."""
    path = workspace_main
    for i, name in enumerate(sub_names):
        path = path / name
        assert (path / f"{name}.txt").exists()
        if i < len(sub_names) - 1:
            assert (path / "gimera.yml").exists()

    repo = Repo(workspace_main)
    dirty = [x for x in repo.all_dirty_files if x.stem != '.gitignore']
    assert not dirty


def test_recursive_gimeras_2_levels(temppath):
    workspace = temppath / "workspace_tree_dirty_files"
    workspace.mkdir()
    workspace_main = workspace / "main_working"
    sub_names = ["sub", "subsub"]

    for ttype_sub, ttype_subsub in [
        ("integrated", "integrated"),
        ("submodule", "integrated"),
        ("integrated", "submodule"),
        ("submodule", "submodule"),
    ]:
        _prepare_recursive_repos(
            temppath, workspace, workspace_main,
            sub_names, [ttype_sub, ttype_subsub],
        )
        os.chdir(workspace_main)
        gimera_apply([], update=None, recursive=True, strict=True)
        _assert_recursive_structure(workspace_main, sub_names)


def test_recursive_gimeras_3_levels(temppath):
    workspace = temppath / "workspace_tree_dirty_files_3"
    workspace.mkdir()
    workspace_main = workspace / "main_working"
    sub_names = ["sub1", "sub2", "sub3"]

    permutations = list(sorted(set(itertools.permutations("000111", 3))))

    for permutation in permutations:
        types = ["integrated" if int(x) else "submodule" for x in permutation]
        _prepare_recursive_repos(
            temppath, workspace, workspace_main, sub_names, types,
        )
        os.chdir(workspace_main)
        gimera_apply([], update=None, recursive=True, strict=True)
        _assert_recursive_structure(workspace_main, sub_names)


def test_recursive_gimeras_5_levels(temppath):
    workspace = temppath / "test_recursive_gimeras_4_levels"
    workspace.mkdir()
    workspace_main = workspace / "main_working"
    sub_names = ["sub1", "sub2", "sub3", "sub4", "sub5"]

    permutations = list(sorted(set(itertools.permutations("0000011111", 5))))

    for permutation in permutations:
        types = ["integrated" if int(x) else "submodule" for x in permutation]
        _prepare_recursive_repos(
            temppath, workspace, workspace_main, sub_names, types,
        )
        os.chdir(workspace_main)
        gimera_apply([], update=None, recursive=True, strict=True)
        _assert_recursive_structure(workspace_main, sub_names)
