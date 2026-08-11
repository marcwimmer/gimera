import os
import time
import uuid
import click
import shutil
import subprocess
from pathlib import Path
from .consts import gitcmd as git
from .consts import REPO_TYPE_INT
from .repo import Repo
from .tools import prepare_dir
from .tools import remember_cwd
from .tools import reformat_url
from .tools import _raise_error
from .tools import rmtree
from .tools import replace_dir_with
from .tools import temppath
from .userconfig import explain_no_cache
from .userconfig import is_no_cache

# The golden cache is a bare clone, kept once. An older gimera also wrote a
# gzipped tarball of the same packfile next to it - see _drop_legacy_tarfile.


from contextlib import contextmanager


def _make_cache_path(url):
    try:
        urlsafe = reformat_url(url, "git")
    except Exception:
        urlsafe = url
    for c in "?:+[]{}\\/\"'_":
        urlsafe = urlsafe.replace(c, "-")
    urlsafe = urlsafe.split("@")[-1]
    base = Path(os.environ.get("GIMERA_CACHE_DIR") or os.path.expanduser("~/.cache/gimera"))
    return base / urlsafe


def _invalidate_cache_if_needed(golden_path):
    must_exist = ["HEAD", "refs", "objects", "config"]
    if golden_path.exists() and (any(
        not (golden_path / x).exists() for x in must_exist
    ) or os.getenv("GIMERA_CLEAR_CACHE") == "1"):
        click.secho(f"Removing cache directory:\n{golden_path}", fg="red")
        rmtree(golden_path)

    # No GIMERA_CLEAR_ZIP_CACHE any more: there is no second copy to clear.
    # It used to be a separate switch, which is why GIMERA_CLEAR_CACHE=1 alone
    # emptied the directory but left the tarball - and the next run restored
    # the very state the user wanted gone.
    _drop_legacy_tarfile(golden_path)


def _wants_partial_clone(repo_yml):
    """Whether this repo's cache may omit file contents (blobs).

    Integrated repos are materialized with `git archive <sha>` (see
    integrated.py), which pulls exactly the blobs of that one snapshot from
    the promisor remote and keeps them. So the cache grows along the snapshots
    we actually use instead of along the full history: measured on odoo/odoo
    that is 1.4 GB instead of ~17 GB, and a pin bump of 300 commits adds
    ~100 MB.

    Submodule repos are excluded: `git submodule update` clones *out of* the
    cache over file://, and upload-pack cannot serve objects it does not have
    - it aborts with "could not fetch ... from promisor remote". Those repos
    are small anyway (ansible roles here), so there is nothing to win.

    GIMERA_FULL_CLONE=1 turns the filter off everywhere, for a server that
    cannot filter or a repo where partial clone misbehaves.
    """
    if os.getenv("GIMERA_FULL_CLONE", "") == "1":
        return False
    return repo_yml.type == REPO_TYPE_INT


