from .fixtures import * # required for all
import os
import yaml
from pathlib import Path
import subprocess
from ..consts import gitcmd as git
from ..repo import Repo
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_apply

# test change something in submodule and check if gets lost if not pushed

def test_switch_submodule_to_integrated_dont_loose_changes(temppath):
    """
    A gimera sub has changes and is submodule.
    Changes shall not be lost when switching to integrated modus.
    """
    workspace = temppath / "test_switch_submodule_to_integrated_dont_loose_changes"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub = _make_remote_repo(temppath / "sub1")

    repos_sub = {
        "repos": [
            {
                "url": f"file://{repo_sub}",
                "branch": "branch1",
                "path": "sub1",
                "patches": [],
                "type": "submodule",
            },
        ]
    }
    repos_int = {
        "repos": [
            {
                "url": f"file://{repo_sub}",
                "branch": "branch1",
                "path": "sub1",
                "patches": [],
                "type": "integrated",
            },
        ]
    }
    with clone_and_commit(repo_sub, "main") as repopath:
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

    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_int))
    repo.simple_commit_all()

    # make it dirty
    dirty_file = workspace_main / "sub1" / "file1.txt"
    original_content = dirty_file.read_text()
    dirty_file.write_text("i changed the file")

    os.chdir(workspace_main)
    try:
        gimera_apply([], None, raise_exception=True)
    except Exception:
        pass
    else:
        raise NotImplementedError("Should warn about changed content.")

    # switch back
    dirty_file.write_text(original_content)
    gimera_apply([], None)

    # now change in the integrated mode the file and try to switch to submodule
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_sub))
    dirty_file.write_text("dirty content")
    try:
        gimera_apply([], None, raise_exception=True)
    except Exception:
        pass
    else:
        raise NotImplementedError("Should warn about changed content.")
    dirty_file.write_text(original_content)
    gimera_apply([], None)


def test_switch_submodule_to_integrated_dont_loose_changes_with_subsub_repos(temppath):
    """
    A gimera sub has changes and is submodule.
    Changes shall not be lost when switching to integrated modus.
    """
    workspace = (
        temppath
        / "test_switch_submodule_to_integrated_dont_loose_changes_with_subsub_repos"
    )
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub = _make_remote_repo(temppath / "sub1")
    repo_subsub = _make_remote_repo(temppath / "subsub")

    def switch_to(gimera_path, ttype):
        content = yaml.safe_load(gimera_path.read_text())
        for repo in content["repos"]:
            repo["type"] = ttype
        gimera_path.write_text(yaml.dump(content))

    with clone_and_commit(repo_sub, "main") as repopath:
        (repopath / "gimera.yml").write_text(
            yaml.dump(
                {
                    "repos": [
                        {
                            "url": f"file://{repo_subsub}",
                            "branch": "main",
                            "path": "subsub",
                            "patches": [],
                            "type": "integrated",
                        },
                    ]
                }
            )
        )
        os.chdir(repopath)
        gimera_apply([], None)

    repos_gimera = {
        "repos": [
            {
                "url": f"file://{repo_sub}",
                "branch": "main",
                "path": "sub1",
                "patches": [],
                "type": "submodule",
            },
        ]
    }
    with clone_and_commit(repo_sub, "main") as repopath:
        (repopath / "repo_sub.txt").write_text("This is a new function")
        (repopath / "dont_look_at_me").write_text("i am ugly")
        Repo(repopath).simple_commit_all()

    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    os.chdir(workspace_main)
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_gimera))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    os.chdir(workspace_main)
    gimera_apply([], None, recursive=True, strict=True)

    dirty_file = workspace_main / "sub1" / "subsub" / "file1.txt"
    original_content = dirty_file.read_text()
    dirty_file.write_text("changed it")
    os.chdir(workspace_main / "sub1")
    switch_to(Path("gimera.yml"), "submodule")
    try:
        gimera_apply([], None, raise_exception=True)
    except Exception:
        pass
    else:
        raise ValueError("Error for diff losts expected.")

    dirty_file.write_text(original_content)
    gimera_apply([], None)
    dirty_file.write_text("dirty")
    os.chdir(workspace_main / "sub1")
    switch_to(Path("gimera.yml"), "integrated")
    try:
        gimera_apply([], None)
    except Exception:
        pass
    else:
        raise ValueError("Error for diff losts expected.")
