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
from .patches import _apply_patchfile
from .cachedir import _get_cache_dir

def _update_integrated_module(
    working_dir,
    main_repo,
    repo_yml,
    update,
    **options,
):
    """
    Put contents of a git repository inside the main repository.
    """
    # use a cache directory for pulling the repository and updating it
    cache_dir = _get_cache_dir(main_repo, repo_yml)
    if not os.access(cache_dir, os.W_OK):
        _raise_error(f"No R/W rights on {cache_dir}")
    repo = Repo(cache_dir)

    parent_repo = main_repo
    if (working_dir / ".git").exists():
        parent_repo = Repo(working_dir)

    dest_path = Path(working_dir) / repo_yml.path
    dest_path.parent.mkdir(exist_ok=True, parents=True)
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
            parent_repo.commit_dir_if_dirty(repo_yml.path, "\n".join(msgs))
        del repo

    # apply patches:
    _apply_patches(repo_yml)
    parent_repo.commit_dir_if_dirty(
        repo_yml.path, f"updated {REPO_TYPE_INT} submodule: {repo_yml.path}"
    )
    repo_yml.sha = new_sha

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