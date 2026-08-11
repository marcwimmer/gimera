"""Bumping the sha of an integrated repo must actually re-vendor the files.

Background — the bug this test pins down
---------------------------------------

``_update_integrated_module`` has a fast path that skips extracting the
upstream files when the vendored directory is already at the wanted commit.
Skipping is a pure speed optimization: extracting means ``git archive`` plus an
``rsync``, which is wasteful when nothing changed.

The decision *whether* something changed used to be made like this::

    sha_before = repo_yml.sha                                    # from gimera.yml
    commit     = repo_yml.sha or repo_yml.branch                 # from gimera.yml
    new_sha    = repo.out(*(git + ["rev-parse", commit]))        # resolves to itself
    if sha_before == new_sha and dest_path.exists() and ...:
        # "already at <sha> - skipping extract"

Both sides of that comparison come from the same place: the ``sha`` entry in
``gimera.yml``. That entry describes the state we *want*, never the state that
is actually on disk. For a sha-pinned integrated repo ``new_sha`` is simply
that same sha resolved to itself, so the condition is a tautology and the
extract is skipped **every single time**.

The practical damage is silent and nasty: you edit ``gimera.yml`` to a newer
sha, run ``gimera apply``, get exit code 0 and a friendly "already at ... -
skipping extract", and the vendored directory keeps the *old* content. From
then on ``gimera.yml`` claims a state that does not exist in the tree. In a
real repository of ours a pinned module drifted 39 commits behind its own pin
this way, and nobody noticed because every command reported success.

Note what made the bug survive: the only situations that forced an extract were
``--update`` (which takes the commit from the branch instead of the sha) and
pinned patches. Both are common enough that the fast path looked like it worked.

The fix compares content instead of intent: the git tree hash of the upstream
commit against the tree hash of the vendored directory as committed in the
parent repository. Tree hashes are content addressed and carry no repository
identity, so they are equal exactly when the files are equal. Whenever that
comparison cannot be made (directory not committed yet, path outside the parent
repo, dirty working tree) the code errs towards extracting — a needless extract
costs a bit of time, a skipped one costs correctness.

What this test does
-------------------

1. creates a remote repo whose ``file1.txt`` says "version 1", remembers that sha
2. pushes a second commit saying "version 2", remembers that sha too
3. vendors the repo into a main repo pinned to sha 1 and asserts the content
4. rewrites ``gimera.yml`` to sha 2 and applies again
5. asserts the file now says "version 2" — this is the assertion that failed
   before the fix — and that ``gimera.yml`` still holds sha 2

Step 5 is deliberately the *content* of the file and not the sha in
``gimera.yml``: the old code updated the sha (it writes ``repo_yml.sha =
new_sha`` at the end) while leaving the files untouched, so a test that only
looked at the config would have passed on the broken code.
"""

from .fixtures import *  # required for all
import os
import subprocess
import yaml
from pathlib import Path

from .tools import gimera_apply
from .tools import _make_remote_repo
from .tools import clone_and_commit
from ..consts import gitcmd as git


