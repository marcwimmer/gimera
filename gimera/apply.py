from contextlib import contextmanager
import os
from pathlib import Path
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
        migrate_changes=migrate_changes,
    )


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
    config = Config(
        force_type=force_type,
        recursive=recursive,
        common_vars=common_vars,
        parent_config=parent_config,
    )
    repos = config.get_repos(repos)
    # update repos in parallel to be faster
    _fetch_repos_in_parallel(
        main_repo, repos, update=update, minimal_fetch=no_fetch, no_fetch=no_fetch
    )
    # does not work in sub repos, because at apply at this point in time
    # the files are not committed and still dirty
    effective_migrate_changes = migrate_changes and not sub_path
    with main_repo.stay_at_commit(not auto_commit and not sub_path):
        if effective_migrate_changes:
            snapshot_recursive(
                main_repo.path, [main_repo.path / repo.path for repo in repos]
            )

        for repo in repos:
            verbose(f"applying {repo.path}")
            _turn_into_correct_repotype(
                sub_path or main_repo.path, main_repo, repo, config
            )
            if repo.type == REPO_TYPE_SUB:
                _make_sure_subrepo_is_checked_out(
                    sub_path or main_repo.path, main_repo, repo
                )
                _fetch_latest_commit_in_submodule(
                    sub_path or main_repo.path, main_repo, repo, update=update
                )
            elif repo.type == REPO_TYPE_INT:
                if not no_patches:
                    make_patches(sub_path or main_repo.path, main_repo, repo)

                try:
                    _update_integrated_module(
                        sub_path or main_repo.path,
                        main_repo,
                        repo,
                        update,
                        **options,
                    )
                except Exception as ex:
                    msg = (
                        f"Error updating integrated submodules for: {repo.path}\n\n{ex}"
                    )
                    _raise_error(msg)

                if not strict:
                    # fatal: refusing to create/use '.git/modules/addons_connector/modules/addons_robot/aaa' in another submodule's git dir
                    # not submodules inside integrated modules
                    force_type = REPO_TYPE_INT

            if recursive:
                common_vars.update(config.yaml_config.get("common", {}).get("vars", {}))
                _apply_subgimera(
                    main_repo,
                    repo,
                    update,
                    force_type,
                    strict=strict,
                    no_patches=no_patches,
                    common_vars=common_vars,
                    parent_config=config,
                    auto_commit=auto_commit,
                    sub_path=sub_path,
                    migrate_changes=migrate_changes,
                    **options,
                )
        if effective_migrate_changes:
            snapshot_restore(
                main_repo.path, [main_repo.path / repo.path for repo in repos]
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
    **options,
):
    subgimera = Path(repo.path) / "gimera.yml"
    if sub_path and sub_path.relative_to(main_repo.path) == Path("."):
        sub_path = main_repo.path

    new_sub_path = Path(sub_path or main_repo.path) / repo.path
    pwd = os.getcwd()
    if subgimera.exists():
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
            **options,
        )

        dirty_files = list(
            filter(
                lambda x: safe_relative_to(x, new_sub_path), main_repo.all_dirty_files
            )
        )
        if dirty_files:
            main_repo.please_no_staged_files()
            for f in dirty_files:
                main_repo.X(*(git + ["add", f]))
            main_repo.X(
                *(git + ["commit", "-m", f"gimera: updated sub path {repo.path}"])
            )
        # commit submodule updates or changed dirs
    os.chdir(pwd)


def _turn_into_correct_repotype(working_dir, main_repo, repo_config, config):
    """
    if git submodule and exists: nothing todo
    if git submodule and not exists: cloned
    if git submodule and already exists a path: path removed, submodule added

    if integrated and exists no sub: nothing todo
    if integrated and not exists: cloned (later not here)
    if integrated and git submodule and already exists a path: submodule removed

    """
    path = repo_config.path
    repo = main_repo
    if (working_dir / ".git").exists():
        repo = Repo(working_dir)
    if repo_config.type == REPO_TYPE_INT:
        # always delete
        submodules = repo.get_submodules()
        existing_submodules = list(
            filter(lambda x: x.equals(repo.path / path), submodules)
        )
        if existing_submodules:
            repo.force_remove_submodule(path)
    else:
        __add_submodule(main_repo.path ,working_dir, repo, repo_config, config)
