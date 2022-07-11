import os
from pathlib import Path
from .tools import safe_relative_to, yieldlist, X


class GitCommands(object):
    def __init__(self, path=None):
        self.path = Path(path or os.getcwd())

    @property
    def configdir(self):
        from .repo import Repo
        stop_at = Repo(self.path).root_repo
        here = self.path
        while True:
            default = here / '.git'
            if default.exists() and default.is_dir():
                return default
            if default.is_file():
                path = default.read_text().strip().split("gitdir:")[1].strip()
                return (here / path).resolve()

            if here == stop_at:
                break
            here = here.parent
        raise Exception("Config dir not found")

    def X(self, *params, allow_error=False):
        return X(*params, output=False, cwd=self.path, allow_error=allow_error)

    def out(self, *params, allow_error=False):
        return X(*params, output=True, cwd=self.path, allow_error=allow_error)

    def _parse_git_status(self):
        for line in X(
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            cwd=self.path,
            output=True,
        ).splitlines():
            # splits: A  asdas
            #         M   asdasd
            #          M  asdsad
            #         ??  asasdasd
            modifier = line[:2]
            path = line.strip().split(" ", 1)[1]
            if path.startswith(".."):
                continue
            path = Path(path.strip())
            if parent_path := getattr(self, "parent_path", None):
                path = parent_path / path
            else:
                path = self.path / path
            if safe_relative_to(path, self.path):
                yield modifier, path

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
    def untracked_files(self):
        for modifier, path in self._parse_git_status():
            if modifier == "??" or modifier[0] == "A":
                yield path

    @property
    def dirty(self):
        return bool(list(self._parse_git_status()))

    def is_submodule(self, path):
        path = self._combine(path)
        for line in X(
            "git", "submodule", "status", output=True, cwd=self.path
        ).splitlines():
            line = line.strip()
            _, _path, _ = line.split(" ", 2)
            if _path == str(path.relative_to(self.path)):
                return path

    def _combine(self, path):
        """
        Makes a new path
        """
        path = self.path / path
        path.relative_to(self.path)
        return path

    def output_status(self):
        self.X("git", "status")

    def get_all_branches(self):
        res = list(
            map(
                lambda x: x.strip(),
                self.out(
                    "git", "for-each-ref", "--format=%(refname:short)", "refs/heads"
                ).splitlines(),
            )
        )
        return res

    @property
    def dirty(self):
        files = []
        for modifier, path in self._parse_git_status():
            if str(path.relative_to(self.path)) == "gimera.yml":
                continue
            files.append(path)
        return bool(files)

    def simple_commit_all(self, msg="."):
        self.X("git", "add", ".")
        self.X("git", "commit", "-am", msg)

    @property
    def hex(self):
        return self.out("git", "log", "-n", "1", "--pretty=%H")

    def checkout(self, ref, force=False):
        self.X("git", "checkout", "-f" if force else None, ref)
