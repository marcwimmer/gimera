from .fixtures import * # required for all
import pytest
import uuid
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
import click
import inspect
import os
from pathlib import Path
from .tools import gimera_apply
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git


def test_commit(temppath, monkeypatch):
    """
    Standard case: the integrated path is tracked in the main repo.
    (For the gitignored path see test_commit_gitignored_path.)
    """
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    monkeypatch.setenv("GIMERA_NON_INTERACTIVE", "1")

    # region gimera config
    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "sub1",
                "type": "integrated",
            },
        ]
    }
    # endregion

    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    (workspace / "main.txt").write_text("main repo")
    subprocess.check_call(git + ["add", "main.txt"], cwd=workspace)
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)
    monkeypatch.chdir(workspace)
    gimera_apply([], None)
    Repo(workspace).simple_commit_all()
    assert not Repo(workspace).staged_files

    click.secho(
        "Now we have a repo with integrated and gitignored sub"
        "\nWe change something and check if a patch is made."
    )
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")

    gimera_apply([], update=False)

    (workspace / "sub1" / "file2.txt").write_text("a new file!")

    gimera_commit("sub1", "branch1", "i committed", False)
    monkeypatch.setenv("GIMERA_FORCE", "1")
    os.unlink(workspace / "sub1" / "file2.txt")
    subprocess.check_output(git + ["checkout", "sub1/file1.txt"])
    monkeypatch.setenv("GIMERA_NON_THREADED", "1")
    gimera_apply([], update=True)
    assert (
        workspace / "sub1" / "file2.txt"
    ).exists(), "sub1/file2.txt should now exist"

    # failed patch handling
    file1 = workspace / "sub1" / "file1.txt"
    file1.write_text("main\na change!")
    gimera_commit("sub1", "branch1", "i committed", False)
    subprocess.check_output(git + ["checkout", "sub1/file1.txt"])
    gimera_apply([], update=True)
    assert "a change!" in (workspace / "sub1" / "file1.txt").read_text()


def _setup_ignored_integrated_workspace(temppath, monkeypatch):
    """Workspace with an integrated sub1 that is gitignored in the main repo
    (the zync situation) — applied and ready for local modifications."""
    workspace = temppath / "workspace"

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    monkeypatch.setenv("GIMERA_NON_INTERACTIVE", "1")
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")

    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub_repo}",
                "branch": "branch1",
                "path": "sub1",
                "type": "integrated",
            },
        ]
    }
    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    (workspace / ".gitignore").write_text("/sub1\n")
    subprocess.check_call(git + ["add", "."], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)
    monkeypatch.chdir(workspace)
    gimera_apply([], None)
    return workspace, remote_sub_repo


def test_commit_gitignored_path(temppath, monkeypatch):
    """
    The integrated path is gitignored in the main repo (never tracked there).
    gimera commit must build the patch against the upstream state, not the
    main repo's index — previously this crashed because `git add` refuses
    ignored paths (or, for untracked paths, produced unappliable
    whole-file-is-new patches).
    """
    workspace, remote_sub_repo = _setup_ignored_integrated_workspace(
        temppath, monkeypatch
    )

    # sub1 must not be tracked in the main repo
    tracked = subprocess.check_output(
        git + ["ls-files", "--", "sub1"], cwd=workspace, encoding="utf8"
    )
    assert not tracked.strip()

    # change a tracked file and add a new one inside the ignored dir
    (workspace / "sub1" / "file1.txt").write_text(
        "random repo on branch1\na local fix!"
    )
    (workspace / "sub1" / "file_new.txt").write_text("brand new")

    gimera_commit("sub1", "branch1", "fix from main repo", False)

    # upstream must now contain exactly those changes — full equality, so a
    # wrong-diff-base whole-file patch (clobbering the original first line)
    # would be caught
    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert (
            subpath / "file1.txt"
        ).read_text() == "random repo on branch1\na local fix!"
        assert (subpath / "file_new.txt").read_text() == "brand new"
        log = subprocess.check_output(
            git + ["log", "-1", "--format=%s"], cwd=subpath, encoding="utf8"
        )
        assert log.strip() == "fix from main repo"

    # round 2: pull the new upstream state, then commit a file DELETION —
    # rsync into the temp repo must run with --delete so removals are part
    # of the patch
    gimera_apply([], update=True)
    assert (workspace / "sub1" / "file_new.txt").exists()
    (workspace / "sub1" / "file_new.txt").unlink()

    gimera_commit("sub1", "branch1", "remove file_new", False)

    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert not (subpath / "file_new.txt").exists()
        assert (
            subpath / "file1.txt"
        ).read_text() == "random repo on branch1\na local fix!"


