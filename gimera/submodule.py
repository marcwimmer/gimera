import os
from pathlib import Path
from .consts import gitcmd as git
from .tools import _raise_error, safe_relative_to, is_empty_dir
from .repo import Repo
from contextlib import contextmanager
from .cachedir import _get_cache_dir
from .consts import REPO_TYPE_SUB


def _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo):
    """
    If the submodule is clean inside but is not committed to the parent
    repository, this module does that.
    """
    if subrepo.dirty:
        return False

    if not [
        x for x in main_repo.all_dirty_files if x.absolute() == subrepo.path.absolute()
    ]:
        return

    try:
        main_repo.X(*(git + ["add", subrepo.path]))
    except Exception:
        if os.getenv("GIMERA_FORCE") == "1":
            return
    sha = subrepo.hex
    main_repo.X(
        *(
            git
            + [
                "commit",
                "-m",
                (
                    f"gimera: updated submodule at {subrepo.path.relative_to(main_repo.path)} "
                    f"to latest version {sha}"
                ),
            ]
        )
    )


def _fetch_latest_commit_in_submodule(working_dir, main_repo, repo_yml, update=False):
    path = Path(working_dir) / repo_yml.path
    if not path.exists():
        return

    repo = main_repo
    if (working_dir / ".git").exists():
        repo = Repo(working_dir)
    subrepo = repo.get_submodule(repo_yml.path)
    if subrepo.dirty:
        if os.getenv("GIMERA_FORCE") != "1":
            _raise_error(
                f"Directory {repo_yml.path} contains modified "
                "files. Please commit or purge before!"
            )
    sha = repo_yml.sha if not update else None

    def _commit_submodule():
        _commit_submodule_inside_clean_but_not_linked_to_parent(repo, subrepo)
        if main_repo.path != repo.path:
            _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, repo)

    if sha:
        if not subrepo.contain_commit(sha):
            with _temporary_switch_remote_to_cachedir(main_repo, repo_yml):
                subrepo.X(*(git + ["fetch", "--all"]))

        if not subrepo.contain_commit(sha):
            _raise_error(
                f"SHA {sha} does not seem to belong to a "
                f"branch at module {repo_yml.path}"
            )

        subrepo.X(*(git + ["checkout", "-f", repo_yml.branch]))
        subrepo.out("git", "reset", "--hard", f"origin/{repo_yml.branch}").strip()
        sha_of_branch = subrepo.out("git", "rev-parse", repo_yml.branch).strip()
        if sha_of_branch == sha:
            subrepo.X(*(git + ["checkout", "-f", repo_yml.branch]))
        else:
            subrepo.X(*(git + ["checkout", "-f", sha]))
    else:
        try:
            subrepo.X(*(git + ["checkout", "-f", repo_yml.branch]))
            subrepo.X(*(git + ["pull"]))
        except Exception:  # pylint: disable=broad-except
            _raise_error(f"Failed to checkout {repo_yml.branch} in {path}")
        else:
            _commit_submodule()

    subrepo.X(*(git + ["submodule", "update", "--init", "--recursive"]))
    _commit_submodule()

    # check if sha collides with branch
    subrepo.X(*(git + ["clean", "-xdff"]))
    if not repo_yml.sha or update:
        subrepo.X(*(git + ["checkout", "-f", repo_yml.branch]))
        with _temporary_switch_remote_to_cachedir(repo, repo_yml):
            subrepo.pull(repo_yml=repo_yml)
        _commit_submodule()

    # update gimera.yml on demand
    repo_yml.sha = subrepo.hex


@contextmanager
def _temporary_switch_remote_to_cachedir(main_repo, repo_yml):
    cache_dir = _get_cache_dir(main_repo, repo_yml)
    main_repo.X(*(git + ["submodule", "set-url", repo_yml.path, f"file://{cache_dir}"]))
    try:
        yield
    finally:
        main_repo.X(*(git + ["submodule", "set-url", repo_yml.path, repo_yml.url]))


def _make_sure_subrepo_is_checked_out(working_dir, main_repo, repo_yml):
    """
    Could be, that git submodule update was not called yet.
    """
    assert repo_yml.type == REPO_TYPE_SUB
    path = working_dir / repo_yml.path
    if path.exists() and not is_empty_dir(path):
        return
    with _temporary_switch_remote_to_cachedir(main_repo, repo_yml):
        main_repo.X(*(git + ["submodule", "update", "--init", "--recursive", path]))

    if not path.exists():
        _raise_error(
            f"After submodule update the path {repo_yml['path']} did not exist"
        )

def _has_repo_latest_commit(repo, branch):
    out = repo.out(*(git + ["ls-remote", "origin", branch]))
    sha = out.splitlines()[0].strip().split()[0].strip()
    current = repo.out(*(git + ["rev-parse", branch])).splitlines()[0].strip()
    return sha == current

