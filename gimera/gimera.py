#!/usr/bin/env python3
import os
from datetime import datetime
import inquirer
import click
import json
import yaml
import sys
import subprocess
from pathlib import Path
from gimera.gitcommands import GitCommands
from .tools import X, _raise_error, _strip_paths
from .repo import Repo, Remote
from .gitcommands import GitCommands
from .tools import _raise_error, safe_relative_to, is_empty_dir
from .tools import yieldlist

REPO_TYPE_INT = "integrated"
REPO_TYPE_SUB = "submodule"

@click.group()
def cli():
    pass


@cli.command(name="clean", help="Removes all dirty")
def clean():
    Cmd = GitCommands()
    if not Cmd.dirty:
        click.secho("Everything already clean!", fg="green")
        return
    Cmd.output_status()
    doit = inquirer.confirm(
        f"Continue cleaning? All local changes are lost.", default=True
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
    config = load_config()
    repos = []
    for repo in config.get("repos", []):
        if not repo.get("path"):
            continue
        if incomplete:
            if not repo.get("path", "").startswith(incomplete):
                continue
        repos.append(repo["path"])
    return sorted(repos)


@cli.command(name="apply", help="Applies configuration from gimera.yml")
@click.argument("repos", nargs=-1, default=None, shell_complete=_get_available_repos)
@click.option(
    "-u",
    "--update",
    is_flag=True,
    help="If set, then latest versions are pulled from remotes.",
)
def apply(repos, update):
    return _apply(repos, update)


def _apply(repos, update):
    """
    :param repos: user input parameter from commandline
    :param update: bool - flag from command line
    """
    config = load_config()

    repos = list(_strip_paths(repos))
    for check in repos:
        if check not in map(lambda x: x["path"], config["repos"]):
            _raise_error(f"Invalid path: {check}")

    _internal_apply(repos, update)


def _internal_apply(repos, update):
    main_repo = Repo(os.getcwd())
    config = load_config()

    for repo in config["repos"]:
        if repos and repo["path"] not in repos:
            continue
        _turn_into_correct_repotype(main_repo, repo)
        del repo

    for repo in config["repos"]:
        if repos and repo["path"] not in repos:
            continue
        if not repo.get("type"):
            repo["type"] = REPO_TYPE_INT

        repo["branch"] = str(repo["branch"])  # e.g. if 15.0

        if repo.get("type") == REPO_TYPE_SUB:
            _make_sure_subrepo_is_checked_out(main_repo, repo)
            _fetch_latest_commit_in_submodule(main_repo, repo, update=update)
        elif repo.get("type") == REPO_TYPE_INT:
            _make_patches(main_repo, repo)
            _update_integrated_module(main_repo, repo, update)

        _apply_subgimera(main_repo, repo, update)


def _apply_subgimera(main_repo, repo, update):
    subgimera = Path(repo["path"]) / "gimera.yml"
    sub_path = main_repo.path / repo["path"]
    pwd = os.getcwd()
    if subgimera.exists():
        os.chdir(sub_path)
        _internal_apply([], update)

        dirty_files = list(
            filter(lambda x: safe_relative_to(x, sub_path), main_repo.all_dirty_files)
        )
        if dirty_files:
            main_repo.please_no_staged_files()
            for f in dirty_files:
                main_repo.X("git", "add", f)
            main_repo.X(
                "git", "commit", "-m", f"gimera: updated sub path {repo['path']}"
            )
        # commit submodule updates or changed dirs
    os.chdir(pwd)


def _make_sure_subrepo_is_checked_out(main_repo, repo_yml):
    """
    Could be, that git submodule update was not called yet.
    """
    assert repo_yml["type"] == REPO_TYPE_SUB
    path = main_repo.path / repo_yml["path"]
    if path.exists() and not is_empty_dir(path):
        return
    main_repo.X("git", "submodule", "update", "--init", "--recursive", repo_yml["path"])
    if not path.exists():
        _raise_error("After submodule update the path {repo_yml['path']} did not exist")


def _make_patches(main_repo, repo_yml):
    subrepo_path = main_repo.path / repo_yml["path"]
    if not subrepo_path.exists():
        return
    subrepo = main_repo.get_submodule(repo_yml["path"], force=True)
    changed_files = subrepo.filterout_submodules(subrepo.all_dirty_files)
    untracked_files = subrepo.filterout_submodules(subrepo.untracked_files)
    if not changed_files:
        return

    files_in_lines = "\n".join(map(str, sorted(changed_files)))
    if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
        correct = True
    else:
        correct = inquirer.confirm(
            f"Continue making patches for: {files_in_lines}", default=False
        )
    if not correct:
        sys.exit(-1)

    to_reset = []
    if repo_yml["type"] == REPO_TYPE_INT:
        cwd = main_repo.working_dir
    elif repo_yml["type"] == REPO_TYPE_INT:
        cwd = main_repo.working_dir / repo_yml["path"]
    else:
        raise NotImplementedError(repo_yml["type"])
    repo = Repo(cwd)
    for untracked_file in untracked_files:
        # add with empty blob to index, appears like that then:
        """
        Changes not staged for commit:
        (use "git add <file>..." to update what will be committed)
        (use "git restore <file>..." to discard changes in working directory)
                modified:   roles2/sub1/file2.txt
                new file:   roles2/sub1/file3.txt
        """
        repo.X("git", "add", "-N", untracked_file)
        to_reset.append(untracked_file)
        del untracked_file

    subdir_path = Path(main_repo.working_dir) / repo_yml["path"]
    repo.X("git", "add", subdir_path)
    repo.X("git", "commit", "-m", "for patch")

    patch_content = Repo(subdir_path).out(
        "git", "format-patch", "HEAD~1", "--stdout", "--relative"
    )
    repo.X("git", "reset", "HEAD~1")

    if not repo_yml.get("patches"):
        _raise_error(
            f"Please define at least one directory, where patches are stored for {repo_yml['path']}"
        )

    if len(repo_yml["patches"]) == 1:
        patch_dir = Path(repo_yml["patches"][0])
    else:
        questions = [
            inquirer.List(
                "path",
                message="Please choose a directory where to put the patch file.",
                choices=["Type directory"] + repo_yml["patches"],
            )
        ]
        answers = inquirer.prompt(questions)
        if answers["path"] == "Type directory":
            questions = [
                inquirer.Text(
                    "path",
                    message="Where shall i put the patch file? (directory)",
                    default="./",
                )
            ]
            answers = inquirer.prompt(questions)
        patch_dir = Path(answers["path"])

    patch_dir.mkdir(exist_ok=True, parents=True)
    (patch_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + ".patch")).write_text(
        patch_content
    )

    for to_reset in to_reset:
        main_repo.X("git", "reset", to_reset)

    # commit the patches - do NOT - could lie in submodule - is hard to do
    # subprocess.check_call(['git', 'add', repo['path']], cwd=main_repo.working_dir)
    # subprocess.check_call(['git', 'add', patch_dir], cwd=main_repo.working_dir)
    # subprocess.check_call(['git', 'commit', '-m', 'added patches'], cwd=main_repo.working_dir)


