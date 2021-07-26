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
    config_file = Path(os.getcwd()) / 'gimera.yml'
    if not config_file.exists():
        click.secho(f"Did not find: {config_file}")
        sys.exit(-1)

    config = load_config(config_file)

    for repo in config['repos']:
        _apply_repo(repo)

def load_config(config_file):
    config = yaml.load(config_file.read_text(), Loader=yaml.FullLoader)
    for repo in config['repos']:
        path = repo['path']
        name = path.split("/")[-1]
        if path.endswith("/"):
            name = repo['url'].split("/")[-1].replace(".git", "")
            path = path + name
        repo['path'] = path
    return config

def __add_submodule(repo, config):
    path = config['path']

    submodule = repo.create_submodule(
        name=path,
        path=path,
        url=config['url'],
        branch=config['branch'],
    )
    repo.index.add(['.gitmodules'])
    click.secho(f"Added submodule {path} pointing to {config['url']}", fg='yellow')
    repo.index.commit(f"gimera added submodule: {path}") #, author=author, committer=committer)


def _apply_repo(repo_config):
    """
    makes sure that git submodules exist for the repo
    """
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

    repo.git.pull('--recurse-submodules', '--jobs=10')


@gimera.command(name='update', help="Fetches latest versions of branches and applies patches")
def update():

    # make sure latest branch is checked out


    # submodule = repos.submodule('submodule-name')
    # submodule.module().git.checkout('wanted commit')

    # add new submodule commit to main repo pythonic from # https://stackoverflow.com/questions/31835812/gitpython-how-to-commit-updated-submodule
    #submodule.binsha = submodule.module().head.commit.binsha
    #repos.index.add([submodule])
    #repos.index.commit("updated submodule to 'wanted commit'")
    pass



if __name__ == '__main__':
    gimera()