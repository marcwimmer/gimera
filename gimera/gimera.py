#!/usr/bin/env python3
import uuid
import shutil
import threading
import traceback
import time
import tempfile
import re
from contextlib import contextmanager
import os
from datetime import datetime
import inquirer
import click
import json
import yaml
import sys
import subprocess
from pathlib import Path
from .repo import Repo, Remote
from .gitcommands import GitCommands
from .fetch import _fetch_repos_in_parallel
from .tools import _get_main_repo
from .tools import _raise_error, safe_relative_to, is_empty_dir
from .tools import yieldlist
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
from .tools import is_forced
from .tools import get_url_type
from .tools import reformat_url
from .tools import verbose
from .tools import try_rm_tree
from .tools import remember_cwd
from .tools import _get_remotes
from .patches import _apply_patchfile
from .cachedir import _get_cache_dir
from .submodule import _make_sure_subrepo_is_checked_out
from .submodule import _fetch_latest_commit_in_submodule


@click.group()
def cli():
    pass


def _expand_repos(repos):
    def unique():
        config = Config()
        for repo in repos:
            if "*" not in repo:
                if not repo.endswith("/"):
                    yield repo
            repo = repo.replace("*", ".*")
            for candi in config.repos:
                if not candi.enabled:
                    continue
                if re.findall(repo, str(candi.path)):
                    yield str(candi.path)

    res = list(set(unique()))
    exact_match = [x for x in res if x in repos]
    if len(exact_match) == 1:
        return exact_match
    return res


@cli.command(name="clean", help="Removes all git-dirty items")
def clean():
    Cmd = GitCommands()
    if not Cmd.dirty:
        click.secho("Everything already clean!", fg="green")
        return
    Cmd.output_status()
    doit = inquirer.confirm(
        "Continue cleaning? All local changes are lost.", default=True
    )
    if not doit:
        return
    Repo(Cmd.path).full_clean()
    click.secho("Cleaning done.", fg="green")
    Cmd.output_status()


@cli.command(name="combine-patch", help="Combine patches")
def combine_patches():
    click.secho("\n\nHow to combine patches:\n", fg="yellow")
    click.secho("1. Please install patchutils:\n\n\tapt install patchutils\n")
    click.secho("2. combinediff patch1 patch2 > patch_combined\n")


def _get_available_repos(ctx, param, incomplete):
    repos = []

    if "/" in incomplete:
        incomplete = incomplete.replace("/", "/*") + "*"
    else:
        incomplete = "*" + incomplete + "*"

    repos = list(_expand_repos([incomplete]))

    return sorted(repos)


def _get_available_patchfiles(ctx, param, incomplete):
    config = Config(force_type=False, recursive=True)
    cwd = Path(os.getcwd())
    patchfiles = []
    filtered_patchfiles = []
    for repo in config.repos:
        if not repo.enabled:
            continue
        for patchdir in repo.all_patch_dirs(rel_or_abs="absolute"):
            if not patchdir._path.exists():
                continue
            for file in patchdir._path.glob("*.patch"):
                patchfiles.append(file.relative_to(cwd))
    if incomplete:
        for file in patchfiles:
            if incomplete in str(file):
                filtered_patchfiles.append(file)
    else:
        filtered_patchfiles = patchfiles
    filtered_patchfiles = list(sorted(filtered_patchfiles))
    return sorted(list(set(map(str, filtered_patchfiles))))