def _update_integrated_module(main_repo, repo_yml, update):
    """
    Put contents of a git repository inside the main repository.
    """

    def _get_cache_dir():
        url = repo_yml.get("url")
        if not url:
            click.secho(f"Missing url: {json.dumps(repo, indent=4)}")
            sys.exit(-1)
        path = Path(os.path.expanduser("~/.cache/gimera")) / url.replace(
            ":", "_"
        ).replace("/", "_")
        path.parent.mkdir(exist_ok=True, parents=True)
        if not path.exists():
            click.secho(
                f"Caching the repository {repo_yml['url']} for quicker reuse",
                fg="yellow",
            )
            Repo(main_repo.path).X("git", "clone", url, path)
        return path

    # use a cache directory for pulling the repository and updating it
    local_repo_dir = _get_cache_dir()
    if not os.access(local_repo_dir, os.W_OK):
        _raise_error(f"No R/W rights on {local_repo_dir}")
    repo = Repo(local_repo_dir)
    repo.fetch()
    repo.X("git", "checkout", "-f", str(repo_yml["branch"]))
    repo.X("git", "clean", "-xdff")
    repo.pull()

    sha = repo_yml.get("sha")
    if not update and sha:
        branches = repo.get_all_branches()
        if repo_yml["branch"] not in branches:
            repo.pull()
            _store(main_repo, repo_yml, {"sha": None})
        else:
            subprocess.check_call(
                ["git", "config", "advice.detachedHead", "false"], cwd=local_repo_dir
            )
            repo.checkout(sha, force=True)

    new_sha = repo.hex
    _apply_merges(repo, repo_yml)

    dest_path = Path(main_repo.path) / repo_yml["path"]
    dest_path.parent.mkdir(exist_ok=True, parents=True)
    subprocess.check_call(
        [
            "rsync",
            "-ar",
            "--exclude=.git",
            "--delete-after",
            str(local_repo_dir) + "/",
            str(dest_path) + "/",
        ],
        cwd=main_repo.working_dir,
    )

    # apply patches:
    _apply_patches(main_repo, repo_yml)

    # commit updated directories
    if any(
        map(
            lambda filepath: safe_relative_to(
                filepath, main_repo.path / repo_yml["path"]
            ),
            main_repo.all_dirty_files,
        )
    ):
        main_repo.X("git", "add", repo_yml["path"])
        main_repo.X(
            "git",
            "commit",
            "-m",
            f'updated {REPO_TYPE_INT} submodule: {repo_yml["path"]}',
        )

    repo.X("git", "reset", "--hard", f'origin/{repo_yml["branch"]}')
    if new_sha != sha:
        _store(main_repo, repo_yml, {"sha": new_sha})


