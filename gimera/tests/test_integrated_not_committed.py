"""Integrated repos that must stay out of the parent repository.

odoo.sh style projects gitignore paths like ``odoo/enterprise``: the files have
to be on disk to run the project, but they must never be committed into the
project repository.

Three states are worth pinning down, and they differ in one thing only -
whether the parent repository tracks the path already:

1. gitignored and untracked - nothing gets committed, no flag needed. This
   worked before by accident: ``git status --porcelain`` does not list ignored
   files, so the ``git add`` at the end of ``_update_integrated_module`` was
   never reached. The decision is now taken explicitly, once, up front.

2. tracked *and* matched by an ignore rule - keeps being committed. That is
   deliberate: ``git check-ignore`` is asked with the index, which reports a
   tracked path as not ignored. A repository that vendors a directory today
   must not silently stop receiving updates because somebody adds a matching
   ignore rule; the copy in the repository would rot and nothing would say why.

3. tracked, but the user asked for it to stop - ``dont_commit: true``. This is
   the case the flag exists for, and the case the original proposal did not
   actually cover: it only guarded the final ``git add``, while
   ``commit_dir_if_dirty(..., force=True)`` earlier in the run had already
   staged the content with ``git add -f`` and committed it.
"""

from .fixtures import *  # required for all
import os
import subprocess
import yaml
from pathlib import Path

from .tools import gimera_apply
from .tools import _make_remote_repo
from ..consts import gitcmd as git


def _make_workspace(temppath, name, gitignore, dont_commit=False):
    """A main repo with one integrated repo at odoo/enterprise."""
    workspace = temppath / name
    workspace.mkdir(parents=True)

    remote_main_repo = _make_remote_repo(temppath / f"{name}_mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / f"{name}_sub")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    (workspace / ".gitignore").write_text(gitignore)
    repo = {
        "url": f"file://{remote_sub_repo}",
        "branch": "branch1",
        "path": "odoo/enterprise",
        "type": "integrated",
    }
    if dont_commit:
        repo["dont_commit"] = True
    (workspace / "gimera.yml").write_text(
        yaml.dump({"repos": [repo]}, default_flow_style=False)
    )
    subprocess.check_call(git + ["add", ".gitignore", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-m", "setup"], cwd=workspace)
    return workspace


def _tracked(workspace, path):
    return subprocess.check_output(
        git + ["ls-files", path], cwd=workspace, encoding="utf8"
    ).strip()


def test_gitignored_integrated_repo_is_not_committed(temppath):
    """Case 1: gitignored and untracked - pulled, but not put into the repo."""
    workspace = _make_workspace(
        temppath, "ws_ignored", gitignore="/odoo/enterprise/\n"
    )

    os.chdir(workspace)
    gimera_apply([], update=None)

    # the files are there ...
    assert (workspace / "odoo" / "enterprise" / "file1.txt").exists()
    # ... but the parent repo knows nothing about them
    assert not _tracked(workspace, "odoo")
    # and nothing is left staged behind either
    assert not subprocess.check_output(
        git + ["diff", "--cached", "--name-only"], cwd=workspace, encoding="utf8"
    ).strip()

    # the sha however must have been written and committed
    config = yaml.safe_load((workspace / "gimera.yml").read_text())
    assert config["repos"][0]["sha"]
    assert "gimera.yml" not in subprocess.check_output(
        git + ["status", "--porcelain"], cwd=workspace, encoding="utf8"
    )


def test_tracked_path_keeps_being_committed_despite_gitignore(temppath):
    """Case 2: an ignore rule must not silently orphan an already tracked path."""
    workspace = _make_workspace(
        temppath, "ws_tracked", gitignore="/odoo/enterprise/\n"
    )

    # somebody vendored the directory before the ignore rule existed
    dest = workspace / "odoo" / "enterprise"
    dest.mkdir(parents=True)
    (dest / "file1.txt").write_text("vendored by hand")
    subprocess.check_call(git + ["add", "-f", "odoo/enterprise"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-m", "vendored earlier"], cwd=workspace)

    os.chdir(workspace)
    gimera_apply([], update=None)

    assert (dest / "file1.txt").read_text() == "random repo on branch1"
    assert _tracked(workspace, "odoo/enterprise/file1.txt")
    # the update landed in a commit, not in the working tree
    assert not subprocess.check_output(
        git + ["status", "--porcelain", "odoo"], cwd=workspace, encoding="utf8"
    ).strip()


def test_dont_commit_keeps_tracked_path_out_of_new_commits(temppath):
    """Case 3: dont_commit wins over "it is tracked already"."""
    workspace = _make_workspace(
        temppath,
        "ws_dont_commit",
        gitignore="/odoo/enterprise/\n",
        dont_commit=True,
    )

    dest = workspace / "odoo" / "enterprise"
    dest.mkdir(parents=True)
    (dest / "file1.txt").write_text("vendored by hand")
    subprocess.check_call(git + ["add", "-f", "odoo/enterprise"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-m", "vendored earlier"], cwd=workspace)
    head_before = subprocess.check_output(
        git + ["rev-parse", "HEAD:odoo/enterprise/file1.txt"],
        cwd=workspace,
        encoding="utf8",
    ).strip()

    os.chdir(workspace)
    gimera_apply([], update=None)

    # content updated on disk
    assert (dest / "file1.txt").read_text() == "random repo on branch1"
    # but the committed blob is untouched: this is what the original proposal
    # did not achieve, commit_dir_if_dirty(force=True) committed it anyway
    head_after = subprocess.check_output(
        git + ["rev-parse", "HEAD:odoo/enterprise/file1.txt"],
        cwd=workspace,
        encoding="utf8",
    ).strip()
    assert head_before == head_after
    # and gimera left nothing staged of it
    assert not subprocess.check_output(
        git + ["diff", "--cached", "--name-only", "--", "odoo"],
        cwd=workspace,
        encoding="utf8",
    ).strip()


def test_dont_commit_rejected_for_submodules(temppath):
    """A submodule without its gitlink is not a submodule - say so."""
    workspace = temppath / "ws_submodule"
    workspace.mkdir(parents=True)
    remote_main_repo = _make_remote_repo(temppath / "ws_submodule_mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "ws_submodule_sub")
    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    (workspace / "gimera.yml").write_text(
        yaml.dump(
            {
                "repos": [
                    {
                        "url": f"file://{remote_sub_repo}",
                        "branch": "branch1",
                        "path": "sub/sub1",
                        "type": "submodule",
                        "dont_commit": True,
                    }
                ]
            },
            default_flow_style=False,
        )
    )
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-m", "setup"], cwd=workspace)

    os.chdir(workspace)
    with pytest.raises(Exception, match="dont_commit"):
        gimera_apply([], update=None)
