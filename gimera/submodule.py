import os
from pathlib import Path
from .consts import gitcmd as git
from .tools import _raise_error, safe_relative_to, is_empty_dir
from .repo import Repo
from contextlib import contextmanager
from .cachedir import _get_cache_dir
from .consts import REPO_TYPE_SUB
import click
from .tools import rmtree
from .tools import is_forced
from .tools import get_effective_state
from .tools import verbose


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


def _fetch_latest_commit_in_submodule(
    working_dir, main_repo, repo_yml, common_vars, update=False
):
    path = Path(working_dir) / repo_yml.path
    if not path.exists():
        return
    verbose(f"Fetching latest commit in submodule {path}")

    state = get_effective_state(main_repo.path, path, common_vars)
    parent_gimera = state["parent_gimera"]
    repo = Repo(state["parent_repo"])
    relpath = state["parent_repo_relpath"]
    subrepo = repo.get_submodule(relpath)
    if subrepo.dirty:
        if os.getenv("GIMERA_FORCE") != "1":
            _raise_error(
                f"Directory {repo_yml.path} contains modified "
                "files. Please commit or purge before or migrate changes with -M flag!"
            )
    sha = repo_yml.sha if not update else None

    def _commit_submodule():
        _commit_submodule_inside_clean_but_not_linked_to_parent(repo, subrepo)
        if main_repo.path != repo.path:
            _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, repo)

    if sha:
        if not subrepo.contain_commit(sha):
            with _temporary_switch_remote_to_cachedir(main_repo, repo_yml, relpath):
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
            subrepo.X(*(git + ["pull", "--rebase", "--autostash"]))
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
        with _temporary_switch_remote_to_cachedir(repo, repo_yml, relpath):
            subrepo.pull(repo_yml=repo_yml)
        _commit_submodule()

    # update gimera.yml on demand
    repo_yml.sha = subrepo.hex


@contextmanager
def _temporary_switch_remote_to_cachedir(main_repo, repo_yml, relpath):
    with _get_cache_dir(main_repo, repo_yml) as cache_dir:
        main_repo.X(*(git + ["submodule", "set-url", relpath, f"file://{cache_dir}"]))
        try:
            yield
        finally:
            main_repo.X(*(git + ["submodule", "set-url", relpath, repo_yml.url]))


def _make_sure_subrepo_is_checked_out(working_dir, main_repo, repo_yml, common_vars):
    """
    Could be, that git submodule update was not called yet.
    """
    assert repo_yml.type == REPO_TYPE_SUB
    path = working_dir / repo_yml.path
    state = get_effective_state(main_repo.path, path, common_vars)
    if path.exists() and not is_empty_dir(path):
        return
    repo = Repo(state["parent_repo"])
    with _temporary_switch_remote_to_cachedir(
        repo, repo_yml, state["parent_repo_relpath"]
    ):
        repo.X(
            *(
                git
                + [
                    "submodule",
                    "update",
                    "--init",
                    "--recursive",
                    state["parent_repo_relpath"],
                ]
            )
        )

    if not path.exists():
        _raise_error(f"After submodule update the path {path} did not exist")


def _has_repo_latest_commit(repo, branch):
    out = repo.out(*(git + ["ls-remote", "origin", branch]))
    sha = out.splitlines()[0].strip().split()[0].strip()
    current = repo.out(*(git + ["rev-parse", branch])).splitlines()[0].strip()
    result = sha == current
    return result


def __add_submodule(root_dir, working_dir, repo, config, all_config, common_vars):
    if config.type != REPO_TYPE_SUB:
        return
    verbose(f"Adding submodule {config.path}")
    path = working_dir / config.path
    relpath = path.relative_to(repo.path)
    if path.exists():
        # if it is already a submodule, dont touch
        try:
            submodule = repo.get_submodule(relpath)
        except ValueError:
            repo.output_status()
            repo.please_no_staged_files()
            # remove current path

            dirty_files = [
                x
                for x in repo.all_dirty_files_absolute
                if safe_relative_to(x, repo.path / relpath)
            ]
            if dirty_files:
                if not is_forced():
                    _raise_error(
                        f"Dirty files exist in {repo.path / relpath}. Changes would be lost."
                    )

            if repo.lsfiles(relpath):
                repo.X(*(git + ["rm", "-f", "-r", relpath]))
            if (repo.path / relpath).exists():
                rmtree(repo.path / relpath)

            repo.clear_empty_subpaths(config)
            repo.output_status()
            if not [
                # x for x in repo.staged_files if safe_relative_to(x, repo.path / relpath)
                x
                for x in repo.all_dirty_files
                if safe_relative_to(x, repo.path / relpath)
            ]:
                if relpath.exists():
                    # in case of deletion it does not exist
                    repo.X(*(git + ["add", relpath]))
            if repo.staged_files:
                repo.X(
                    *(
                        git
                        + [
                            "commit",
                            "-m",
                            f"removed path {relpath} to insert submodule",
                        ]
                    )
                )

            # make sure does not exist; some leftovers sometimes
            repo.force_remove_submodule(relpath)

        else:
            # if submodule points to another url, also remove
            if submodule.get_url(noerror=True) != config.url:
                repo.force_remove_submodule(submodule.path.relative_to(repo.path))
            else:
                return
    else:
        repo.force_remove_submodule(relpath)

    repo._fix_to_remove_subdirectories(all_config)
    if (repo.path / relpath).exists():
        # helped in a in the wild repo, where a submodule was hidden below
        repo.X(*(git + ["rm", "-rf", relpath]))
        rmtree(repo.path / relpath)

    with _get_cache_dir(repo, config) as cache_dir:
        repo.submodule_add(config.branch, str(cache_dir), relpath)
        repo.X(*(git + ["submodule", "set-url", relpath, config.url]))
        repo.X(*(git + ["add", ".gitmodules"]))
        click.secho(f"Added submodule {relpath} pointing to {config.url}", fg="yellow")
        if repo.staged_files:
            repo.X(*(git + ["commit", "-m", f"gimera added submodule: {relpath}"]))

    # check for success
    state = get_effective_state(
        root_dir,
        path,
        common_vars,
    )
    assert state["is_submodule"]