def test_commit_untracked_not_ignored_path(temppath, monkeypatch):
    """
    The integrated path exists in the workspace but is neither tracked nor
    gitignored (e.g. the ignore entry was removed after apply). Previously
    `git add` recorded every file as new (diff base = main repo index), which
    produced unappliable whole-file-is-new patches. The untracked branch of
    _needs_separate_dir must route this through the temp repo, too.
    """
    workspace, remote_sub_repo = _setup_ignored_integrated_workspace(
        temppath, monkeypatch
    )

    # drop the ignore entry — sub1 is now untracked but NOT ignored
    (workspace / ".gitignore").write_text("")
    subprocess.check_call(git + ["commit", "-am", "unignore sub1"], cwd=workspace)
    tracked = subprocess.check_output(
        git + ["ls-files", "--", "sub1"], cwd=workspace, encoding="utf8"
    )
    assert not tracked.strip()
    rc = subprocess.run(
        git + ["check-ignore", "-q", "sub1"], cwd=workspace
    ).returncode
    assert rc != 0, "sub1 must not be ignored in this scenario"

    # modification only — exactly the case where a whole-file-is-new patch
    # cannot apply upstream
    (workspace / "sub1" / "file1.txt").write_text(
        "random repo on branch1\na local fix!"
    )

    gimera_commit("sub1", "branch1", "fix from main repo", False)

    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert (
            subpath / "file1.txt"
        ).read_text() == "random repo on branch1\na local fix!"


def test_commit_preview(temppath, monkeypatch):
    """
    preview=True shows the staged diff and asks for confirmation:
    declining must not push anything, accepting must commit and push.
    """
    import gimera.commit as commit_module

    workspace, remote_sub_repo = _setup_ignored_integrated_workspace(
        temppath, monkeypatch
    )

    (workspace / "sub1" / "file1.txt").write_text(
        "random repo on branch1\na local fix!"
    )

    # decline → upstream must stay untouched
    monkeypatch.setattr(
        commit_module.inquirer, "confirm", lambda *a, **kw: False
    )
    gimera_commit("sub1", "branch1", "declined", True)
    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert (subpath / "file1.txt").read_text() == "random repo on branch1"

    # accept → change lands upstream
    monkeypatch.setattr(
        commit_module.inquirer, "confirm", lambda *a, **kw: True
    )
    gimera_commit("sub1", "branch1", "accepted", True)
    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert (
            subpath / "file1.txt"
        ).read_text() == "random repo on branch1\na local fix!"
        log = subprocess.check_output(
            git + ["log", "-1", "--format=%s"], cwd=subpath, encoding="utf8"
        )
        assert log.strip() == "accepted"


def test_commit_to_other_branch(temppath, monkeypatch):
    """
    Committing to a branch other than the configured one: the patch base is
    the locally applied state (configured branch). A clean delta (new file)
    applies; a conflicting modification must fail hard instead of pushing a
    wrong tree.
    """
    workspace, remote_sub_repo = _setup_ignored_integrated_workspace(
        temppath, monkeypatch
    )

    # a new file applies cleanly onto 'main' even though file1 differs there
    (workspace / "sub1" / "file_new.txt").write_text("brand new")
    gimera_commit("sub1", "main", "new file to main", False)
    with clone_and_commit(remote_sub_repo, "main", commit=False) as subpath:
        assert (subpath / "file_new.txt").read_text() == "brand new"
        assert (subpath / "file1.txt").read_text() == "random repo on main"
    # the configured branch must be untouched
    with clone_and_commit(remote_sub_repo, "branch1", commit=False) as subpath:
        assert not (subpath / "file_new.txt").exists()

    # a modification based on branch1 content conflicts on main → hard error
    (workspace / "sub1" / "file_new.txt").unlink()
    (workspace / "sub1" / "file1.txt").write_text(
        "random repo on branch1\nconflicting fix!"
    )
    with pytest.raises(Exception, match="Error applying patch"):
        gimera_commit("sub1", "main", "conflict", False)
    # nothing must have been pushed
    with clone_and_commit(remote_sub_repo, "main", commit=False) as subpath:
        assert (subpath / "file1.txt").read_text() == "random repo on main"
