import os
import click
import json
import git
import yaml
import sys
from git import Repo
from git import Actor
from pathlib import Path

@click.group()
def gimera():
    pass

@gimera.command(name='apply', help="Applies configuration from gimera.yml")
def apply():
    import pudb;pudb.set_trace()
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
        if path.endswith("/X"):
            name = repo['url'].split("/")[-1].replace(".git", "")
        path = path[:-1] + name
        repo['path'] = path
    return config

def __add_submodule(repo, config):
    path = config['path']

    submodule = repo.create_submodule(
        name=path,
        path=path,
        url=config['url'],
    )
    repo.index.add(['.gitmodules'])
    repo.index.commit(f"gimera added submodule: {path}") #, author=author, committer=committer)
    import pudb;pudb.set_trace()
    submodule.module().git.checkout('--track', f"origin/{config['branch']}")
    # submodule.repo.git.branch(f'--set-upstream-to=origin/{config["branch"]}', config['branch'])
    repo.git.config('-f', '.gitmodules', f'submodule.{path}.branch', config['branch'])


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
    #submodule.repo.git.checkout(repo_config['branch'])
    repo.git.pull('--recurse-submodules', '--jobs=10')
    # make sure latest branch is checked out


    # submodule = repos.submodule('submodule-name')
    # submodule.module().git.checkout('wanted commit')

    # add new submodule commit to main repo pythonic from # https://stackoverflow.com/questions/31835812/gitpython-how-to-commit-updated-submodule
    #submodule.binsha = submodule.module().head.commit.binsha
    #repos.index.add([submodule])
    #repos.index.commit("updated submodule to 'wanted commit'")




if __name__ == '__main__':
    gimera()