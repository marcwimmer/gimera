from contextlib import contextmanager
import os
from pathlib import Path
import click
from .repo import Repo
from .fetch import _fetch_repos_in_parallel
from .tools import _get_main_repo
from .tools import _raise_error, safe_relative_to
from .consts import gitcmd as git
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB
from .config import Config
from .patches import make_patches
from .tools import verbose
from .integrated import _update_integrated_module
from .submodule import _make_sure_subrepo_is_checked_out
from .snapshot import snapshot_recursive, snapshot_restore
from .submodule import _fetch_latest_commit_in_submodule
from .submodule import __add_submodule
from .tools import get_closest_gimera
from .tools import get_effective_state
from .tools import _make_sure_hidden_gimera_dir
from .cachedir import _get_cache_dir


def _check_sha_belongs_to_branch(main_repo, repo_yml):
    if not repo_yml.sha:
        return

    with _get_cache_dir(main_repo, repo_yml, no_action_if_not_exist=True) as cache_dir:
        if not cache_dir:
            return
        repo = Repo(cache_dir)
        try:
            repo.X(*(git + ["merge-base", "--is-ancestor", repo_yml.sha, repo_yml.branch]))
        except Exception:
            if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
                click.secho(
                    f"SHA {repo_yml.sha} does not belong to branch "
                    f"{repo_yml.branch}. Removing SHA.",
                    fg="yellow",
                )
            else:
                answer = click.prompt(
                    f"SHA {repo_yml.sha} does not belong to branch "
                    f"{repo_yml.branch}. Removing SHA? (ok or abort)",
                    type=click.Choice(["ok", "abort"], case_sensitive=False),
                )
                if answer == "abort":
                    _raise_error("Aborted by user.")
            repo_yml._sha = None


def _apply(
    repos,
    update,
    force_type=False,
    strict=False,
    recursive=False,
    no_patches=False,
    remove_invalid_branches=False,
    auto_commit=True,
    no_fetch=False,
    migrate_changes=False,
    raise_exception=False,
):
    """
    :param repos: user input parameter from commandline
    :param update: bool - flag from command line
    """
    if raise_exception:
        os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"
    if migrate_changes:
        no_patches = True


    sub_path = None
    main_repo = _get_main_repo()
    closest_gimera = (
        get_closest_gimera(main_repo.path, Path(os.getcwd()) / "dummy")
        or main_repo.path
    )
    if not sub_path:
        _make_sure_hidden_gimera_dir(main_repo.path)
    os.chdir(closest_gimera)
    if main_repo.path != closest_gimera:
        sub_path = closest_gimera

    _internal_apply(
        repos,
        update,
        force_type,
        strict=strict,
        recursive=recursive,
        no_patches=no_patches,
        remove_invalid_branches=remove_invalid_branches,
        auto_commit=auto_commit,
        no_fetch=no_fetch,
        sub_path=sub_path,
        migrate_changes=migrate_changes,
    )


def _commit_recursive_changes(main_repo, repo, effective_path, common_vars):
    """Commit submodule and gimera.yml changes after recursive apply."""
    state = get_effective_state(
        main_repo.path, effective_path / repo.path, common_vars
    )
    parent_repo = Repo(state["parent_repo"])
    relpath = state['parent_repo_relpath']
    # commit a gitmodule if sha updated
    if relpath in parent_repo.all_dirty_files:
        parent_repo.commit_dir_if_dirty(relpath, "gimera: updated submodule")
    # commit updated gimera if e.g. sha changed
    gimera_yml = Path(relpath / 'gimera.yml')
    if gimera_yml in parent_repo.all_dirty_files:
        parent_repo.commit_dir_if_dirty(gimera_yml, "gimera: updated submodule")


