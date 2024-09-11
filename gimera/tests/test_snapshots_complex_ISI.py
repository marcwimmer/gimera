import itertools
from .fixtures import *  # required for all
import shutil
import os
import yaml
import subprocess
from ..consts import gitcmd as git
from ..repo import Repo
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_apply
from ..tools import safe_relative_to
from ..tools import get_effective_state
from ..tools import _make_sure_hidden_gimera_dir

token = {"token": 0}

import inspect
import os
from pathlib import Path

current_file = Path(os.path.abspath(inspect.getfile(inspect.currentframe())))
basename = current_file.stem

combinations = [
    ("S", "S", "S"),
    ("S", "S", "I"),
    ("S", "I", "S"),
    ("I", "S", "S"),
    ("S", "I", "I"),
    ("I", "S", "I"),
    ("I", "I", "S"),
    ("I", "I", "I"),
]

if basename == "test_snapshots_complex":
    for combo in combinations:
        letters = "".join(combo)
        filename = f"{basename}_{letters}.py"
        path = current_file.parent / filename
        code = current_file.read_text()
        code = code.replace("__COMBO__ = [('I', 'S', 'I')]", f"__COMBO__ = [{combo}]")
        code = code.replace(
            "test_snapshot_complex_ISI", f"test_snapshot_complex_{letters}"
        )
        path.write_text(code)
__COMBO__ = [('I', 'S', 'I')]


def test_snapshot_complex_ISI(temppath):
    for I, combo in enumerate(__COMBO__):

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
    _make_sure_hidden_gimera_dir(repo.path)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    # change every level of the repo for its own; then change all levels and check
    for mode in ["use_gimera_migrate", "direct_snapshots"]:
    # for mode in ["direct_snapshots"]:
    # for mode in ["use_gimera_migrate"]:
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
                [
                    "a1/b1/sub1/a11/b11/sub1.1",
                    "a1/b1/sub1",
                    "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                ],
                [
                    "a1/b1/sub1/a11/b11/sub1.1",
                    "a1/b1/sub1",
                    "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                ],
                [
                    "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                    "a1/b1/sub1/a11/b11/sub1.1",
                    "a1/b1/sub1",
                ],
                [
                    "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                    "a1/b1/sub1",
                    "a1/b1/sub1/a11/b11/sub1.1",
                ],
                ["a1/b1/sub1", "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1"],
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
            token["token"] += 1
            os.environ["GIMERA_TOKEN"] = str(token["token"])
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
                for j, adapted_path in enumerate(adapted_paths):
                    state = get_effective_state(
                        workspace_main, workspace_main / adapted_path, {}
                    )
                    closest_gimera = state["closest_gimera"]
                    parent_gimera = state["parent_gimera"]
                    parent_repo = Repo(state["parent_repo"])
                    working_dir = parent_gimera
                    relpath = safe_relative_to(
                        workspace_main / adapted_path, working_dir
                    )
                    effstate = get_effective_state(
                        workspace_main, workspace_main / adapted_path, {}
                    )
                    if effstate["is_submodule"]:
                        other_type = "integrated"
                    else:
                        other_type = "submodule"
                    pwd = os.getcwd()
                    os.chdir(working_dir)
                    token["token"] += 1
                    os.environ["GIMERA_TOKEN"] = str(token["token"])

                    def _apply():
                        gimera_apply(
                            [effstate["parent_gimera_relpath"]],
                            None,
                            force_type=other_type,
                            recursive=True,
                            migrate_changes=True,
                            strict=True,
                        )

                    # Explanation for gimera force = True:
                    # If submodules receive commits they get changed; so
                    # they appear as "new commits" in git status. It is uncertain,
                    # that other commits were done to the sup repo as well and then
                    # just deleting the subrepo would be a loss.
                    # Keeping this comment: we check transferring the changes, so just
                    # forcing takes some of the test complexity away.
                    # We explicitly commit the dirty sub repos.
                    assert os.getenv("GIMERA_FORCE") == "0"

                    for path in [
                        ".",
                        "a1/b1/sub1",
                        "a1/b1/sub1/a11/b11/sub1.1",
                        "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                        ".",
                        "a1/b1/sub1",
                        "a1/b1/sub1/a11/b11/sub1.1",
                        "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                        ".",
                        "a1/b1/sub1",
                        "a1/b1/sub1/a11/b11/sub1.1",
                        "a1/b1/sub1/a11/b11/sub1.1/a111/b111/sub1.1.1",
                    ]:
                        repo = Repo(workspace_main / path)
                        list(repo.get_submodules_with_new_commits())
                        for submodule in list(repo.get_submodules_with_new_commits()):
                            repo.X(*(git + ["add", submodule.path]))
                            repo.X(*(git + ["commit", "-m", "committed changes"]))
                    _apply()
                    os.chdir(pwd)
                    _assure_kept_changes(workspace_main, adapted_path)


def _assure_kept_changes(workspace_main, adapted_path):
    dirty_file = workspace_main / adapted_path / "file1.txt"
    added_file = workspace_main / adapted_path / "newfile.txt"
    deleted_file = workspace_main / adapted_path / "dont_look_at_me"
    # make sure that situation is like before:
    state = get_effective_state(workspace_main, workspace_main / adapted_path, {})
    parent_repo = state["parent_repo"]

    assert dirty_file.read_text() == "i changed the file"
    assert added_file.exists()
    assert not deleted_file.exists()

    os.environ["BREAKPOINT"] = "1"
    for file in [dirty_file, added_file, deleted_file]:
        if state["is_submodule"]:
            repo = Repo(adapted_path)
        else:
            repo = Repo(parent_repo)
        assert (
            file in repo.all_dirty_files_absolute
        ), f"{file} not in {repo.all_dirty_files}"
