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
from .config import Config

to_cleanup = []


def get_snapshots(root_dir):
    path = root_dir / ".gimera" / "snapshots"
    res = []
    for snapshot in reversed(list(path.glob("*"))):
        res.append(snapshot.name)
    return res


def _get_repo_for_filter_paths(root_dir, filter_paths):
    repos = set()
    for path in filter_paths:
        repo = get_nearest_repo(root_dir, path)
        repos.add(repo)
    if len(repos) > 1:
        raise NotImplementedError("Two many repos associated.")
    repo = list(repos)[0]
    return repo


def snapshot_recursive(root_dir, filter_paths, token=None):
    repo = _get_repo_for_filter_paths(root_dir, filter_paths)
    parent = get_nearest_repo(root_dir, repo)
    assert isinstance(filter_paths, list)

    _snapshot_dir(
        root_dir,
        Repo(repo),
        parent_path=parent,
        filter_paths=filter_paths,
    )
    return _get_token()


def snapshot_restore(root_dir, filter_paths, token=None):
    token = token or _get_token()
    patches = root_dir / ".gimera" / "snapshots" / token
    for patchfile in patches.rglob("**/*.patch"):
        relpath = safe_relative_to(patchfile.parent, root_dir)
        relpath = Path("/".join(relpath.parts[3:]))

        assert all(
            str(x).startswith("/") for x in filter_paths
        ), "Only absolute paths please"

        if filter_paths and (root_dir / relpath / patchfile.stem) not in filter_paths:
            continue

        repo_dir = root_dir / relpath / patchfile.stem
        subprocess.check_call((git + ["apply", patchfile]), cwd=repo_dir)


def _snapshot_dir(root_dir, repo, parent_path, filter_paths=None):
    if filter_paths is None:
        filter_paths = []
        filter_paths.append(repo.path)

    assert isinstance(filter_paths, list)
    for path in filter_paths:
        repo.X("git", "reset")
        subprocess.check_call((git + ["add", "."]), cwd=path)
        patch_file_content = subprocess.check_output(
            (git + ["diff", "--cached", "--relative"]), cwd=repo.path
        )

        if patch_file_content:
            cache_file = _get_patch_filepath(root_dir, path)
            cache_file.write_bytes(patch_file_content)
            subprocess.check_call((git + ["reset", path]), cwd=repo.path)
            subprocess.check_call((git + ["checkout", path]), cwd=repo.path)
            for dirtyfile in repo.untracked_files:
                if dirtyfile.is_dir():
                    shutil.rmtree(dirtyfile)
                else:
                    dirtyfile.unlink()

    for submodule in repo.get_submodules():
        _snapshot_dir(root_dir, submodule, repo.path, None)


def cleanup():
    for path in to_cleanup:
        if path.exists():
            if path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)


def _get_token():
    if not os.getenv("GIMERA_TOKEN"):
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
        parts = dir.parts
        parts = parts[parts.index("snapshots") + 1 :]
        res.append("/".join(parts))
    return res
