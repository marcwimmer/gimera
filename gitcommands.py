import subprocess
from pathlib import Path
from .tools import yieldlist, X


class GitCommands(object):
    def __init__(self, path):
        self.path = path

    @property
    def is_dirty(self):
        dirty = X("git", "status", "-s", cwd=self.path, output=True)
        return bool(dirty)

    def _parse_git_status(self):
        for line in X(
            "git", "status", "--porcelain", cwd=self.path, output=True
        ).splitlines():
            # splits: A  asdas
            #         ??  asasdasd
            modifier, path = list(filter(bool, line.split(" ")))
            if path.startswith(".."):
                continue
            path = Path(path.strip())
            path = self.path / path
            yield modifier, path

    @property
    @yieldlist
    def staged_files(self):
        for modifier, path in self._parse_git_status():
            if modifier == "A":
                yield path

    @property
    @yieldlist
    def dirty_existing_files(self):
        for modifier, path in self._parse_git_status():
            if modifier == "M":
                yield path

    @property
    @yieldlist
    def all_dirty_files(self):
        return self.untracked_files + self.dirty_existing_files

    @property
    @yieldlist
    def untracked_files(self):
        for modifier, path in self._parse_git_status():
            if modifier == "??" or modifier == "A":
                yield path

    def is_submodule(self, path):
        path = self._combine(path)
        for line in X("git", "submodule", "status", output=True, cwd=self.path).splitlines():
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
