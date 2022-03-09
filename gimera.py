#!/usr/bin/env python3
import re
from ctypes.wintypes import PUSHORT
import os
from datetime import datetime
import inquirer
import click
import json
import git
import yaml
import sys
# from git import Repo
import subprocess
from git import Actor
from pathlib import Path

REPO_TYPE_INT = 'integrated'
REPO_TYPE_SUB = 'submodule'

class Repo(object):
    class Submodule(object):
        def __init__(self, path):
            assert not str(path).startswith("/")
            self.path = Path(path)

        def equals(self, other):
            if isinstance(other, str):
                return str(self.path) == other
            if isinstance(other, Path):
                return self.path.absolute() == other.path.absolute()
            raise NotImplementedError(other)

    def __init__(self, path):
        self.path = Path(path)
        self.working_dir = Path(path)

    @property
    def dirty(self):
        status = subprocess.check_output([
            "git", "status", "-s"], 
            encoding="utf-8", cwd=self.path).strip()
        return bool(status)

    @property
    def hex(self):
        hex = subprocess.check_output([
            "git", "log", "-n", "1", "--pretty=%H"], 
            encoding="utf-8", cwd=self.path).strip()
        if hex:
            return hex.strip()

    def _get_submodules(self):
        submodules = subprocess.check_output([
            "git", "submodule"],
            encoding="utf-8",
            cwd=self.path
        ).strip().splitlines()
        for line in submodules:
            sha, path, refs = line.strip().split(" ", 2)
            yield Repo.Submodule(path)

    def get_submodules(self):
        return list(self._get_submodules())

@click.group()
def gimera():
    pass

def _raise_error(msg):
    click.secho(msg, fg='red')
    sys.exit(-1)

@gimera.command(name='combine-patch', help="Combine patches")
def combine_patches():
    click.secho("\n\nHow to combine patches:\n", fg='yellow')
    click.secho("1. Please install patchutils:\n\n\tapt install patchutils\n")
    click.secho("2. combinediff patch1 patch2 > patch_combined\n")

def _get_available_repos(*args, **kwargs):
    config = load_config()
    repos = []
    for repo in config.get('repos', []):
        if not repo.get('path'): continue
        repos.append(repo['path'])
    return sorted(repos)

def _strip_paths(paths):
    for x in paths:
        if x.endswith("/"):
            x = x[:-1]
        yield x

@gimera.command(name='apply', help="Applies configuration from gimera.yml")
@click.argument('repos', nargs=-1, default=None, autocompletion=_get_available_repos)
@click.option('-u', '--update', is_flag=True, help="If set, then latest versions are pulled from remotes.")
def apply(repos, update):
    config = load_config()
    main_repo = Repo(os.getcwd())
    repos = list(_strip_paths(repos))

    for check in repos:
        if check not in map(lambda x: x['path'], config['repos']):
            _raise_error(f"Invalid path: {check}")

    for repo in config['repos']:
        if repos and repo['path'] not in repos:
            continue
        _apply_repo(main_repo, repo)
        del repo

    for repo in config['repos']:
        if repos and repo['path'] not in repos:
            continue
        if not repo.get('type'):
            repo['type'] = REPO_TYPE_INT

        repo['branch'] = str(repo['branch'])  # e.g. if 15.0

        if repo.get('type') == REPO_TYPE_SUB:
            # _make_patches(main_repo, repo)
            _fetch_latest_commit_in_submodule(main_repo, repo, update=update)
        elif repo.get('type') == REPO_TYPE_INT:
            _make_patches(main_repo, repo)
            _update_integrated_module(main_repo, repo, update)


