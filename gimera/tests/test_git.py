import os
import subprocess
from ..consts import gitcmd as git
from ..repo import Repo
from . tools import _make_remote_repo
from . tools import clone_and_commit
from . import temppath

def test_git_status(temppath):
    """
    make dirty submodule then repo.full_clean
    """
    workspace = temppath / "workspace_git_status"
    os.chdir(workspace.parent)

    repo_main = _make_remote_repo(temppath / "mainrepo")

    with clone_and_commit(repo_main, "main") as repopath:
        (repopath / "file1.txt").write_text("This is a new function")
        Repo(repopath).simple_commit_all()

    workspace_main = workspace / "main_working"
    subprocess.check_call(git + ["clone", f"file://{repo_main}", workspace_main])
    (workspace_main / "file8.txt").write_text("Newfile")
    repo = Repo(workspace_main)
    assert not repo.staged_files
    assert repo.untracked_files
