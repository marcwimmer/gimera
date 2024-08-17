from .fixtures import *  # required for all
import os
import yaml
import subprocess
from ..consts import gitcmd as git
from ..repo import Repo
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_apply


def test_switch_submodule_to_integrated_migrate_changes(temppath):
    """
    A gimera sub has changes and is submodule.
    Changes shall not be lost when switching to integrated modus.
    """

    def _make_changes():
        # make it dirty
        dirty_file = workspace_main / "a" / "b" / "sub1" / "file1.txt"
        original_content = dirty_file.read_text()
        dirty_file.write_text("i changed the file")
        # add a file
        added_file = workspace_main / "a" / "b" / "sub1" / "newfile.txt"
        added_file.write_text("new file")
        # delete a file
        deleted_file = workspace_main / "a" / "b" / "sub1" / "dont_look_at_me"
        deleted_file.unlink()

    def _assert_changes():
        dirty_file = workspace_main / "a" / "b" / "sub1" / "file1.txt"
        added_file = workspace_main / "a" / "b" / "sub1" / "newfile.txt"
        deleted_file = workspace_main / "a" / "b" / "sub1" / "dont_look_at_me"
        assert dirty_file.read_text() == "i changed the file"
        assert added_file.exists()
        assert not deleted_file.exists()

    workspace = temppath / "test_switch_submodule_to_integrated_migrate_changes"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub = _make_remote_repo(temppath / "sub1")

    repos_sub = {
        "repos": [
            {
                "url": f"file://{repo_sub}",
                "branch": "branch1",
                "path": "a/b/sub1",
                "patches": [],
                "type": "submodule",
            },
        ]
    }
    with clone_and_commit(repo_sub, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        Repo(repopath).simple_commit_all()

    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_sub))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    os.chdir(workspace_main)
    gimera_apply([], None)

    _make_changes()

    os.chdir(workspace_main)
    gimera_apply([], update=True, migrate_changes=True)

    # check if still dirty
    _assert_changes()
