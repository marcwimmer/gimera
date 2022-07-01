import subprocess
from curses import wrapper

def yieldlist(method):
    def wrapper(*args, **kwargs):
        result = list(method(*args, **kwargs))
        return result
    return wrapper

def X(*params, output=False, cwd=None):
    if output:
        return subprocess.check_output(params, encoding="utf-8", cwd=cwd).strip()
    return subprocess.check_call(params, cwd=cwd)