def test_integrated_pin_bump_revendors_files(temppath):
    workspace = temppath / "workspace_pin_bump"
    workspace.mkdir(parents=True)

    remote_main_repo = _make_remote_repo(temppath / "mainrepo")
    remote_sub_repo = _make_remote_repo(temppath / "sub1")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    # two upstream states we can tell apart by looking at file1.txt
    with clone_and_commit(remote_sub_repo, "branch1") as repopath:
        (repopath / "file1.txt").write_text("version 1")
        subprocess.check_call(git + ["add", "file1.txt"], cwd=repopath)
        subprocess.check_call(git + ["commit", "-m", "version 1"], cwd=repopath)
        sha1 = subprocess.check_output(
            git + ["rev-parse", "HEAD"], cwd=repopath, encoding="utf8"
        ).strip()

    with clone_and_commit(remote_sub_repo, "branch1") as repopath:
        (repopath / "file1.txt").write_text("version 2")
        subprocess.check_call(git + ["add", "file1.txt"], cwd=repopath)
        subprocess.check_call(git + ["commit", "-m", "version 2"], cwd=repopath)
        sha2 = subprocess.check_output(
            git + ["rev-parse", "HEAD"], cwd=repopath, encoding="utf8"
        ).strip()

    assert sha1 != sha2

    def write_config(sha):
        (workspace / "gimera.yml").write_text(
            yaml.dump(
                {
                    "repos": [
                        {
                            "url": f"file://{remote_sub_repo}",
                            "branch": "branch1",
                            "path": "integrated/sub1",
                            "type": "integrated",
                            "sha": sha,
                        }
                    ]
                },
                default_flow_style=False,
            )
        )
        subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
        subprocess.check_call(
            git + ["commit", "-m", f"pin {sha[:7]}"], cwd=workspace
        )

    vendored_file = workspace / "integrated" / "sub1" / "file1.txt"

    # --- pin to the first state -------------------------------------------
    write_config(sha1)
    os.chdir(workspace)
    gimera_apply([], update=None)
    assert vendored_file.read_text() == "version 1"

    # --- bump the pin to the second state ---------------------------------
    # No --update here: that is the whole point. A plain apply after editing
    # the sha by hand is the everyday way of moving a pin forward.
    write_config(sha2)
    os.chdir(workspace)
    gimera_apply([], update=None)

    # Before the fix this was still "version 1": apply reported success and
    # skipped the extract, so the pin and the files disagreed silently.
    assert vendored_file.read_text() == "version 2", (
        "vendored files were not updated after bumping the pin - "
        "the fast path skipped the extract"
    )

    # and the config still says what we asked for
    config = yaml.safe_load((workspace / "gimera.yml").read_text())
    assert config["repos"][0]["sha"] == sha2


def test_integrated_unchanged_pin_still_skips(temppath):
    """The optimization must survive the fix.

    Re-applying an unchanged pin should *not* extract again — otherwise the fix
    would trade a correctness bug for a performance regression on every run.
    We cannot observe the skip from the outside directly, so we check the thing
    the skip is meant to protect: applying twice leaves the vendored directory
    byte-identical and produces no new commit in the parent repo.
    """
    workspace = temppath / "workspace_unchanged_pin"
    workspace.mkdir(parents=True)

    remote_main_repo = _make_remote_repo(temppath / "mainrepo2")
    remote_sub_repo = _make_remote_repo(temppath / "sub2")

    subprocess.check_output(
        git + ["clone", "file://" + str(remote_main_repo), workspace.name],
        cwd=workspace.parent,
    )
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"

    with clone_and_commit(remote_sub_repo, "branch1") as repopath:
        (repopath / "file1.txt").write_text("stable")
        subprocess.check_call(git + ["add", "file1.txt"], cwd=repopath)
        subprocess.check_call(git + ["commit", "-m", "stable"], cwd=repopath)
        sha = subprocess.check_output(
            git + ["rev-parse", "HEAD"], cwd=repopath, encoding="utf8"
        ).strip()

    (workspace / "gimera.yml").write_text(
        yaml.dump(
            {
                "repos": [
                    {
                        "url": f"file://{remote_sub_repo}",
                        "branch": "branch1",
                        "path": "integrated/sub2",
                        "type": "integrated",
                        "sha": sha,
                    }
                ]
            },
            default_flow_style=False,
        )
    )
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=workspace)
    subprocess.check_call(git + ["commit", "-m", "pin"], cwd=workspace)

    os.chdir(workspace)
    gimera_apply([], update=None)

    head_after_first = subprocess.check_output(
        git + ["rev-parse", "HEAD"], cwd=workspace, encoding="utf8"
    ).strip()
    content_after_first = (workspace / "integrated" / "sub2" / "file1.txt").read_text()

    os.chdir(workspace)
    gimera_apply([], update=None)

    head_after_second = subprocess.check_output(
        git + ["rev-parse", "HEAD"], cwd=workspace, encoding="utf8"
    ).strip()
    content_after_second = (workspace / "integrated" / "sub2" / "file1.txt").read_text()

    assert content_after_first == content_after_second == "stable"
    assert head_after_first == head_after_second, (
        "re-applying an unchanged pin created a commit - the fast path no "
        "longer recognizes an up to date directory"
    )
