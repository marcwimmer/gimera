#!/usr/bin/env python3
import yaml
from git import Repo
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


def test_basicbehaviour(temppath, python, gimera):
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
    import pudb;pudb.set_trace()
    subprocess.check_call(gimera + ["apply"], cwd=workspace)
    subprocess.check_call(["git", "add", "gimera.yml"])
    subprocess.check_call(["git", "commit", "-am", "updated gimera"])
    return

    click.secho(
        "Now we have a repo with two subrepos; now we update the subrepos and pull"
    )
    (remote_sub_repo / "file2.txt").write_text("This is a new function")
    subprocess.check_call(["git", "add", "file2.txt"], cwd=remote_sub_repo)
    subprocess.check_call(["git", "commit", "-am", "file2 added"], cwd=remote_sub_repo)
    import pudb;pudb.set_trace()
    return
    subprocess.check_call(gimera + ["apply", "--update"], cwd=path)

    click.secho(str(path), fg="green")
    assert (path / "roles" / "sub1" / "file2.txt").exists()
    assert (path / "roles2" / "sub1" / "file2.txt").exists()

    # check dirty - disabled because the command is_path_dirty is not cool
    os.environ["GIMERA_DEBUG"] = "1"
    (path / "roles2" / "sub1" / "file2.txt").write_text("a change!")
    (path / "roles2" / "sub1" / "file3.txt").write_text("a new file!")
    (path / "file4.txt").write_text("a new file!")
    test = subprocess.check_output(
        ["python3", current_dir.parent / "gimera.py", "is_path_dirty", "roles2/sub1"],
        cwd=path,
    ).decode("utf-8")
    assert "file2.txt" in test
    assert "file3.txt" in test
    assert "file4.txt" not in test

    # now lets make a patch
    subprocess.check_call(
        ["python3", current_dir.parent / "gimera.py", "apply", "--update"], cwd=path
    )
    subprocess.check_call(["git", "add", "roles2"], cwd=path)
    subprocess.check_call(["git", "commit", "-am", "patches"], cwd=path)

    # now lets make an update and see if patches are applied
    (remote_sub_repo / "file5.txt").write_text("I am no 5")
    subprocess.check_call(["git", "add", "file5.txt"], cwd=remote_sub_repo)
    subprocess.check_call(["git", "commit", "-am", "file5 added"], cwd=remote_sub_repo)
    # should apply patches now
    subprocess.check_call(
        ["python3", current_dir.parent / "gimera.py", "apply"], cwd=path
    )


def _make_remote_repo(path):
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "--bare", "--initial-branch=main"], cwd=path)

    tmp = path.parent / 'tmp'
    subprocess.check_call(["git", "clone", f"file://{path}", tmp])
    (tmp / "file1.txt").write_text("random repo on main")
    subprocess.check_call(["git", "add", "file1.txt"], cwd=tmp)
    subprocess.check_call(["git", "commit", "-am", "on main"], cwd=tmp)
    subprocess.check_call(["git", "push"], cwd=tmp)

    subprocess.check_call(["git", "checkout", "-b", "branch1"], cwd=tmp)
    (tmp / "file1.txt").write_text("random repo on branch1")
    subprocess.check_call(["git", "add", "file1.txt"], cwd=tmp)
    subprocess.check_call(["git", "commit", "-am", "on branch1"], cwd=tmp)
    subprocess.check_call(["git", "push", "--set-upstream", "origin", "branch1"], cwd=tmp)

    shutil.rmtree(tmp)
    return path
