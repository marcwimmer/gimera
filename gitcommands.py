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

    @property
    @yieldlist
    def staged_files(self):
        for file in subprocess.check_output(
            ["git", "diff", "--name-only", "--cached"], cwd=self.path, encoding="utf-8"
        ).splitlines():
            file = self.path / file
            file = file.relative_to(self.path)
            if not file:
                continue
            yield file

    @property
    @yieldlist
    def dirty_existing_files(self):
        for file in subprocess.check_output(
            ["git", "diff", "--name-only"], cwd=self.path, encoding="utf-8"
        ).splitlines():
            file = self.path / file
            file = file.relative_to(self.path)
            if not file:
                continue
            yield file

    @property
    @yieldlist
    def all_dirty_files(self):
        return self.untracked_files + self.dirty_existing_files

    @property
    @yieldlist
    def untracked_files(self):
        for file in subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "."], cwd=self.path, encoding="utf-8"
        ).splitlines():
            file = self.path / file
            file = file.relative_to(self.path)
            if not file:
                continue
            yield file