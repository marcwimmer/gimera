import subprocess
from pathlib import Path
from .consts import gitcmd as git
from .repo import Repo
from .tools import get_nearest_repo
from .tools import safe_relative_to
import os
import uuid
from datetime import datetime
import shutil
from .patches import remove_file_from_patch

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
    assert isinstance(filter_paths, list)

    _snapshot_dir(
        root_dir,
        path=None,
        filter_paths=filter_paths,
    )
    return _get_token()


def snapshot_restore(root_dir, filter_paths, token=None):
    token = token or _get_token()
    patches = root_dir / ".gimera" / "snapshots" / token

    for patchfile in patches.rglob("**/*.patch"):
        relpath = safe_relative_to(patchfile.parent, root_dir)
        relpath = Path("/".join(relpath.parts[3:])) / patchfile.stem

        assert all(
            str(x).startswith("/") for x in filter_paths
        ), "Only absolute paths please"

        if filter_paths and not [
            (str(root_dir / relpath / patchfile.stem)).startswith(str(x))
            for x in filter_paths
        ]:
            continue

        repo_dir = root_dir / relpath
        # find out the belonging repository; if switched from submodule to integrated
        # a new root must be added to the patch
        nearest_repo_path = get_nearest_repo(root_dir, repo_dir)
        delta_path = safe_relative_to(repo_dir, nearest_repo_path)
        cmd = git + ["apply", "--reject"]
        if str(delta_path) != ".":
            cmd += ["--directory", delta_path]
        cmd += [patchfile]
        subprocess.check_call(cmd, cwd=nearest_repo_path)


def _find_matching_dirs(root_dir, path, filter_paths, cache=None):
    cache = cache or {}
    if path is None:
        path = root_dir

    cache.setdefault("nearest", {})
    repo = get_nearest_repo(root_dir, path)

    def _matches_filter_paths(path, direction):
        if direction == "before":
            return bool(any(x for x in filter_paths if safe_relative_to(x, path)))
        else:
            return bool(any(x for x in filter_paths if safe_relative_to(path, x)))

    before = _matches_filter_paths(path, "before")
    after = _matches_filter_paths(path, "after")

    if before or after:
        cache.setdefault("dirty", {})
        if repo not in cache["dirty"]:
            cache["dirty"][repo] = Repo(repo).all_dirty_files
        if cache["dirty"][repo]:
            yield Repo(repo), path
        for sub in path.iterdir():
            if sub.is_dir():
                if sub.name == ".git":
                    continue
                yield from _find_matching_dirs(root_dir, sub, filter_paths, cache=cache)


def _snapshot_dir(root_dir, path, filter_paths=None):
    matching_dirs = list(
        reversed(list(_find_matching_dirs(root_dir, path, filter_paths)))
    )

    cache = {"dirty": {}}
    for repo, path in matching_dirs:
        if repo.path not in cache["dirty"]:
            repo.X("git", "reset", output=True)
            cache["dirty"][repo.path] = repo.all_dirty_files_absolute

        dirty_files = cache["dirty"][repo.path]
        if not dirty_files:
            continue
        dirty_files = [x for x in dirty_files if x.parent == path]
        if not dirty_files:
            continue
        cache["dirty"].pop(repo.path)
        for dirty_file in dirty_files:
            if any(x == dirty_file.name for x in [".gitmodules", ".git"]):
                continue
            subprocess.check_call((git + ["add", dirty_file]), cwd=path)
            del dirty_file
        patch_file_content = subprocess.check_output(
            (git + ["diff", "--cached", "--relative"]), cwd=path
        )
        if patch_file_content:
            cache_file = _get_patch_filepath(root_dir, path)
            cache_file.write_bytes(patch_file_content)

    repos = map(Repo, set(x[0].path for x in matching_dirs))
    for repo in repos:
        subprocess.check_call((git + ["reset"]), cwd=repo.path)
        subprocess.check_call((git + ["checkout", "."]), cwd=repo.path)
        for dirtyfile in repo.untracked_files_absolute:
            if dirtyfile.is_dir():
                shutil.rmtree(dirtyfile)
            else:
                dirtyfile.unlink()


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
    path = root_dir / '.gimera' / "snapshots" / token / f"{file_relpath}.patch"
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
