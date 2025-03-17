import os
import uuid
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
from .tools import rmtree
from .tools import replace_dir_with

# store big repos in tar file and try to restore from there;
# otherwise lot of downloads have to be done


from contextlib import contextmanager


@contextmanager
def _get_cache_dir(main_repo, repo_yml, no_action_if_not_exist=False, update=None):
    url = repo_yml.url
    if not url:
        click.secho(f"Missing url: {json.dumps(repo_yml, indent=4)}")
        sys.exit(-1)

    try:
        urlsafe = reformat_url(url, "git")
    except:
        urlsafe = url

    for c in "?:+[]{}\\/\"'_":
        urlsafe = urlsafe.replace(c, "-")
    urlsafe = urlsafe.split("@")[-1]

    path = Path(os.path.expanduser("~/.cache/gimera")) / urlsafe
    golden_path = path
    if no_action_if_not_exist and not golden_path.exists():
        yield None
        return
    possible_temp_path = Path(str(path) + "." + str(uuid.uuid4()))
    del path
    try:
        golden_path.parent.mkdir(exist_ok=True, parents=True)

        must_exist = ["HEAD", "refs", "objects", "config", "info"]
        if golden_path.exists() and any(
            not (golden_path / x).exists() for x in must_exist
        ):
            rmtree(golden_path)

        just_cloned = False
        if not golden_path.exists():
            click.secho(
                f"Caching the repository {repo_yml.url} for quicker reuse",
                fg="yellow",
            )
            tarfile = _get_cache_dir_tarfile(golden_path)
            with prepare_dir(possible_temp_path) as _path:
                with remember_cwd(
                    "/tmp"
                ):  # called from other situations where path may not exist anymore
                    if tarfile.exists():
                        _extract_tar_file(_path, tarfile)
                        just_cloned = True
                    else:
                        Repo(main_repo.path).X(*(git + ["clone", "--bare", url, _path]))
                        _make_tar_file(_path, tarfile)
                        just_cloned = True

        effective_path = possible_temp_path if just_cloned else golden_path

        if repo_yml.sha:
            repo = Repo(effective_path)
            if not repo.contain_commit(repo_yml.sha):
                # make a fetch quickly; sha is missing
                repo.X(*(git + ["fetch", "--all"]))
                if not repo.contain_commit(repo_yml.sha):
                    if not update:
                        _raise_error(
                            (
                                f"After fetching the commit {repo_yml.sha} "
                                f"was not found for {repo_yml.path}"
                            )
                        )

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
    subprocess.check_call(["tar", "cfz", str(tarfile), "-C", str(_path), "."])


def _extract_tar_file(_path, tarfile):
    click.secho(f"Extracting tar file {tarfile} to {_path}", fg="yellow")
    subprocess.check_call(["tar", "xfz", str(tarfile)], cwd=_path)
