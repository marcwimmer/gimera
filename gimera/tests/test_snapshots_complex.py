from .fixtures import *  # required for all
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
from ..tools import get_nearest_repo
from ..tools import safe_relative_to
from ..tools import get_parent_gimera
from ..tools import get_effective_state

token  = {'token': 1}

def test_snapshot_and_restore_complex_add_delete_modify_direct_subrepo(temppath):
    for I, combo in enumerate(
        [
            # ("S", "S", "S"),
            # ("S", "S", "I"),
            ("S", "I", "S"),
            # ("I", "S", "S"),
            # ("S", "I", "I"),
            # ("I", "S", "I"),
            # ("I", "I", "S"),
            # ("I", "I", "I"),
        ]
    ):

        def _e(x):
            assert x in ("S", "I")
            return "submodule" if x == "S" else "integrated"

        type1 = _e(combo[0])
        type11 = _e(combo[1])
        type111 = _e(combo[2])

        _test_snapshot_and_restore_complex_add_delete_modify_direct_subrepo_submodule(
            temppath,
            type1,
            type11,
            type111,
        )
        shutil.rmtree(temppath / "sub1.1.1")
        shutil.rmtree(temppath / "sub1.1")
        shutil.rmtree(temppath / "sub1")
        shutil.rmtree(temppath / "mainrepo")
        shutil.rmtree(temppath / "test_snapshot_and_restore")


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
                            "url": str(repo_sub111),
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
                            "url": str(repo_sub11),
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
                "url": str(repo_sub1),
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
        git + ["clone", str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_yaml))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    # change every level of the repo for its own; then change all levels and check
    # TODO
    # for mode in ["use_gimera_migrate"]:
    for mode in ["use_gimera_migrate", "direct_snapshots"]:
        for i, adapted_paths in enumerate(
            [
                # ["a1/b1/sub1"],
                # ["a1/b1/sub1/a11/b11/sub1.1"],
                # ["a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1"],
                # [
                #     "a1/b1/sub1/a11/b11/sub1.1",
                #     "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                # ],
                # [
                #     "a1/b1/sub1",
                #     "a1/b1/sub1/a11/b11/sub1.1",
                #     "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                # ],
                ["a1/b1/sub1" ,"a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1"],
                ["a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1", "a1/b1/sub1"],
            ]
        ):
            if workspace_main.exists():
                shutil.rmtree(workspace_main)
            subprocess.check_output(
                git + ["clone", str(repo_main), workspace_main],
                cwd=workspace.parent,
            )
            os.chdir(workspace_main)
            gimera_apply([], None, recursive=True, strict=True)
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

            os.chdir(workspace_main)
            if mode == "direct_snapshots":
                snapshot_path = workspace_main / "a1/b1/sub1"
                snapshot_recursive(workspace_main, [snapshot_path])

            # reapply
            os.chdir(workspace_main)

            if mode == "direct_snapshots":
                os.environ["GIMERA_FORCE"] = "1"
                gimera_apply([], None, recursive=True, strict=True)

                for adapted_path in adapted_paths:
                    dirty_file = workspace_main / adapted_path / "file1.txt"
                    assert dirty_file.read_text() == original_content
            else:
                os.environ["GIMERA_FORCE"] = "0"
                os.environ["PYTHONBREAKPOINT"] = "pudb"
                gimera_apply(
                    [], None, recursive=True, migrate_changes=True, strict=True
                )

            # restore
            if mode == "direct_snapshots":
                snapshot_restore(workspace_main, [snapshot_path])

            for adapted_path in adapted_paths:
                _assure_kept_changes(workspace_main, adapted_path)

            if mode == "use_gimera_migrate":
                # switch to other mode integrated/submodule and check
                # if changes are transported
                for adapted_path in adapted_paths:
                    state = get_effective_state(
                        workspace_main, workspace_main / adapted_path
                    )
                    closest_gimera = state["closest_gimera"]
                    parent_gimera = state["parent_gimera"]
                    parent_repo = Repo(state["parent_repo"])
                    working_dir = parent_gimera
                    relpath = safe_relative_to(
                        workspace_main / adapted_path, working_dir
                    )
                    effstate = get_effective_state(
                        workspace_main, workspace_main / adapted_path
                    )
                    if effstate["is_submodule"]:
                        other_type = "integrated"
                    else:
                        other_type = "submodule"
                    pwd = os.getcwd()
                    os.chdir(working_dir)
                    os.environ['GIMERA_TOKEN'] = str(token['token'])
                    token['token'] += 1
                    gimera_apply(
                        [effstate["parent_gimera_relpath"]],
                        None,
                        force_type=other_type,
                        recursive=True,
                        migrate_changes=True,
                        strict=True,
                    )
                    os.chdir(pwd)
                    _assure_kept_changes(workspace_main, adapted_path)


def _assure_kept_changes(workspace_main, adapted_path):
    dirty_file = workspace_main / adapted_path / "file1.txt"
    added_file = workspace_main / adapted_path / "newfile.txt"
    deleted_file = workspace_main / adapted_path / "dont_look_at_me"
    # make sure that situation is like before:
    assert dirty_file.read_text() == "i changed the file"
    assert added_file.exists()
    assert not deleted_file.exists()
