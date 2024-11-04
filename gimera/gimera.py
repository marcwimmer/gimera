#!/usr/bin/env python3
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
from .tools import _raise_error
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB
from .config import Config
from .patches import _get_available_patchfiles
from .tools import try_rm_tree
from .tools import _get_missing_repos
from .tools import _get_main_repo
from .apply import _apply
from .commit import _commit
from .patches import _edit_patch


@click.group()
def cli():
    pass


def _expand_repos(repos):
    def unique():
        config = Config()
        for repo in repos:
            if "*" not in repo:
                if repo.endswith("/"):
                    repo = repo[:-1]
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
@click.option(
    "--do-not-apply-patches",
    is_flag=True,
    help="Do not apply patches",
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
    do_not_apply_patches,
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
    if do_not_apply_patches:
        os.environ['GIMERA_DO_NOT_APPLY_PATCHES'] = "1"
    if all_integrated and all_submodule:
        _raise_error("Please set either -I or -S")
    ttype = None
    ttype = REPO_TYPE_INT if all_integrated else ttype
    ttype = REPO_TYPE_SUB if all_submodule else ttype

    repos = list(_expand_repos(repos))

    if missing:
        config = Config()
        repos = list(map(lambda x: str(x.path), _get_missing_repos(config)))
        if not repos:
            click.secho("Nothing to do - all paths exist.", fg="green")
            return

    try:
        _apply(
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
        raise


def clean_branch_names(arr):
    for x in arr:
        x = x.strip()
        if x.startswith("* "):
            x = x[2:]
        yield x


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
        if str(repo.path) == path:
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


@cli.command()
def status():
    config = Config()
    repos = list(_get_missing_repos(config))
    for repo in repos:
        click.secho(f"[{repo.type[0].upper()}] {repo.path}", fg="red")
    main_repo = _get_main_repo()
    for repo in config.get_repos(None):
        full_path = main_repo.path / repo.path
        if not full_path.exists():
            continue
        eff_S = bool(main_repo.is_path_a_submodule(repo.path))
        deviates = (
            repo.type == REPO_TYPE_INT
            and eff_S
            or repo.type == REPO_TYPE_SUB
            and not eff_S
        )
        text = f"[{repo.type[0].upper()}] {repo.path}"
        if deviates:
            text += " IS NOW " + ("submodule" if eff_S else "integrated")
        click.secho(text, fg="green" if not deviates else "yellow")


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


@cli.command(help="Removes all dirty")
def purge():
    config = Config()
    repos = config.get_repos(None)
    for repo in repos:
        click.secho(f"Deleting: {repo.path}")
        try_rm_tree(repo.path)


@cli.command()
def list_snapshots():
    from .snapshot import list_snapshots

    main_repo = _get_main_repo()

    for snap in reversed(list(list_snapshots(main_repo.path))):
        click.secho(snap, fg="green")


@cli.command()
@click.argument("name", required=True)
@click.argument("repos", nargs=-1, default=None, shell_complete=_get_available_repos)
def snap(name, repos):
    from .snapshot import snapshot_recursive

    os.environ["GIMERA_TOKEN"] = datetime.now().strftime(f"%Y-%m-%d-%H%M%S-{name}")
    main_repo = _get_main_repo()
    if not repos:
        config = Config()
        repos = [x.path for x in config.get_repos(None) if x.path.exists()]
    else:
        repos = list(_expand_repos(repos))
    token = snapshot_recursive(
        main_repo.path, [main_repo.path / repo for repo in repos]
    )
    click.secho(f"Snapshot stored under token: {token}", fg="green")


@cli.command()
@click.argument("repos", nargs=-1, default=None, shell_complete=_get_available_repos)
def snaprestore(repos):
    from .snapshot import snapshot_restore
    from .snapshot import get_snapshots

    main_repo = _get_main_repo()
    snapshots = get_snapshots(main_repo.path)
    token = inquirer.prompt(
        [
            inquirer.List(
                "snapshot",
                "Choose snapshot",
                default=True,
                choices=snapshots,
            )
        ]
    )["snapshot"]
    filter_repos = []
    if repos:
        repos = list(_expand_repos(repos))
        for repo in repos:
            filter_repos.append(str(repo))

    snapshot_restore(main_repo.path, filter_repos, token=token)
