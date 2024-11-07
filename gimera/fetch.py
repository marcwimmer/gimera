import subprocess
from .tools import get_url_type, reformat_url
import traceback
import os
import threading
import click
import uuid
from .submodule import _has_repo_latest_commit
from .consts import gitcmd as git
from .repo import Repo
from .cachedir import _get_cache_dir
from .tools import verbose
from .tools import wait_git_lock
from .tools import _raise_error
from .tools import try_rm_tree

threadLimiter = threading.BoundedSemaphore(4)


def _fetch_repos_in_parallel(
    main_repo, repos, update=None, minimal_fetch=None, no_fetch=None
):
    results = {"errors": {}, "urls": set()}
    if os.getenv("GIMERA_NON_THREADED", "0") == "1":
        threaded = False
    else:
        threaded = len(repos) > 1

    def _pull_repo(index, main_repo, repo_yml):
        threadLimiter.acquire()
        try:
            if repo_yml.url in results["urls"]:
                return
            verbose(f"Fetching {repo_yml.url}")
            results["urls"].add(repo_yml.url)
            with _get_cache_dir(
                main_repo, repo_yml, no_action_if_not_exist=True
            ) as cache_dir:
                if cache_dir is not None:
                    repo = Repo(cache_dir)
                    do_fetch = True
                    if minimal_fetch:
                        with wait_git_lock(cache_dir):
                            if repo_yml.sha:
                                if repo.contains(repo_yml.sha):
                                    do_fetch = False
                            else:
                                if repo.contains_branch(repo_yml.branch):
                                    do_fetch = False

                    if do_fetch:
                        with wait_git_lock(cache_dir):
                            _fetch_branch(
                                repo, repo_yml, filter_remote="origin", no_fetch=False
                            )

        except Exception as ex:
            if os.getenv("GIMERA_IGNORE_FETCH_ERRORS") == "1":
                click.secho(
                    "Following error is ignored because GIMERA_IGNORE_FETCH_ERRORS is set:"
                )
                click.secho(str(ex), fg="red")
            else:
                trace = traceback.format_exc()
                results["errors"][main_repo.path] = f"{ex}\n\n{trace}"
                if not threaded:
                    raise
        finally:
            threadLimiter.release()

    if not threaded:
        for index, repo in enumerate(repos):
            _pull_repo(index, main_repo, repo)
    else:

        threads = []
        for index, repo in enumerate(repos):
            t = threading.Thread(target=_pull_repo, args=(index, main_repo, repo))
            t.daemon = True
            threads.append(t)
        [x.start() for x in threads]
        [x.join() for x in threads]

        if results["errors"]:
            raise Exception(results["errors"])


def _fetch_branch(repo, repo_yml, no_fetch=False, filter_remote=None, **options):
    url = repo_yml.url

    fetch_exception = None
    if no_fetch:
        return
    for remote in repo.remotes:
        try:
            url = remote.url
            _set_url_and_fetch(
                repo, repo_yml, remote.name, url, filter_remote=filter_remote
            )
        except Exception as ex:
            fetch_exception = ex
            for combination in [
                ("git", "http"),
                ("http", "git"),
            ]:
                if get_url_type(url) == combination[0]:
                    url_http = reformat_url(url, combination[1])
                    try:
                        _set_url_and_fetch(
                            repo,
                            repo_yml,
                            remote.name,
                            url_http,
                            filter_remote=filter_remote,
                        )
                        break
                    except Exception:
                        raise fetch_exception
            else:
                raise fetch_exception


def _set_url_and_fetch(
    repo, repo_yml, remote_name, url, filter_remote=None, trycount=0
):
    repo.set_remote_url(remote_name, url)
    branch = repo_yml.branch
    todo_branches = [branch]
    success = False

    with wait_git_lock(repo.path):
        try:
            repo.out(*(git + ["fetch", remote_name] + todo_branches))
            for branch in todo_branches:
                remote_sha = (
                    repo.X(*(git + ["ls-remote", "origin", branch]), output=True)
                    .strip()
                    .split("\t")[0]
                )
                repo.X(*(git + ["update-ref", f"refs/heads/{branch}", remote_sha]))
            success = True
        except subprocess.CalledProcessError as ex:
            click.secho(ex.stderr, fg="red")

    if success:
        if not _has_repo_latest_commit(repo, repo_yml.branch):
            success = False

    if not success:
        if trycount == 0:
            click.secho(
                (
                    f"This the absolutely LAST RESORT: deleting now {repo.path} as "
                    "fetching the origin and updating the branches did not update the "
                    "local branches."
                )
            )

            try_rm_tree(repo.path)
            with _get_cache_dir(repo, repo_yml) as path:
                pass
            _set_url_and_fetch(
                repo,
                repo_yml,
                remote_name,
                url,
                filter_remote=filter_remote,
                trycount=trycount + 1,
            )
        else:
            _raise_error(
                f"Even after rebuilding cache dir it was not possible to clone {repo_yml.path}"
            )
