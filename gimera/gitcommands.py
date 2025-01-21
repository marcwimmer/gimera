import os
from pathlib import Path
from .tools import safe_relative_to, yieldlist, X, wait_git_lock
from .consts import gitcmd as git


class GitCommands(object):
    def __init__(self, path=None):
        self.path = Path(path or os.getcwd())
        self.path_absolute = self.path.absolute()

    @property
    def configdir(self):
        from .repo import Repo

        stop_at = Repo(self.path_absolute).root_repo
        here = self.path_absolute
        while True:
            default = here / ".git"
            if default.exists() and default.is_dir():
                return default
            if default.is_file():
                path = default.read_text().strip().split("gitdir:")[1].strip()
                return (here / path).resolve()

            if here == stop_at:
                break
            here = here.parent
        raise Exception("Config dir not found")

    def X(self, *params, allow_error=False, env=None, output=None):
        if output is None:
            output = False
        with wait_git_lock(self.path_absolute):
            kwparams = {
                "output": output,
                "allow_error": allow_error,
                "env": env,
            }
            if self.path.exists():
                # case not existing at recreating cache dir e.g.
                kwparams["cwd"] = self.path
            return X(*params, **kwparams)

    def out(self, *params, allow_error=False, env=None):
        return X(*params, output=True, cwd=self.path, allow_error=allow_error, env=env)

    def _parse_git_status(self):
        for line in X(
            *(
                git
                + [
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ]
            ),
            cwd=self.path_absolute,
            output=True,
        ).splitlines():
            # splits: A  asdas
            #         M   asdasd
            #          M  asdsad
            #         ??  asasdasd
            modifier = line[:2]
            path = line.strip().split(" ", 1)[1].strip()
            if path.startswith(".."):
                continue

            yield modifier, Path(path)

    @property
    @yieldlist
    def staged_files(self):
        for modifier, path in self._parse_git_status():
            if modifier[0] in ["A", "M", "D"]:
                yield path

    @property
    @yieldlist
    def dirty_existing_files(self):
        for modifier, path in self._parse_git_status():
            if modifier[0] == "M" or modifier[1] == "M" or modifier[1] == "D":
                yield path

    @property
    @yieldlist
    def all_dirty_files(self):
        return self.untracked_files + self.dirty_existing_files

    @property
    @yieldlist
    def all_dirty_files_absolute(self):
        res = self.untracked_files + self.dirty_existing_files
        res = list(map(lambda x: self.path_absolute / x, res))
        return res

    @property
    @yieldlist
    def untracked_files(self):
        for modifier, path in self._parse_git_status():
            if modifier == "??" or modifier[0] == "A":
                yield path

    @property
    @yieldlist
    def untracked_files_absolute(self):
        for file in self.untracked_files:
            yield self.path_absolute / file

    @property
    def dirty(self):
        return bool(list(self._parse_git_status()))

    def is_submodule(self, path):
        path = self._combine(path)
        for line in X(
            *(git + ["submodule", "status"]), output=True, cwd=self.path_absolute
        ).splitlines():
            line = line.strip()
            _, _path, _ = line.split(" ", 2)
            if _path == str(path.relative_to(self.path_absolute)):
                return path

    def _combine(self, path):
        """
        Makes a new path
        """
        path = self.path / path
        path.relative_to(self.path)
        return path

    def output_status(self):
        self.X(*(git + ["status"]))

    def get_all_branches(self):
        """
        4031c5eb19120f76a91b7cd9052bb27c5efe159a refs/heads/17.0
        2e45846285c6afc396a7bbadaa9dad54360ed51c refs/heads/main
        4031c5eb19120f76a91b7cd9052bb27c5efe159a refs/remotes/origin/17.0
        2e45846285c6afc396a7bbadaa9dad54360ed51c refs/remotes/origin/HEAD
        2e45846285c6afc396a7bbadaa9dad54360ed51c refs/remotes/origin/main
        2e45846285c6afc396a7bbadaa9dad54360ed51c refs/remotes/origin/test123
        """
        res = list(
            set(
            filter(
                lambda x: x not in ["HEAD"],
                map(
                    lambda x: x.strip().split()[-1].split("/")[-1],
                    self.out(*(git + ["show-ref"])).splitlines(),
                ),
            )
            )
        )
        return res

    @property
    def dirty(self):
        files = []
        for modifier, path in self._parse_git_status():
            if str(path) == "gimera.yml":
                continue
            files.append(path)
        return bool(files)

    def simple_commit_all(self, msg="."):
        self.X(*(git + ["add", "."]))
        self.X(*(git + ["commit", "--allow-empty", "-am", msg]))

    @property
    def hex(self):
        return self.out(*(git + ["log", "-n", "1", "--pretty=%H"]))

    def checkout(self, ref, force=False):
        self.X(*(git + ["checkout", "-f" if force else None, ref]))