@yieldlist
def _get_remotes(repo_yml):
    config = repo_yml.get("remotes")
    if not config:
        return

    for name, url in dict(config).items():
        yield Remote(None, name, url)


def _apply_merges(repo, repo_yml):
    if not repo_yml.get("merges"):
        return
    configured_remotes = _get_remotes(repo_yml)
    for remote in configured_remotes:
        if list(filter(lambda x: x.name == remote.name, repo.remotes)):
            repo.remove_remote(remote)
        repo.add_remote(remote)

    for remote, ref in repo_yml["merges"]:
        remote = repo.get_remote(remote)
        repo.fetch(remote, ref)
    for remote, ref in repo_yml["merges"]:
        remote = repo.get_remote(remote)
        repo.pull(remote, ref)


def _apply_patches(main_repo, repo_yml):
    for dir in repo_yml.get("patches", []) or []:
        dir = main_repo.working_dir / dir
        dir.relative_to(main_repo.path)

        dir.mkdir(parents=True, exist_ok=True)
        for file in sorted(dir.rglob("*.patch")):
            click.secho(
                (f"Applying patch {file.relative_to(main_repo.working_dir)}"), fg="blue"
            )
            # Git apply fails silently if applied within local repos
            try:
                cwd = Path(main_repo.working_dir) / repo_yml["path"]
                output = subprocess.check_output(
                    ["patch", "-p1"],
                    input=file.read_text(),  # bytes().decode('utf-8'),
                    cwd=cwd,
                    encoding="utf-8",
                )
                click.secho(
                    (f"Applied patch {file.relative_to(main_repo.working_dir)}"),
                    fg="blue",
                )
            except subprocess.CalledProcessError as ex:
                click.secho(
                    ("\n\nFailed to apply the following patch file:\n\n"), fg="yellow"
                )
                click.secho(
                    (
                        f"{file}\n"
                        "============================================================================================="
                    ),
                    fg="red",
                    bold=True,
                )
                click.secho(
                    (f"{ex.stdout or ''}\n" f"{ex.stderr or ''}\n"), fg="yellow"
                )

                click.secho(file.read_text(), fg="cyan")
                if not inquirer.confirm("Continue?", default=True):
                    sys.exit(-1)
            except Exception as ex:
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


def _fetch_latest_commit_in_submodule(main_repo, repo_yml, update=False):
    path = Path(main_repo.working_dir) / repo_yml["path"]
    if not path.exists():
        return
    subrepo = main_repo.get_submodule(repo_yml["path"])
    if subrepo.dirty:
        _raise_error(
            f"Directory {repo_yml['path']} contains modified "
            "files. Please commit or purge before!"
        )
    if sha := repo_yml.get("sha"):
        try:
            branches = list(
                clean_branch_names(
                    subrepo.out("git", "branch", "--contains", sha).splitlines()
                )
            )
        except Exception:  # pylint: disable=broad-except
            _raise_error(
                f"SHA {sha} does not seem to belong to a "
                f"branch at module {repo_yml['path']}"
            )

        if not [x for x in branches if repo_yml["branch"] == x]:
            _raise_error(
                f"SHA {sha} does not exist on branch "
                f"{repo_yml['branch']} at repo {repo_yml['path']}"
            )
        subrepo.X("git", "checkout", "-f", sha)
    else:
        try:
            subrepo.X("git", "checkout", "-f", repo_yml["branch"])
        except Exception:  # pylint: disable=broad-except
            _raise_error(f"Failed to checkout {repo_yml['branch']} in {path}")
        else:
            _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo)

    subrepo.X("git", "submodule", "update", "--init", "--recursive")
    _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo)

    # check if sha collides with branch
    subrepo.X("git", "clean", "-xdff")
    if not repo_yml.get("sha") or update:
        subrepo.X("git", "checkout", repo_yml["branch"])
        subrepo.pull()
        _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo)

    # update gimera.yml on demand

    _store(main_repo, repo_yml, {"sha": subrepo.hex})


