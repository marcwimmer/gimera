import subprocess
from pathlib import Path
import click
import sys
from curses import wrapper

def yieldlist(method):
    def wrapper(*args, **kwargs):
        result = list(method(*args, **kwargs))
        return result
    return wrapper

def X(*params, output=False, cwd=None):
    params = list(filter(lambda x: x is not None, list(params)))
    if output:
        return subprocess.check_output(params, encoding="utf-8", cwd=cwd).rstrip()
    return subprocess.check_call(params, cwd=cwd)

def _raise_error(msg):
    click.secho(msg, fg="red")
    sys.exit(-1)

def _strip_paths(paths):
    for x in paths:
        if x.endswith("/"):
            x = x[:-1]
        yield x

def safe_relative_to(path, path2):
    try:
        res = Path(path).relative_to(path2)
    except ValueError:
        return False
    else:
        return res

def is_empty_dir(path):
    return not any(Path(path).rglob("*"))