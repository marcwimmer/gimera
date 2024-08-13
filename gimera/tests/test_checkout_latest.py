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

def test_checkout_not_update_if_last_commit_matches_branch_make_branch_be_checked_out(
    temppath,
):
    workspace = temppath / "workspace_checkout_match_branch"
    workspace.mkdir(exist_ok=True)
    os.chdir(workspace.parent)

    repo_main = _make_remote_repo(workspace / "mainrepo")
    repo_submodule = _make_remote_repo(workspace / "repo_submodule")

    with clone_and_commit(repo_submodule, "main") as repopath:
        (repopath / "submodule.txt").write_text("This is a new function")
        repo = Repo(repopath)
        repo.simple_commit_all()
        sha = repo.out("git", "log", "-n1", "--format=%H")
        (repopath / "submodule.txt").write_text("This is a new function2")
        repo.simple_commit_all()

    repos = {
        "repos": [
            {
                "url": f"file://{repo_submodule}",
                "branch": "main",
                "path": "sub1",
                "sha": sha,
                "type": "submodule",
            },
        ]
    }
    workspace_main = workspace / "main_working"
    main_repo = Repo(workspace_main)
    subprocess.check_call(git + ["clone", f"file://{repo_main}", workspace_main])
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos))

    os.chdir(workspace_main)
    gimera_apply([], update=None, recursive=True, strict=True)

    assert (workspace_main / "sub1" / "submodule.txt").exists()

    def _get_branch():
        branch = [
            x
            for x in subprocess.check_output(
                ["git", "branch"], encoding="utf8", cwd=workspace_main / "sub1"
            )
            .strip()
            .splitlines()
            if x.startswith("* ")
        ][0]
        return branch

    assert sha[:7] in _get_branch()

    os.chdir(workspace_main)
    gimera_apply([], update=True)
    assert " main" in _get_branch()