def _make_patches(main_repo, repo):
    changed_files = list(_get_dirty_files(main_repo, repo['path'], mode='all'))
    untracked_files = list(_get_dirty_files(main_repo, repo['path'], mode='untracked'))
    if not changed_files:
        return

    files_in_lines = '\n'.join(map(str, sorted(changed_files)))
    correct = inquirer.confirm(f"Continue making patches for: {files_in_lines}", default=False)
    if not correct:
        sys.exit(-1)

    to_reset = []
    if repo['type'] == REPO_TYPE_INT:
        cwd = main_repo.working_dir
    elif repo['type'] == REPO_TYPE_INT:
        cwd = main_repo.working_dir / repo['path']
    else:
        raise NotImplementedError(repo['type'])
    for untracked_file in untracked_files:
        # add with empty blob to index, appears like that then:
        """
        Changes not staged for commit:
        (use "git add <file>..." to update what will be committed)
        (use "git restore <file>..." to discard changes in working directory)
                modified:   roles2/sub1/file2.txt
                new file:   roles2/sub1/file3.txt
        """
        subprocess.check_call(['git', 'add', '-N', untracked_file], cwd=cwd)
        to_reset.append(untracked_file)
        del untracked_file
    subprocess.check_call(["git", "add", str(Path(main_repo.working_dir) / repo['path'])], cwd=cwd)
    subprocess.check_call(["git", "commit", '-m', 'for patch'], cwd=cwd)

    patch_content = subprocess.check_output([
        "git", "format-patch", "HEAD~1", '--stdout', '--relative'],
        encoding='utf-8',
        cwd=str(Path(main_repo.working_dir) / repo['path'])
        )
    subprocess.check_call(["git", "reset", "HEAD~1"], cwd=cwd)

    if not repo.get('patches'):
        _raise_error(f"Please define at least one directory, where patches are stored for {repo['path']}")

    if len(repo['patches']) == 1:
        patch_dir = Path(repo['patches'][0])
    else:
        questions = [
            inquirer.List('path',
                message="Please choose a directory where to put the patch file.",
                choices=['Type directory'] + repo['patches']
            )
        ]
        answers = inquirer.prompt(questions)
        if answers['path'] == 'Type directory':
            questions = [
                inquirer.Text('path',
                    message="Where shall i put the patch file? (directory)",
                    default="./"
                )
            ]
            answers = inquirer.prompt(questions)
        patch_dir = Path(answers['path'])

    patch_dir.mkdir(exist_ok=True, parents=True)
    (patch_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + '.patch')).write_text(patch_content)

    for to_reset in to_reset:
        subprocess.check_call(['git', 'reset', to_reset], cwd=main_repo.working_dir)

    # commit the patches - do NOT - could lie in submodule - is hard to do
    #subprocess.check_call(['git', 'add', repo['path']], cwd=main_repo.working_dir)
    #subprocess.check_call(['git', 'add', patch_dir], cwd=main_repo.working_dir)
    #subprocess.check_call(['git', 'commit', '-m', 'added patches'], cwd=main_repo.working_dir)

def _get_remotes(repo_dir):
    lines = subprocess.check_output([
        'git', 'remote', '-v'],
        encoding='utf-8',
        cwd=repo_dir).splitlines()
    remotes = {}
    for line in lines:
        line = line
        name, url = line.split('\t')
        url = url.split(' ')[0]
        v = remotes.setdefault(name, url)
        if v != url:
            raise NotImplementedError(
                'Different urls gor push and fetch for remote %s\n'
                '%s != %s' % (name, url, v)
            )
    return remotes

def _add_remotes(remotes, repo_dir):
    if not remotes:
        return
    _remotes = _get_remotes(repo_dir)
    for name, url in remotes:
        _add_remote(name, url, _remotes, repo_dir)

def _add_remote(name, url, remotes, repo_dir):
    existing_url = remotes.get(name)
    if existing_url == url:
        return

    if not existing_url:
        subprocess.check_call(['git', 'remote', 'add', name, url], cwd=repo_dir)
    else:
        _remove_remote(name, repo_dir)
        subprocess.check_call(['git', 'remote', 'add', name, url], cwd=repo_dir)

def _fetch_remotes(remotes, merges, repo_dir):
    for remote, ref in merges:
        subprocess.check_call(['git', 'fetch', remote, ref], cwd=repo_dir)

def _remove_remote(name, repo_dir):
    subprocess.check_call(['git', 'remote', 'rm', name], cwd=repo_dir)

def _remove_remotes(remotes, repo_dir):
    for name, url in remotes:
        _remove_remote(name, repo_dir)

def _merge(merges, repo_dir):
    for remote, ref in merges:
        subprocess.check_call(['git', 'pull', '--no-edit', remote, ref], cwd=repo_dir)

