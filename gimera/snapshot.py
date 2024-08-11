import subprocess
import click
from pathlib import Path
from .consts import gitcmd as git
from .repo import Repo
from .tools import get_nearest_repo
from .tools import safe_relative_to
from .tools import _make_sure_hidden_gimera_dir
import os
import uuid
from datetime import datetime
import shutil

to_cleanup = []


def get_snapshots(root_dir):
    path = root_dir / ".gimera" / "snapshots"
    res = []
    for snapshot in path.glob("*"):
        res.append(snapshot.name)
    return res


def snapshot_recursive(root_dir, start_path):
    repo = get_nearest_repo(root_dir, start_path)
    parent = get_nearest_repo(root_dir, repo)

    _snapshot_dir(
        root_dir,
        Repo(repo),
        parent_path=parent,
        filter_paths=[start_path],
    )
    return _get_token()


def snapshot_restore(root_dir, start_path, token=None):
    repo = get_nearest_repo(root_dir, start_path)
    token = token or _get_token()
    patches = root_dir / ".gimera" / "snapshots" / token
    for patchfile in patches.rglob("**/*.patch"):
        relpath = safe_relative_to(patchfile.parent, root_dir)
        relpath = Path("/".join(relpath.parts[3:]))

        repo_dir = root_dir / relpath / patchfile.name.rstrip(".patch")
        subprocess.check_call((git + ["apply", patchfile]), cwd=repo_dir)


def _snapshot_dir(root_dir, repo, parent_path, filter_paths):
    subprocess.check_call((git + ["add", "."]), cwd=repo.path)
    patch_file_content = subprocess.check_output(
        (git + ["diff", "--cached", "--relative"]), cwd=repo.path
    )
    subprocess.check_call((git + ["stash", "--include-untracked"]), cwd=repo.path)

    if patch_file_content:
        cache_file = _get_patch_filepath(root_dir, repo.path)
        cache_file.write_bytes(patch_file_content)

    for submodule in repo.get_submodules():
        _snapshot_dir(root_dir, submodule, repo.path, None)


def _snapshot_restore(repo):
    pass


def cleanup():
    for path in to_cleanup:
        if path.exists():
            shutil.rmtree(path)


def _get_token():
    token = os.getenv("GIMERA_TOKEN")
    if not token:
        os.environ["GIMERA_TOKEN"] = (
            datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())
        )
    return os.getenv("GIMERA_TOKEN")


def _get_patch_filepath(root_dir, file_relpath):
    token = _get_token()
    file_relpath = safe_relative_to(file_relpath, root_dir)
    path = (
        _make_sure_hidden_gimera_dir(root_dir)
        / "snapshots"
        / token
        / f"{file_relpath}.patch"
    )
    to_cleanup.append(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def list_snapshots(root_dir):
    res = []
    for dir in (root_dir / ".gimera" / "snapshots").glob("*"):
        if not dir.is_dir():
            continue
        res.append(dir)
    return res
