from .fixtures import *  # required for all
import itertools
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


def test_snapshot_switch_around_and_check_if_everything_is_there_several_subpaths(
    temppath,
):
    _test_snapshot_switch_around_and_check_if_everything_is_there(temppath, "a/b/sub1")


def test_snapshot_switch_around_and_check_if_everything_is_there_direct_root(temppath):
    _test_snapshot_switch_around_and_check_if_everything_is_there(temppath, "sub1")


def _test_snapshot_switch_around_and_check_if_everything_is_there(temppath, sub_path):
    """
    Challenge is, that the logic of snapshots can handle the root paths
    """
    workspace = (
        temppath / "test_snapshot_switch_around_and_check_if_everything_is_there"
    )
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "main")
    repo_sub1 = _make_remote_repo(temppath / "sub1")

    with clone_and_commit(repo_sub1, "branch1") as repopath:
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
                            "path": sub_path,
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
    os.chdir(workspace_main)
    gimera_apply([], None)
    # assert everything is there
    assert (workspace_main / sub_path).exists()

    # make it dirty
    dirty_file1 = workspace_main / sub_path / "repo_sub.txt"
    assert dirty_file1.exists()
    dirty_file1.write_text("1")
    os.environ["GIMERA_FORCE"] = "0"
    gimera_apply([], None, recursive=True, migrate_changes=True, strict=True)

    assert dirty_file1.read_text() == "1"
    gimera_apply(
        [],
        None,
        force_type="submodule",
        recursive=True,
        migrate_changes=True,
        strict=True,
    )

    assert dirty_file1.read_text() == "1"
    gimera_apply(
        [],
        None,
        force_type="integrated",
        recursive=True,
        migrate_changes=True,
        strict=True,
    )