def clean_branch_names(arr):
    for x in arr:
        x = x.strip()
        if x.startswith("* "):
            x = x[2:]
        yield x


def _get_config_file():
    config_file = Path(os.getcwd()) / "gimera.yml"
    if not config_file.exists():
        _raise_error(f"Did not find: {config_file}")
    return config_file


def _store(main_repo, repo, value):
    """
    Makes a commit of the changes.
    """
    if main_repo.staged_files:
        _raise_error("There mustnt be any staged files when updating gimera.yml")

    config_file = _get_config_file()
    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    param_repo = repo
    for repo in config["repos"]:
        if repo["path"] == param_repo["path"]:
            repo.update(value)
    config_file.write_text(yaml.dump(config, default_flow_style=False))
    main_repo.please_no_staged_files()
    main_repo.X("git", "add", config_file)
    if main_repo.staged_files:
        main_repo.X("git", "commit", "-m", "auto update gimera.yml")


def load_config():
    config_file = _get_config_file()
    paths = set()

    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    for repo in config["repos"]:
        path = repo["path"]
        if path in paths:
            _raise_error("Duplicate path: " + path)
        if path.endswith("/"):
            _raise_error("Paths may not end on /")
        repo["path"] = path
        paths.add(path)

        if repo.get("remotes"):
            repo["remotes"] = repo["remotes"].items()
        if repo.get("merges"):
            _merges = []
            for merge in repo.get("merges"):
                remote, ref = merge.split(" ")
                _merges.append((remote.strip(), ref.strip()))
            repo["merges"] = _merges

        if repo.get("type") not in [REPO_TYPE_SUB, REPO_TYPE_INT]:
            _raise_error(
                "Please provide type for repo "
                f"{config['path']}: either '{REPO_TYPE_INT}' or '{REPO_TYPE_SUB}'"
            )

    return config


def __add_submodule(repo, config):

    if config.get("type") != REPO_TYPE_SUB:
        return
    path = repo.path / config["path"]
    relpath = path.relative_to(repo.path)
    if path.exists():
        # if it is already a submodule, dont touch
        try:
            submodule = repo.get_submodule(relpath)
        except ValueError:
            repo.output_status()
            repo.please_no_staged_files()
            # remove current path
            repo.X("git", "rm", "-f", "-r", relpath)
            repo.clear_empty_subpaths(config)
            repo.output_status()
            if not [
                # x for x in repo.staged_files if safe_relative_to(x, repo.path / relpath)
                x for x in repo.all_dirty_files if safe_relative_to(x, repo.path / relpath)
            ]:
                if relpath.exists():
                    # in case of deletion it does not exist
                    repo.X("git", "add", relpath)
            repo.X("git", "commit", "-m", f"removed path {relpath} to insert submodule")
        else:
            # if submodule points to another url, also remove
            if submodule.get_url() != config["url"]:
                repo.force_remove_submodule(submodule.path.relative_to(repo.path))
            else:
                return
    repo.X(
        "git",
        "submodule",
        "add",
        "--force",
        "-b",
        str(config["branch"]),
        config["url"],
        path.relative_to(repo.path),
    )
    # repo.X("git", "add", ".gitmodules", relpath)
    click.secho(f"Added submodule {relpath} pointing to {config['url']}", fg="yellow")
    repo.X("git", "commit", "-m", f"gimera added submodule: {relpath}")


def _turn_into_correct_repotype(repo, repo_config):
    """
    if git submodule and exists: nothing todo
    if git submodule and not exists: cloned
    if git submodule and already exists a path: path removed, submodule added

    if integrated and exists no sub: nothing todo
    if integrated and not exists: cloned (later not here)
    if integrated and git submodule and already exists a path: submodule removed

    """
    path = repo_config["path"]
    if repo_config.get("type") == REPO_TYPE_INT:
        try:
            repo.get_submodule(path)
        except ValueError:
            pass
        else:
            repo.force_remove_submodule(path)  # updated at apply
    else:
        __add_submodule(repo, repo_config)
        submodules = repo.get_submodules()
        existing_submodules = list(
            filter(lambda x: x.equals(repo.path / path), submodules)
        )
        if not existing_submodules:
            _raise_error(f"Error with submodule {path}")
        del existing_submodules


if __name__ == "__main__":
    # _make_sure_in_root()
    gimera()
