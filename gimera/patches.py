import os
import shutil
import sys
import subprocess
import click
from .repo import Repo
from datetime import datetime
from contextlib import contextmanager
from .tools import confirm
from .tools import temppath
from .tools import path1inpath2
from .consts import inquirer_theme
from .tools import (
    _raise_error,
    safe_relative_to,
    is_empty_dir,
    _strip_paths,
    temppath,
    rsync,
    wait_git_lock,
)
import inquirer
from pathlib import Path
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB


def make_patches(working_dir, main_repo, repo_yml):
    if repo_yml.type != REPO_TYPE_INT:
        raise NotImplementedError(repo_yml.type)

    with _if_ignored_move_to_separate_dir(working_dir, main_repo, repo_yml) as (main_repo):
        with _prepare(main_repo, repo_yml) as (
            subrepo,
            subrepo_path,
            changed_files,
            untracked_files,
        ):
            if not changed_files:
                return
            if not _start_question(repo_yml, changed_files):
                return

            with _temporarily_add_untracked_files(main_repo, untracked_files):
                subdir_path = Path(main_repo.path) / repo_yml.path
                patch_content = _technically_make_patch(main_repo, subdir_path)

                if not repo_yml.all_patch_dirs(rel_or_abs="relative"):
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


@contextmanager
def _temporarily_move_gimera(repo_yml, to_path):
    remember_config_path = repo_yml.config.config_file
    repo_yml.config.config_file = to_path / "gimera.yml"
    repo_yml.config.config_file.parent.mkdir(exist_ok=True, parents=True)
    shutil.copy(remember_config_path, repo_yml.config.config_file)

    yield

    repo_yml.config.config_file = remember_config_path


@contextmanager
def _if_ignored_move_to_separate_dir(working_dir, main_repo, repo_yml):
    """
    If directory is ignored then move to temporary path.
    Apply changes from local dir to get the diffs.
    """
    from .gimera import _get_cache_dir
    from .gimera import _update_integrated_module

    if (
        main_repo.check_ignore(repo_yml.path)
        and (main_repo.path / repo_yml.path).exists()
    ):
        # TODO perhaps faster when just copied .git into the hidden dir
        with temppath() as path:
            subprocess.check_call(
                ["git", "init", "--initial-branch=main", "."], cwd=path
            )
            main_repo2 = Repo(path)
            for patchdir in repo_yml.patches:
                dest_path = main_repo2.path / patchdir
                dest_path.mkdir(exist_ok=True, parents=True)
                rsync(main_repo.path / patchdir, dest_path)
            main_repo2.simple_commit_all()
            with _temporarily_move_gimera(repo_yml, main_repo2.path):
                _update_integrated_module(
                    main_repo2.path,
                    main_repo2, repo_yml, update=False, parallel_safe=True
                )
                main_repo2.simple_commit_all()

                # now transfer the latest changes:
                rsync(
                    main_repo.path / repo_yml.path,
                    path / repo_yml.path,
                    exclude=[".git"],
                )
                yield main_repo2

                for patchdir in repo_yml.patches:
                    rsync(main_repo2.path / patchdir, main_repo.path / patchdir)
    else:
        yield main_repo


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
    if path1inpath2(patch_dir._path, subrepo.path):
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
        subprocess.check_call(["git", "add", repo_yml.path], cwd=main_repo.path)
        subprocess.check_call(["git", "add", patch_dir._path], cwd=main_repo.path)
        subprocess.check_call(
            ["git", "commit", "-m", f"added patch {patch_filename}"],
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
        repo.X("git", "add", "-N", untracked_file)

    yield

    for to_reset in untracked_files:
        repo.X("git", "reset", to_reset)


@contextmanager
def _prepare(main_repo, repo_yml):
    subrepo_path = main_repo.path / repo_yml.path
    if not subrepo_path.exists():
        yield None, None, [], []
    else:
        subrepo = main_repo.get_submodule(repo_yml.path, force=True)
        if subrepo.path.exists():
            changed_files = subrepo.filterout_submodules(subrepo.all_dirty_files)
            untracked_files = subrepo.filterout_submodules(subrepo.untracked_files)
        else:
            changed_files, untracked_files = [], []
        yield subrepo, subrepo_path, changed_files, untracked_files


def _clone_directory_and_add_patch_file(
    main_repo, repo_yml, branch, repo_url, patch_path, content
):
    from .gimera import _fetch_and_reset_branch, _get_cache_dir

    with temppath() as path:
        path = path / "repo"
        subprocess.check_call(["git", "clone", repo_url, path])
        repo = Repo(path)
        repo.X("git", "checkout", branch)
        patch_path = path / patch_path
        assert patch_path.relative_to(path)
        patch_path.parent.mkdir(exist_ok=True, parents=True)
        patch_path.write_text(content)
        repo.X("git", "add", patch_path.relative_to(path))
        repo.X("git", "commit", "-m", f"added patchfile: {patch_path}")
        repo.X("git", "push")
        # also make sure that local cache is updated, because
        # latest repo version is applied to project
        local_repo_dir = _get_cache_dir(main_repo, repo_yml)
        with wait_git_lock(local_repo_dir):
            repo = Repo(local_repo_dir)
            _fetch_and_reset_branch(repo, repo_yml)
        return repo.hex


def _technically_make_patch(repo, path):
    repo.X("git", "add", path)
    repo.X("git", "commit", "-m", "for patch")

    patch_content = Repo(path).out(
        "git", "format-patch", "HEAD~1", "--stdout", "--relative"
    )
    repo.X("git", "reset", "HEAD~1")
    return patch_content


def _apply_patches(repo_yml):
    for patchdir in repo_yml.all_patch_dirs(rel_or_abs="absolute") or []:
        # with patchdir.path as dir:
        if not patchdir._path.exists():
            patchdir._path.mkdir(parents=True)
        relevant_patch_files = []
        for file in sorted(patchdir._path.rglob("*.patch")):
            if repo_yml.ignore_patchfile(file):
                continue
            relevant_patch_files.append(file)

        problems = []
        for file in relevant_patch_files:
            click.secho((f"Checking patch {file}"), fg="blue")
            # Git apply fails silently if applied within local repos
            if not _apply_patchfile(
                file, patchdir.apply_from_here_dir, error_ok=False, just_check=True
            ):
                problems.append(file)

        if problems:
            click.secho("Error at following patchfiles", fg="red")
            for file in problems:
                click.secho(f"{file}", fg="red")
            sys.exit(-1)

        for file in relevant_patch_files:
            click.secho((f"Applying patch {file}"), fg="blue")
            # Git apply fails silently if applied within local repos
            _apply_patchfile(file, patchdir.apply_from_here_dir, error_ok=False)


def _apply_patchfile(file, working_dir, error_ok=False, just_check=False):
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
