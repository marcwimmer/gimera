import subprocess
import click
import sys
from curses import wrapper

def yieldlist(method):
    def wrapper(*args, **kwargs):
        result = list(method(*args, **kwargs))
        return result
    return wrapper

def X(*params, output=False, cwd=None):
    if 'checkout' in params:
        import pudb;pudb.set_trace()
    params = list(filter(lambda x: x is not None, list(params)))
    if output:
        return subprocess.check_output(params, encoding="utf-8", cwd=cwd).strip()
    return subprocess.check_call(params, cwd=cwd)

def _raise_error(msg):
    click.secho(msg, fg="red")
    sys.exit(-1)

def _strip_paths(paths):
    for x in paths:
        if x.endswith("/"):
            x = x[:-1]
        yield x
