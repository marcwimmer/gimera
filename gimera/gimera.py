#!/usr/bin/env python3
from ctypes.wintypes import PUSHORT
import tempfile
from contextlib import contextmanager
import shutil
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


class Config(object):
    class RepoItem(object):
        def __init__(self, config, config_section):
            self.config = config
            self._sha = config_section.get("sha", None)
            self.path = Path(config_section["path"])
            self.branch = str(config_section["branch"])
            self.merges = config_section.get("merges", [])
            self.patches = config_section.get("patches", [])
            self._type = config_section["type"]
            self._url = config_section["url"]
            self._remotes = config_section.get("remotes", {})
            if self.path in [x.path for x in config.repos]:
                _raise_error(f"Duplicate path: {self.path}")
            config._repos.append(self)

            self.remotes = self._remotes.items() or None

            if self.merges:
                _merges = []
                for merge in self.merges:
                    remote, ref = merge.split(" ")
                    _merges.append((remote.strip(), ref.strip()))
                self.merges = _merges

            if self.type not in [REPO_TYPE_SUB, REPO_TYPE_INT]:
                _raise_error(
                    "Please provide type for repo "
                    f"{self.path}: either '{REPO_TYPE_INT}' or '{REPO_TYPE_SUB}'"
                )

        @property
        def sha(self):
            return self._sha

        @sha.setter
        def sha(self, value):
            self._sha = value
            self.config._store(self, {"sha": value})

        def as_dict(self):
            return {
                "path": self.path,
                "branch": self.branch,
                "patches": self.patches,
                "type": self._type,
                "url": self._url,
                "merges": self._merges,
                "remotes": self._remotes,
            }

        @property
        def url(self):
            return self._url

        @property
        def url_public(self):
            url = self._url.replace("ssh://git@", "https://")
            return url

        @property
        def type(self):
            if self.config.force_type:
                return self.config.force_type
            return self._type

    def __init__(self, force_type):
        self.force_type = force_type
        self._repos = []
        self.load_config()

    @property
    def repos(self):
        return self._repos

    def _get_config_file(self):
        config_file = Path(os.getcwd()) / "gimera.yml"
        if not config_file.exists():
            _raise_error(f"Did not find: {config_file}")
        return config_file

    def load_config(self):
        self.config_file = self._get_config_file()

        config = yaml.load(self.config_file.read_text(), Loader=yaml.FullLoader)
        for repo in config["repos"]:
            Config.RepoItem(self, repo)
        self.config = config

    def _store(self, repo, value):
        """
        Makes a commit of the changes.
        """
        main_repo = Repo(self.config_file.parent)
        if main_repo.staged_files:
            _raise_error("There mustnt be any staged files when updating gimera.yml")

        config = yaml.load(self.config_file.read_text(), Loader=yaml.FullLoader)
        param_repo = repo
        for repo in config["repos"]:
            if Path(repo["path"]) == param_repo.path:
                for k, v in value.items():
                    repo[k] = v
        self.config_file.write_text(yaml.dump(config, default_flow_style=False))
        main_repo.please_no_staged_files()
        if self.config_file.resolve() in [
            x.resolve() for x in main_repo.all_dirty_files
        ]:
            main_repo.X("git", "add", self.config_file)
        if main_repo.staged_files:
            main_repo.X("git", "commit", "-m", "auto update gimera.yml")


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
    config = Config(force_type=False)
    repos = []
    for repo in config.repos:
        if not repo.path:
            continue
        if incomplete:
            if "/" not in incomplete:
                if incomplete not in str(repo.path):
                    continue
            else:
                if not str(repo.path).startswith(incomplete):
                    continue
        repos.append(str(repo.path))
    return sorted(repos)


