import os
import yaml
import subprocess
from ..consts import gitcmd as git
from ..repo import Repo
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_apply
from .fixtures import set_env_vars


def test_switch_submodule_to_integrated_migrate_changes(temppath):
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
    gimera_apply([], {})

    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_int))
    repo.simple_commit_all()

    # make it dirty
    dirty_file = workspace_main / "sub1" / "file1.txt"
    original_content = dirty_file.read_text()
    dirty_file.write_text("i changed the file")

    os.chdir(workspace_main)
    gimera_apply([], update=True, migrate_changes=True)

    # check if still dirty
    assert "i changed the file" in dirty_file.read_text()

    # switch back
    dirty_file.write_text(original_content)
    gimera_apply([], update=True, migrate_changes=True)
    assert "i changed the file" in dirty_file.read_text()

    raise NotImplementedError("Test update of integrated module")
    raise NotImplementedError("Test update of submodule module")

    # now change in the integrated mode the file and try to switch to submodule
    (workspace_main / "gimera.yml").write_text(yaml.dump(repos_sub))
    dirty_file.write_text("dirty content")
    gimera_apply([], migrate_changes=True)
    dirty_file.write_text(original_content)
    gimera_apply([], None)