def _internal_apply(
    repos,
    update,
    force_type,
    strict=False,
    recursive=False,
    no_patches=False,
    common_vars=None,
    parent_config=None,
    auto_commit=True,
    sub_path=None,
    no_fetch=None,
    migrate_changes=None,
    **options,
):
    common_vars = common_vars or {}
    main_repo = _get_main_repo()
    effective_path = sub_path or main_repo.path
    config = Config(
        force_type=force_type,
        recursive=recursive,
        common_vars=common_vars,
        parent_config=parent_config,
    )
    repos = config.get_repos(repos)
    _fetch_repos_in_parallel(
        main_repo, repos, update=update, minimal_fetch=no_fetch, no_fetch=no_fetch
    )
    if sub_path:
        verbose(f"internal apply at sub path: {sub_path}")
    common_vars.update(config.yaml_config.get("common", {}).get("vars", {}))
    verbose(f"common vars: {common_vars}")
    with main_repo.stay_at_commit(not auto_commit and not sub_path):
        if migrate_changes:
            relative_sub_path = (
                sub_path and safe_relative_to(sub_path, main_repo.path) or Path(".")
            )
            snapshot_recursive(
                main_repo.path,
                [main_repo.path / relative_sub_path / repo.path for repo in repos],
            )

        try:
            for repo in repos:
                verbose(f"applying {repo.path}")
                if not update:
                    _check_sha_belongs_to_branch(main_repo, repo)
                _turn_into_correct_repotype(
                    effective_path, main_repo, repo, config, common_vars,
                )
                if repo.type == REPO_TYPE_SUB:
                    _make_sure_subrepo_is_checked_out(
                        effective_path, main_repo, repo, common_vars
                    )
                    _fetch_latest_commit_in_submodule(
                        effective_path, main_repo, repo, common_vars, update=update,
                    )
                elif repo.type == REPO_TYPE_INT:
                    if not no_patches:
                        make_patches(effective_path, main_repo, repo, common_vars)

                    try:
                        _update_integrated_module(
                            effective_path, main_repo, repo, update,
                            common_vars, **options,
                        )
                    except Exception as ex:
                        _raise_error(
                            f"Error updating integrated submodules for: {repo.path}\n\n{ex}"
                        )

                    if not strict:
                        # not submodules inside integrated modules
                        force_type = REPO_TYPE_INT

                if recursive:
                    _apply_subgimera(
                        main_repo, repo, update,
                        force_type if not strict else None,
                        strict=strict, no_patches=no_patches,
                        common_vars=common_vars, parent_config=config,
                        auto_commit=auto_commit, sub_path=sub_path,
                        migrate_changes=False,
                        **options,
                    )
                    if auto_commit:
                        _commit_recursive_changes(
                            main_repo, repo, effective_path, common_vars
                        )
        finally:
            if migrate_changes:
                snapshot_restore(
                    main_repo.path,
                    [main_repo.path / relative_sub_path / repo.path for repo in repos],
                )


def _apply_subgimera(
    main_repo,
    repo,
    update,
    force_type,
    strict,
    no_patches,
    parent_config,
    sub_path,
    common_vars,
    **options,
):
    subgimera = Path(repo.path) / "gimera.yml"
    if sub_path and sub_path.relative_to(main_repo.path) == Path("."):
        sub_path = main_repo.path

    new_sub_path = Path(sub_path or main_repo.path) / repo.path
    if not subgimera.exists():
        return
    pwd = os.getcwd()

    try:
        verbose(f"apply subgimera: {subgimera}")
        os.chdir(new_sub_path)
        _internal_apply(
            [],
            update,
            force_type=force_type,
            strict=strict,
            recursive=True,
            no_patches=no_patches,
            parent_config=parent_config,
            sub_path=new_sub_path,
            common_vars=common_vars,
            **options,
        )

        state = get_effective_state(main_repo.path, new_sub_path, common_vars)
        parent_repo = Repo(state["parent_repo"])

        dirty_files = list(
            filter(
                lambda x: safe_relative_to(x, new_sub_path), parent_repo.all_dirty_files
            )
        )
        if dirty_files:
            parent_repo.please_no_staged_files()
            for f in dirty_files:
                parent_repo.X(*(git + ["add", f]))
            parent_repo.X(
                *(git + ["commit", "--no-verify", "-m", f"gimera: updated sub path {repo.path}"])
            )
        # commit submodule updates or changed dirs
    finally:
        os.chdir(pwd)


def _turn_into_correct_repotype(
    working_dir, main_repo, repo_config, config, common_vars
):
    """
    if git submodule and exists: nothing todo
    if git submodule and not exists: cloned
    if git submodule and already exists a path: path removed, submodule added

    if integrated and exists no sub: nothing todo
    if integrated and not exists: cloned (later not here)
    if integrated and git submodule and already exists a path: submodule removed

    """
    verbose(f"turn into correct repotype: {repo_config.path}")
    state = get_effective_state(
        main_repo.path, working_dir / repo_config.path, common_vars
    )
    repo = Repo(state["parent_repo"])
    if repo_config.type == REPO_TYPE_INT:
        if state["is_submodule"]:
            # always delete
            repo.force_remove_submodule(state["parent_repo_relpath"])
    else:
        __add_submodule(
            main_repo.path, working_dir, repo, repo_config, config, common_vars
        )