def _get_available_patchfiles(ctx, param, incomplete):
    config = Config(force_type=False)
    cwd = Path(os.getcwd())
    patchfiles = []
    filtered_patchfiles = []
    for repo in config.repos:
        if not repo.patches:
            continue
        for patchdir in repo.patches:
            _dir = cwd / patchdir
            if not _dir.exists():
                continue
            for file in _dir.glob("*.patch"):
                patchfiles.append(file.relative_to(cwd))
    if incomplete:
        if "/" not in incomplete:
            for file in patchfiles:
                if incomplete in str(file):
                    filtered_patchfiles.append(file)
        else:
            splitted = incomplete.split("/")
            _dir = "/".join(splitted[:-1])
            name = splitted[-1]
            for file in patchfiles:
                if _dir in str(file):
                    if name in file.name:
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
def apply(
    repos, update, all_integrated, all_submodule, parallel_safe, strict, recursive
):
    if all_integrated and all_submodule:
        _raise_error("Please set either -I or -S")
    ttype = None
    ttype = REPO_TYPE_INT if all_integrated else ttype
    ttype = REPO_TYPE_SUB if all_submodule else ttype
    return _apply(
        repos,
        update,
        force_type=ttype,
        parallel_safe=parallel_safe,
        strict=strict,
        recursive=recursive,
    )


def _apply(
    repos, update, force_type=False, parallel_safe=False, strict=False, recursive=False
):
    """
    :param repos: user input parameter from commandline
    :param update: bool - flag from command line
    """
    config = Config(force_type=force_type)

    repos = list(_strip_paths(repos))
    for check in repos:
        if check not in map(lambda x: str(x.path), config.repos):
            _raise_error(f"Invalid path: {check}")

    _internal_apply(
        repos,
        update,
        force_type,
        parallel_safe=parallel_safe,
        strict=strict,
        recursive=recursive,
    )


def _internal_apply(
    repos, update, force_type, parallel_safe=False, strict=False, recursive=False
):
    main_repo = Repo(os.getcwd())
    config = Config(force_type=force_type)

    for repo in config.repos:
        if repos and str(repo.path) not in repos:
            continue
        _turn_into_correct_repotype(main_repo, repo, config)
        if repo.type == REPO_TYPE_SUB:
            _make_sure_subrepo_is_checked_out(main_repo, repo)
            _fetch_latest_commit_in_submodule(main_repo, repo, update=update)
        elif repo.type == REPO_TYPE_INT:
            _make_patches(main_repo, repo)
            _update_integrated_module(main_repo, repo, update, parallel_safe)

            if not strict:
                # fatal: refusing to create/use '.git/modules/addons_connector/modules/addons_robot/aaa' in another submodule's git dir
                # not submodules inside integrated modules
                force_type = REPO_TYPE_INT

        if recursive:
            _apply_subgimera(
                main_repo,
                repo,
                update,
                force_type,
                parallel_safe=parallel_safe,
                strict=strict,
            )


def _apply_subgimera(main_repo, repo, update, force_type, parallel_safe, strict):
    subgimera = Path(repo.path) / "gimera.yml"
    sub_path = main_repo.path / repo.path
    pwd = os.getcwd()
    if subgimera.exists():
        os.chdir(sub_path)
        _internal_apply(
            [],
            update,
            force_type=force_type,
            parallel_safe=parallel_safe,
            strict=strict,
            recursive=True,
        )

        dirty_files = list(
            filter(lambda x: safe_relative_to(x, sub_path), main_repo.all_dirty_files)
        )
        if dirty_files:
            main_repo.please_no_staged_files()
            for f in dirty_files:
                main_repo.X("git", "add", f)
            main_repo.X("git", "commit", "-m", f"gimera: updated sub path {repo.path}")
        # commit submodule updates or changed dirs
    os.chdir(pwd)


def _make_sure_subrepo_is_checked_out(main_repo, repo_yml):
    """
    Could be, that git submodule update was not called yet.
    """
    assert repo_yml.type == REPO_TYPE_SUB
    path = main_repo.path / repo_yml.path
    if path.exists() and not is_empty_dir(path):
        return
    main_repo.X("git", "submodule", "update", "--init", "--recursive", repo_yml.path)
    if not path.exists():
        _raise_error("After submodule update the path {repo_yml['path']} did not exist")


