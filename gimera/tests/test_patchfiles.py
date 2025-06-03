from .fixtures import * # required for all
import itertools
import uuid
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
from pathlib import Path
import shutil
import click
import inspect
import os
from .tools import gimera_apply
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git


def test_common_patchfiles_in_subgimera(temppath):
    """
    * put same repo integrated and submodule into main repo
    * add file2.txt on remote
    * check after apply that file exists in both
    * make a patch in integrated version
    """
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    # Make a repo with a patch file and gimera instruction file to
    # include the local patch files depending on the variable $VERSION
    with clone_and_commit(remote_main_repo, "branch1", commit=False) as repopath:
        file1 = repopath / "file_is_patch.txt"
        file1.write_text("patchfile")

        repo = Repo(repopath)
        repo.simple_commit_all()
        patch_content = subprocess.check_output(
            ["git", "format-patch", "HEAD~1", "--stdout", "--relative"],
            encoding="utf8",
            cwd=repopath,
        )

    # region gimera config
    repos = {
        "common": {
            "vars": {"branch": "branch1"},
            "patches": [],
        },
        "repos": [
            {
                "url": f"file://{remote_main_repo}",
                "branch": "${branch}",
                "path": "integrated/sub1",
                "type": "integrated",
                "patches": [
                    {"path": "mypatches"}
                ]
            },
        ],
    }
    # endregion

    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    (workspace / "main.txt").write_text("main repo")
    (workspace / "mypatches").mkdir(parents=True, exist_ok=True)
    (workspace / "mypatches" / "patch1.patch").write_text(patch_content)
    subprocess.check_call(git + ["add", "mypatches"], cwd=workspace)
    subprocess.check_call(git + ["add", "main.txt"], cwd=workspace)
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)
    os.chdir(workspace)
    gimera_apply([], None)
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    assert not Repo(workspace).staged_files

    click.secho(
        "Now we have a repo with two subrepos; now we update the subrepos and pull"
    )

    os.chdir(workspace)
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"
    gimera_apply([], update=True, recursive=True, strict=True)
    testfile = workspace / "integrated" / "sub1" / "file_is_patch.txt"
    assert testfile.exists()

    # ignore patchfile now
    patchfile = list(
        (workspace / "mypatches").rglob("*.patch")
    )[0]
    repos["repos"][0]["ignored_patchfiles"] = [patchfile.name]
    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    gimera_apply([], None)
    assert not testfile.exists()

