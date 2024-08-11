import tempfile
import re
from contextlib import contextmanager
import os
from datetime import datetime
import inquirer
import click
import sys
from pathlib import Path
from .repo import Repo, Remote
from .gitcommands import GitCommands
from .fetch import _fetch_repos_in_parallel
from .tools import _get_main_repo
from .tools import _raise_error, safe_relative_to
from .consts import gitcmd as git
from .tools import prepare_dir
from .tools import wait_git_lock
from .tools import rmtree
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB
from .config import Config
from .patches import make_patches
from .patches import _apply_patches
from .patches import _apply_patchfile
from .patches import _technically_make_patch
from .patches import _get_available_patchfiles
from .tools import is_forced
from .tools import verbose
from .tools import try_rm_tree
from .tools import _get_remotes
from .patches import _apply_patchfile
from .cachedir import _get_cache_dir
from .submodule import _make_sure_subrepo_is_checked_out
from .submodule import _fetch_latest_commit_in_submodule
from .snapshot import snapshot_recursive, snapshot_restore
from .tools import _get_missing_repos

def _commit(repo, branch, message, preview):
    config = Config()
    repo = config.get_repos(Path(repo))
    path2 = Path(tempfile.mktemp(suffix="."))
    main_repo = _get_main_repo()
    assert len(repo) == 1
    repo = repo[0]

    with prepare_dir(path2) as path2:
        path2 = path2 / "repo"
        gitrepo = Repo(path2)
        main_repo.X(*(git + ["clone", repo.url, path2]))

        if not branch:
            res = click.confirm(
                f"\n\n\nCommitting to branch {repo.branch} - continue?", default=True
            )
            if not res:
                sys.exit(-1)
            branch = repo.branch

        gitrepo.X(*(git + ["checkout", "-f", branch]))
        src_path = main_repo.path / repo.path
        patch_content = _technically_make_patch(main_repo, src_path)

        patchfile = gitrepo.path / "1.patch"
        patchfile.write_text(patch_content)

        _apply_patchfile(patchfile, gitrepo.path, error_ok=False)

        patchfile.unlink()
        gitrepo.X(*(git + ["add", "."]))
        if preview:
            gitrepo.X(*(git + ["diff"]))
            doit = inquirer.confirm("Commit this?", default=True)
            if not doit:
                return
        gitrepo.X(*(git + ["commit", "-m", message]))
        gitrepo.X(*(git + ["push"]))