def _make_patches(main_repo, repo_yml):
    subrepo_path = main_repo.path / repo_yml.path
    if not subrepo_path.exists():
        return
    subrepo = main_repo.get_submodule(repo_yml.path, force=True)
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
    if repo_yml.type == REPO_TYPE_INT:
        cwd = main_repo.working_dir
    else:
        raise NotImplementedError(repo_yml.type)
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

    subdir_path = Path(main_repo.working_dir) / repo_yml.path
    repo.X("git", "add", subdir_path)
    repo.X("git", "commit", "-m", "for patch")

    patch_content = Repo(subdir_path).out(
        "git", "format-patch", "HEAD~1", "--stdout", "--relative"
    )
    repo.X("git", "reset", "HEAD~1")

    if not repo_yml.patches:
        _raise_error(
            f"Please define at least one directory, where patches are stored for {repo_yml['path']}"
        )

    if len(repo_yml.patches) == 1:
        patch_dir = Path(repo_yml.patches[0])
    else:
        questions = [
            inquirer.List(
                "path",
                message="Please choose a directory where to put the patch file.",
                choices=["Type directory"] + repo_yml.patches,
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

    patch_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    if os.getenv("GIMERA_NON_INTERACTIVE") != "1":
        questions = [
            inquirer.Text(
                "filename",
                message="Please give the patch-file a name",
            )
        ]
        answers = inquirer.prompt(questions)
        if not answers:
            sys.exit(-1)
        patch_filename = answers["filename"]
    if not patch_filename:
        _raise_error("No filename provided")

    if not patch_filename.endswith(".patch"):
        patch_filename += ".patch"

    (patch_dir / patch_filename).write_text(patch_content)

    for to_reset in to_reset:
        main_repo.X("git", "reset", to_reset)

    # commit the patches - do NOT - could lie in submodule - is hard to do
    # subprocess.check_call(['git', 'add', repo['path']], cwd=main_repo.working_dir)
    # subprocess.check_call(['git', 'add', patch_dir], cwd=main_repo.working_dir)
    # subprocess.check_call(['git', 'commit', '-m', 'added patches'], cwd=main_repo.working_dir)


def _update_integrated_module(main_repo, repo_yml, update, parallel_safe):
    """
    Put contents of a git repository inside the main repository.
    """

    # TODO eval parallelsafe
    def _get_cache_dir():
        url = repo_yml.url
        if not url:
            click.secho(f"Missing url: {json.dumps(repo, indent=4)}")
            sys.exit(-1)
        path = Path(os.path.expanduser("~/.cache/gimera")) / url.replace(
            ":", "_"
        ).replace("/", "_")
        path.parent.mkdir(exist_ok=True, parents=True)
        if not path.exists():
            click.secho(
                f"Caching the repository {repo_yml.url} for quicker reuse",
                fg="yellow",
            )
            Repo(main_repo.path).X("git", "clone", url, path)
        return path

    # use a cache directory for pulling the repository and updating it
    local_repo_dir = _get_cache_dir()
    if not os.access(local_repo_dir, os.W_OK):
        _raise_error(f"No R/W rights on {local_repo_dir}")
    repo = Repo(local_repo_dir)
    repo.X("git", "remote", "set-url", "origin", repo_yml.url)
    repo.X("git", "fetch", "--all")
    branch = str(repo_yml.branch)
    origin_branch = f"origin/{branch}"
    repo.X("git", "checkout", "-f", branch)
    repo.X("git", "reset", "--hard", origin_branch)
    repo.X("git", "branch", f"--set-upstream-to={origin_branch}", branch)
    repo.X("git", "clean", "-xdff")
    repo.pull(repo_yml=repo_yml)

    if not update and repo_yml.sha:
        branches = repo.get_all_branches()
        if repo_yml.branch not in branches:
            repo.pull(repo_yml=repo_yml)
            repo_yml.sha = None
        else:
            subprocess.check_call(
                ["git", "config", "advice.detachedHead", "false"], cwd=local_repo_dir
            )
            repo.checkout(repo_yml.sha, force=True)

    new_sha = repo.hex
    with _apply_merges(repo, repo_yml, parallel_safe) as (repo, remote_refs):

        dest_path = Path(main_repo.path) / repo_yml.path
        dest_path.parent.mkdir(exist_ok=True, parents=True)
        # BTW: delete-after cannot removed unused directories - cool to know; is
        # just standarded out
        if dest_path.exists():
            shutil.rmtree(dest_path)
        subprocess.check_call(
            [
                "rsync",
                "-ar",
                "--exclude=.git",
                "--delete-after",
                str(repo.path) + "/",
                str(dest_path) + "/",
            ],
            cwd=main_repo.working_dir,
        )
        msg = [f"Merged: {repo_yml.url}"]
        for (remote, ref) in remote_refs:
            msg.append(f"Merged {remote.url}:{ref}")
        main_repo.commit_dir_if_dirty(repo_yml.path, "\n".join(msg))

    del repo

    # apply patches:
    _apply_patches(main_repo, repo_yml)
    main_repo.commit_dir_if_dirty(
        repo_yml.path, f"updated {REPO_TYPE_INT} submodule: {repo_yml.path}"
    )
    repo_yml.sha = new_sha


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
                repo.remove_remote(remote)
            repo.add_remote(remote)

        remotes = []
        for remote, ref in repo_yml.merges:
            remote = [x for x in reversed(configured_remotes) if x.name == remote][0]
            repo.pull(remote=remote, ref=ref)
            remotes.append((remote, ref))

        yield repo, remotes
    finally:
        if parallel_safe:
            shutil.rmtree(repo.path)


def _apply_patchfile(file, main_repo, repo_yml):
    cwd = Path(main_repo.working_dir) / repo_yml.path
    output = subprocess.check_output(
        ["patch", "-p1", "--no-backup-if-mismatch"],
        input=file.read_text(),  # bytes().decode('utf-8'),
        cwd=cwd,
        encoding="utf-8",
    )
    click.secho(
        (f"Applied patch {file.relative_to(main_repo.working_dir)}"),
        fg="blue",
    )


def _apply_patches(main_repo, repo_yml):
    for dir in (repo_yml.patches or []):
        dir = main_repo.working_dir / dir
        dir.relative_to(main_repo.path)

        dir.mkdir(parents=True, exist_ok=True)
        for file in sorted(dir.rglob("*.patch")):
            click.secho(
                (f"Applying patch {file.relative_to(main_repo.working_dir)}"), fg="blue"
            )
            # Git apply fails silently if applied within local repos
            try:
                _apply_patchfile(file, main_repo, repo_yml)
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
                if not inquirer.confirm(
                    f"Patchfile failed ''{file.relative_to(main_repo.path)}'' - continue with next file?",
                    default=True,
                ):
                    sys.exit(-1)
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


def _fetch_latest_commit_in_submodule(main_repo, repo_yml, update=False):
    path = Path(main_repo.working_dir) / repo_yml.path
    if not path.exists():
        return
    subrepo = main_repo.get_submodule(repo_yml.path)
    if subrepo.dirty:
        _raise_error(
            f"Directory {repo_yml.path} contains modified "
            "files. Please commit or purge before!"
        )
    if sha := repo_yml.sha:
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
            subrepo.X("git", "checkout", "-f", repo_yml.branch)
        else:
            subrepo.X("git", "checkout", "-f", sha)
    else:
        try:
            subrepo.X("git", "checkout", "-f", repo_yml.branch)
        except Exception:  # pylint: disable=broad-except
            _raise_error(f"Failed to checkout {repo_yml.branch} in {path}")
        else:
            _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo)

    subrepo.X("git", "submodule", "update", "--init", "--recursive")
    _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo)

    # check if sha collides with branch
    subrepo.X("git", "clean", "-xdff")
    if not repo_yml.sha or update:
        subrepo.X("git", "checkout", "-f", repo_yml.branch)
        subrepo.pull(repo_yml=repo_yml)
        _commit_submodule_inside_clean_but_not_linked_to_parent(main_repo, subrepo)

    # update gimera.yml on demand
    repo_yml.sha = subrepo.hex