def is_partial_clone(path):
    """True if `path` is a partial clone and thus cannot be cloned *from*.

    Git marks the promisor remote in the repo config; that flag is what makes
    a repo unable to serve a full clone to somebody else.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.promisor"],
            capture_output=True,
            encoding="utf8",
        )
    except Exception:
        return False
    return out.stdout.strip() == "true"


def _warn_if_filter_was_ignored(path, url):
    """A server without uploadpack.allowFilter silently sends everything.

    Nothing breaks then - the cache is just as big as before. Say so, because
    otherwise the disk fills up for a reason nobody can see.
    """
    if is_partial_clone(path):
        return
    click.secho(
        f"{url}: the server ignored --filter=blob:none, so the cache holds "
        "the complete history. Set uploadpack.allowFilter on that server, or "
        "GIMERA_FULL_CLONE=1 to stop asking.",
        fg="yellow",
    )


def _bare_clone(main_repo, url, dest, partial):
    """Clone the cache, filtered when allowed, and never fail because of that.

    Most servers that cannot filter just send everything and warn
    (_warn_if_filter_was_ignored reports that). A server that rejects the
    request outright would take the whole apply down over an optimization, so
    fall back to a plain clone once. A second failure is a real one and is
    left to the caller.
    """
    base = ["clone", "--bare"]
    if not partial:
        Repo(main_repo.path).X(*(git + base + [url, dest]))
        return

    try:
        Repo(main_repo.path).X(
            *(git + base + ["--filter=blob:none", url, dest])
        )
    except Exception as ex:
        click.secho(
            f"{url}: clone with --filter=blob:none failed ({ex}).\n"
            "Retrying without the filter - the cache will hold the complete "
            "history.",
            fg="yellow",
        )
        # git removes the target itself when a clone fails, and rmtree() on a
        # missing path exits the process - so check before clearing whatever
        # the failed attempt left behind.
        if dest.exists():
            rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        Repo(main_repo.path).X(*(git + base + [url, dest]))
        return

    _warn_if_filter_was_ignored(dest, url)


def _clone_or_restore(main_repo, url, golden_path, possible_temp_path, partial=False):
    click.secho(
        f"Caching the repository {url} for quicker reuse",
        fg="yellow",
    )
    with prepare_dir(possible_temp_path) as _path:
        with remember_cwd(
            "/tmp"
        ):  # called from other situations where path may not exist anymore
            rmtree(_path)
            _path.mkdir(parents=True)
            _bare_clone(main_repo, url, _path, partial)


def _ensure_sha(repo_yml, effective_path, update):
    if not repo_yml.sha:
        return
    repo = Repo(effective_path)
    if repo.contain_commit(repo_yml.sha):
        return
    # fetch configured branch first (faster than fetchall for large repos;
    # bare cache repos may have no refspec so --all only fetches HEAD)
    if repo_yml.branch:
        try:
            repo.fetch(remote="origin", ref=repo_yml.branch)
        except Exception:
            pass
    if repo.contain_commit(repo_yml.sha):
        return
    repo.fetchall()
    if repo.contain_commit(repo_yml.sha):
        return
    if not update:
        # check whether the SHA exists on a different branch
        try:
            branches_with_sha = repo.X(
                *(git + ["branch", "-r", "--contains", repo_yml.sha]),
                output=True,
            ).strip()
        except Exception:
            branches_with_sha = ""
        if branches_with_sha:
            non_interactive = os.getenv("GIMERA_NON_INTERACTIVE") == "1"
            msg = (
                f"SHA {repo_yml.sha} for '{repo_yml.path}' was not found on "
                f"configured branch '{repo_yml.branch}' but exists on:\n"
                f"  {branches_with_sha}\n"
                f"Switching to HEAD of '{repo_yml.branch}'."
            )
            click.secho(msg, fg="yellow")
            if not non_interactive:
                click.pause()
            repo_yml.sha = None
        else:
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

    # Kein Cache fuer dieses Repo: flacher Checkout genau des gebrauchten
    # Standes statt der kompletten Historie im Golden Cache. Fuer odoo/odoo
    # ist das der Unterschied zwischen ein paar hundert MB und ~18 GB -- auf
    # einer Kundenmaschine will die Historie niemand.
    if is_no_cache(url):
        explain_no_cache(url)
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
            _clone_or_restore(
                main_repo,
                url,
                golden_path,
                possible_temp_path,
                partial=_wants_partial_clone(repo_yml),
            )
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


def _legacy_tarfile(_path):
    """Where gimera <= 0.12.x kept a second copy of the golden cache."""
    return Path(str(_path) + ".tar.gz")


def _drop_legacy_tarfile(golden_path):
    """Remove the tarball an older gimera left next to the cache.

    It is never read again, so keeping it would just occupy the disk it was
    supposed to save - on odoo/odoo that was 16 GB. Reported rather than
    done silently, because the number is large enough that someone watching
    `du` should know where it went.
    """
    tar = _legacy_tarfile(golden_path)
    if not tar.exists():
        return
    try:
        size = tar.stat().st_size
    except OSError:
        size = 0
    click.secho(
        f"Removing tar file left by an older gimera "
        f"({size / 1024 / 1024 / 1024:.1f} GB):\n{tar}",
        fg="yellow",
    )
    try:
        tar.unlink()
    except OSError as ex:
        click.secho(f"Could not remove {tar}: {ex}", fg="red")
