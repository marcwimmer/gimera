import tempfile
from pathlib import Path
import os
import shutil
from ..consts import gitcmd as git
import subprocess
from contextlib import contextmanager


def gimera_apply(*args, **kwargs):
    from ..gimera import _apply

    return _apply(*args, **kwargs)


def gimera_commit(*args, **kwargs):
    from ..gimera import _commit

    return _commit(*args, **kwargs)


@contextmanager
def clone_and_commit(repopath, branch, checkout_options=None, commit=True):
    path = Path(tempfile.mktemp(suffix="."))
    if path.exists():
        shutil.rmtree(path)
    subprocess.check_call(git + ["clone", repopath, path], cwd=repopath)
    subprocess.check_call(
        git + ["checkout"] + (checkout_options or []) + [branch], cwd=path
    )
    try:
        yield path
        if commit:
            subprocess.check_call(
                git + ["push", "--set-upstream", "origin", branch], cwd=path
            )
    finally:
        shutil.rmtree(path)


def _make_remote_repo(path):
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "--bare", "--initial-branch=main"], cwd=path)

    tmp = path.parent / "tmp"
    subprocess.check_call(git + ["clone", f"file://{path}", tmp])
    (tmp / "file1.txt").write_text("random repo on main")
    subprocess.check_call(git + ["add", "file1.txt"], cwd=tmp)
    subprocess.check_call(git + ["commit", "-am", "on main"], cwd=tmp)
    subprocess.check_call(git + ["push"], cwd=tmp)

    subprocess.check_call(git + ["checkout", "-b", "branch1"], cwd=tmp)
    (tmp / "file1.txt").write_text("random repo on branch1")
    subprocess.check_call(git + ["add", "file1.txt"], cwd=tmp)
    subprocess.check_call(git + ["commit", "-am", "on branch1"], cwd=tmp)
    subprocess.check_call(
        git + ["push", "--set-upstream", "origin", "branch1"], cwd=tmp
    )

    shutil.rmtree(tmp)
    return path
