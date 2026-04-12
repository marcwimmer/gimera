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


def test_submodule_unpushed_commits_protected(temppath):
    """
    If a submodule has local commits that are not pushed to the remote,
    gimera apply must refuse to run (unless GIMERA_FORCE=1).
    """
    workspace = temppath / "test_unpushed"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub = _make_remote_repo(temppath / "sub1")

    repos_config = {
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

    with clone_and_commit(repo_sub, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("initial content")
        Repo(repopath).simple_commit_all()

    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_config))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    os.chdir(workspace_main)
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    gimera_apply([], None)

    # Make a local commit in the submodule WITHOUT pushing
    sub_path = workspace_main / "sub1"
    (sub_path / "local_change.txt").write_text("unpushed change")
    sub_repo = Repo(sub_path)
    sub_repo.simple_commit_all()

    # gimera apply should fail - unpushed commits would be lost
    os.chdir(workspace_main)
    os.environ["GIMERA_FORCE"] = "0"
    try:
        gimera_apply([], None, raise_exception=True)
    except Exception:
        pass
    else:
        raise AssertionError("Should have raised due to unpushed commits")

    # Verify the local commit still exists
    assert (sub_path / "local_change.txt").exists()

    # With GIMERA_FORCE=1, it should succeed (override protection)
    os.environ["GIMERA_FORCE"] = "1"
    gimera_apply([], None)
    os.environ["GIMERA_FORCE"] = "0"


def test_switch_submodule_to_integrated_unpushed_commits_protected(temppath):
    """
    Switching from submodule to integrated must not lose unpushed commits.
    """
    workspace = temppath / "test_unpushed_switch"
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

    with clone_and_commit(repo_sub, "branch1") as repopath:
        (repopath / "repo_sub.txt").write_text("initial content")
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
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    gimera_apply([], None)

    # Make a local commit in the submodule WITHOUT pushing
    sub_path = workspace_main / "sub1"
    (sub_path / "local_change.txt").write_text("unpushed change")
    sub_repo = Repo(sub_path)
    sub_repo.simple_commit_all()

    # Switch to integrated - should fail due to unpushed commits
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_int))
    repo.simple_commit_all()

    os.chdir(workspace_main)
    os.environ["GIMERA_FORCE"] = "0"
    try:
        gimera_apply([], None, raise_exception=True)
    except Exception:
        pass
    else:
        raise AssertionError(
            "Should have raised due to unpushed commits when switching to integrated"
        )


import itertools

# Combos where at least one submodule level starts as "S" (submodule type)
# and changes - only submodule type can have unpushed commits
# Format: (level1_from, level1_to, level2_from, level2_to)
_nested_combos = [
    # sub1=S with unpushed, sub1.1=S with unpushed - both switch
    ("S", "I", "S", "I"),
    ("S", "I", "S", "S"),
    ("S", "S", "S", "I"),
    # sub1=S with unpushed, sub1.1=I (no unpushed possible at level2)
    ("S", "I", "I", "I"),
    ("S", "I", "I", "S"),
    # sub1=I (no unpushed), sub1.1=S with unpushed
    ("I", "I", "S", "I"),
    ("I", "I", "S", "S"),
    ("I", "S", "S", "I"),
    ("I", "S", "S", "S"),
]


@pytest.mark.parametrize(
    "combo",
    _nested_combos,
    ids=["".join(c) for c in _nested_combos],
)
def test_nested_unpushed_commits_protected(temppath, combo):
    """
    2-level nested submodules: main -> sub1 -> sub1.1
    Make unpushed commits in submodule-type repos.
    Verify gimera refuses to apply when unpushed commits would be lost.
    """
    type1_from, type1_to, type11_from, type11_to = [
        "submodule" if x == "S" else "integrated" for x in combo
    ]

    workspace = temppath / "test_nested_unpushed"
    workspace.mkdir()
    workspace_main = workspace / "main_working"

    repo_main = _make_remote_repo(temppath / "mainrepo")
    repo_sub1 = _make_remote_repo(temppath / "sub1")
    repo_sub11 = _make_remote_repo(temppath / "sub1.1")

    def _gimera_cfg(t1):
        return {
            "repos": [
                {
                    "url": f"file://{repo_sub1}",
                    "branch": "branch1",
                    "path": "sub1",
                    "patches": [],
                    "type": t1,
                },
            ]
        }

    def _sub_gimera_cfg(t11):
        return {
            "repos": [
                {
                    "url": f"file://{repo_sub11}",
                    "branch": "branch1",
                    "path": "sub1.1",
                    "patches": [],
                    "type": t11,
                },
            ]
        }

    # Setup sub1.1 remote
    with clone_and_commit(repo_sub11, "branch1") as repopath:
        (repopath / "sub11_file.txt").write_text("sub1.1 content")
        Repo(repopath).simple_commit_all()

    # Setup sub1 remote with gimera.yml pointing to sub1.1
    with clone_and_commit(repo_sub1, "branch1") as repopath:
        (repopath / "sub1_file.txt").write_text("sub1 content")
        (repopath / "gimera.yml").write_text(yaml.dump(_sub_gimera_cfg(type11_from)))
        Repo(repopath).simple_commit_all()

    # Setup main repo
    subprocess.check_output(
        git + ["clone", "file://" + str(repo_main), workspace_main],
        cwd=workspace.parent,
    )
    (workspace_main / "gimera.yml").write_text(yaml.dump(_gimera_cfg(type1_from)))
    (workspace_main / "main.txt").write_text("main repo")
    repo = Repo(workspace_main)
    repo.simple_commit_all()
    repo.X(*(git + ["push"]))

    os.chdir(workspace_main)
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    os.environ["GIMERA_FORCE"] = "0"
    gimera_apply([], None, recursive=True, strict=True)

    # Make unpushed commits only in submodule-type repos
    sub1_path = workspace_main / "sub1"
    sub11_path = sub1_path / "sub1.1"

    if type1_from == "submodule":
        (sub1_path / "unpushed_level1.txt").write_text("level 1 unpushed")
        Repo(sub1_path).simple_commit_all()

    if type11_from == "submodule":
        (sub11_path / "unpushed_level2.txt").write_text("level 2 unpushed")
        Repo(sub11_path).simple_commit_all()

    # Now switch types in main gimera.yml
    (workspace_main / "gimera.yml").write_text(yaml.dump(_gimera_cfg(type1_to)))
    repo.simple_commit_all()

    # Update sub1's gimera.yml for sub1.1 type change
    if sub1_path.exists() and (sub1_path / "gimera.yml").exists():
        (sub1_path / "gimera.yml").write_text(yaml.dump(_sub_gimera_cfg(type11_to)))
        if type1_from == "submodule":
            Repo(sub1_path).simple_commit_all()

    os.chdir(workspace_main)
    os.environ["GIMERA_FORCE"] = "0"
    try:
        gimera_apply(
            [], None, recursive=True, strict=True, raise_exception=True
        )
    except Exception:
        pass
    else:
        raise AssertionError(
            f"Should have raised due to unpushed commits "
            f"(combo={''.join(combo)})"
        )