@cli.command(name="apply", help="Applies configuration from gimera.yml")
@click.argument("repos", nargs=-1, default=None, shell_complete=_get_available_repos)
@click.option(
    "-u",
    "--update",
    is_flag=True,
    help="If set, then latest versions are pulled from remotes.",
)
@click.option(
    "-I",
    "--all-integrated",
    is_flag=True,
    help="Overrides setting in gimera.yml and sets 'integrated' for all.",
)
@click.option(
    "-S",
    "--all-submodule",
    is_flag=True,
    help="Overrides setting in gimera.yml and sets 'submodule' for all.",
)
@click.option(
    "-s",
    "--strict",
    is_flag=True,
    help=(
        "If set, then submodules of 'integrated' branches are not automatically "
        "set to integrated. They stay how they are defined in the children gimera.yml files."
    ),
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help=("Executes recursive gimeras (analog to submodules initialization)"),
)
@click.option(
    "-P",
    "--no-patches",
    is_flag=True,
)
@click.option(
    "-m",
    "--missing",
    is_flag=True,
    help="Only updates paths, that dont exist yet in filesystem",
)
@click.option(
    "--remove-invalid-branches",
    is_flag=True,
    help="If branch does not exist in repository, the configuration item is removed.",
)
@click.option(
    "-I",
    "--non-interactive",
    is_flag=True,
    help="",
)
@click.option(
    "-C",
    "--no-auto-commit",
    is_flag=True,
    help="",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="",
)
@click.option(
    "-n",
    "--no-fetch",
    is_flag=True,
    help="",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="",
)
@click.option(
    "-SHA",
    "--no-sha-update",
    is_flag=True,
    help="If set, then in gimera.yml the shas are not updated.",
)
@click.option(
    "-M",
    "--migrate-changes",
    is_flag=True,
    help="Keeps changes to repo",
)
@click.option(
    "--raise-exception",
    is_flag=True,
    help="Raises exception instead of exit of program",
)
def apply(
    repos,
    update,
    all_integrated,
    all_submodule,
    strict,
    recursive,
    no_patches,
    missing,
    remove_invalid_branches,
    non_interactive,
    no_auto_commit,
    force,
    no_fetch,
    verbose,
    no_sha_update,
    migrate_changes,
    raise_exception,
):
    if verbose:
        os.environ["GIMERA_VERBOSE"] = "1"
    if no_sha_update:
        os.environ["GIMERA_NO_SHA_UPDATE"] = "1"
    if force:
        os.environ["GIMERA_FORCE"] = "1"
    if non_interactive:
        os.environ["GIMERA_NON_INTERACTIVE"] = "1"
        os.environ["GIT_TERMINAL_PROMPT"] = "0"
    if all_integrated and all_submodule:
        _raise_error("Please set either -I or -S")
    ttype = None
    ttype = REPO_TYPE_INT if all_integrated else ttype
    ttype = REPO_TYPE_SUB if all_submodule else ttype

    repos = list(_expand_repos(repos))

    if missing:
        config = Config()
        repos = list(map(lambda x: str(x.path), _get_missing_repos(config)))

    try:
        res = _apply(
            repos,
            update,
            force_type=ttype,
            strict=strict,
            recursive=recursive,
            no_patches=no_patches,
            remove_invalid_branches=remove_invalid_branches,
            auto_commit=not no_auto_commit,
            no_fetch=no_fetch,
            migrate_changes=migrate_changes,
            raise_exception=raise_exception,
        )
    except Exception as ex:
        from . import snapshot

        snapshot.cleanup()

    return res


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
    with main_repo.stay_at_commit(not auto_commit and not sub_path):
        for repo in repos:

            # if migrate_changes:
            #     import pudb

            #     pudb.set_trace()

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


def clean_branch_names(arr):
    for x in arr:
        x = x.strip()
        if x.startswith("* "):
            x = x[2:]
        yield x


def __add_submodule(working_dir, repo, config, all_config):
    if config.type != REPO_TYPE_SUB:
        return
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
                for x in repo.all_dirty_files
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

    cache_dir = _get_cache_dir(repo, config)
    repo.submodule_add(config.branch, f"file://{cache_dir}", relpath)
    repo.X(*(git + ["submodule", "set-url", relpath, config.url]))
    repo.X(*(git + ["add", ".gitmodules"]))
    click.secho(f"Added submodule {relpath} pointing to {config.url}", fg="yellow")
    if repo.staged_files:
        repo.X(*(git + ["commit", "-m", f"gimera added submodule: {relpath}"]))


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
        __add_submodule(working_dir, repo, repo_config, config)
        submodules = repo.get_submodules()
        existing_submodules = list(
            filter(lambda x: x.equals(repo.path / path), submodules)
        )
        if not existing_submodules:
            _raise_error(f"Error with submodule {path}")
        del existing_submodules


@cli.command()
@click.option(
    "-x",
    "--execute",
    is_flag=True,
    help=("Execute the script to insert completion into users rc-file."),
)
def completion(execute):
    shell = os.environ["SHELL"].split("/")[-1]
    rc_file = Path(os.path.expanduser(f"~/.{shell}rc"))
    line = f'eval "$(_GIMERA_COMPLETE={shell}_source gimera)"'
    if execute:
        content = rc_file.read_text().splitlines()
        if not list(
            filter(
                lambda x: line in x and not x.strip().startswith("#"),
                content,
            )
        ):
            content += [f"\n{line}"]
            click.secho(
                f"Inserted successfully\n{line}" "\n\nPlease restart you shell."
            )
            rc_file.write_text("\n".join(content))
        else:
            click.secho("Nothing done - already existed.")

    click.secho("\n\n" f"Insert into {rc_file}\n\n" f"echo 'line' >> {rc_file}" "\n\n")


