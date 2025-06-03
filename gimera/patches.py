import re
import os
from inquirer import errors
import shutil
import sys
import subprocess
import click
from .repo import Repo
from datetime import datetime
from contextlib import contextmanager
from .consts import gitcmd as git
from .tools import confirm
from .tools import temppath
from .tools import path1inpath2
from .tools import verbose
from .consts import inquirer_theme
from .tools import (
    _raise_error,
    get_nearest_repo,
    safe_relative_to,
    is_empty_dir,
    _strip_paths,
    temppath,
    rsync,
    wait_git_lock,
    files_relative_to,
    filter_files_to_folders,
)
import inquirer
from pathlib import Path
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB
from .config import Config


def make_patches(working_dir, main_repo, repo_yml, common_vars):
    if repo_yml.type != REPO_TYPE_INT:
        raise NotImplementedError(repo_yml.type)
    verbose(f"Making patches for {repo_yml.path}")

    with _if_ignored_move_to_separate_dir(
        working_dir, main_repo, repo_yml, common_vars
    ) as (main_repo, is_temp_path):
        with _prepare(main_repo, repo_yml) as (
            subrepo,
            subrepo_path,
            changed_files,
            untracked_files,
        ):
            if not changed_files:
                return
            if is_temp_path and changed_files:
                if  os.getenv("GIMERA_FORCE") == "1":
                    return
                # hold on full stop: we are in an ignored directory and have changes
                # They would be lost if we just continue
                click.secho(
                    f"Changed files detected in probably ignored directory.\nPlease analyze changes here: \n{main_repo.path}",
                    fg="red",
                )
                main_repo.X(*(git + ["status"]))
                main_repo.X(*(git + ["diff"]))
                _raise_error("Halted to avoid data loss. Please check your changes or provide --force option to continue.")
            if not _start_question(repo_yml, changed_files):
                return

            with _temporarily_add_untracked_files(main_repo, untracked_files):
                subdir_path = Path(main_repo.path) / repo_yml.path
                patch_content = _technically_make_patch(main_repo, subdir_path)

                if not repo_yml.all_patch_dirs(rel_or_abs="relative"):
                    if os.getenv("GIMERA_FORCE") == "1":
                        return
                    if os.getenv("GIMERA_NON_INTERACTIVE") != "1" and not is_temp_path:
                        repo_yml = _ask_user_to_create_path_directory(repo_yml)
                    if not repo_yml.all_patch_dirs:
                        _raise_error(
                            "Please define at least one directory, "
                            f"where patches are stored for {repo_yml.path}"
                        )

                with _prepare_patchdir(repo_yml) as (patch_dir, patch_filename):
                    _write_patch_content(
                        main_repo,
                        repo_yml,
                        subrepo,
                        subrepo_path,
                        patch_dir,
                        patch_filename,
                        patch_content,
                    )


def _ask_user_to_create_path_directory(repo_yml):
    def validation(answers, current):
        if current and current.startswith("/"):
            raise errors.ValidationError(
                "", reason="Please provide relative paths only."
            )
        return True

    questions = [
        inquirer.Text(
            "path",
            validate=validation,
            message=(
                f"Please define a patch directory for {repo_yml.path} "
                " - relative path please starting from root."
            ),
        )
    ]
    answers = inquirer.prompt(questions, theme=inquirer_theme)
    path = answers["path"]

    repo_yml.config._store(repo_yml, {"patches": [path]})
    repo_yml.config.load_config()
    repo_yml = [x for x in repo_yml.config.repos if x.path == repo_yml.path][0]
    return repo_yml


@contextmanager
def _temporarily_move_gimera(repo_yml, to_path):
    remember_config_path = repo_yml.config.config_file
    repo_yml.config.config_file = to_path / "gimera.yml"
    repo_yml.config.config_file.parent.mkdir(exist_ok=True, parents=True)
    shutil.copy(remember_config_path, repo_yml.config.config_file)

    yield

    repo_yml.config.config_file = remember_config_path


