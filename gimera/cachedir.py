import os
import time
import uuid
import click
import shutil
import subprocess
from pathlib import Path
from .consts import gitcmd as git
from .repo import Repo
from .tools import prepare_dir
from .tools import remember_cwd
from .tools import reformat_url
from .tools import _raise_error
from .tools import rmtree
from .tools import replace_dir_with
from .tools import temppath

# store big repos in tar file and try to restore from there;
# otherwise lot of downloads have to be done


from contextlib import contextmanager


def _make_cache_path(url):
    try:
        urlsafe = reformat_url(url, "git")
    except Exception:
        urlsafe = url
    for c in "?:+[]{}\\/\"'_":
        urlsafe = urlsafe.replace(c, "-")
    urlsafe = urlsafe.split("@")[-1]
    return Path(os.path.expanduser("~/.cache/gimera")) / urlsafe


def _invalidate_cache_if_needed(golden_path):
    must_exist = ["HEAD", "refs", "objects", "config"]
    if golden_path.exists() and (any(
        not (golden_path / x).exists() for x in must_exist
    ) or os.getenv("GIMERA_CLEAR_CACHE") == "1"):
        click.secho(f"Removing cache directory:\n{golden_path}", fg="red")
        rmtree(golden_path)

    if os.getenv("GIMERA_CLEAR_ZIP_CACHE", "") == "1":
        tar = _get_cache_dir_tarfile(golden_path)
        if tar.exists():
            click.secho(f"Removing cache tar file:\n{tar}", fg="red")
            tar.unlink()


def _clone_or_restore(main_repo, url, golden_path, possible_temp_path):
    click.secho(
        f"Caching the repository {url} for quicker reuse",
        fg="yellow",
    )
    tar = _get_cache_dir_tarfile(golden_path)
    with prepare_dir(possible_temp_path) as _path:
        with remember_cwd(
            "/tmp"
        ):  # called from other situations where path may not exist anymore
            restored = False
            if tar.exists():
                try:
                    _extract_tar_file(_path, tar)
                    restored = True
                except Exception:
                    click.secho(
                        f"Failed to extract tar file {tar} - will try to clone again.",
                        fg="red",
                    )
                    tar.unlink()

            if not restored:
                rmtree(_path)
                _path.mkdir(parents=True)
                Repo(main_repo.path).X(*(git + ["clone", "--bare", url, _path]))
                _make_tar_file(_path, tar)


def _ensure_sha(repo_yml, effective_path, update):
    if not repo_yml.sha:
        return
    repo = Repo(effective_path)
    if repo.contain_commit(repo_yml.sha):
        return
    repo.fetchall()
    if repo.contain_commit(repo_yml.sha):
        return
    if not update:
        _raise_error(
            (
                f"After fetching the commit {repo_yml.sha} "
                f"was not found for {repo_yml.path}.\n"
                f"All remote branches were checked."
            )
        )
    else:
        click.secho(
            f"Warning: commit {repo_yml.sha} not found "
            f"for {repo_yml.path} - will retry after update.",
            fg="yellow",
        )


@contextmanager
def _get_cache_dir(main_repo, repo_yml, no_action_if_not_exist=False, update=None):
    url = repo_yml.url
    if not url:
        _raise_error(f"Missing url for: {repo_yml.path}")

    golden_path = _make_cache_path(url)

    if os.getenv("GIMERA_NO_CACHE", "") == "1":
        TEMP_KEY = f"{repo_yml.url}_{repo_yml.sha or repo_yml.branch}"
        with temppath(mkdir=False, reuse_key=TEMP_KEY) as path:
            if not path.exists():
                subprocess.run(["git", "clone", "--single-branch", "--depth=1", "--branch", repo_yml.branch, repo_yml.url, path], check=True)
                if repo_yml.sha:
                    Repo(path).X(*(git + ["fetch", "origin", repo_yml.sha]))
                    Repo(path).X(*(git + ["checkout", repo_yml.sha]))
            yield path
            return

    if no_action_if_not_exist and not golden_path.exists():
        yield None
        return

    possible_temp_path = Path(str(golden_path) + "." + str(uuid.uuid4()))
    try:
        golden_path.parent.mkdir(exist_ok=True, parents=True)
        _invalidate_cache_if_needed(golden_path)

        just_cloned = False
        if not golden_path.exists():
            _clone_or_restore(main_repo, url, golden_path, possible_temp_path)
            just_cloned = True

        effective_path = possible_temp_path if just_cloned else golden_path
        _ensure_sha(repo_yml, effective_path, update)

        yield effective_path

        if just_cloned:
            replace_dir_with(possible_temp_path, golden_path)

    finally:
        possible_temp_path = Path(possible_temp_path)
        if possible_temp_path.exists():
            rmtree(possible_temp_path)


def _get_cache_dir_tarfile(_path):
    return Path(str(_path) + ".tar.gz")


def _make_tar_file(_path, tarfile):
    if tarfile.exists():
        tarfile.unlink()
    click.secho(
        f"Creating tar file {tarfile} from {_path} - might take some time on large repos.",
        fg="yellow",
    )
    tempfilename = str(tarfile) + "." + str(uuid.uuid4())
    subprocess.check_call(["tar", "cfz", str(tempfilename), "-C", str(_path), "."])
    os.replace(tempfilename, tarfile)


def _extract_tar_file(_path, tarfile):
    click.secho(f"Extracting tar file {tarfile} to {_path}", fg="yellow")
    subprocess.check_call(["tar", "xfz", str(tarfile)], cwd=_path)
