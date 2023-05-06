from pathlib import Path
import click
import yaml
import os
from contextlib import contextmanager
from .repo import Repo, Remote
from .tools import (
    _raise_error,
    safe_relative_to,
    is_empty_dir,
    _strip_paths,
    remember_cwd,
)
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB


class Patchdir(object):
    def __init__(self, path, root_dir):
        self._path = Path(path)
        self.root_dir = root_dir

    def __str__(self):
        return f"{self.path}"

    @property
    @contextmanager
    def path(self):
        with remember_cwd(self.root_dir):
            path = self._path
            if self.root_dir:
                path = self.root_dir
            yield path


class Config(object):
    def __init__(self, force_type=None, recursive=False):
        self.force_type = force_type
        self._repos = []
        self.recursive = recursive
        self.load_config()

    @property
    def repos(self):
        return self._repos

    def _get_config_file(self):
        config_file = Path(os.getcwd()) / "gimera.yml"
        if not config_file.exists():
            _raise_error(f"Did not find: {config_file}")
        return config_file

    def load_config(self):
        self.config_file = self._get_config_file()

        self.yaml_config = yaml.load(
            self.config_file.read_text(), Loader=yaml.FullLoader
        )
        for repo in self.yaml_config.get("repos", []):
            repoitem = Config.RepoItem(self, repo)
            if self.recursive:
                repoitem.collect_recursive_informations()

    def remove(self, path):
        config = yaml.load(self.config_file.read_text(), Loader=yaml.FullLoader)
        repos = config["repos"]
        repos2 = []
        for repo in repos:
            if (
                Path(repo["path"]).resolve().absolute()
                != Path(path).resolve().absolute()
            ):
                repos2.append(repo)
        config["repos"] = repos2
        self.config_file.write_text(yaml.dump(config, default_flow_style=False))

    def _store(self, repo, value):
        """
        Makes a commit of the changes.
        """
        main_repo = Repo(self.config_file.parent)
        if main_repo.staged_files:
            _raise_error("There mustnt be any staged files when updating gimera.yml")

        config = yaml.load(self.config_file.read_text(), Loader=yaml.FullLoader)
        param_repo = repo
        for repo in config["repos"]:
            if Path(repo["path"]) == param_repo.path:
                for k, v in value.items():
                    repo[k] = v
                break
        else:
            config["repos"].append(value)
        self.config_file.write_text(yaml.dump(config, default_flow_style=False))
        main_repo.please_no_staged_files()
        if self.config_file.resolve() in [
            x.resolve() for x in main_repo.all_dirty_files
        ]:
            main_repo.X("git", "add", self.config_file)
        if main_repo.staged_files:
            main_repo.X("git", "commit", "-m", "auto update gimera.yml")

    class RepoItem(object):
        def __init__(self, config, config_section):
            """ """
            self.config = config
            self._sha = config_section.get("sha", None)
            self.enabled = config_section.get("enabled", True)
            self.path = Path(config_section["path"])
            self.branch = self.eval(str(config_section["branch"]))
            self.merges = config_section.get("merges", [])
            self.patches = config_section.get("patches", [])
            self._type = config_section["type"]
            self._url = self.eval(config_section["url"])
            self._remotes = config_section.get("remotes", {})
            if self.path in [x.path for x in config.repos]:
                _raise_error(f"Duplicate path: {self.path}")
            config._repos.append(self)
            self.additional_patch_dirs = []

            self.remotes = self._remotes.items() or None

            if self.merges:
                _merges = []
                for merge in self.merges:
                    remote, ref = merge.split(" ")
                    _merges.append((remote.strip(), ref.strip()))
                self.merges = _merges

            if self.type not in [REPO_TYPE_SUB, REPO_TYPE_INT]:
                _raise_error(
                    "Please provide type for repo "
                    f"{self.path}: either '{REPO_TYPE_INT}' or '{REPO_TYPE_SUB}'"
                )

        def collect_recursive_informations(self):
            working_dir = self.config.config_file.parent / self.path
            working_dir = working_dir.absolute()
            gimera_yml = working_dir / "gimera.yml"
            if not gimera_yml.exists():
                return
            config = yaml.load(gimera_yml.read_text(), Loader=yaml.FullLoader)
            additional_patch_dirs = config.get("common", {}).get("patches", [])

            def transform_patchdir(dir):
                root = working_dir
                return Patchdir(root / dir, root)

            self.additional_patch_dirs += list(
                map(transform_patchdir, additional_patch_dirs)
            )

        @property
        def common_vars(self):
            return self.config.yaml_config.get("common", {}).get("vars", {})

        def eval(self, text):
            for k, v in self.common_vars.items():
                text = text.replace(f"${{{k}}}", v)
            return text

        def drop_dead(self):
            Config().remove(self.path)

        @property
        def sha(self):
            return self._sha

        @sha.setter
        def sha(self, value):
            self._sha = value
            self.config._store(self, {"sha": value})

        def as_dict(self):
            return {
                "path": self.path,
                "branch": self.branch,
                "patches": self.patches,
                "type": self._type,
                "url": self._url,
                "merges": self._merges,
                "remotes": self._remotes,
            }

        @property
        def url(self):
            return self._url

        @property
        def url_public(self):
            url = self._url.replace("ssh://git@", "https://")
            return url

        @property
        def type(self):
            if self.config.force_type:
                return self.config.force_type
            return self._type

        def all_patch_dirs(self):
            def transform_local_patchdirs(dir):
                root = self.config.config_file.parent / self.path
                dir = self.config.config_file.parent / dir
                return Patchdir(dir, root)

            res = list(map(transform_local_patchdirs, self.patches))

            res += list(self.additional_patch_dirs)

            def eval(dir):
                dir._path = Path(self.eval(str(dir._path)))
                dir.root_dir = Path(self.eval(str(dir.root_dir)))
                return dir

            res = list(map(eval, res))
            for test in res:
                with test.path as testpath:
                    if not testpath.exists():
                        click.secho(f"Warning: not found: {test}", fg="yellow")
            return res
