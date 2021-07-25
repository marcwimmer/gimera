#!/usr/bin/env python3
import os
import subprocess
import tempfile
from pathlib import Path
import shutil
import click

import inspect
import os
from pathlib import Path
current_dir = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))

path = tempfile.mktemp(suffix='')
click.secho(f"Tempdirectory:\n{path}", fg='yellow')


shutil.copytree(current_dir / 'test_ansible', path)
os.system(f"cd {path}; python3 {current_dir.parent / 'chimera.py'}")
subprocess.check_call(["ls", "-lhtra", path], shell=True)