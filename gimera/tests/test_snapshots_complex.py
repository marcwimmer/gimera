import shutil
import os
import yaml
import subprocess
from ..consts import gitcmd as git
from ..repo import Repo
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_apply


def test_snapshot_and_restore_complex_add_delete_modify_direct_subrepo(temppath):
    for I, combo in enumerate(
        [
            ("S", "S", "S"),
            ("S", "S", "I"),
            ("S", "I", "S"),
            ("I", "S", "S"),
            ("S", "I", "I"),
            ("I", "S", "I"),
            ("I", "I", "S"),
            ("I", "I", "I"),
        ]
    ):

        def _e(x):
            assert x in ("S", "I")
            return "submodule" if x == "S" else "integrated"

        type1 = _e(combo[0])
        type11 = _e(combo[0])
        type111 = _e(combo[0])

        _test_snapshot_and_restore_complex_add_delete_modify_direct_subrepo_submodule(
            temppath,
            type1,
            type11,
            type111,
        )
        shutil.rmtree(temppath / "sub1.1.1")
        shutil.rmtree(temppath / "sub1.1")
        shutil.rmtree(temppath / "sub1")


def _test_snapshot_and_restore_complex_add_delete_modify_direct_subrepo_submodule(
    temppath, type1, type11, type111
):
    repo_sub111 = _make_remote_repo(temppath / "sub1.1.1")
    repo_sub11 = _make_remote_repo(temppath / "sub1.1")
    repo_sub1 = _make_remote_repo(temppath / "sub1")
    with clone_and_commit(repo_sub111, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        Repo(repopath).simple_commit_all()

    with clone_and_commit(repo_sub11, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        (repopath / "gimera.yml").write_text(
            yaml.dump(
                {
                    "repos": [
                        {
                            "url": f"file://{repo_sub111}",
                            "branch": "branch1",
                            "path": "a111/b111/sub1.1.1",
                            "patches": [],
                            "type": type111,
                        }
                    ]
                }
            )
        )
        Repo(repopath).simple_commit_all()

    with clone_and_commit(repo_sub1, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        (repopath / "gimera.yml").write_text(
            yaml.dump(
                {
                    "repos": [
                        {
                            "url": f"file://{repo_sub11}",
                            "branch": "branch1",
                            "path": "a11/b11/sub1.1",
                            "patches": [],
                            "type": type11,
                        }
                    ]
                }
            )
        )
        Repo(repopath).simple_commit_all()

    repos_yaml = {
        "repos": [
            {
                "url": f"file://{repo_sub1}",
                "branch": "branch1",
                "path": "a1/b1/sub1",
                "patches": [],
                "type": type1,
            },
        ]
    }
    _test_snapshot_and_restore_simple_add_delete_modify_direct(
        temppath, repo_sub1, repo_sub11, repo_sub111, repos_yaml
    )


def _test_snapshot_and_restore_simple_add_delete_modify_direct(
    temppath, repo_sub1, repo_sub11, repo_sub111, repos_yaml
):
    from ..snapshot import snapshot_recursive
    from ..snapshot import snapshot_restore

    workspace = temppath / "test_snapshot_and_restore"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")

    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_yaml))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    # change every level of the repo for its own; then change all levels and check
    for i, adapted_paths in enumerate(
        [
            ["a1/b1/sub1"],
            ["a1/b1/sub1/a11/b11/sub1.1"],
            ["a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1"],
            [
                "a1/b1/sub1/a11/b11/sub1.1",
                "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
            ],
            [
                "a1/b1/sub1",
                "a1/b1/sub1/a11/b11/sub1.1",
                "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
            ],
            ["a1/b1/sub1", "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1"],
        ]
    ):
        if workspace_main.exists():
            shutil.rmtree(workspace_main)
        subprocess.check_output(
            git + ["clone", "file://" + str(repo_main), workspace_main],
            cwd=workspace.parent,
        )
        os.chdir(workspace_main)
        gimera_apply([], None, recursive=True)
        # assert everything is there
        assert (
            workspace_main
            / "a1/b1/sub1"
            / "a11/b11/sub1.1"
            / "a111/b111/sub1.1.1"
            / "repo_sub.txt"
        ).exists()

        for adapted_path in adapted_paths:

            # make it dirty
            dirty_file = workspace_main / adapted_path / "file1.txt"
            original_content = dirty_file.read_text()
            dirty_file.write_text("i changed the file")
            # add a file
            added_file = workspace_main / adapted_path / "newfile.txt"
            added_file.write_text("new file")
            # delete a file
            deleted_file = workspace_main / adapted_path / "dont_look_at_me"
            deleted_file.unlink()

        # if i == 1:
        #     import pudb

        #     pudb.set_trace()
        os.chdir(workspace_main)
        snapshot_path = workspace_main / "a1/b1/sub1"
        snapshot_recursive(workspace_main, snapshot_path)

        # reapply
        os.chdir(workspace_main)
        os.environ["GIMERA_FORCE"] = "1"
        gimera_apply([], None, recursive=True)

        for adapted_path in adapted_paths:
            dirty_file = workspace_main / adapted_path / "file1.txt"
            assert dirty_file.read_text() == original_content

        # restore
        snapshot_restore(workspace_main, snapshot_path)

        for adapted_path in adapted_paths:
            dirty_file = workspace_main / adapted_path / "file1.txt"
            added_file = workspace_main / adapted_path / "newfile.txt"
            deleted_file = workspace_main / adapted_path / "dont_look_at_me"
            # make sure that situation is like before:
            assert dirty_file.read_text() == "i changed the file"
            assert added_file.exists()
            assert not deleted_file.exists()
