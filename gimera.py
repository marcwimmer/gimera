#!/usr/bin/env python3
import os
from datetime import datetime
import inquirer
import click
import json
import git
import yaml
import sys
from git import Repo
import subprocess
from git import Actor
from pathlib import Path

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

@gimera.command(name='apply', help="Applies configuration from gimera.yml")
@click.option('-u', '--update', is_flag=True, help="If set, then latest versions are pulled from remotes.")
def apply(update):
    config = load_config()

    for repo in config['repos']:
        _apply_repo(repo)
        del repo

    main_repo = Repo(os.getcwd())

    for repo in config['repos']:
        if not repo.get('type'):
            repo['type'] = 'integrated'

        if repo.get('type') == 'submodule':
            if update:
                _fetch_latest_commit_in_submodule(main_repo, repo)
        elif repo.get('type') == 'integrated':
            _make_patches(main_repo, repo)
            _update_integrated_module(main_repo, repo, update)


def _make_patches(main_repo, repo):
    changed_files = list(_get_dirty_files(main_repo, repo['path']))
    untracked_files = list(_get_dirty_files(main_repo, repo['path'], untracked=True))
    if not changed_files:
        return

    files_in_lines = '\t'.join(map(str, sorted(changed_files + untracked_files)))
    correct = inquirer.confirm(f"Continue making patches for: {files_in_lines}", default=False)
    if not correct:
        sys.exit(-1)

    to_reset = []
    for untracked_file in untracked_files:
        # add with empty blob to index, appears like that then:
        """
        Changes not staged for commit:
        (use "git add <file>..." to update what will be committed)
        (use "git restore <file>..." to discard changes in working directory)
                modified:   roles2/sub1/file2.txt
                new file:   roles2/sub1/file3.txt
        """
        subprocess.check_call(['git', 'add', '-N', untracked_file], cwd=main_repo.working_dir)
        to_reset.append(untracked_file)
        del untracked_file
    subprocess.check_output(["git", "add", str(Path(main_repo.working_dir) / repo['path'])], cwd=main_repo.working_dir)
    subprocess.check_output(["git", "commit", '-m', 'for patch'], cwd=main_repo.working_dir)
    patch_content = subprocess.check_output(["git", "format-patch", "HEAD~1", '--stdout', '--relative'], cwd=str(Path(main_repo.working_dir) / repo['path']))
    subprocess.check_output(["git", "reset", "HEAD~1"], cwd=main_repo.working_dir)

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
    (patch_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + '.patch')).write_bytes(patch_content)

    for to_reset in to_reset:
        subprocess.check_call(['git', 'reset', to_reset], cwd=main_repo.working_dir)

    # commit the patches - do NOT - could lie in submodule - is hard to do
    #subprocess.check_call(['git', 'add', repo['path']], cwd=main_repo.working_dir)
    #subprocess.check_call(['git', 'add', patch_dir], cwd=main_repo.working_dir)
    #subprocess.check_call(['git', 'commit', '-m', 'added patches'], cwd=main_repo.working_dir)



def _update_integrated_module(main_repo, repo, update):
    """
    Put contents of a git repository inside the main repository.
    """
    def _get_cache_dir():
        path = Path(os.path.expanduser("~/.cache/gimera")) / repo['url'].replace(":", "_").replace("/", "_")
        path.parent.mkdir(exist_ok=True, parents=True)
        if not path.exists():
            click.secho(f"Caching the repository {repo['url']} for quicker reuse", fg='yellow')
            subprocess.check_call(['git', 'clone', repo['url'], path])
        return path

    # use a cache directory for pulling the repository and updating it
    local_repo_dir = _get_cache_dir()
    subprocess.check_call(['git', 'checkout', '-f', repo['branch']], cwd=local_repo_dir)
    subprocess.check_call(['git', 'clean', '-xdff'], cwd=local_repo_dir)
    subprocess.check_call(['git', 'pull'], cwd=local_repo_dir)
    if not update and repo.get('sha'):
        branches = list(
            filter(
                bool, map(
                    lambda x: x.strip().replace("* ", ""),
                    subprocess.check_output([
                        'git', 'branch', '--contains', repo['sha']
                        ], cwd=local_repo_dir).decode('utf-8').split('\n'))))
        if repo['branch'] not in branches:
            subprocess.check_call(['git', 'pull'], cwd=local_repo_dir)
            _store(main_repo, repo, {'sha': None})
        else:
            subprocess.check_call(['git', 'config', 'advice.detachedHead', 'false'], cwd=local_repo_dir)
            subprocess.check_call(['git', 'checkout', '-f', repo['sha']], cwd=local_repo_dir)
    dest_path = Path(main_repo.working_dir) / repo['path']
    dest_path.parent.mkdir(exist_ok=True, parents=True)
    subprocess.check_call(['rsync', '-ar', '--exclude=.git', '--delete-after', str(local_repo_dir) + "/", str(dest_path) + "/"], cwd=main_repo.working_dir)
    sha = Repo(local_repo_dir).head.object.hexsha
    _store(main_repo, repo, {'sha': sha})

    # apply patches:
    for dir in repo.get('patches', []):
        dir = Path(main_repo.working_dir) / dir
        for file in sorted(dir.glob("*.patch")):
            print("===============================")
            print(file.read_text())
            print("===============================")
            # subprocess.check_call(['git', 'apply', '--stat', str(file)], cwd=Path(main_repo.working_dir) / repo['path'])
            subprocess.check_output(
                ['patch', '-p1'],
                input=file.read_bytes(),
                cwd=Path(main_repo.working_dir) / repo['path']
                )
            click.secho(f"Applied patch {file.relative_to(main_repo.working_dir)}", fg='blue')

    if list(_get_dirty_files(main_repo, repo['path'])):
        subprocess.check_call(['git', 'add', repo['path']], cwd=main_repo.working_dir)
        subprocess.check_call(['git', 'commit', '-m', f'updated integrated submodule: {repo["path"]}'], cwd=main_repo.working_dir)


