import subprocess
from pathlib import Path
from .tools import yieldlist


class GitCommands(object):
    def __init__(self, path):
        self.path = path

    @property
    def is_dirty(self):
        dirty = subprocess.check_output(["git", "status", "-s"], cwd=self.path).strip()
        return bool(dirty)

    def _parse_git_status(self):
        for line in subprocess.check_output(
            ["git", "status", "--porcelain"], encoding="utf8", cwd=self.path
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