def clean_branch_names(arr):
    for x in arr:
        x = x.strip()
        if x.startswith("* "):
            x = x[2:]
        yield x


def __add_submodule(repo, config, all_config):

    if config.type != REPO_TYPE_SUB:
        return
    path = repo.path / config.path
    relpath = path.relative_to(repo.path)
    if path.exists():
        # if it is already a submodule, dont touch
        try:
            submodule = repo.get_submodule(relpath)
        except ValueError:
            repo.output_status()
            repo.please_no_staged_files()
            # remove current path

            if repo.lsfiles(relpath):
                repo.X("git", "rm", "-f", "-r", relpath)
            if (repo.path / relpath).exists():
                shutil.rmtree(repo.path / relpath)

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
        shutil.rmtree(repo.path / relpath)

    repo.submodule_add(config.branch, config.url, relpath)
    # repo.X("git", "add", ".gitmodules", relpath)
    click.secho(f"Added submodule {relpath} pointing to {config.url}", fg="yellow")
    if repo.staged_files:
        repo.X("git", "commit", "-m", f"gimera added submodule: {relpath}")


def _turn_into_correct_repotype(repo, repo_config, config):
    """
    if git submodule and exists: nothing todo
    if git submodule and not exists: cloned
    if git submodule and already exists a path: path removed, submodule added

    if integrated and exists no sub: nothing todo
    if integrated and not exists: cloned (later not here)
    if integrated and git submodule and already exists a path: submodule removed

    """
    path = repo_config.path
    if repo_config.type == REPO_TYPE_INT:
        # always delete
        submodules = repo.get_submodules()
        existing_submodules = list(
            filter(lambda x: x.equals(repo.path / path), submodules)
        )
        if existing_submodules:
            repo.force_remove_submodule(path)
    else:
        __add_submodule(repo, repo_config, config)
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
def check_all_submodules_initialized():
    if not _check_all_submodules_initialized():
        sys.exit(-1)


