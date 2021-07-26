#!/usr/bin/env python3
from git import Repo
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

def test1():
    path = Path(tempfile.mktemp(suffix=''))

    remote_main_repo = _make_remote_repo()
    remote_sub_repo = _make_remote_repo()

    subprocess.check_output(['git', 'clone', "-b", "main", "file://" + str(remote_main_repo), path.name], cwd=path.parent)

    (path / 'gimera.yml').write_text(f"""
repos:
    - url: "file://{remote_sub_repo}"
      branch: branch1
      path: roles/sub1
      patches: []
      type: submodule
    - url: "file://{remote_sub_repo}"
      branch: branch1
      path: roles2/sub1
      patches: 
          - 'roles2/sub1_patches'
      type: integrated
    """.replace("    ", "    "))
    (path / 'main.txt').write_text("main repo")
    subprocess.check_call(['git', 'add', 'main.txt'], cwd=path)
    subprocess.check_call(['git', 'add', 'gimera.yml'], cwd=path)
    subprocess.check_call(['git', 'commit', '-am', 'on main'], cwd=path)
    subprocess.check_call(["python3", current_dir.parent / 'gimera.py', 'apply'], cwd=path)

    click.secho("Now we have a repo with two subrepos; now we update the subrepos and pull")
    (remote_sub_repo / 'file2.txt').write_text("This is a new function")
    subprocess.check_call(['git', 'add', 'file2.txt'], cwd=remote_sub_repo)
    subprocess.check_call(['git', 'commit', '-am', 'file2 added'], cwd=remote_sub_repo)
    subprocess.check_call(["python3", current_dir.parent / 'gimera.py', 'apply', '--update'], cwd=path)

    click.secho(str(path), fg='green')
    assert (path / 'roles' / 'sub1' / 'file2.txt').exists()
    assert (path / 'roles2' / 'sub1' / 'file2.txt').exists()

    # check dirty - disabled because the command is_path_dirty is not cool
    os.environ['GIMERA_DEBUG'] = '1'
    (path / 'roles2' / 'sub1' / 'file2.txt').write_text('a change!')
    (path / 'roles2' / 'sub1' / 'file3.txt').write_text('a new file!')
    (path / 'file4.txt').write_text('a new file!')
    test = subprocess.check_output(["python3", current_dir.parent / 'gimera.py', 'is_path_dirty', 'roles2/sub1'], cwd=path).decode('utf-8')
    assert 'file2.txt' in test
    assert 'file3.txt' in test
    assert 'file4.txt' not in test

    # now lets make a patch
    subprocess.check_call(["python3", current_dir.parent / 'gimera.py', 'apply', '--update'], cwd=path)
    subprocess.check_call(["git", "add", "roles2"], cwd=path)
    subprocess.check_call(["git", "commit", "-am", "patches"], cwd=path)

    # now lets make an update and see if patches are applied
    (remote_sub_repo / 'file5.txt').write_text("I am no 5")
    subprocess.check_call(["git", "add", "file5.txt"], cwd=remote_sub_repo)
    subprocess.check_call(["git", "commit", "-am", "file5 added"], cwd=remote_sub_repo)
    # should apply patches now
    subprocess.check_call(["python3", current_dir.parent / 'gimera.py', 'apply'], cwd=path)


def _make_remote_repo():
    path = Path(tempfile.mktemp(suffix=''))
    path.mkdir(parents=True)
    subprocess.check_call(['git', 'init', '--initial-branch=main'], cwd=path)
    (path / 'file1.txt').write_text("random repo on main")
    subprocess.check_call(['git', 'add', 'file1.txt'], cwd=path)
    subprocess.check_call(['git', 'commit', '-am', 'on main'], cwd=path)

    (path / 'file1.txt').write_text("random repo on branch1")
    subprocess.check_call(['git', 'checkout', '-b', 'branch1'], cwd=path)
    subprocess.check_call(['git', 'add', 'file1.txt'], cwd=path)
    subprocess.check_call(['git', 'commit', '-am', 'on branch1'], cwd=path)

    return path

if __name__ == '__main__':
    test1()