@contextmanager
def _if_ignored_move_to_separate_dir(working_dir, main_repo, repo_yml, common_vars):
    """
    If directory is ignored then move to temporary path.
    Apply changes from local dir to get the diffs.
    """
    from .cachedir import _get_cache_dir
    from .integrated import _update_integrated_module

    if (
        main_repo.check_ignore(repo_yml.path)
        and (main_repo.path / repo_yml.path).exists()
    ):
        # TODO perhaps faster when just copied .git into the hidden dir
        with temppath() as path:
            subprocess.check_call(
                (git + ["init", "--initial-branch=main", "."]), cwd=path
            )
            main_repo2 = Repo(path)
            for patchdir in repo_yml.patches:
                dest_path = main_repo2.path / patchdir
                dest_path.mkdir(exist_ok=True, parents=True)
                patch_path = main_repo.path / patchdir
                if not patch_path.exists():
                    if os.getenv("GIMERA_NON_INTERACTIVE") != "1":
                        confirm(f"Path {patch_path} does not exist. Create?")
                        patch_path.mkdir(parents=True, exist_ok=True)
                rsync(main_repo.path / patchdir, dest_path)
            main_repo2.simple_commit_all()
            with _temporarily_move_gimera(repo_yml, main_repo2.path):
                _update_integrated_module(
                    main_repo2.path,
                    main_repo2,
                    repo_yml,
                    update=False,
                    common_vars=common_vars,
                )
                main_repo2.simple_commit_all()

                # now transfer the latest changes:
                rsync(
                    main_repo.path / repo_yml.path,
                    path / repo_yml.path,
                    exclude=[".git"],
                )
                yield main_repo2, True

                for patchdir in repo_yml.patches:
                    rsync(main_repo2.path / patchdir, main_repo.path / patchdir)
    else:
        yield main_repo, False


def _update_edited_patchfile(repo_yml):
    click.secho(
        "Editing a patch is in progress - continuing for " f"{repo_yml.edit_patchfile}",
        fg="yellow",
    )
    ttype = repo_yml._get_type_of_patchfolder(Path(repo_yml.edit_patchfile).parent)
    if (ttype) == "from_outside":
        edit_patchfile = repo_yml.config.config_file.parent / repo_yml.edit_patchfile
    elif ttype == "internal":
        edit_patchfile = (
            repo_yml.config.config_file.parent / repo_yml.path / repo_yml.edit_patchfile
        )
    else:
        raise NotImplementedError(ttype)
    patch_dir = [
        x
        for x in repo_yml.all_patch_dirs("absolute")
        if x._path == edit_patchfile.parent
    ][0]
    patch_filename = Path(repo_yml.edit_patchfile).name
    return patch_dir, patch_filename


def _get_new_patchfilename(repo_yml):
    patchdirs = repo_yml.all_patch_dirs(rel_or_abs="absolute")
    if len(patchdirs) == 1:
        patch_dir = patchdirs[0]
    else:
        if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
            _raise_error(
                (
                    "A patch dir is required but non interactive mode is set. "
                    "You can provide the --no-patch option perhaps."
                )
            )

        questions = [
            inquirer.List(
                "path",
                message="Please choose a directory where to put the patch file.",
                # choices=["Type directory"] + patchdirs,
                choices=patchdirs,
            )
        ]
        answers = inquirer.prompt(questions, theme=inquirer_theme)
        patch_dir = answers["path"]
    return patch_dir


@contextmanager
def _prepare_patchdir(repo_yml):
    remove_edit_patchfile = False
    if repo_yml.edit_patchfile:
        patch_dir, patch_filename = _update_edited_patchfile(repo_yml)
        remove_edit_patchfile = True
    else:
        patch_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
        patch_dir = _get_new_patchfilename(repo_yml)

    patch_dir._path.mkdir(exist_ok=True, parents=True)

    if os.getenv("GIMERA_NON_INTERACTIVE") != "1" and not repo_yml.edit_patchfile:
        questions = [
            inquirer.Text(
                "filename",
                message="Please give the patch-file a name",
            )
        ]
        answers = inquirer.prompt(questions, theme=inquirer_theme)
        if not answers:
            sys.exit(-1)
        patch_filename = answers["filename"]
    if not patch_filename:
        _raise_error("No filename provided")

    if not patch_filename.endswith(".patch"):
        patch_filename += ".patch"

    yield patch_dir, patch_filename

    if remove_edit_patchfile:
        repo_yml.config._store(
            repo_yml,
            {
                "edit_patchfile": "",
            },
        )


