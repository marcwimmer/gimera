from .fixtures import *  # required for all
import time
import uuid
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
import click
import inspect
import os
from pathlib import Path
from .tools import gimera_apply
from .tools import _make_remote_repo
from .tools import clone_and_commit

from ..consts import gitcmd as git

def test_basicbehaviour(temppath):
    """
    * put same repo integrated and submodule into main repo
    * add file2.txt on remote
    * check after apply that file exists in both
    * make a patch in integrated version
    """
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    # region gimera config
    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "submodules/sub1",
                "patches": [],
                "type": "submodule",
            },
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "integrated/sub1",
                "patches": ["integrated/sub1_patches"],
                "type": "integrated",
            },
        ]
    }
    # endregion

    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    (workspace / "main.txt").write_text("main repo")
    subprocess.check_call(git + ["add", "main.txt"], cwd=workspace)
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)
    (workspace / repos["repos"][1]["patches"][0]).mkdir(exist_ok=True, parents=True)
    os.chdir(workspace)
    os.environ["GIMERA_NON_THREADED"] = "1"
    gimera_apply([], None)
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    assert not Repo(workspace).staged_files
    # subprocess.check_call(git + ["commit", "-am", "updated gimera"], cwd=workspace)

    click.secho(
        "Now we have a repo with two subrepos; now we update the subrepos and pull"
    )
    with clone_and_commit(remote_sub_repo, "branch1") as repopath:
        (repopath / "file2.txt").write_text("This is a new function")
        subprocess.check_call(git + ["add", "file2.txt"], cwd=repopath)
        subprocess.check_call(git + ["commit", "-am", "file2 added"], cwd=repopath)

    os.chdir(workspace)
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    gimera_apply([], update=True)

    click.secho(str(workspace), fg="green")
    assert (workspace / "submodules" / "sub1" / "file2.txt").exists()
    assert (workspace / "integrated" / "sub1" / "file2.txt").exists()

    # check dirty - disabled because the command is_path_dirty is not cool
    (workspace / "integrated" / "sub1" / "file2.txt").write_text("a change!")
    (workspace / "integrated" / "sub1" / "file3.txt").write_text("a new file!")
    (workspace / "file4.txt").write_text(
        "a new file!"
    )  # should not stop the process but should not be committed

    # annotation: it would be bad if file3.txt would be gone
    # and also the change of file2.txt

    # now lets make a patch for new integrated/sub1/file3.txt and changed integrated/sub1/file2.txt
    os.chdir(workspace)
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"
    (workspace / repos["repos"][1]["patches"][0]).mkdir(exist_ok=True, parents=True)
    gimera_apply([], update=True)
    assert (workspace / "integrated" / "sub1" / "file3.txt").exists()

    # now lets make an update and see if patches are applied
    with clone_and_commit(remote_sub_repo, "branch1") as repopath:
        (repopath / "file5.txt").write_text("This is a new function")
        subprocess.check_call(git + ["add", "file5.txt"], cwd=repopath)
        subprocess.check_call(git + ["commit", "-am", "file5 added"], cwd=repopath)

    # should apply patches now
    os.chdir(workspace)
    gimera_apply([], update=False)

    # check if test is applied
    assert "file4.txt" in [x.name for x in Repo(workspace).untracked_files]
    assert (workspace / "integrated" / "sub1" / "file3.txt").exists()
    assert (
        "a change"
        in (
            (workspace / "integrated" / "sub1" / "file3.txt").parent / "file2.txt"
        ).read_text()
    )

    # now lets edit that patch again
    Repo(workspace).simple_commit_all()
    patchfile = list((workspace / "integrated" / "sub1_patches").glob("*"))[
        0
    ].relative_to(workspace)
    os.chdir(workspace)
    from ..patches import _edit_patch as edit_patch

    edit_patch([patchfile])
    dirty_files = Repo(workspace).all_dirty_files_absolute
    assert (workspace / str(patchfile)) not in dirty_files
    assert (workspace / "integrated/sub1/file3.txt") in dirty_files
    assert (workspace / "integrated/sub1/file2.txt") in dirty_files