@cli.command()
@click.option("-u", "--url", required=True)
@click.option("-b", "--branch", required=True)
@click.option("-p", "--path", required=True)
@click.option("-t", "--type", required=True)
def add(url, branch, path, type):
    data = {
        "url": url,
        "branch": branch,
        "path": path,
        "type": type,
    }
    config = Config()
    repos = config.repos
    for repo in repos:
        if repo.path == path:
            config._store(repo, data)
            break
    else:
        ri = Config.RepoItem(config, data)
        config._store(ri, data)


@cli.command()
def check_all_submodules_initialized():
    if not _check_all_submodules_initialized():
        sys.exit(-1)


def _check_all_submodules_initialized():
    root = Path(os.getcwd())

    def _get_all_submodules(root):
        for submodule in Repo(root).get_submodules():
            path = submodule.path
            yield submodule
            if submodule._git_path.exists():
                yield from _get_all_submodules(path)

    error = False
    for submodule in _get_all_submodules(root):
        if not submodule._git_path.exists():
            click.secho(f"Not initialized: {submodule.path}", fg="red")
            error = True

    return not error


@cli.command()
@click.argument(
    "patchfiles", nargs=-1, shell_complete=_get_available_patchfiles, required=True
)
def edit_patch(patchfiles):
    _edit_patch(patchfiles)


@cli.command
def abort():
    for repo in Config().repos:
        if repo.edit_patchfile:
            repo.config._store(
                repo,
                {
                    "edit_patchfile": "",
                },
            )


def _get_repo_to_patchfiles(patchfiles):
    for patchfile in patchfiles:
        patchfile = Path(patchfile)
        if patchfile.exists() and str(patchfile).startswith("/"):
            patchfile = str(patchfile.relative_to(Path(os.getcwd())))
        patchfile = _get_available_patchfiles(None, None, str(patchfile))
        if not patchfile:
            _raise_error(f"Not found: {patchfile}")
        if len(patchfile) > 1:
            _raise_error(f"Too many patchfiles found: {patchfile}")

        cwd = Path(os.getcwd())
        patchfile = cwd / patchfile[0]
        config = Config(force_type=False)

        def _get_repo_of_patchfile():
            for repo in config.repos:
                if not repo.enabled:
                    continue
                patch_dirs = repo.all_patch_dirs(rel_or_abs="absolute")
                if not patch_dirs:
                    continue
                for patchdir in patch_dirs:
                    path = patchdir._path
                    for file in path.glob("*.patch"):
                        if file == patchfile:
                            return repo

        repo = _get_repo_of_patchfile()
        if not repo:
            _raise_error(f"Repo not found for {patchfile}")

        if repo.type != REPO_TYPE_INT:
            _raise_error(f"Repo {repo.path} is not integrated")
        yield (repo, patchfile)


def _edit_patch(patchfiles):
    patchfiles = list(sorted(set(patchfiles)))
    for patchfile in list(_get_repo_to_patchfiles(patchfiles)):
        repo, patchfile = patchfile
        if repo.edit_patchfile:
            _raise_error(f"Already WIP for patchfile: {repo.edit_patchfile}")
        try:
            repo.edit_patchfile = str(patchfile.relative_to(repo.fullpath))
        except ValueError:
            repo.edit_patchfile = patchfile.relative_to(repo.config.config_file.parent)
        repo.config._store(
            repo,
            {
                "edit_patchfile": str(repo.edit_patchfile),
            },
        )
        break
    _internal_apply(str(repo.path), update=False, force_type=None)


def _get_missing_repos(config):
    for repo in config.repos:
        if not repo.enabled:
            continue
        if not repo.path.exists():
            yield repo


@cli.command()
def status():
    config = Config()
    repos = list(_get_missing_repos(config))
    for repo in repos:
        click.secho(f"Missing: {repo.path}", fg="red")


@cli.command(
    name="commit", help="Collects changes and commits them to the specified branch."
)
@click.argument(
    "repo", default=None, shell_complete=_get_available_repos, required=True
)
@click.argument("message", required=True)
@click.option(
    "-p",
    "--preview",
    is_flag=True,
)
@click.argument("branch", required=False)
def commit(repo, branch, message, preview):
    return _commit(repo, branch, message, preview)


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


@cli.command(help="Removes all dirty")
def purge():
    config = Config()
    repos = config.get_repos(None)
    for repo in repos:
        click.secho(f"Deleting: {repo.path}")
        try_rm_tree(repo.path)
