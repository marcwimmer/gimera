from .fixtures import * # required for all
import uuid
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
import click
import inspect
import os
from pathlib import Path
from .tools import gimera_apply
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git


def test_commit(temppath):
    """
    Standard case: the integrated path is tracked in the main repo.
    (For the gitignored path see test_commit_gitignored_path.)
    """
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    # region gimera config
    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "sub1",
                "type": "integrated",
            },
        ]
    }
    # endregion

    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    (workspace / "main.txt").write_text("main repo")
    subprocess.check_call(git + ["add", "main.txt"], cwd=workspace)
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)
    os.chdir(workspace)
    gimera_apply([], None)
    Repo(workspace).simple_commit_all()
    assert not Repo(workspace).staged_files

    click.secho(
        "Now we have a repo with integrated and gitignored sub"
        "\nWe change something and check if a patch is made."
    )
    os.chdir(workspace)
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"

    os.chdir(workspace)
    gimera_apply([], update=False)

    (workspace / "sub1" / "file2.txt").write_text("a new file!")

    gimera_commit("sub1", "branch1", "i committed", False)
    os.environ["GIMERA_FORCE"] = "1"
    os.unlink(workspace / "sub1" / "file2.txt")
    subprocess.check_output(git + ["checkout", "sub1/file1.txt"])
    os.environ["GIMERA_NON_THREADED"] = "1"
    gimera_apply([], update=True)
    assert (
        workspace / "sub1" / "file2.txt"
    ).exists(), "sub1/file2.txt should now exist"

    # failed patch handling
    file1 = workspace / "sub1" / "file1.txt"
    file1.write_text("main\na change!")
    gimera_commit("sub1", "branch1", "i committed", False)
    subprocess.check_output(git + ["checkout", "sub1/file1.txt"])
    gimera_apply([], update=True)
    assert "a change!" in (workspace / "sub1" / "file1.txt").read_text()


def test_commit_gitignored_path(temppath):
    """
    The integrated path is gitignored in the main repo (never tracked there).
    gimera commit must build the patch against the upstream state, not the
    main repo's index — previously this crashed because `git add` refuses
    ignored paths (or, for untracked paths, produced unappliable
    whole-file-is-new patches).
    """
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"

    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "sub1",
                "type": "integrated",
            },
        ]
    }
    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    # the zync situation: integrated path is gitignored in the main repo
    (workspace / ".gitignore").write_text("/sub1\n")
    subprocess.check_call(git + ["add", "."], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)
    os.chdir(workspace)
    gimera_apply([], None)

    # sub1 must not be tracked in the main repo
    tracked = subprocess.check_output(
        git + ["ls-files", "--", "sub1"], cwd=workspace, encoding="utf8"
    )
    assert not tracked.strip()

    # change a tracked file and add a new one inside the ignored dir
    (workspace / "sub1" / "file1.txt").write_text(
        "random repo on branch1\na local fix!"
    )
    (workspace / "sub1" / "file_new.txt").write_text("brand new")

    gimera_commit("sub1", "branch1", "fix from main repo", False)

    # upstream must now contain exactly those changes
    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert "a local fix!" in (subpath / "file1.txt").read_text()
        assert (subpath / "file_new.txt").read_text() == "brand new"
