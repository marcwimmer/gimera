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

    # Fast path: no patch dirs configured and non-interactive → nothing to
    # save and nowhere to save it.  Skip the expensive git-status / prepare
    # dance entirely.
    if not repo_yml.patches and os.getenv("GIMERA_NON_INTERACTIVE") == "1":
        return

    # Fast path: if the directory is git-ignored, check for local modifications
    # before doing the expensive temp-repo dance. If no files changed on disk
    # compared to what's there, skip patch creation entirely.
    subrepo_path = main_repo.path / repo_yml.path
    if main_repo.check_ignore(repo_yml.path) and subrepo_path.exists():
        # For ignored dirs we cannot rely on git status. Instead we just skip
        # make_patches when running non-interactively, because the expensive
        # _if_ignored_move_to_separate_dir would create a full temp repo just
        # to discover there are no diffs.
        if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
            return

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
            if not _start_question(repo_yml, changed_files, main_repo=main_repo):
                return

            with _temporarily_add_untracked_files(main_repo, untracked_files):
                subdir_path = Path(main_repo.path) / repo_yml.path
                with main_repo.temporary_unignore(subdir_path):
                    patch_content = _technically_make_patch(main_repo, subdir_path)

                    if not repo_yml.patches:
                        if os.getenv("GIMERA_FORCE") == "1":
                            return
                        if os.getenv("GIMERA_NON_INTERACTIVE") != "1" and not is_temp_path:
                            repo_yml = _ask_user_to_create_path_directory(repo_yml)
                        if not repo_yml.patches:
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
    from .config import PatchDir

    repo_yml.config._store(repo_yml, {"patches": [PatchDir(repo_yml, path, None)]})
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

    also transfer the parent .gitignore file, so that e.g. pyc files are 
    ignored
    """
    from .cachedir import _get_cache_dir
    from .integrated import _update_integrated_module

    if (
        main_repo.check_ignore(repo_yml.path)
        and (main_repo.path / repo_yml.path).exists()
    ):
        with temppath() as path:
            subprocess.check_call(
                (git + ["init", "--initial-branch=main", "."]), cwd=path
            )
            Repo(path).X(*(git + ["commit", "-m", 'init', '--allow-empty']), output=True)
            main_repo2 = Repo(path)
            for patchdir in repo_yml.patches:
                dest_path = main_repo2.path / patchdir._path
                dest_path.mkdir(exist_ok=True, parents=True)
                patch_path = main_repo.path / patchdir._path
                if not patch_path.exists():
                    if os.getenv("GIMERA_NON_INTERACTIVE") != "1":
                        confirm(f"Path {patch_path} does not exist. Create?")
                        patch_path.mkdir(parents=True, exist_ok=True)
                rsync(main_repo.path / patchdir._path, dest_path)
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
                gitignore_file = main_repo.path / ".gitignore"
                if gitignore_file.exists():
                    shutil.copy(
                        gitignore_file,
                        path / ".gitignore",
                    )
                yield main_repo2, True

                for patchdir in repo_yml.patches:
                    rsync(main_repo2.path / patchdir._path, main_repo.path / patchdir._path)
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
        for x in repo_yml.patches
        if x.path_absolute == edit_patchfile.parent
    ][0]
    patch_filename = Path(repo_yml.edit_patchfile).name
    return patch_dir, patch_filename


def _get_new_patchfilename(repo_yml):
    patchdirs = repo_yml.patches
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


def _start_question(repo_yml, changed_files, main_repo=None):
    files_in_lines = "\n".join(map(str, sorted(changed_files)))
    if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
        correct = True
    else:
        choice_yes = "Yes - make a patch"
        if repo_yml.edit_patchfile:
            choice_yes = f"Merge all changes into patchfile {repo_yml.edit_patchfile}"

        for file in files_in_lines.splitlines():
            click.secho(f"  * {file}")

        while True:
            questions = [
                inquirer.List(
                    "correct",
                    message=f"Continue making patches for the lines above?",
                    default="no",
                    choices=[
                        choice_yes,
                        "Show diff",
                        "Abort",
                        "Ignore",
                    ],
                )
            ]
            answers = inquirer.prompt(questions, theme=inquirer_theme)
            correct = answers["correct"][0]
            if correct == "S" and main_repo:
                # Show diff --stat followed by full diff
                subdir_path = Path(main_repo.path) / repo_yml.path
                diff_stat = main_repo.out(
                    *(git + ["diff", "--stat", "--", str(subdir_path)]),
                    allow_error=True,
                )
                diff_full = main_repo.out(
                    *(git + ["diff", "--", str(subdir_path)]),
                    allow_error=True,
                )
                if diff_stat:
                    click.secho("\n--- diff --stat ---", fg="cyan")
                    click.echo(diff_stat)
                if diff_full:
                    click.secho("--- diff ---", fg="cyan")
                    click.echo(diff_full)
                    click.secho("--- end ---\n", fg="cyan")
                continue
            break

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
        (patch_dir.path_absolute / patch_filename).write_text(patch_content)

        # commit the patches - do NOT - could lie in submodule - is hard to do
        with main_repo.temporary_unignore(repo_yml.path):
            # make sure by that, that e.g. pyc files are ignored
            subprocess.check_call((git + ["add", repo_yml.path]), cwd=main_repo.path)
        subprocess.check_call((git + ["add", patch_dir._path]), cwd=main_repo.path)
        subprocess.check_call(
            (git + ["commit", "-m", f"added patch {patch_filename}", "--no-verify"]),
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
        repo.X(*(git + ["commit", "--no-verify", "-m", f"added patchfile: {patch_path}"]))
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
    repo.X(*(git + ["commit", "-m", "for patch", "--no-verify"]))

    # core.quotepath=false → non-ASCII filenames stay as readable UTF-8
    # instead of octal-escaped `"a/\303\274.txt"`, so the round-trip apply
    # (and human review) is cleaner.
    patch_content = Repo(path).out(
        *(git + ["-c", "core.quotepath=false", "format-patch", "HEAD~1",
                 "--stdout", "--relative"])
    )
    repo.X(*(git + ["reset", "HEAD~1"]))
    return patch_content


def _apply_patches(repo_yml):
    verbose(f"Applying patches for {repo_yml.path}")
    relevant_patch_files = set()
    for patchdir in repo_yml.patches:
        # with patchdir.path as dir:
        if not patchdir.path_absolute.exists():
            patchdir.path_absolute.mkdir(parents=True)
        for file in sorted(patchdir.path_absolute.rglob("*.patch")):
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


MAX_PATCH_STRIP_LEVEL = 4
# Sentinel: a patch deliberately rejected for safety (unsafe paths or a
# non-unified format). Distinct from None ("no strip level fit"), so the
# caller skips the -p1 diagnostic re-run and interactive prompt.
_PATCH_REFUSED = object()
# Never descended into when searching relocation candidates — huge and
# never legitimate patch targets.
PATCH_SEARCH_PRUNE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}


def _dry_run_patch(patch_file, cwd, strip):
    cmd = [
        "patch",
        f"-p{strip}",
        "--dry-run",
        "--force",
        "-s",
        "-i",
        str(patch_file),
    ]
    try:
        subprocess.check_output(
            cmd, cwd=cwd, encoding="utf-8", stderr=subprocess.STDOUT,
        )
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        _raise_error("the 'patch' binary is required but was not found")
        return False


def _unquote_git_path(raw):
    """Decode a git ``core.quotepath`` C-style quoted path.

    With its default config git wraps paths containing non-ASCII bytes in
    double quotes and octal-escapes the bytes, e.g. ``"a/\\303\\274.txt"``
    for ``a/ümlaut.txt``. `patch` understands this, so we must too — decode
    to the real path (rather than refusing it) and let the rest of the
    pipeline containment-check the *decoded* result. Returns `raw` unchanged
    if it is not a quoted path.
    """
    if raw is None or len(raw) < 2 or not (raw[0] == '"' and raw[-1] == '"'):
        return raw
    inner = raw[1:-1]
    simple = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13,
              '"': 34, "\\": 92}
    out = bytearray()
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
            elif nxt in "01234567":
                digits = ""
                j = 0
                while j < 3 and i + 1 + j < len(inner) and inner[i + 1 + j] in "01234567":
                    digits += inner[i + 1 + j]
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i += 1 + j
            else:
                out.append(ord(nxt))
                i += 2
        else:
            out.extend(c.encode("utf-8"))
            i += 1
    return out.decode("utf-8", errors="replace")


def _is_unsafe_patch_path(raw):
    """True if `raw` could write somewhere it must not.

    Decodes git-quoted paths first, then flags: absolute paths, empty paths,
    `..` components (incl. octal-escaped `\\056\\056`), anything writing into
    a `.git` directory (a `.git/hooks/...` write is remote code execution),
    and a still-leading quote left by malformed quoting.
    """
    if raw is None:
        return False
    raw = _unquote_git_path(raw)
    if raw.startswith('"'):  # malformed quoting we won't risk applying
        return True
    parts = Path(raw).parts
    return (
        Path(raw).is_absolute()
        or ".." in parts
        or ".git" in parts
        or not parts
    )


# git-diff header lines that carry a target path even when there is no
# unified `---`/`+++` body (renames, copies, mode changes, binary patches).
_GIT_HEADER_PREFIXES = (
    "diff --git ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _consume_hunk_body(lines, i, old_count, new_count):
    """Advance past one hunk's body, consuming exactly the number of old/new
    lines its `@@` header declared, so body lines that happen to start with
    `--- `/`+++ `/`@@ ` are never re-interpreted as file headers. Returns the
    index of the first line after the hunk body.
    """
    n = len(lines)
    while i < n and (old_count > 0 or new_count > 0):
        bl = lines[i]
        if bl.startswith("\\"):  # "\ No newline at end of file"
            i += 1
            continue
        if bl.startswith("-"):
            old_count -= 1
        elif bl.startswith("+"):
            new_count -= 1
        elif bl.startswith(" ") or bl == "":
            old_count -= 1
            new_count -= 1
        else:
            break  # malformed hunk — stop consuming
        i += 1
    return i


def _extract_patch_file_pairs(patch_file):
    """Parse `--- <old>` / `+++ <new>` header pairs from a unified diff.

    Returns a list of (old, new) tuples with the raw paths as written in
    the patch (`a/`/`b/` prefixes included); `/dev/null` becomes None
    (new file / deletion). Returns [] if no unified headers could be
    parsed (e.g. a rename-only, binary, context-diff or ed-script patch).

    The scan is hunk-aware: a `--- `/`+++ `/`@@ ` triple starts a file
    section, then each hunk's body is consumed exactly according to the
    line counts in its `@@ -a,b +c,d @@` header. Body lines are therefore
    never re-interpreted as headers — this is essential for zero-context
    (`git diff -U0`) diffs and for patches that themselves edit diff/patch
    files, where body lines can legitimately start with `--- `/`+++ `/`@@`.

    Security: if any referenced path — in a unified header *or* in a git
    `diff --git`/`rename`/`copy` line — is unsafe (see _is_unsafe_patch_path),
    return None. Callers must refuse such patches outright. Likewise a
    patch with no parseable unified header ([]) must not be blindly applied,
    since its targets cannot be containment-checked.
    """
    pairs = []
    try:
        content = Path(patch_file).read_text(errors="replace")
    except OSError:
        return pairs
    lines = content.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if (
            line.startswith("--- ")
            and i + 2 < n
            and lines[i + 1].startswith("+++ ")
            and _HUNK_RE.match(lines[i + 2])
        ):
            old = _unquote_git_path(line[4:].split("\t")[0].strip())
            new = _unquote_git_path(lines[i + 1][4:].split("\t")[0].strip())
            pairs.append(
                (
                    None if old == "/dev/null" else old,
                    None if new == "/dev/null" else new,
                )
            )
            i += 2  # land on the first @@ of this file section
            while i < n:
                m = _HUNK_RE.match(lines[i])
                if not m:
                    break
                old_count = int(m.group(1)) if m.group(1) is not None else 1
                new_count = int(m.group(2)) if m.group(2) is not None else 1
                i = _consume_hunk_body(lines, i + 1, old_count, new_count)
            continue
        i += 1
    # Refuse symlink-creating/-altering patches: `patch` would materialise a
    # symlink that could point out of the sub-repo (and get committed).
    if any(_is_symlink_mode_line(line) for line in lines):
        return None
    # Safety scan over both unified header paths and git rename/copy paths.
    for old, new in pairs:
        if _is_unsafe_patch_path(old) or _is_unsafe_patch_path(new):
            return None
    for token in _extract_git_header_paths(lines):
        if _is_unsafe_patch_path(token):
            return None
    return pairs


def _extract_git_header_paths(lines):
    """Paths carried by git `diff --git`/`rename`/`copy` header lines.

    A normal content patch repeats these in its `---`/`+++` pairs (so they
    are already containment-checked), but they are collected separately so a
    hand-crafted patch whose git header names a different (possibly symlinked)
    path than its unified header can still be containment-checked at apply.
    """
    paths = []
    for line in lines:
        for prefix in _GIT_HEADER_PREFIXES:
            if line.startswith(prefix):
                rest = line[len(prefix):].strip()
                # `diff --git a/x b/y` carries two paths; rename/copy one.
                paths.extend(_unquote_git_path(tok) for tok in rest.split())
    return paths


def _is_symlink_mode_line(line):
    """True for a git header line declaring symlink mode (120000) — a new,
    changed or indexed symlink."""
    s = line.strip()
    if not s.endswith("120000"):
        return False
    return (
        s.startswith("new file mode ")
        or s.startswith("old mode ")
        or s.startswith("new mode ")
        or s.startswith("deleted file mode ")
        or s.startswith("index ")
    )


def _effective_path(raw, strip, strict=False):
    """Path that `patch -p<strip>` resolves `raw` to.

    `patch` falls back to the basename when a name has fewer components
    than the strip level; strict=True returns None instead (used for
    relocation, where a bare basename would match far too much).
    """
    parts = Path(raw).parts
    if len(parts) <= strip:
        return None if strict else Path(parts[-1])
    return Path(*parts[strip:])


def _target_contained(cwd, eff):
    """True if `cwd/eff`, resolved through any symlinks, stays inside cwd.

    Guards against a patch whose header path traverses an in-tree symlink
    that points outside the sub-repo (`is_file()` alone would follow it).
    For a not-yet-existing file the existing parent portion is resolved,
    so an escaping parent symlink is still caught.
    """
    return bool(safe_relative_to((cwd / eff).resolve(), Path(cwd).resolve()))


def _strip_level_fits(pairs, cwd, strip, strict=False):
    """True if the patch headers are consistent with `-p<strip>` in cwd.

    `patch` picks, for each hunk, whichever of the `---`/`+++` names exists
    on disk, so a modification/rename pair fits when *either* side resolves
    to an existing file. Deletions need their source; new files anchor via
    their target's parent directory. EVERY resolved side — existing or not,
    e.g. a not-yet-created rename/new target — must stay inside cwd, so a
    destination reached through an in-tree symlink cannot escape. At least
    one pair must anchor, so a strip level never "fits" by vacuity.
    """
    cwd = Path(cwd)
    anchored = False
    for old, new in pairs:
        old_eff = (
            _effective_path(old, strip, strict=strict) if old is not None else None
        )
        new_eff = (
            _effective_path(new, strip, strict=strict) if new is not None else None
        )
        # Containment applies to both sides regardless of existence: `patch`
        # may write to the `+++`/rename destination, which need not exist yet.
        for eff in (old_eff, new_eff):
            if eff is not None and not _target_contained(cwd, eff):
                return False
        if old is not None and new is not None:
            # modification or rename: at least one side must exist on disk
            if not any(
                eff is not None and (cwd / eff).is_file()
                for eff in (old_eff, new_eff)
            ):
                return False
            anchored = True
        elif old is not None:
            # deletion: source must exist
            if old_eff is None or not (cwd / old_eff).is_file():
                return False
            anchored = True
        else:
            # new file: target's parent dir must exist
            if new_eff is None:
                return False
            if (cwd / new_eff).parent.is_dir():
                anchored = True
    return anchored


def _find_relocation_candidates(pairs, cwd, max_levels):
    """Find (strip, candidate_cwd) combos for a patch authored from a
    directory deeper than gimera's cwd (e.g. `odoo/odoo/`, not `odoo/`).

    Anchors on the names of every non-new-file pair (both `---` and `+++`
    sides, so rename patches whose only on-disk file is the target still
    anchor), walks the tree once (pruning .git/node_modules/... and never
    following symlinks) and keeps every directory whose layout matches ALL
    patch headers. Patches that only create files have no on-disk anchor and
    are not relocatable. Results are sorted (shallowest path first) so the
    choice is deterministic across filesystems.
    """
    # Anchor on the names of EVERY non-new-file pair (both `---`/`+++`
    # sides), not just the first: git orders sections alphabetically, so the
    # first pair can be a `/dev/null` new file whose name exists nowhere —
    # anchoring only on it would miss the existing files later in the patch.
    anchor_raws = []
    seen_raw = set()
    for old, new in pairs:
        if old is None:  # pure new file — no reliable on-disk anchor
            continue
        for raw in (old, new):
            if raw is not None and raw not in seen_raw:
                seen_raw.add(raw)
                anchor_raws.append(raw)
    if not anchor_raws:
        return []
    anchor_effectives = []
    seen_eff = set()
    for raw in anchor_raws:
        for p in range(1, max_levels + 1):
            eff = _effective_path(raw, p, strict=True)
            if eff is not None and (p, eff) not in seen_eff:
                seen_eff.add((p, eff))
                anchor_effectives.append((p, eff))
    candidates = []
    seen = set()
    for root, dirs, _files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in PATCH_SEARCH_PRUNE_DIRS]
        root = Path(root)
        for p, eff in anchor_effectives:
            if not (root / eff).is_file():
                continue
            candidate_cwd = root
            if candidate_cwd == cwd or (p, candidate_cwd) in seen:
                continue
            seen.add((p, candidate_cwd))
            # belt and braces: never relocate outside the requested cwd
            if not safe_relative_to(candidate_cwd.resolve(), cwd.resolve()):
                continue
            if _strip_level_fits(pairs, candidate_cwd, p, strict=True):
                candidates.append((p, candidate_cwd))
    candidates.sort(key=lambda c: (len(c[1].parts), str(c[1]), c[0]))
    return candidates


def _resolved_target_signature(pairs, cwd, strip):
    """Set of absolute files a patch would touch at (cwd, strip) — used to
    tell genuinely different targets apart from the same file reached via
    different strip/cwd combinations."""
    cwd = Path(cwd)
    targets = set()
    for old, new in pairs:
        for raw in (old, new):
            if raw is None:
                continue
            eff = _effective_path(raw, strip)
            if eff is not None:
                targets.add(str((cwd / eff).resolve()))
    return frozenset(targets)


def _find_working_patch_args(patch_file, cwd, max_levels=MAX_PATCH_STRIP_LEVEL):
    """Derive (strip_level, cwd) for a patch from its `---`/`+++` headers.

    Phase 1 — keep the requested cwd and pick the strip level whose
    resolved paths actually exist there (then confirm with one dry-run).
    Handles patches authored inside the sub-repo (`-p1`) as well as from
    the parent repo's root (sub-repo prefix in paths, `-p2`...).

    Phase 2 — if no level fits, the patch was likely authored from a
    directory deeper than gimera's cwd; relocate (see
    _find_relocation_candidates).

    Ambiguity (several levels/dirs match) is resolved deterministically —
    lowest level / shallowest dir — and reported loudly.

    Returns (strip_level, working_dir, pairs), None (no fit), or the
    _PATCH_REFUSED sentinel (deliberately rejected for safety).
    """
    cwd = Path(cwd)
    # Relocation runs `patch` in a different cwd, so the patch path must be
    # absolute or `-i <relative>` would silently fail there.
    patch_file = Path(patch_file).resolve()
    pairs = _extract_patch_file_pairs(patch_file)
    if pairs is None:
        # Unsafe content — absolute / `..` / `.git` paths, or a symlink-mode
        # hunk — that could write outside the sub-repo or into .git. Refuse.
        click.secho(
            f"Refusing patch {patch_file}: it references unsafe paths "
            "(absolute, '..', .git/) or creates a symlink.",
            fg="red",
        )
        return _PATCH_REFUSED
    if not pairs:
        # No parseable unified header → targets can't be enumerated and
        # containment-checked. Refuse rather than blindly run `patch -p1`,
        # which would honor `..`/symlinks in a context diff or ed script
        # and write outside the sub-repo.
        click.secho(
            f"Refusing patch {patch_file}: no unified-diff file headers "
            "found (context diffs, ed scripts and binary/rename-only "
            "patches are not auto-applied).",
            fg="red",
        )
        return _PATCH_REFUSED

    # One candidate level per distinct resolved target set — `patch`
    # collapses too-short names to their basename, so several -p levels can
    # touch the same files; only genuinely different targets are ambiguous.
    seen_targets = set()
    fitting = []
    for p in range(1, max_levels + 1):
        if not _strip_level_fits(pairs, cwd, p):
            continue
        sig = _resolved_target_signature(pairs, cwd, p)
        if sig in seen_targets:
            continue
        seen_targets.add(sig)
        if _dry_run_patch(patch_file, cwd, p):
            fitting.append(p)
    if fitting:
        verbose(f"{patch_file}: phase 1 fitting strip levels {fitting} in {cwd}")
        if len(fitting) > 1:
            click.secho(
                f"Warning: patch {patch_file} applies with several strip "
                f"levels ({', '.join(f'-p{p}' for p in fitting)}) resolving "
                f"to different files; using -p{fitting[0]}.",
                fg="yellow",
            )
        return (fitting[0], cwd, pairs)
    verbose(f"{patch_file}: no strip level fit in {cwd}, trying relocation")

    working = [
        (p, candidate_cwd)
        for p, candidate_cwd in _find_relocation_candidates(pairs, cwd, max_levels)
        if _dry_run_patch(patch_file, candidate_cwd, p)
    ]
    if not working:
        return None
    # Collapse combos that resolve to the same physical files — different
    # (strip, cwd) reaching one target is not real ambiguity.
    distinct = []
    seen_targets = set()
    for p, candidate_cwd in working:
        sig = _resolved_target_signature(pairs, candidate_cwd, p)
        if sig in seen_targets:
            continue
        seen_targets.add(sig)
        distinct.append((p, candidate_cwd))
    verbose(f"{patch_file}: phase 2 relocation candidates {distinct}")
    if len(distinct) > 1:
        alternatives = ", ".join(f"-p{p} in {c}" for p, c in distinct[1:])
        click.secho(
            f"Warning: patch {patch_file} matches several directories; "
            f"using -p{distinct[0][0]} in {distinct[0][1]} "
            f"(also possible: {alternatives}).",
            fg="yellow",
        )
    strip, real_cwd = distinct[0]
    return (strip, real_cwd, pairs)


def _report_patch_failure(file, output, error_ok, headline):
    click.secho(f"\n\n{headline}\n\n", fg="yellow")
    click.secho(
        (
            f"{file}\n"
            "============================================================================================="
        ),
        fg="red",
        bold=True,
    )
    if output:
        click.secho(f"{output}\n", fg="yellow")
    click.secho(file.read_text(), fg="cyan")
    if os.getenv("GIMERA_NON_INTERACTIVE") == "1" or not inquirer.confirm(
        f"Patchfile failed ''{file}'' - continue with next file?",
        default=True,
    ):
        if not error_ok:
            _raise_error(f"Error applying patch: {file}")
    return False


def _apply_patchfile(file, working_dir, error_ok=False):
    verbose(f"Applying patchfile {file} in working dir {working_dir}")
    cwd = Path(working_dir)
    # Reversed / already-applied patches fail every `--dry-run` probe in
    # _find_working_patch_args and land in the failure path below — no
    # "Assume -R?" smartness; we force defined state over such behaviours.
    file = Path(file).resolve()
    args = _find_working_patch_args(file, cwd)
    if args is _PATCH_REFUSED:
        # Already reported with a specific reason; don't re-run patch on
        # deliberately rejected (possibly malicious) input or prompt.
        if not error_ok:
            _raise_error(f"Error applying patch: {file}")
        return False
    if args is None:
        # Re-run the plain -p1 dry-run only to harvest diagnostics for the
        # user; the failure is reported regardless of its exit code.
        proc = subprocess.run(
            ["patch", "-p1", "--dry-run", "--force", "-i", str(file)],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
        )
        output = "\n".join(filter(None, [proc.stdout, proc.stderr]))
        return _report_patch_failure(
            file,
            output,
            error_ok,
            f"Failed to apply patch — tried -p1..-p{MAX_PATCH_STRIP_LEVEL} "
            "and relocated cwds, none matched:",
        )
    strip, real_cwd, pairs = args
    # Defense in depth, right before the write. Two things the selection did
    # not fully guarantee at write time:
    #   * re-run _strip_level_fits to catch a TOCTOU change on disk between
    #     selection and the write (selection already validated `pairs`);
    #   * containment-check the git `diff --git`/rename/copy header paths,
    #     which selection never inspected, in case the running `patch`
    #     prefers them over the `---`/`+++` names (GNU patch can).
    patch_lines = file.read_text(errors="replace").splitlines()
    git_targets = _extract_git_header_paths(patch_lines)
    git_effs = [_effective_path(raw, strip) for raw in git_targets]
    if any(line.startswith("rename from ") for line in patch_lines):
        # `patch` ignores git rename headers: it edits the existing source
        # in place and never creates the renamed target. Warn so a silent
        # "Applied" is not mistaken for a completed rename.
        click.secho(
            f"Warning: patch {file} contains a git rename; `patch` applies "
            "the content change but does not rename the file.",
            fg="yellow",
        )
    if not _strip_level_fits(pairs, real_cwd, strip) or any(
        not _target_contained(real_cwd, eff) for eff in git_effs
    ):
        click.secho(
            f"Refusing patch {file}: target would escape the working "
            "directory.",
            fg="red",
        )
        if not error_ok:
            _raise_error(f"Error applying patch: {file}")
        return False
    try:
        cmd = [
            "patch",
            f"-p{strip}",
            "--no-backup-if-mismatch",
            "--force",
            "-s",
            "-i",
            str(file),
        ]
        subprocess.check_output(
            cmd, cwd=real_cwd, encoding="utf-8", stderr=subprocess.STDOUT
        )
        if real_cwd != cwd:
            rel = safe_relative_to(real_cwd, cwd)
            suffix = f"-p{strip}, cwd=./{rel}" if rel else f"-p{strip}, cwd={real_cwd}"
            click.secho(
                f"Note: patch {file} was applied in a relocated working "
                f"directory ({suffix}).",
                fg="yellow",
            )
        else:
            suffix = f"-p{strip}"
        click.secho(
            (f"Applied patch {file} ({suffix})"),
            fg="blue",
        )
    except subprocess.CalledProcessError as ex:
        output = "\n".join(filter(None, [ex.stdout, ex.stderr]))
        return _report_patch_failure(
            file, output, error_ok, "Failed to apply the following patch file:"
        )
    except Exception as ex:  # pylint: disable=broad-except
        _raise_error(str(ex))
        return False
    else:
        return True


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
                patches = repo.patches
                if not patches:
                    continue
                for patchdir in patches:
                    path = patchdir.path_absolute
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
        for patchdir in repo.patches:
            if not patchdir.path_absolute.exists():
                continue
            for file in patchdir.path_absolute.glob("*.patch"):
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