def _start_question(repo_yml, changed_files):
    files_in_lines = "\n".join(map(str, sorted(changed_files)))
    if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
        correct = True
    else:
        choice_yes = "Yes - make a patch"
        if repo_yml.edit_patchfile:
            choice_yes = f"Merge all changes into patchfile {repo_yml.edit_patchfile}"

        for file in files_in_lines.splitlines():
            click.secho(f"  * {file}")

        questions = [
            inquirer.List(
                "correct",
                message=f"Continue making patches for the lines above?",
                default="no",
                choices=[
                    choice_yes,
                    "Abort",
                    "Ignore",
                ],
            )
        ]
        answers = inquirer.prompt(questions, theme=inquirer_theme)
        correct = answers["correct"][0]
        if correct == "Y":
            correct = True
        elif correct == "A":
            correct = False
    if not correct:
        sys.exit(-1)
    if correct == "I":
        return False
    return True


def _write_patch_content(
    main_repo, repo_yml, subrepo, subrepo_path, patch_dir, patch_filename, patch_content
):
    if path1inpath2(patch_dir._path, subrepo_path):
        # case: patch must be put within patches folder of the integrated module
        # so it must be uploaded via a temp path; and the latest version must be
        # pulled

        hex = _clone_directory_and_add_patch_file(
            main_repo=main_repo,
            repo_yml=repo_yml,
            branch=repo_yml.branch,
            repo_url=repo_yml.url,
            patch_path=patch_dir._path.relative_to(subrepo_path) / patch_filename,
            content=patch_content,
        )
        # write latest hex to gimera
        repo_yml.config._store(
            repo_yml,
            {
                "sha": hex,
            },
        )
        repo_yml.sha = hex

    else:
        # case: patch file is in main repo and can be committed there
        (patch_dir._path / patch_filename).write_text(patch_content)

        # commit the patches - do NOT - could lie in submodule - is hard to do
        subprocess.check_call((git + ["add", repo_yml.path]), cwd=main_repo.path)
        subprocess.check_call((git + ["add", patch_dir._path]), cwd=main_repo.path)
        subprocess.check_call(
            (git + ["commit", "-m", f"added patch {patch_filename}"]),
            cwd=main_repo.path,
        )


@contextmanager
def _temporarily_add_untracked_files(repo, untracked_files):
    for untracked_file in untracked_files:
        # add with empty blob to index, appears like that then:
        #
        # Changes not staged for commit:
        # (use "git add <file>..." to update what will be committed)
        # (use "git restore <file>..." to discard changes in working directory)
        #         modified:   roles2/sub1/file2.txt
        #         new file:   roles2/sub1/file3.txt
        repo.X(*(git + ["add", "-f", "-N", untracked_file]))

    yield

    for to_reset in untracked_files:
        repo.X(*(git + ["reset", to_reset]))


@contextmanager
def _prepare(main_repo, repo_yml):
    subrepo_path = main_repo.path / repo_yml.path
    if not subrepo_path.exists():
        yield None, None, [], []
    else:
        try:
            subrepo = main_repo.get_submodule(repo_yml.path)
        except ValueError:
            subrepo = None

        if subrepo and subrepo.path.exists():
            changed_files = subrepo.all_dirty_files
            untracked_files = subrepo.untracked_files
        elif subrepo_path.exists():
            repo = Repo(get_nearest_repo(main_repo.path, subrepo_path))
            changed_files = repo.all_dirty_files_absolute
            untracked_files = repo.untracked_files_absolute
            changed_files = list(
                files_relative_to(
                    filter_files_to_folders(changed_files, [subrepo_path]), repo.path
                )
            )
            untracked_files = list(
                files_relative_to(
                    filter_files_to_folders(untracked_files, [subrepo_path]), repo.path
                )
            )

        else:
            changed_files, untracked_files = [], []
        yield subrepo, subrepo_path, changed_files, untracked_files


