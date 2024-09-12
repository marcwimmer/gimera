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
from ..tools import _make_sure_hidden_gimera_dir


def test_snapshot_and_restore_simple_add_delete_modify_direct_subrepo_submodule(
    temppath,
):
    repo_sub = _make_remote_repo(temppath / "sub1")
    repos_yaml = {
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
    _test_snapshot_and_restore_simple_add_delete_modify_direct(
        temppath, repo_sub, repos_yaml
    )


def test_snapshot_and_restore_simple_add_delete_modify_direct_subrepo_integrated(
    temppath,
):
    repo_sub = _make_remote_repo(temppath / "sub1")
    repos_yaml = {
        "repos": [
            {
                "url": f"file://{repo_sub}",
                "branch": "branch1",
                "path": "a/b/sub1",
                "patches": [],
                "type": "integrated",
            },
        ]
    }
    _test_snapshot_and_restore_simple_add_delete_modify_direct(
        temppath, repo_sub, repos_yaml
    )


def _test_snapshot_and_restore_simple_add_delete_modify_direct(
    temppath, repo_sub, repos_yaml
):
    from ..snapshot import snapshot_recursive
    from ..snapshot import snapshot_restore

    workspace = temppath / "test_snapshot_and_restore"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")

    with clone_and_commit(repo_sub, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        Repo(repopath).simple_commit_all()

    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_yaml))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    _make_sure_hidden_gimera_dir(repo.path)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))
    os.chdir(workspace_main)
    gimera_apply([], None)

    # make it dirty
    dirty_file = workspace_main / repos_yaml["repos"][0]["path"] / "file1.txt"
    original_content = dirty_file.read_text()
    dirty_file.write_text("i changed the file")
    # add a file
    added_file = workspace_main / repos_yaml["repos"][0]["path"] / "newfile.txt"
    added_file.write_text("new file")
    # delete a file
    deleted_file = workspace_main / repos_yaml["repos"][0]["path"] / "dont_look_at_me"
    deleted_file.unlink()

    os.chdir(workspace_main)
    snapshot_path = workspace_main / repos_yaml["repos"][0]["path"]
    snapshot_recursive(workspace_main, [snapshot_path])

    # reapply
    os.chdir(workspace_main)
    os.environ["GIMERA_FORCE"] = "1"
    gimera_apply([], None)

    assert dirty_file.read_text() == original_content

    # restore
    snapshot_restore(workspace_main, [snapshot_path])

    # make sure that situation is like before:
    assert dirty_file.read_text() == "i changed the file"
    assert added_file.exists()
    assert not deleted_file.exists()


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
    os.chdir(workspace_main)
    gimera_apply([], None)
    # assert everything is there
    assert (workspace_main / "sub1").exists()
    assert (workspace_main / "sub2").exists()

    # make it dirty
    dirty_file1 = workspace_main / "sub1" / "repo_sub.txt"
    dirty_file2 = workspace_main / "sub2" / "repo_sub.txt"
    assert dirty_file1.exists()
    assert dirty_file2.exists()
    dirty_file1.write_text("1")
    dirty_file2.write_text("2")
    os.environ["GIMERA_FORCE"] = "0"
    gimera_apply([], None, recursive=True, migrate_changes=True)

    assert dirty_file1.read_text() == "1"
    assert dirty_file2.read_text() == "2"
