import os
import click
import json
import shutil
import sys
from pathlib import Path
from .consts import gitcmd as git
from .repo import Repo
from .tools import prepare_dir
from .tools import remember_cwd

def _get_cache_dir(main_repo, repo_yml):
    url = repo_yml.url
    if not url:
        click.secho(f"Missing url: {json.dumps(repo_yml, indent=4)}")
        sys.exit(-1)
    path = Path(os.path.expanduser("~/.cache/gimera")) / url.replace(":", "_").replace(
        "/", "_"
    )
    path.parent.mkdir(exist_ok=True, parents=True)

    must_exist = ["HEAD", "packed-refs", "refs", "objects", "config", "info"]
    if path.exists() and any(not (path / x).exists() for x in must_exist):
        shutil.rmtree(path)

    if not path.exists():
        click.secho(
            f"Caching the repository {repo_yml.url} for quicker reuse",
            fg="yellow",
        )
        with prepare_dir(path) as _path:
            with remember_cwd(
                "/tmp"
            ):  # called from other situations where path may not exist anymore
                Repo(main_repo.path).X(*(git + ["clone", "--bare", url, _path]))
    if repo_yml.sha:
        if not Repo(path).contain_commit(repo_yml.sha):
            # make a fetch quickly; sha is missing
            Repo(path).X(*(git + ["fetch", "--all"]))
    return path
