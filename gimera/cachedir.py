import os
import click
import json
import shutil
import sys
import subprocess
from pathlib import Path
from .consts import gitcmd as git
from .repo import Repo
from .tools import prepare_dir
from .tools import remember_cwd
from .tools import reformat_url
from .tools import _raise_error

# store big repos in tar file and try to restore from there;
# otherwise lot of downloads have to be done


def _get_cache_dir(main_repo, repo_yml):
    url = repo_yml.url
    if not url:
        click.secho(f"Missing url: {json.dumps(repo_yml, indent=4)}")
        sys.exit(-1)

    try:
        urlsafe = reformat_url(url, 'git')
    except:
        urlsafe = url

    for c in "?:+[]{}\\/\"'":
        urlsafe = urlsafe.replace(c, "_")

    path = Path(os.path.expanduser("~/.cache/gimera")) / urlsafe
    path.parent.mkdir(exist_ok=True, parents=True)

    must_exist = ["HEAD", "refs", "objects", "config", "info"]
    if path.exists() and any(not (path / x).exists() for x in must_exist):
        shutil.rmtree(path)

    if not path.exists():
        click.secho(
            f"Caching the repository {repo_yml.url} for quicker reuse",
            fg="yellow",
        )
        tarfile = _get_cache_dir_tarfile(path)
        with prepare_dir(path) as _path:
            with remember_cwd(
                "/tmp"
            ):  # called from other situations where path may not exist anymore
                if tarfile.exists():
                    _extract_tar_file(_path, tarfile)
                else:
                    Repo(main_repo.path).X(*(git + ["clone", "--bare", url, _path]))
                    _make_tar_file(_path, tarfile)

    if repo_yml.sha:
        repo = Repo(path)
        if not repo.contain_commit(repo_yml.sha):
            # make a fetch quickly; sha is missing
            repo.X(*(git + ["fetch", "--all"]))
            if not repo.contain_commit(repo_yml.sha):
                _raise_error((
                    f"After fetching the commit {repo_yml.sha} "
                    f"was not found for {repo_yml.path}"
                ))
    return path

def _get_cache_dir_tarfile(_path):
    return Path(str(_path) + ".tar.gz")

def _make_tar_file(_path, tarfile):
    if tarfile.exists():
        tarfile.unlink()
    subprocess.check_call(["tar", "cfz", str(tarfile), "-C", str(_path), '.'])

def _extract_tar_file(_path, tarfile):
    subprocess.check_call(["tar", "xfz", str(tarfile)], cwd=_path)