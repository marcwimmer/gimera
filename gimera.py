import os
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

@gimera.command(name='apply', help="Applies configuration from gimera.yml")
def apply():
    config = load_config()

    for repo in config['repos']:
        _apply_repo(repo)
        del repo

    main_repo = Repo(os.getcwd())
    # main_repo.git.pull('--recurse-submodules', '--jobs=10')

    for repo in config['repos']:
        if not repo.get('type'):
            repo['type'] = 'integrated'

        if repo.get('type') == 'submodule':
            _fetch_latest_commit_in_submodule(main_repo, repo)
        elif repo.get('type') == 'integrated':
            if not repo.get('patches'):
                click.secho(f"Please provide at least one path where to search patches for {repo['url']} with key patches.", fg='red')
                sys.exit(-1)
            _update_integrated_module(main_repo, repo)


def _update_integrated_module(main_repo, repo):
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
    dest_path = Path(main_repo.working_dir) / repo['path']
    dest_path.parent.mkdir(exist_ok=True, parents=True)
    subprocess.check_call(['rsync', '-arP', '--exclude=.git', '--delete-after', str(local_repo_dir) + "/", str(dest_path) + "/"], cwd=main_repo.working_dir)


def _fetch_latest_commit_in_submodule(main_repo, repo):
    path = Path(main_repo.working_dir) / repo['path']
    subprocess.check_call(['git', 'checkout', '-f', repo['branch']], cwd=path)
    subprocess.check_call(['git', 'clean', '-xdff'], cwd=path)
    subprocess.check_call(['git', 'pull'], cwd=path)

def load_config():
    config_file = Path(os.getcwd()) / 'gimera.yml'
    if not config_file.exists():
        click.secho(f"Did not find: {config_file}")
        sys.exit(-1)

    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    for repo in config['repos']:
        path = repo['path']
        name = path.split("/")[-1]
        if path.endswith("/"):
            name = repo['url'].split("/")[-1].replace(".git", "")
            path = path + name
        repo['path'] = path

        if repo.get('type') not in ['submodule', 'integrated']:
            click.secho("Please provide type for repo {config['path']}: either 'integrated' or 'submodule'", fg='red')
            sys.exit(-1)

    return config

def __add_submodule(repo, config):
    path = config['path']

    # branch is added with refs/head/branch1 then instead of branch1 in .gitmodules; makes problems at pull then
    # submodule = repo.create_submodule(name=path, path=path, url=config['url'], branch=config['branch'],)
    if config.get('type') == 'submodule':
        subprocess.check_call(['git', 'submodule', 'add', '-b', config['branch'], config['url'], path], cwd=repo.working_dir)
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
        click.secho(f"Error with submodule {repo_config['path']}", fg='red')
        sys.exit(-1)
    submodule = existing_submodules[0]
    del existing_submodules


@gimera.command(name='update', help="Fetches latest versions of branches and applies patches")
def update():
    apply()

    # make sure latest branch is checked out


    # submodule = repos.submodule('submodule-name')
    # submodule.module().git.checkout('wanted commit')

    # add new submodule commit to main repo pythonic from # https://stackoverflow.com/questions/31835812/gitpython-how-to-commit-updated-submodule
    #submodule.binsha = submodule.module().head.commit.binsha
    #repos.index.add([submodule])
    #repos.index.commit("updated submodule to 'wanted commit'")
    pass

def _get_dirty_files(repo, path):
    files = repo.index.diff(None)

    def perhaps_yield(x):
        try:
            x.relative_to(path)
        except ValueError:
            pass
        else:
            yield x.relative_to(Path(repo.working_dir))

    for diff in repo.index.diff(None):
        diff_path = Path(repo.working_dir) / Path(diff.b_path)
        yield from perhaps_yield(diff_path)
    for untracked_file in repo.untracked_files:
        diff_path = Path(repo.working_dir) / Path(untracked_file)
        yield from perhaps_yield(diff_path)
    return files


@gimera.command(name='is_path_dirty')
@click.argument("path")
def is_path_dirty(path):
    path = Path(os.getcwd()) / path

    files = list(_get_dirty_files(Repo(os.getcwd()), path))
    print("\n".join(map(str, files)))


if __name__ == '__main__':
    gimera()