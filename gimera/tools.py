import subprocess
import os
from pathlib import Path
import click
import sys
from curses import wrapper

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
    if os.getenv("GIMERA_EXCEPTION_THAN_SYSEXIT")=="1":
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