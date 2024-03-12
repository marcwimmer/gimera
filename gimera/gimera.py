#!/usr/bin/env python3
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
from .tools import _raise_error, safe_relative_to, is_empty_dir, _strip_paths
from .tools import yieldlist
from .tools import rsync
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
    return res


@cli.command(name="clean", help="Removes all dirty")
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
    return sorted(map(str, filtered_patchfiles))


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
    "-p",
    "--parallel-safe",
    is_flag=True,
    help=(
        "In multi environments using the same cache directory this avoids "
        "race conditions."
    ),
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
def apply(
    repos,
    update,
    all_integrated,
    all_submodule,
    parallel_safe,
    strict,
    recursive,
    no_patches,
    missing,
    remove_invalid_branches,
    non_interactive,
    no_auto_commit,
    force,
    no_fetch,
):
    if force:
        os.environ["GIMERA_FORCE"] = "1"
    if non_interactive:
        os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    if all_integrated and all_submodule:
        _raise_error("Please set either -I or -S")
    ttype = None
    ttype = REPO_TYPE_INT if all_integrated else ttype
    ttype = REPO_TYPE_SUB if all_submodule else ttype

    repos = list(_expand_repos(repos))

    if missing:
        config = Config()
        repos = list(map(lambda x: str(x.path), _get_missing_repos(config)))

    return _apply(
        repos,
        update,
        force_type=ttype,
        parallel_safe=parallel_safe,
        strict=strict,
        recursive=recursive,
        no_patches=no_patches,
        remove_invalid_branches=remove_invalid_branches,
        auto_commit=not no_auto_commit,
        no_fetch=no_fetch,
    )


def _apply(
    repos,
    update,
    force_type=False,
    parallel_safe=False,
    strict=False,
    recursive=False,
    no_patches=False,
    remove_invalid_branches=False,
    auto_commit=True,
    no_fetch=False,
):
    """
    :param repos: user input parameter from commandline
    :param update: bool - flag from command line
    """
    _internal_apply(
        repos,
        update,
        force_type,
        parallel_safe=parallel_safe,
        strict=strict,
        recursive=recursive,
        no_patches=no_patches,
        remove_invalid_branches=remove_invalid_branches,
        auto_commit=auto_commit,
        no_fetch=no_fetch,
    )


def _get_main_repo():
    # main_repo = Repo(os.getcwd())
    path = Path(os.getcwd())
    while True:
        # if (path / ".git").exists() and (path / ".git").is_dir():
        if (path / ".git").exists():
            break
        path = path.parent
        if len(path.parts) == 1:
            path = Path(os.getcwd())
            break

    return Repo(path)