def _check_all_submodules_initialized():
    root = Path(os.getcwd())

    def _get_all_submodules(root):

        for path in (
            Repo(root).out("git", "submodule--helper", "list").strip().splitlines()
        ):
            path = root / path.split("\t", 1)[1]
            yield path
            if path.exists():
                yield from _get_all_submodules(path)

    error = False
    for path in _get_all_submodules(root):
        if not path.exists():
            click.secho(f"Not initialized: {path}", fg="red")
            error = True

    return not error


@cli.command()
@click.argument(
    "patchfiles", nargs=-1, shell_complete=_get_available_patchfiles, required=True
)
def edit_patch(patchfiles):
    _edit_patch(patchfiles)


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
                if not repo.patches:
                    continue
                for patchdir in repo.patches:
                    for file in (cwd / patchdir).glob("*.patch"):
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
    deactivated_names = []
    main_repo = Repo(Path(os.getcwd()))
    for patchfile in list(_get_repo_to_patchfiles(patchfiles)):
        repo, patchfile = patchfile
        deactivated_name = patchfile.parent / f"{patchfile.name}.deactivated"
        deactivated_names.append(deactivated_name)
        patchfile.rename(deactivated_name)
    try:
        _internal_apply(str(repo.path), update=False, force_type=None)

        # apply just the patchfile now
        for deactivated_name in sorted(set(deactivated_names)):
            _apply_patchfile(deactivated_name, main_repo, repo)

        deactivated_name.unlink()

    except Exception:  # pylint: disable=broad-except
        for deactivated_name in sorted(set(deactivated_names)):
            deactivated_name.rename(
                deactivated_name.parent / f"{deactivated_name.stem}"
            )
        raise


if __name__ == "__main__":
    # _make_sure_in_root()
    gimera()