def _update_integrated_module(main_repo, repo, update):
    """
    Put contents of a git repository inside the main repository.
    """
    def _get_cache_dir():
        if not repo.get('url'):
            click.secho(f"Missing url: {json.dumps(repo, indent=4)}")
            sys.exit(-1)
        path = Path(os.path.expanduser("~/.cache/gimera")) / repo['url'].replace(":", "_").replace("/", "_")
        path.parent.mkdir(exist_ok=True, parents=True)
        if not path.exists():
            click.secho(f"Caching the repository {repo['url']} for quicker reuse", fg='yellow')
            subprocess.check_call(['git', 'clone', repo['url'], path])
        return path

    # use a cache directory for pulling the repository and updating it
    local_repo_dir = _get_cache_dir()
    if not os.access(local_repo_dir, os.W_OK):
        _raise_error(f"No R/W rights on {local_repo_dir}")

    subprocess.check_call(['git', 'fetch'], cwd=local_repo_dir)
    subprocess.check_call(['git', 'checkout', '-f', str(repo['branch'])], cwd=local_repo_dir)
    subprocess.check_call(['git', 'clean', '-xdff'], cwd=local_repo_dir)
    subprocess.check_call(['git', 'pull'], cwd=local_repo_dir)

    sha = repo.get('sha')
    if not update and sha:
        branches = list(
            filter(
                bool, map(
                    lambda x: x.strip().replace("* ", ""),
                    subprocess.check_output([
                        'git', 'branch', '--no-color', '--contains', sha
                    ], cwd=local_repo_dir, encoding='utf-8').splitlines())))
        if repo['branch'] not in branches:
            subprocess.check_call(['git', 'pull'], cwd=local_repo_dir)
            _store(main_repo, repo, {'sha': None})
        else:
            subprocess.check_call(['git', 'config', 'advice.detachedHead', 'false'], cwd=local_repo_dir)
            subprocess.check_call(['git', 'checkout', '-f', sha], cwd=local_repo_dir)

    new_sha = Repo(local_repo_dir).hex
    if repo.get('merges'):
        remotes = repo.get('remotes', [])
        _add_remotes(remotes, local_repo_dir)
        _fetch_remotes(remotes, repo['merges'], local_repo_dir)
        _merge(repo['merges'], local_repo_dir)
        _remove_remotes(remotes, local_repo_dir)

    dest_path = Path(main_repo.working_dir) / repo['path']
    dest_path.parent.mkdir(exist_ok=True, parents=True)
    subprocess.check_call([
        'rsync', '-ar', '--exclude=.git',
        '--delete-after', str(local_repo_dir) + "/", str(dest_path) + "/"],
        cwd=main_repo.working_dir)

    # apply patches:
    for dir in (repo.get('patches', []) or []):
        dir = Path(main_repo.working_dir) / dir
        dir.mkdir(parents=True, exist_ok=True)
        for file in sorted(dir.rglob("*.patch")):
            click.secho(f"Applying patch {file.relative_to(main_repo.working_dir)}", fg='blue')
            # Git apply fails silently if applied within local repos
            try:
                cwd = Path(main_repo.working_dir) / repo['path']
                subprocess.check_output(
                    ['patch', '-p1'],
                    input=file.read_bytes(),
                    cwd=cwd
                    )
                click.secho(f"Applied patch {file.relative_to(main_repo.working_dir)}", fg='blue')
            except Exception as ex:
                _raise_error((
                    f"Failed to apply patch: {file}\n\n"
                    f"Working Directory: {cwd}"
                    f"{ex.stdout}"
                    f"{ex.stderr}"
                ))

    if list(_get_dirty_files(main_repo, repo['path'], mode='all')):
        subprocess.check_call(['git', 'add', repo['path']], cwd=main_repo.working_dir)
        subprocess.check_call(['git', 'commit', '-m', f'updated {REPO_TYPE_INT} submodule: {repo["path"]}'], cwd=main_repo.working_dir)

    subprocess.check_call(['git', 'reset', '--hard', f'origin/{repo["branch"]}'], cwd=local_repo_dir)
    if new_sha != sha:
        _store(main_repo, repo, {'sha': new_sha})

def _fetch_latest_commit_in_submodule(main_repo, repo, update=False):
    path = Path(main_repo.working_dir) / repo['path']
    if list(_get_dirty_files(main_repo, repo['path'], mode='all')):
        _raise_error(f"Directory {repo['path']} contains modified files. Please commit or purge before!")
    if repo.get('sha'):
        sha = repo['sha']
        try:
            branches = list(clean_branch_names(subprocess.check_output([
                "git", "branch", "--contains", sha],
                cwd=path, encoding="utf-8").splitlines))
        except:
            _raise_error(f"SHA {sha} does not seem to belong to a branch at module {repo['path']}")

        if not [x for x in branches if repo['branch'] == x]:
            _raise_error(f"SHA {sha} does not exist on branch {repo['branch']} at repo {repo['path']}")
        subprocess.check_call(['git', 'checkout', '-f', sha], cwd=path)
    else:
        subprocess.check_call(['git', 'checkout', '-f', repo['branch']], cwd=path)
    # check if sha collides with branch
    subprocess.check_call(['git', 'clean', '-xdff'], cwd=path)
    if not repo.get('sha') or update:
        subprocess.check_call(['git', 'checkout', repo['branch']], cwd=path)
        subprocess.check_call(['git', 'pull'], cwd=path)

def clean_branch_names(arr):
    for x in arr:
        x = x.strip()
        if x.startswith("* "):
            x = x[2:]
        yield x
