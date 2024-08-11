from .fixtures import *  # required for all
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
import inspect
import os
from pathlib import Path
from .tools import gimera_apply
from ..tools import rsync
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git
import time

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def test_snapshot_two_root_submodules(temppath):
    """
    Challenge is, that the logic of snapshots can handle the root paths
    """
    workspace = temppath / "test_snapshot_two_root_submodules"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "main")
    repo_sub1 = _make_remote_repo(temppath / "sub1")
    repo_sub2 = _make_remote_repo(temppath / "sub2")

    with clone_and_commit(repo_sub1, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        Repo(repopath).simple_commit_all()
    with clone_and_commit(repo_sub2, "branch2", ["-b"]) as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        Repo(repopath).simple_commit_all()

    with clone_and_commit(repo_main, "main") as repopath:
        (repopath / "repo_main.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        (repopath / "gimera.yml").write_text(
            yaml.dump(
                {
                    "repos": [
                        {
                            "url": str(repo_sub1),
                            "branch": "branch1",
                            "path": "sub1",
                            "type": "integrated",
                        },
                        {
                            "url": str(repo_sub2),
                            "branch": "branch2",
                            "path": "sub2",
                            "type": "integrated",
                        },
                    ]
                }
            )
        )
        Repo(repopath).simple_commit_all()

    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    repo = Repo(workspace_main)
    os.chdir(workspace_main)
    gimera_apply([], None)
    # assert everything is there
    assert (workspace_main / "sub1").exists()
    assert (workspace_main / "sub2").exists()

    # make it dirty
    dirty_file1 = workspace_main / "sub1" / "repo_sub.txt"
    dirty_file2 = workspace_main / "sub1" / "repo_sub.txt"
    assert dirty_file1.exists()
    assert dirty_file2.exists()
    dirty_file1.write_text("1")
    dirty_file2.write_text("1")
    os.environ["GIMERA_FORCE"] = "0"
    gimera_apply([], None, recursive=True, migrate_changes=True)

    assert dirty_file1.read_text() == "1"
    assert dirty_file2.read_text() == "1"