def _fetch_latest_commit_in_submodule(main_repo, repo):
    path = Path(main_repo.working_dir) / repo['path']
    if list(_get_dirty_files(main_repo, repo['path'])):
        _raise_error(f"Directory {repo['path']} contains modified files. Please commit or purge before!")
    subprocess.check_call(['git', 'checkout', '-f', repo['branch']], cwd=path)
    subprocess.check_call(['git', 'clean', '-xdff'], cwd=path)
    subprocess.check_call(['git', 'pull'], cwd=path)

def _get_config_file():
    config_file = Path(os.getcwd()) / 'gimera.yml'
    if not config_file.exists():
        _raise_error(f"Did not find: {config_file}")
    return config_file

def _store(main_repo, repo, value):
    config_file = _get_config_file()
    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    param_repo = repo
    for repo in config['repos']:

        if repo['path'] == param_repo['path']:
            repo.update(value)
    config_file.write_text(yaml.dump(config, default_flow_style=False))
    if main_repo.index.diff("HEAD"):
        _raise_error("There mustnt be any staged files when updating gimera.yml")
    subprocess.check_call(['git', 'add', config_file], cwd=main_repo.working_dir)
    if main_repo.index.diff("HEAD"):
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

        if repo.get('type') not in ['submodule', 'integrated']:
            _raise_error("Please provide type for repo {config['path']}: either 'integrated' or 'submodule'")

    return config

def __add_submodule(repo, config):
    path = config['path']

    # branch is added with refs/head/branch1 then instead of branch1 in .gitmodules; makes problems at pull then
    # submodule = repo.create_submodule(name=path, path=path, url=config['url'], branch=config['branch'],)
    if config.get('type') == 'submodule':
        subprocess.check_call(['git', 'submodule', 'add', '--force', '-b', config['branch'], config['url'], path], cwd=repo.working_dir)
        repo.index.add(['.gitmodules'])
        click.secho(f"Added submodule {path} pointing to {config['url']}", fg='yellow')
        repo.index.commit(f"gimera added submodule: {path}") #, author=author, committer=committer)
    elif config.get('type') == 'integrated':
        # nothing to do here - happens at update
        pass


def _apply_repo(repo_config):
    """
    makes sure that git submodules exist for the repo
    """
    if repo_config.get('type') != 'submodule':
        return
    repo = Repo(os.getcwd())
    existing_submodules = list(filter(lambda x: x.path == repo_config['path'], repo.submodules))
    if not existing_submodules:
        __add_submodule(repo, repo_config)
    existing_submodules = list(filter(lambda x: x.path == repo_config['path'], repo.submodules))
    if not existing_submodules:
        _raise_error(f"Error with submodule {repo_config['path']}")
    submodule = existing_submodules[0]
    del existing_submodules

def _get_dirty_files(repo, path, untracked=False):
    files = repo.index.diff(None)

    def perhaps_yield(x):
        try:
            x.relative_to(Path(repo.working_dir) / path)
        except ValueError:
            pass
        else:
            yield x.relative_to(Path(repo.working_dir))

    if not untracked:
        for diff in repo.index.diff(None):
            diff_path = Path(repo.working_dir) / Path(diff.b_path)
            yield from perhaps_yield(diff_path)
    for untracked_file in repo.untracked_files:
        diff_path = Path(repo.working_dir) / Path(untracked_file)
        yield from perhaps_yield(diff_path)
    return files

if os.getenv("GIMERA_DEBUG") == "1":
    @gimera.command(name='is_path_dirty')
    @click.argument("path")
    def is_path_dirty(path):
        path = Path(os.getcwd()) / path

        files = list(_get_dirty_files(Repo(os.getcwd()), path))
        print("\n".join(map(str, files)))


if __name__ == '__main__':
    gimera()
