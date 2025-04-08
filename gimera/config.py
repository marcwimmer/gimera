from pathlib import Path
from copy import deepcopy
import click
import yaml
import os
from contextlib import contextmanager
from .repo import Repo, Remote
from .consts import gitcmd as git
from .tools import (
    _raise_error,
    safe_relative_to,
    is_empty_dir,
    _strip_paths,
    remember_cwd,
)
from .consts import REPO_TYPE_INT, REPO_TYPE_SUB


class Patchdir(object):
    def __init__(self, path, apply_from_here_dir):
        """
        Internal patches must be applied starting from subfolder.
        Patches from the main repo must be applied starting from parent main folder.
        """
        self._path = Path(path)
        self.apply_from_here_dir = apply_from_here_dir

    def __str__(self):
        return f"{self._path}"

    @property
    @contextmanager
    def path(self):
        with remember_cwd(self.apply_from_here_dir):
            path = self._path
            if self.apply_from_here_dir:
                path = self.apply_from_here_dir
            yield path


class Config(object):
    def __init__(
        self, force_type=None, recursive=False, common_vars=None, parent_config=None,
        force_gimera_file=None,
    ):
        self.force_type = force_type
        self._repos = []
        self.recursive = recursive
        self.parent_common_vars = common_vars
        self.parent_config = parent_config
        self.force_gimera_file = force_gimera_file
        self.load_config()

    @property
    def parent_path(self):
        if self.parent_config:
            return self.parent_config.config_file.parent
        else:
            return Path(".")

    @property
    def repos(self):
        return self._repos

    # @property
    # def root_path(self):
    #     p = self
    #     while p.parent_config:
    #         p = p.parent_config
    #     return p.config_file.parent

    def _get_config_file(self):
        if self.force_gimera_file:
            return self.force_gimera_file
        config_file = Path(os.getcwd()) / "gimera.yml"
        if not config_file.exists():
            _raise_error(f"Did not find: {config_file}")
        return config_file

    def load_config(self):
        self._repos = []
        self.config_file = self._get_config_file()

        self.yaml_config = yaml.load(
            self.config_file.read_text(), Loader=yaml.FullLoader
        )
        for repo in self.yaml_config.get("repos", []):
            repoitem = Config.RepoItem(self, repo)
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
                    if k == "sha":
                        v = str(v)
                    repo[k] = v
                break
        else:
            config["repos"].append(value)
        for k, v in value.items():
            try:
                if getattr(param_repo, k) != v:
                    setattr(param_repo, k, v)
            except AttributeError as ex:
                raise Exception(f"Cannot set attribute {k}") from ex
        self.config_file.write_text(yaml.dump(config, default_flow_style=False))
        main_repo.please_no_staged_files()
        if self.config_file.resolve() in [
            x.resolve() for x in main_repo.all_dirty_files
        ]:
            main_repo.X(*(git + ["add", self.config_file]))
        if main_repo.staged_files:
            cmd = ["commit", "-m", "auto update gimera.yml", "--no-verify"]
            main_repo.X(*(git + cmd))

    def get_repos(self, names):
        if not names:
            return self.repos
        if isinstance(names, (Path, str)):
            names = [names]
        names = list(_strip_paths(names))
        res = []

        for item in self.repos:
            if not item.enabled:
                continue
            if str(item.path) in names:
                res.append(item)
                names.remove(str(item.path))
        if names:
            _raise_error(f"Invalid path: {','.join(names)}")
        return res

    class RepoItem(object):
        def __init__(self, config, config_section):
            """ """
            self.config = config
            self._sha = config_section.get("sha", None)
            self.enabled = config_section.get("enabled", True)
            self.freeze_sha = config_section.get("freeze_sha", False)
            self.path = Path(config_section["path"])
            self.branch = self.eval(str(config_section["branch"]))
            self.merges = config_section.get("merges", [])
            self.patches = config_section.get("patches", [])
            self.ignored_patchfiles = config_section.get("ignored_patchfiles", [])
            self.edit_patchfile = config_section.get("edit_patchfile", "")
            self._type = config_section["type"]
            self._url = self.eval(config_section["url"])
            self._remotes = config_section.get("remotes", {})
            if self.path in [x.path for x in config.repos]:
                _raise_error(f"Duplicate path: {self.path}")
            config._repos.append(self)
            self.internal_patch_dirs = []

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

        def ignore_patchfile(self, path):
            if path.name in [Path(x).name for x in self.ignored_patchfiles]:
                click.secho(
                    f"Warning: patchfile {path} is ignored and not applied. As configured.",
                    fg="yellow",
                )
                return True
            if self.edit_patchfile:
                if self.edit_patchfile_full_path == path:
                    return True

        def collect_recursive_informations(self):
            gimera_yml = self.config.config_file.parent / self.path / "gimera.yml"
            if not gimera_yml.exists():
                return
            config = yaml.load(gimera_yml.read_text(), Loader=yaml.FullLoader)
            internal_patch_dirs = config.get("common", {}).get("patches", [])
            self.internal_patch_dirs += internal_patch_dirs

        @property
        def common_vars(self):
            res = deepcopy(self.config.parent_common_vars or {})
            common = self.config.yaml_config.get("common", {})
            res.update(common.get("vars", {}))
            return res

        def eval(self, text):
            for k, v in self.common_vars.items():
                text = text.replace(f"${{{k}}}", str(v))
            if "${" in text:
                _raise_error(f"Please define variables for {text}")
            return text

        def drop_dead(self):
            Config().remove(self.path)

        @property
        def sha(self):
            return self._sha

        @sha.setter
        def sha(self, value):
            self._sha = value
            if not self.freeze_sha and os.getenv("GIMERA_NO_SHA_UPDATE") != "1":
                self.config._store(self, {"sha": value})

        def as_dict(self):
            return {
                "path": self.path,
                "branch": self.branch,
                "patches": self.patches,
                "type": self._type,
                "url": self._url,
                "merges": self.merges,
                "remotes": self._remotes,
            }

        @property
        def url(self):
            return self._url

        @url.setter
        def url(self, value):
            self._url = value

        @property
        def url_public(self):
            url = self._url.replace("ssh://git@", "https://")
            return url

        @property
        def type(self):
            if self.config.force_type:
                return self.config.force_type
            return self._type

        @type.setter
        def type(self, value):
            self._type = value

        def all_patch_dirs(self, rel_or_abs=None):
            if not rel_or_abs:
                raise ValueError("Please define rel_or_abs")

            def transform_outbound_patchdirs(dir):
                patch_path = Path(dir)
                apply_from_here = self.config.parent_path / self.path
                if rel_or_abs == "absolute":
                    root = self.config.config_file.parent
                    patch_path = root / patch_path
                    apply_from_here = root / apply_from_here
                dir = Patchdir(patch_path, apply_from_here)
                return dir

            if isinstance(self.patches, str):
                raise ValueError(
                    f"Patches must be a list. But is {self.patches} for {self.url}"
                )
            res = list(map(transform_outbound_patchdirs, self.patches))

            def transform_internal_patchdir(dir):
                patch_path = Path(self.eval(str(dir)))
                apply_from_here = self.path

                if rel_or_abs == "absolute":
                    root = self.config.config_file.parent
                    patch_path = root / self.path / patch_path
                    apply_from_here = root / apply_from_here
                dir = Patchdir(patch_path, apply_from_here)
                return dir

            res += list(map(transform_internal_patchdir, self.internal_patch_dirs))
            for test in res:
                with test.path as testpath:
                    if not (self.config.config_file.parent / testpath).exists():
                        click.secho(f"Warning: not found: {test}", fg="yellow")
            return res

        @property
        def fullpath(self):
            return self.config.config_file.parent / self.path

        def _get_type_of_patchfolder(self, path):
            for test in self.patches:
                if str(path).startswith(str(test)):
                    return "from_outside"

            for test in self.internal_patch_dirs:
                if str(path).startswith(self.eval(str(test))):
                    return "internal"
            raise ValueError(f"Undefined patchfolder: {path}")

        @property
        def edit_patchfile_full_path(self):
            ttype = self._get_type_of_patchfolder(self.edit_patchfile)
            if (ttype) == "from_outside":
                return self.config.config_file.parent / self.edit_patchfile
            elif ttype == "internal":
                return self.fullpath / self.edit_patchfile
            else:
                raise NotImplementedError(ttype)

        def abs(self, path):
            if str(path).startswith("/"):
                raise ValueError(f"Path must be relative: {path}")
            return self.config.config_file.parent / self.path / path
