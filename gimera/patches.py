import os
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
from .tools import _raise_error, safe_relative_to, is_empty_dir, _strip_paths
import inquirer
from pathlib import Path
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB


def make_patches(main_repo, repo_yml):
    with _make_patches_prepare(main_repo, repo_yml) as (
        subrepo,
        subrepo_path,
        changed_files,
        untracked_files,
    ):
        if not changed_files:
            return
        if not _make_patch_start_question(repo_yml, changed_files):
            return

        if repo_yml.type == REPO_TYPE_INT:
            cwd = main_repo.working_dir
        else:
            raise NotImplementedError(repo_yml.type)
        repo = Repo(cwd)
        with _make_patch_reset_untracked_files(main_repo, repo, untracked_files):
            subdir_path = Path(main_repo.working_dir) / repo_yml.path
            patch_content = _technically_make_patch(repo, subdir_path)

            if not repo_yml.all_patch_dirs(rel_or_abs="relative"):
                _raise_error(
                    "Please define at least one directory, "
                    f"where patches are stored for {repo_yml.path}"
                )

            with _make_patch_prepare_patchdir(repo_yml) as (patch_dir, patch_filename):
                _make_patch_write_patch_content(
                    main_repo,
                    repo_yml,
                    subrepo,
                    subrepo_path,
                    patch_dir,
                    patch_filename,
                    patch_content,
                )


def _make_patch_update_edited_patchfile(repo_yml):
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


def _make_patch_get_new_patchfilename(repo_yml):
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
def _make_patch_prepare_patchdir(repo_yml):
    remove_edit_patchfile = False
    if repo_yml.edit_patchfile:
        patch_dir, patch_filename = _make_patch_update_edited_patchfile(repo_yml)
        remove_edit_patchfile = True
    else:
        patch_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
        patch_dir = _make_patch_get_new_patchfilename(repo_yml)

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


def _make_patch_start_question(repo_yml, changed_files):
    files_in_lines = "\n".join(map(str, sorted(changed_files)))
    if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
        correct = True
    else:
        choice_yes = "Yes - make a patch"
        if repo_yml.edit_patchfile:
            choice_yes = f"Merge all changes into patchfile {repo_yml.edit_patchfile}"
        questions = [
            inquirer.List(
                "correct",
                message=f"Continue making patches for: {files_in_lines}",
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


def _make_patch_write_patch_content(
    main_repo, repo_yml, subrepo, subrepo_path, patch_dir, patch_filename, patch_content
):
    if path1inpath2(patch_dir._path, subrepo.path):
        # case: patch must be put within patches folder of the integrated module
        # so it must be uploaded via a temp path; and the latest version must be
        # pulled

        hex = _clone_directory_and_add_patch_file(
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
        subprocess.check_call(["git", "add", repo_yml.path], cwd=main_repo.working_dir)
        subprocess.check_call(
            ["git", "add", patch_dir._path], cwd=main_repo.working_dir
        )
        subprocess.check_call(
            ["git", "commit", "-m", f"added patch {patch_filename}"],
            cwd=main_repo.working_dir,
        )


@contextmanager
def _make_patch_reset_untracked_files(main_repo, repo, untracked_files):
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
        main_repo.X("git", "reset", to_reset)


@contextmanager
def _make_patches_prepare(main_repo, repo_yml):
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


def _clone_directory_and_add_patch_file(branch, repo_url, patch_path, content):
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
        return repo.hex


def _technically_make_patch(repo, path):
    repo.X("git", "add", path)
    repo.X("git", "commit", "-m", "for patch")

    patch_content = Repo(path).out(
        "git", "format-patch", "HEAD~1", "--stdout", "--relative"
    )
    repo.X("git", "reset", "HEAD~1")
    return patch_content
