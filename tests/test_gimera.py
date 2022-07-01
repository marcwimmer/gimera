#!/usr/bin/env python3
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
import tempfile
from pathlib import Path
import shutil
import click
import sys
import inspect
import os
from pathlib import Path
import pytest

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


@pytest.fixture(autouse=True)
def python():
    return sys.executable


@pytest.fixture(autouse=True)
def gimera():
    return [sys.executable, current_dir.parent / "gimera.py"]


@pytest.fixture(autouse=True)
def temppath():
    path = Path(tempfile.mktemp(suffix=""))
    path = Path("/tmp/gimeratest")
    path.mkdir(exist_ok=True)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(autouse=True)
def cleangimera_cache():
    cache_dir = Path(os.path.expanduser("~")) / ".cache/gimera"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


@contextmanager
def clone_and_commit(repopath, branch):
    path = Path(tempfile.mktemp(suffix="."))
    if path.exists():
        shutil.rmtree(path)
    subprocess.check_call(["git", "clone", repopath, path])
    subprocess.check_call(["git", "checkout", branch], cwd=path)
    try:
        yield path
        subprocess.check_call(
            ["git", "push", "--set-upstream", "origin", branch], cwd=path
        )
    finally:
        shutil.rmtree(path)


def test_basicbehaviour(temppath, python, gimera):
    """
    * put same repo integrated and submodule into main repo
    * add file2.txt on remote
    * check after apply that file exists in both
    * make a patch in integrated version
    """
    return  # TODO undo
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        ["git", "clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )

    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "roles/sub1",
                "patches": [],
                "type": "submodule",
            },
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "roles2/sub1",
                "patches": ["roles2/sub1_patches"],
                "type": "integrated",
            },
        ]
    }

    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    (workspace / "main.txt").write_text("main repo")
    subprocess.check_call(["git", "add", "main.txt"], cwd=workspace)
    subprocess.check_call(["git", "add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(["git", "commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(["git", "push"], cwd=workspace)
    import pudb

    pudb.set_trace()
    subprocess.check_call(gimera + ["apply"], cwd=workspace)
    subprocess.check_call(["git", "add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(["git", "commit", "-am", "updated gimera"], cwd=workspace)

    click.secho(
        "Now we have a repo with two subrepos; now we update the subrepos and pull"
    )
    import pudb

    pudb.set_trace()

    with clone_and_commit(remote_sub_repo, "branch1") as repopath:
        (repopath / "file2.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file2.txt"], cwd=repopath)
        subprocess.check_call(["git", "commit", "-am", "file2 added"], cwd=repopath)

    subprocess.check_call(gimera + ["apply", "--update"], cwd=workspace)

    click.secho(str(workspace), fg="green")
    assert (workspace / "roles" / "sub1" / "file2.txt").exists()
    assert (workspace / "roles2" / "sub1" / "file2.txt").exists()

    # check dirty - disabled because the command is_path_dirty is not cool
    os.environ["GIMERA_DEBUG"] = "1"
    (workspace / "roles2" / "sub1" / "file2.txt").write_text("a change!")
    (workspace / "roles2" / "sub1" / "file3.txt").write_text("a new file!")
    (workspace / "file4.txt").write_text("a new file!")
    test = subprocess.check_output(
        ["python3", current_dir.parent / "gimera.py", "is_path_dirty", "roles2/sub1"],
        cwd=workspace,
    ).decode("utf-8")
    assert "file2.txt" in test
    assert "file3.txt" in test
    assert "file4.txt" not in test

    # now lets make a patch
    subprocess.check_call(gimera + ["apply", "--update"], cwd=workspace)
    subprocess.check_call(["git", "add", "roles2"], cwd=workspace)
    subprocess.check_call(["git", "commit", "-am", "patches"], cwd=workspace)

    # now lets make an update and see if patches are applied
    (remote_sub_repo / "file5.txt").write_text("I am no 5")
    subprocess.check_call(["git", "add", "file5.txt"], cwd=remote_sub_repo)
    subprocess.check_call(["git", "commit", "-am", "file5 added"], cwd=remote_sub_repo)
    # should apply patches now
    subprocess.check_call(
        ["python3", current_dir.parent / "gimera.py", "apply"], cwd=workspace
    )


def _make_remote_repo(path):
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "--bare", "--initial-branch=main"], cwd=path)

    tmp = path.parent / "tmp"
    subprocess.check_call(["git", "clone", f"file://{path}", tmp])
    (tmp / "file1.txt").write_text("random repo on main")
    subprocess.check_call(["git", "add", "file1.txt"], cwd=tmp)
    subprocess.check_call(["git", "commit", "-am", "on main"], cwd=tmp)
    subprocess.check_call(["git", "push"], cwd=tmp)

    subprocess.check_call(["git", "checkout", "-b", "branch1"], cwd=tmp)
    (tmp / "file1.txt").write_text("random repo on branch1")
    subprocess.check_call(["git", "add", "file1.txt"], cwd=tmp)
    subprocess.check_call(["git", "commit", "-am", "on branch1"], cwd=tmp)
    subprocess.check_call(
        ["git", "push", "--set-upstream", "origin", "branch1"], cwd=tmp
    )

    shutil.rmtree(tmp)
    return path


def test_submodule_tree_dirty_files(temppath, python, gimera):
    """
    * put same repo integrated and submodule into main repo
    * add file2.txt on remote
    * check after apply that file exists in both
    * make a patch in integrated version
    """
    workspace = temppath / "workspace_git_basics"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub = _make_remote_repo(temppath / "sub1")
    repo_subsub = _make_remote_repo(temppath / "subsub1")
    repo_2 = _make_remote_repo(temppath / "repo2")

    subprocess.check_output(
        ["git", "clone", "file://" + str(repo_main), workspace.name],
        cwd=workspace.parent,
    )
    with clone_and_commit(repo_2, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    with clone_and_commit(repo_subsub, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    with clone_and_commit(repo_sub, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(
            ["git", "submodule", "add", f"file://{repo_subsub}", "subsub"], cwd=repopath
        )
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    with clone_and_commit(repo_main, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(
            ["git", "submodule", "add", f"file://{repo_sub}", "sub"], cwd=repopath
        )
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    workspace_main = workspace / "main_working"
    subprocess.check_call(["git", "clone", f"file://{repo_main}", workspace_main])
    subprocess.check_call(
        ["git", "submodule", "update", "--init", "--recursive"], cwd=workspace_main
    )
    assert (workspace_main / "sub" / "subsub" / "file1.txt").exists()

    from ..gitcommands import GitCommands

    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert not GitCommands(workspace_main / "sub" / "subsub").all_dirty_files
    (workspace_main / "sub" / "subsub" / "newfile.txt").write_text("new")
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert GitCommands(workspace_main / "sub" / "subsub").all_dirty_files
    assert GitCommands(workspace_main / "sub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub").untracked_files
    assert GitCommands(workspace_main / "sub").all_dirty_files
    assert GitCommands(workspace_main).dirty_existing_files
    assert not GitCommands(workspace_main).untracked_files
    assert GitCommands(workspace_main).all_dirty_files
    (workspace_main / "sub" / "subsub" / "newfile.txt").unlink()
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert not GitCommands(workspace_main / "sub" / "subsub").all_dirty_files
    (workspace_main / "sub" / "newfile.txt").write_text("new")
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert not GitCommands(workspace_main / "sub" / "subsub").all_dirty_files
    assert GitCommands(workspace_main).dirty_existing_files
    assert not GitCommands(workspace_main).untracked_files
    assert GitCommands(workspace_main).all_dirty_files
    (workspace_main / "sub" / "newfile.txt").unlink()
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert not GitCommands(workspace_main / "sub" / "subsub").all_dirty_files
    (workspace_main / "newfile.txt").write_text("new")
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert not GitCommands(workspace_main / "sub" / "subsub").all_dirty_files
    (workspace_main / "newfile.txt").unlink()
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert not GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert not GitCommands(workspace_main / "sub" / "subsub").all_dirty_files

    # make a submodule and check if marked as dirty
    subprocess.check_call(
        ["git", "submodule", "add", f"file://{repo_2}", "repo2"],
        cwd=workspace_main / "sub" / "subsub",
    )
    assert not GitCommands(workspace_main / "sub" / "subsub").dirty_existing_files
    assert GitCommands(workspace_main / "sub" / "subsub").untracked_files
    assert GitCommands(workspace_main / "sub" / "subsub").all_dirty_files

    assert GitCommands(workspace_main / "sub").is_submodule('subsub')

def test_cleanup_dirty_submodule(temppath, python, gimera):
    """
    make dirty submodule then repo.full_clean
    """
    workspace = temppath / "workspace_cleanup_dirty_submodule"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub = _make_remote_repo(temppath / "sub1")
    repo_subsub = _make_remote_repo(temppath / "subsub1")

    subprocess.check_output(
        ["git", "clone", "file://" + str(repo_main), workspace.name],
        cwd=workspace.parent,
    )
    with clone_and_commit(repo_subsub, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    with clone_and_commit(repo_sub, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(
            ["git", "submodule", "add", f"file://{repo_subsub}", "subsub"], cwd=repopath
        )
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    with clone_and_commit(repo_main, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        subprocess.check_call(["git", "add", "file1.txt"], cwd=repopath)
        subprocess.check_call(
            ["git", "submodule", "add", f"file://{repo_sub}", "sub"], cwd=repopath
        )
        subprocess.check_call(["git", "commit", "-am", "file1 added"], cwd=repopath)

    workspace_main = workspace / "main_working"
    subprocess.check_call(["git", "clone", f"file://{repo_main}", workspace_main])
    subprocess.check_call(
        ["git", "submodule", "update", "--init", "--recursive"], cwd=workspace_main
    )
    assert (workspace_main / "sub" / "subsub" / "file1.txt").exists()

    # make dirty
    (workspace_main / 'sub' / 'subsub' / 'file5.txt').write_text("data")
    import pudb;pudb.set_trace()
    Repo(workspace_main).full_clean()