def _get_config_file():
    config_file = Path(os.getcwd()) / 'gimera.yml'
    if not config_file.exists():
        _raise_error(f"Did not find: {config_file}")
    return config_file

def _store(main_repo, repo, value):
    """
    Makes a commit of the changes.
    """
    if main_repo.dirty:
        _raise_error("There mustnt be any staged files when updating gimera.yml")

    config_file = _get_config_file()
    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    param_repo = repo
    for repo in config['repos']:
        if repo['path'] == param_repo['path']:
            repo.update(value)
    config_file.write_text(yaml.dump(config, default_flow_style=False))
    subprocess.check_call(['git', 'add', config_file], cwd=main_repo.working_dir)
    if main_repo.dirty:
        subprocess.check_call(['git', 'commit', '-m', 'auto update gimera.yml'], cwd=main_repo.working_dir)

def load_config():
    config_file = _get_config_file()
    paths = set()

    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    for repo in config['repos']:
        path = repo['path']
        if path in paths:
            _raise_error("Duplicate path: " + path)
        if path.endswith("/"):
            _raise_error("Paths may not end on /")
        repo['path'] = path
        paths.add(path)

        if repo.get('remotes'):
            repo['remotes'] = repo['remotes'].items()
        if repo.get('merges'):
            _merges = []
            for merge in repo.get('merges'):
                remote, ref = merge.split(' ')
                _merges.append((remote.strip(), ref.strip()))
            repo['merges'] = _merges

        if repo.get('type') not in [REPO_TYPE_SUB, REPO_TYPE_INT]:
            _raise_error(f"Please provide type for repo {config['path']}: either '{REPO_TYPE_INT}' or '{REPO_TYPE_SUB}'")

    return config

def __add_submodule(repo, config):
    path = config['path']

    # branch is added with refs/head/branch1 then instead of branch1 in .gitmodules; makes problems at pull then
    # submodule = repo.create_submodule(name=path, path=path, url=config['url'], branch=config['branch'],)
    if config.get('type') == REPO_TYPE_SUB:
        if Path(path).exists():
            subprocess.check_call(["git", "rm", "-f", "-r", path])
            subprocess.check_call(["git", "commit", "-m", f"removed existing path as inserted as submodule: {path}"])
        subprocess.check_call([
            'git', 'submodule', 'add',
            '--force', '-b', str(config['branch']),
            config['url'], path
            ], cwd=repo.working_dir)
        repo.index.add(['.gitmodules'])
        click.secho(f"Added submodule {path} pointing to {config['url']}", fg='yellow')
        repo.index.commit(f"gimera added submodule: {path}") #, author=author, committer=committer)
    elif config.get('type') == REPO_TYPE_INT:
        # nothing to do here - happens at update
        pass

class Submodule(object):
    def __init__(self, path):
        self.path = path

def _apply_repo(repo, repo_config):
    """
    makes sure that git submodules exist for the repo
    """
    if repo_config.get('type') != REPO_TYPE_SUB:
        return
    submodules = repo.get_submodules()
    existing_submodules = list(filter(lambda x: x.equals(repo_config['path']), submodules))
    if not existing_submodules:
        __add_submodule(repo, repo_config)
    existing_submodules = list(filter(lambda x: x.equals(repo_config['path']), submodules))
    if not existing_submodules:
        _raise_error(f"Error with submodule {repo_config['path']}")
    del existing_submodules

def _get_dirty_files(repo, path, mode='all'):
    # initially used index diff but fucks up when uninintialized submodules exist
    assert mode in ['all', 'untracked', 'existing']
    cwd = repo.working_dir / path
    if not cwd.exists():
        return

    def perhaps_yield(x):
        try:
            x.relative_to(Path(repo.working_dir) / path)
        except ValueError:
            pass
        else:
            yield x.relative_to(Path(repo.working_dir))

    if mode in ['all', 'existing']:
        files = list(filter(bool, subprocess.check_output([
            "git", "diff", "--name-only", "."
        ], encoding="utf-8", cwd=cwd).splitlines()))

        for diff in files:
            diff_path = cwd / Path(diff)
            yield from perhaps_yield(diff_path)
            del diff

    if mode in ['all', 'untracked']:
        untracked_files = list(filter(bool, subprocess.check_output([
            "git", "ls-files", "--others", "--exclude-standard", "."
            ], cwd=cwd, encoding="utf8").splitlines()))
        for untracked_file in untracked_files:
            diff_path = cwd / Path(untracked_file)
            yield from perhaps_yield(diff_path)

def _make_sure_in_root():
    path = Path(os.getcwd())
    git_dir = path / '.git'
    if not git_dir.exists():
        _raise_error("Please go into the root of the git repository.")


if __name__ == '__main__':
    _make_sure_in_root()
    gimera()
