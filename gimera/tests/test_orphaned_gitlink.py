"""
Reproduce crashes and stuck states when a submodule→integrated conversion
is interrupted, leaving the index/working tree inconsistent.

Two scenarios:

1. **Orphaned gitlink** — a gitlink (160000) exists in the index but
   .gitmodules has no matching entry.  `git submodule status` fails with
   exit 128: ``fatal: no submodule mapping found in .gitmodules for path '...'``

2. **Leftover staged files** — a previous conversion staged the gitlink
   deletion + new files but never committed.  On the next run
   `force_remove_submodule` refuses to proceed (``please_no_staged_files``)
   and `make_patches` asks the user about "changes" that aren't theirs.

gimera must recover from both states and complete the conversion.
"""
from .fixtures import *  # required for all
import yaml
from ..repo import Repo
import os
import subprocess
from pathlib import Path
from .tools import gimera_apply, _make_remote_repo
from ..consts import gitcmd as git


def _setup_submodule_repo(temppath):
    """Create a main repo with one submodule managed by gimera."""
    os.chdir(temppath)  # ensure cwd exists (previous test may have deleted its temppath)
    workspace = temppath / "workspace"

    remote_main = _make_remote_repo(temppath / "mainrepo")
    remote_sub = _make_remote_repo(temppath / "sub1")

    subprocess.check_call(
        git + ["clone", f"file://{remote_main}", str(workspace)],
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    repos = {
        "repos": [
            {
                "url": f"file://{remote_sub}",
                "branch": "branch1",
                "path": "integrated/sub1",
                "patches": [],
                "type": "submodule",
            },
        ]
    }
    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-am", "add gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["push"], cwd=workspace)

    os.chdir(workspace)
    gimera_apply([], None)

    # Verify we now have a submodule
    output = subprocess.check_output(
        git + ["ls-files", "--stage", "integrated/sub1"],
        cwd=workspace, text=True,
    )
    assert output.startswith("160000"), "Expected a gitlink (submodule) in the index"
    subprocess.check_call(git + ["push"], cwd=workspace)

    return workspace, repos, remote_sub


def _assert_integrated(workspace):
    """Verify the path is now integrated (regular files, no gitlink)."""
    assert (workspace / "integrated" / "sub1" / "file1.txt").exists()
    output = subprocess.check_output(
        git + ["ls-files", "--stage", "integrated/sub1"],
        cwd=workspace, text=True,
    )
    assert not output.startswith("160000"), \
        "Gitlink should be gone after conversion to integrated"


def test_apply_with_orphaned_gitlink(temppath):
    """
    Scenario 1: gitlink in index but .gitmodules entry missing.

    Simulates an interrupted conversion where .gitmodules was edited
    and committed but the gitlink was never removed from the index.
    """
    workspace, repos, remote_sub = _setup_submodule_repo(temppath)

    # Switch gimera.yml to integrated
    repos["repos"][0]["type"] = "integrated"
    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)

    # Remove only the .gitmodules entry, keep the gitlink in the index
    (workspace / ".gitmodules").write_text("")
    subprocess.check_call(git + ["add", ".gitmodules"], cwd=workspace)
    subprocess.check_call(
        git + ["commit", "-m", "broken: gitlink without .gitmodules entry"],
        cwd=workspace,
    )
    subprocess.check_call(git + ["push"], cwd=workspace)

    # Confirm the broken state
    result = subprocess.run(
        git + ["submodule", "status"],
        cwd=workspace, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "no submodule mapping found" in result.stderr

    # gimera must recover
    os.chdir(workspace)
    gimera_apply([], update=True)
    _assert_integrated(workspace)


def test_apply_with_leftover_staged_files(temppath):
    """
    Scenario 2: staged files from a previous incomplete conversion.

    Simulates a Ctrl-C / crash mid-conversion: the gitlink deletion and
    new integrated files are staged but never committed.  On the next
    `gimera apply` the conversion must succeed without asking the user
    about patches.
    """
    workspace, repos, remote_sub = _setup_submodule_repo(temppath)

    # Switch gimera.yml to integrated
    repos["repos"][0]["type"] = "integrated"
    (workspace / "gimera.yml").write_text(yaml.dump(repos))
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)

    # Simulate a half-done conversion:
    # 1. Remove the .gitmodules entry and stage it
    (workspace / ".gitmodules").write_text("")
    subprocess.check_call(git + ["add", ".gitmodules"], cwd=workspace)

    # 2. Remove the gitlink from the index, stage deletion
    subprocess.check_call(
        git + ["rm", "--cached", "integrated/sub1"], cwd=workspace,
    )

    # 3. Place integrated files and stage them (as gimera would)
    sub_dir = workspace / "integrated" / "sub1"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "file1.txt").write_text("random repo on branch1")
    subprocess.check_call(
        git + ["add", "integrated/sub1"], cwd=workspace,
    )

    # Do NOT commit — this is the interrupted state.
    # Verify staged files exist
    staged = Repo(workspace).staged_files
    assert len(staged) > 0, "Expected staged files from incomplete conversion"

    # gimera must recover: commit the leftovers and complete the conversion
    os.chdir(workspace)
    gimera_apply([], update=True)
    _assert_integrated(workspace)
    # working tree must be clean afterwards
    assert not Repo(workspace).staged_files, "No staged files should remain"