def _clone_directory_and_add_patch_file(
    main_repo, repo_yml, branch, repo_url, patch_path, content
):
    from .fetch import _fetch_branch, _get_cache_dir

    with temppath() as path:
        path = path / "repo"
        subprocess.check_call((git + ["clone", "--branch", branch, repo_url, path]))
        repo = Repo(path)
        repo.X(*(git + ["checkout", branch]))
        patch_path = path / patch_path
        assert patch_path.relative_to(path)
        patch_path.parent.mkdir(exist_ok=True, parents=True)
        patch_path.write_text(content)
        repo.X(*(git + ["add", patch_path.relative_to(path)]))
        repo.X(*(git + ["commit", "-m", f"added patchfile: {patch_path}"]))
        repo.X(*(git + ["push"]))
        del repo
        # also make sure that local cache is updated, because
        # latest repo version is applied to project
        with _get_cache_dir(main_repo, repo_yml) as cache_dir:
            with wait_git_lock(cache_dir):
                repo = Repo(cache_dir)
                _fetch_branch(repo, repo_yml, filter_remote="origin")
                with repo.worktree(branch) as repo:
                    repo.pull(repo_yml=repo_yml)
                    return repo.hex


def _technically_make_patch(repo, path):
    repo.X(*(git + ["add", path]))
    repo.X(*(git + ["commit", "-m", "for patch"]))

    patch_content = Repo(path).out(
        *(git + ["format-patch", "HEAD~1", "--stdout", "--relative"])
    )
    repo.X(*(git + ["reset", "HEAD~1"]))
    return patch_content


def _apply_patches(repo_yml):
    verbose(f"Applying patches for {repo_yml.path}")
    relevant_patch_files = set()
    for patchdir in repo_yml.all_patch_dirs(rel_or_abs="absolute") or []:
        # with patchdir.path as dir:
        if not patchdir._path.exists():
            patchdir._path.mkdir(parents=True)
        for file in sorted(patchdir._path.rglob("*.patch")):
            if repo_yml.ignore_patchfile(file):
                continue
            element = (patchdir, file)
            if not [x for x in relevant_patch_files if x[1] == file]:
                relevant_patch_files.add(element)
        del patchdir

    for patchdir, file in sorted(relevant_patch_files, key=lambda x: x[1].name):
        click.secho((f"Applying patch {file}"), fg="blue")
        # Git apply fails silently if applied within local repos
        _apply_patchfile(file, patchdir.apply_from_here_dir, error_ok=False)


def _apply_patchfile(file, working_dir, error_ok=False, just_check=False):
    verbose(f"Applying patchfile {file} in working dir {working_dir}")
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
        cmd = [
            "patch",
            "-p1",
            "--no-backup-if-mismatch",
            "--force",
            "-s",
            "-i",
            str(file),
        ]
        if just_check:
            cmd += ["--dry-run"]
        subprocess.check_output(cmd, cwd=cwd, encoding="utf-8")
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
        return False
    except Exception as ex:  # pylint: disable=broad-except
        _raise_error(str(ex))
        return False
    else:
        return True


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
    from .apply import _internal_apply

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


def remove_file_from_patch(files_to_exclude, patchfilecontent):
    if not patchfilecontent:
        return
    lines = patchfilecontent.split(b"\n")

    new_lines = []
    skip_lines = False

    for line in lines:
        line = line.decode("utf8")
        # Check if the line indicates the start of a new diff section
        if line.startswith("diff --git"):
            # Extract the file path from the diff line
            match = re.search(r"a/(.+) b/(.+)", line)
            if match:
                file_path = match.group(1)
                # Check if the file should be excluded
                if any(file_path.startswith(x) for x in files_to_exclude):
                    skip_lines = True
                else:
                    skip_lines = False

        # Only add lines if we're not skipping them
        if not skip_lines:
            new_lines.append(line)

    return b"\n".join(map(lambda x: x.encode("utf8"), new_lines))