def _internal_apply(
    repos,
    update,
    force_type,
    parallel_safe=False,
    strict=False,
    recursive=False,
    no_patches=False,
    common_vars=None,
    parent_config=None,
    auto_commit=True,
    sub_path=None,
    no_fetch=None,
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
    _fetch_repos_in_parallel(main_repo, repos, update=update, minimal_fetch=no_fetch)
    with main_repo.stay_at_commit(not auto_commit and not sub_path):
        for repo in repos:
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
                    try:
                        make_patches(sub_path or main_repo.path, main_repo, repo)
                    except Exception as ex:
                        raise
                        msg = f"Error making patches for: {repo.path}\n\n{ex}"
                        _raise_error(msg)

                try:
                    _update_integrated_module(
                        sub_path or main_repo.path,
                        main_repo,
                        repo,
                        update,
                        parallel_safe,
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
                    parallel_safe=parallel_safe,
                    strict=strict,
                    no_patches=no_patches,
                    common_vars=common_vars,
                    parent_config=config,
                    auto_commit=auto_commit,
                    sub_path=sub_path,
                    **options,
                )


def _fetch_repos_in_parallel(main_repo, repos, update=None, minimal_fetch=None):
    results = {"errors": {}, "urls": set()}

    def _pull_repo(index, main_repo, repo_yml):
        try:
            if repo_yml.url in results["urls"]:
                return
            results["urls"].add(repo_yml.url)
            local_repo_dir = _get_cache_dir(main_repo, repo_yml)
            repo = Repo(local_repo_dir)
            do_fetch = True
            if minimal_fetch:
                with wait_git_lock(local_repo_dir):
                    if repo_yml.sha:
                        if repo.contains(repo_yml.sha):
                            do_fetch = False

            if do_fetch:
                with wait_git_lock(local_repo_dir):
                    _fetch_and_reset_branch(repo, repo_yml)

        except Exception as ex:
            trace = traceback.format_exc()
            results["errors"][main_repo.path] = f"{ex}\n\n{trace}"

    threads = []
    for index, repo in enumerate(repos):
        t = threading.Thread(target=_pull_repo, args=(index, main_repo, repo))
        t.daemon = True
        threads.append(t)
    [x.start() for x in threads]
    [x.join() for x in threads]

    if results["errors"]:
        raise Exception(results["errors"])


def _apply_subgimera(
    main_repo,
    repo,
    update,
    force_type,
    parallel_safe,
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
            parallel_safe=parallel_safe,
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
                main_repo.X("git", "add", f)
            main_repo.X("git", "commit", "-m", f"gimera: updated sub path {repo.path}")
        # commit submodule updates or changed dirs
    os.chdir(pwd)


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


def _get_cache_dir(main_repo, repo_yml):
    url = repo_yml.url
    if not url:
        click.secho(f"Missing url: {json.dumps(repo_yml, indent=4)}")
        sys.exit(-1)
    path = Path(os.path.expanduser("~/.cache/gimera")) / url.replace(":", "_").replace(
        "/", "_"
    )
    path.parent.mkdir(exist_ok=True, parents=True)

    if path.exists() and not (path / '.git').exists():
        shutil.rmtree(path)

    if not path.exists():
        click.secho(
            f"Caching the repository {repo_yml.url} for quicker reuse",
            fg="yellow",
        )
        with prepare_dir(path) as _path:
            Repo(main_repo.path).X("git", "clone", url, _path)
    return path


def _update_integrated_module(
    working_dir,
    main_repo,
    repo_yml,
    update,
    parallel_safe,
    **options,
):
    """
    Put contents of a git repository inside the main repository.
    """

    # TODO eval parallelsafe

    # use a cache directory for pulling the repository and updating it
    local_repo_dir = _get_cache_dir(main_repo, repo_yml)
    with wait_git_lock(local_repo_dir):
        if not os.access(local_repo_dir, os.W_OK):
            _raise_error(f"No R/W rights on {local_repo_dir}")
        repo = Repo(local_repo_dir)
        # no_fetch - because everything was pulled in parallel step before
        _fetch_and_reset_branch(repo, repo_yml, no_fetch=True, **options)

        parent_repo = main_repo
        if (working_dir / ".git").exists():
            parent_repo = Repo(working_dir)

        if not update and repo_yml.sha:
            branches = repo.get_all_branches()
            if repo_yml.branch not in branches:
                repo.pull(repo_yml=repo_yml)
                repo_yml.sha = None
            else:
                subprocess.check_call(
                    ["git", "config", "advice.detachedHead", "false"],
                    cwd=local_repo_dir,
                )
                repo.checkout(repo_yml.sha, force=True)

        new_sha = repo.hex
        with _apply_merges(repo, repo_yml, parallel_safe) as (repo, remote_refs):
            dest_path = Path(working_dir) / repo_yml.path
            dest_path.parent.mkdir(exist_ok=True, parents=True)
            # BTW: delete-after cannot removed unused directories - cool to know; is
            # just standarded out
            if dest_path.exists():
                rmtree(dest_path)
            rsync(repo.path, dest_path, exclude=[".git"])
            msg = [f"Merged: {repo_yml.url}"]
            for remote, ref in remote_refs:
                msg.append(f"Merged {remote.url}:{ref}")
            parent_repo.commit_dir_if_dirty(repo_yml.path, "\n".join(msg))

        del repo

        # apply patches:
        _apply_patches(
            repo_yml,
        )
        parent_repo.commit_dir_if_dirty(
            repo_yml.path, f"updated {REPO_TYPE_INT} submodule: {repo_yml.path}"
        )
        repo_yml.sha = new_sha

        if repo_yml.edit_patchfile:
            _apply_patchfile(
                repo_yml.edit_patchfile_full_path, repo_yml.fullpath, error_ok=True
            )


@yieldlist
def _get_remotes(repo_yml):
    config = repo_yml.remotes
    if not config:
        return

    for name, url in dict(config).items():
        yield Remote(None, name, url)


@contextmanager
def _apply_merges(repo, repo_yml, parallel_safe):
    if not repo_yml.merges:
        yield repo, []
        # https://stackoverflow.com/questions/6395063/yield-break-in-python
        return iter([])

    try:
        if parallel_safe:
            repo2 = tempfile.mktemp(suffix=".")
            repo.X(
                "git",
                "clone",
                "--branch",
                str(repo_yml.branch),
                "file://" + str(repo.path),
                repo2,
            )
            repo = Repo(repo2)

        configured_remotes = _get_remotes(repo_yml)
        # as we clone into a temp directory to allow parallel actions
        # we set the origin to the repo source
        configured_remotes.append(Remote(repo, "origin", repo_yml.url))
        for remote in configured_remotes:
            if list(filter(lambda x: x.name == remote.name, repo.remotes)):
                repo.set_remote_url(remote.name, remote.url)
            repo.add_remote(remote, exist_ok=True)

        remotes = []
        for remote, ref in repo_yml.merges:
            remote = [x for x in reversed(configured_remotes) if x.name == remote][0]
            repo.pull(remote=remote, ref=ref)
            remotes.append((remote, ref))

        yield repo, remotes
    finally:
        if parallel_safe:
            rmtree(repo.path)


def _apply_patchfile(file, working_dir, error_ok=False):
    cwd = Path(working_dir)
    # must be check_output due to input keyword
    # Explaining -R option:
    #   at testing a patchfile is created ; although not comitting
    #   git detects, that the file was removed and same patch tries to be applied
    #   Very intelligent but we force defined state over such smart behaviours.
    """
    /tmp/gimeratest/workspace/integrated/sub1/patches/15.0/superpatches/my.patch
    =============================================================================================
    patching file file1.txt
    Reversed (or previously applied) patch detected!  Assume -R? [n]
    Apply anyway? [n]
    Skipping patch.
    1 out of 1 hunk ignored -- saving rejects to file file1.txt.rej
    """
    file = Path(file)
    try:
        subprocess.check_output(
            ["patch", "-p1", "--no-backup-if-mismatch", "--force", "-i", str(file)],
            cwd=cwd,
            encoding="utf-8",
        )
        click.secho(
            (f"Applied patch {file}"),
            fg="blue",
        )
    except subprocess.CalledProcessError as ex:
        click.secho(
            ("\n\nFailed to apply the following patch file:\n\n"),
            fg="yellow",
        )
        click.secho(
            (
                f"{file}\n"
                "============================================================================================="
            ),
            fg="red",
            bold=True,
        )
        click.secho((f"{ex.stdout or ''}\n" f"{ex.stderr or ''}\n"), fg="yellow")

        click.secho(file.read_text(), fg="cyan")
        if os.getenv("GIMERA_NON_INTERACTIVE") == "1" or not inquirer.confirm(
            f"Patchfile failed ''{file}'' - continue with next file?",
            default=True,
        ):
            if not error_ok:
                _raise_error(f"Error applying patch: {file}")
    except Exception as ex:  # pylint: disable=broad-except
        _raise_error(str(ex))


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

    main_repo.X("git", "add", subrepo.path)
    sha = subrepo.hex
    main_repo.X(
        "git",
        "commit",
        "-m",
        (
            f"gimera: updated submodule at {subrepo.path.relative_to(main_repo.path)} "
            f"to latest version {sha}"
        ),
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
        _raise_error(
            f"Directory {repo_yml.path} contains modified "
            "files. Please commit or purge before!"
        )
    sha = repo_yml.sha

    def _commit_submodule():
        _commit_submodule_inside_clean_but_not_linked_to_parent(repo, subrepo)
        if main_repo.path != repo.path:
            _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, repo)

    if sha:
        try:
            branches = list(
                clean_branch_names(
                    subrepo.out("git", "branch", "--contains", sha).splitlines()
                )
            )
        except Exception:  # pylint: disable=broad-except
            _raise_error(
                f"SHA {sha} does not seem to belong to a "
                f"branch at module {repo_yml.path}"
            )

        if not [x for x in branches if repo_yml.branch == x]:
            _raise_error(
                f"SHA {sha} does not exist on branch "
                f"{repo_yml.branch} at repo {repo_yml.path}"
            )
        sha_of_branch = subrepo.out("git", "rev-parse", repo_yml.branch).strip()
        if sha_of_branch == sha:
            subrepo.X(*(git + ["checkout", "-f", repo_yml.branch]))
        else:
            subrepo.X(*(git + ["checkout", "-f", sha]))
    else:
        try:
            subrepo.X(*(git + ["checkout", "-f", repo_yml.branch]))
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
                repo.X("git", "rm", "-f", "-r", relpath)
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
                    repo.X("git", "add", relpath)
            if repo.staged_files:
                repo.X(
                    "git", "commit", "-m", f"removed path {relpath} to insert submodule"
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
        repo.X("git", "rm", "-rf", relpath)
        rmtree(repo.path / relpath)

    cache_dir = _get_cache_dir(repo, config)
    repo.submodule_add(config.branch, f"file://{cache_dir}", relpath)
    repo.X(*(git + ["submodule", "set-url", relpath, config.url]))
    repo.X(*(git + ["add", ".gitmodules"]))
    click.secho(f"Added submodule {relpath} pointing to {config.url}", fg="yellow")
    if repo.staged_files:
        repo.X("git", "commit", "-m", f"gimera added submodule: {relpath}")


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


def _fetch_and_reset_branch(repo, repo_yml, no_fetch=False, **options):
    url = repo_yml.url

    def set_url_and_fetch(url):
        repo.set_remote_url("origin", url)
        repo.X("git", "fetch", "origin")

    fetch_exception = None
    if not no_fetch:
        try:
            set_url_and_fetch(url)
        except Exception as ex:
            fetch_exception = ex
            if get_url_type(url) == "git":
                url_http = reformat_url(url, 'http')
                try:
                    set_url_and_fetch(url_http)
                except Exception:
                    raise fetch_exception

    branch = str(repo_yml.branch)
    origin_branch = f"origin/{branch}"
    try:
        repo.X("git", "checkout", "-f", branch)
    except subprocess.CalledProcessError:
        if options.get("remove_invalid_branches"):
            repo_yml.drop_dead()
            click.secho(
                f"Branch {branch} did not exist in {repo_yml.path}; it is removed.",
                fg="yellow",
            )
        else:
            click.secho(f"Branch {branch} does not exist in {repo_yml.path}", fg="red")
        return
    repo.X("git", "reset", "--hard", origin_branch)
    repo.X("git", "branch", f"--set-upstream-to={origin_branch}", branch)
    repo.X("git", "clean", "-xdff")


@contextmanager
def _temporary_switch_remote_to_cachedir(main_repo, repo_yml):
    cache_dir = _get_cache_dir(main_repo, repo_yml)
    main_repo.X(*(git + ["submodule", "set-url", repo_yml.path, f"file://{cache_dir}"]))
    try:
        yield
    finally:
        main_repo.X(*(git + ["submodule", "set-url", repo_yml.path, repo_yml.url]))


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
@click.argument("branch", required=True)
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
        main_repo.X("git", "clone", repo.url, path2)
        gitrepo.X("git", "checkout", "-f", branch)
        src_path = main_repo.path / repo.path
        patch_content = _technically_make_patch(main_repo, src_path)

        patchfile = gitrepo.path / "1.patch"
        patchfile.write_text(patch_content)

        _apply_patchfile(patchfile, gitrepo.path, error_ok=False)

        patchfile.unlink()
        gitrepo.X("git", "add", ".")
        if preview:
            gitrepo.X("git", "diff")
            doit = inquirer.confirm("Commit this?", default=True)
            if not doit:
                return
        gitrepo.X("git", "commit", "-m", message)
        gitrepo.X("git", "push")
