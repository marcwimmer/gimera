from contextlib import contextmanager
import os
import click
from pathlib import Path
from .repo import Repo, Remote
from .tools import _raise_error
from .consts import gitcmd as git
from .tools import wait_git_lock
from .tools import rmtree
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB
from .patches import _apply_patches
from .patches import _apply_patchfile
from .tools import _get_remotes
from .tools import get_effective_state
from .tools import get_nearest_repo
from .tools import verbose
from .patches import _apply_patchfile
from .cachedir import _get_cache_dir


def _update_integrated_module(
    working_dir,
    main_repo,
    repo_yml,
    update,
    common_vars,
    **options,
):
    """
    Put contents of a git repository inside the main repository.
    """
    # use a cache directory for pulling the repository and updating it
    with _get_cache_dir(main_repo, repo_yml, update=update) as cache_dir:
        if not os.access(cache_dir, os.W_OK):
            _raise_error(f"No R/W rights on {cache_dir}")
        repo = Repo(cache_dir)
        verbose(f"Updating integrated module {repo_yml.path}")

        parent_repo = main_repo
        dest_path = Path(working_dir) / repo_yml.path
        parent_repo = Repo(get_nearest_repo(main_repo.path, dest_path))

        # BTW: delete-after cannot remove unused directories - cool to know; is
        # just standarded out
        if dest_path.exists():
            rmtree(dest_path)

        with wait_git_lock(cache_dir):
            commit = repo_yml.sha or repo_yml.branch if not update else repo_yml.branch
            with repo.worktree(commit) as worktree:
                new_sha = worktree.hex
                msgs = [f"Updating submodule {repo_yml.path}"] + _apply_merges(
                    worktree, repo_yml
                )
                worktree.move_worktree_content(dest_path)
                # TODO perhaps not necessary as of line 63 -- seems to be necessary
                # case: submodule is in .gitignore; updates the submodule
                # then git add <path> needs to add the deleted files
                # Could also be that a subgimera sha was updated
                parent_repo.commit_dir_if_dirty(dest_path, "\n".join(msgs), force=True)
            del repo

        # apply patches:
        if os.getenv("GIMERA_DO_NOT_APPLY_PATCHES") != "1":
            _apply_patches(repo_yml)
        msg = f"updated {REPO_TYPE_INT} submodule: {repo_yml.path}"
        repo_yml.sha = new_sha
        if repo_yml.config.config_file in parent_repo.all_dirty_files_absolute:
            # could be, that the parent path of the gimera.yml belongs to gitignore
            # so force add
            parent_repo.X(*(git + ["add", '-f', repo_yml.config.config_file]))
        parent_repo.commit_dir_if_dirty(dest_path, msg)
        if any(
            str(x).startswith(str(dest_path)) for x in parent_repo.all_dirty_files_absolute
        ):
            parent_repo.X(*(git + ["add", dest_path]))

        if parent_repo.staged_files:
            gitcmd = ["commit", "-m", msg]
            parent_repo.X(*(git + gitcmd))

        if repo_yml.edit_patchfile:
            _apply_patchfile(
                repo_yml.edit_patchfile_full_path, repo_yml.fullpath, error_ok=True
            )


def _apply_merges(repo, repo_yml):
    if not repo_yml.merges:
        return []

    configured_remotes = list(_get_remotes(repo_yml))
    # as we clone into a temp directory to allow parallel actions
    # we set the origin to the repo source
    configured_remotes.append(Remote(repo, "origin", repo_yml.url))
    for remote in configured_remotes:
        if list(filter(lambda x: x.name == remote.name, repo.remotes)):
            repo.set_remote_url(remote.name, remote.url)
        repo.add_remote(remote, exist_ok=True)

    remotes = []
    msg = []
    for remote, ref in repo_yml.merges:
        msg.append(f"Merging {remote} {ref}")
        click.secho(msg[-1])
        remote = [x for x in reversed(configured_remotes) if x.name == remote][0]
        repo.pull(remote=remote, ref=ref)
        remotes.append((remote, ref))
    return msg
