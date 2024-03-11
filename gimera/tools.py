import subprocess
import tempfile
import time
from datetime import datetime
import shutil
import uuid
import os
from pathlib import Path
import click
import sys
from curses import wrapper
from contextlib import contextmanager


def is_forced():
    return os.getenv("GIMERA_FORCE", "0") == "1"


def yieldlist(method):
    def wrapper(*args, **kwargs):
        result = list(method(*args, **kwargs))
        return result

    return wrapper


def X(*params, output=False, cwd=None, allow_error=False):
    params = list(filter(lambda x: x is not None, list(params)))
    if output:
        try:
            return subprocess.check_output(params, encoding="utf-8", cwd=cwd).rstrip()
        except subprocess.CalledProcessError:
            if allow_error:
                return ""
            raise
    try:
        return subprocess.check_call(params, cwd=cwd)
    except subprocess.CalledProcessError:
        if allow_error:
            return None
        raise


def _raise_error(msg):
    click.secho(msg, fg="red")
    if os.getenv("GIMERA_EXCEPTION_THAN_SYSEXIT") == "1":
        raise Exception(msg)
    else:
        sys.exit(-1)


def _strip_paths(paths):
    for x in paths:
        yield str(Path(x))


def safe_relative_to(path, path2):
    try:
        res = Path(path).relative_to(path2)
    except ValueError:
        return False
    else:
        return res


def is_empty_dir(path):
    return not any(Path(path).rglob("*"))


@contextmanager
def prepare_dir(path):
    tmp_path = path.parent / f"{path.name}.{uuid.uuid4()}"
    assert path.parent.exists()
    assert len(path.parts) > 1
    tmp_path.mkdir(parents=True)
    try:
        yield tmp_path
        if path.exists():
            rmtree(path)
        shutil.move(tmp_path, path)
    except Exception as ex:
        raise
    finally:
        if tmp_path.exists():
            try:
                rmtree(tmp_path)
            except Exception:
                pass


def file_age(path):
    try:
        mtime = datetime.fromtimestamp(os.stat(path).st_mtime)
    except:
        return 0
    return (
        datetime.now() - mtime
    ).total_seconds()


@contextmanager
def wait_git_lock(path):
    MAX_TIMEOUT = 3600
    from .filelock import FileLock

    gimera_lock = path / ".git" / "gimera.lock"
    if not gimera_lock.parent.exists():
        gimera_lock = None
    index_lock = path / ".git" / "index.lock"

    def lock_exists():
        if index_lock.exists():
            return True
        if gimera_lock and gimera_lock.exists():
            return True
        return False

    if not index_lock.exists():
        yield
    else:
        while lock_exists():
            if file_age(index_lock) > MAX_TIMEOUT:
                index_lock.unlink()
                continue

            if gimera_lock and file_age(gimera_lock) > MAX_TIMEOUT:
                gimera_lock.unlink()
                continue

            time.sleep(0.5)

        if gimera_lock:
            with FileLock(gimera_lock, timeout=MAX_TIMEOUT):
                yield
        else:
            yield


def rmtree(path):
    try:
        shutil.rmtree(path)
    except:
        click.secho(f"Failed to remove {path}", fg="red")
        sys.exit(-1)


@contextmanager
def remember_cwd(cwd):
    old = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        yield Path(cwd)
    finally:
        os.chdir(old)


def confirm(msg, raise_exception=True):
    if os.getenv("GIMERA_NON_INTERACTIVE") == "1":
        return True
    click.secho(msg, fg="yellow")
    res = click.confirm("Continue?", default=True)
    if not res and raise_exception:
        _raise_error("Aborted by user")
    return res


def retry(func, attempts=3, sleep=5):
    for i in range(attempts):
        try:
            func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep)
        else:
            break


def try_rm_tree(path):
    if not path.exists():
        return

    def _action():
        shutil.rmtree(path)

    retry(func=_action)


@contextmanager
def temppath():
    path = Path(tempfile.mktemp(suffix="."))
    try:
        path.mkdir()
        yield path
    finally:
        try_rm_tree(path)


def path1inpath2(path1, path2):
    try:
        path1.relative_to(path2)
        return True
    except:
        return False


def rsync(dir1, dir2, exclude=None, delete_after=True):
    cmd = [
        "rsync",
        "-ar",
    ]
    if delete_after:
        cmd += ["--delete-after"]
    for X in exclude or []:
        cmd += [f"--exclude={X}"]
    cmd.append(str(dir1) + "/")
    cmd.append(str(dir2) + "/")
    subprocess.check_call(cmd)


def get_url_type(url):
    if url.startswith("https"):
        return "http"
    if url.startswith("git@"):
        return "git"
    if url.startswith("/"):
        return "file"
    raise NotImplementedError(url)


def reformat_url(url, ttype):
    assert ttype in ["http", "git"]

    current = get_url_type(url)
    if ttype == "http" and current == "git":
        if url.startswith("git@"):
            url = url[4:]
        if ":" in url:
            # colon in password possible
            url = "/".join(url.split(":", 1))
        url = "https://" + url
        return url
    else:
        raise NotImplementedError(f"{url} + {ttype}")
