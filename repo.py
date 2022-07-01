import subprocess
from .gitcommands import GitCommands
from pathlib import Path
from .tools import yieldlist, X, safe_relative_to

class Repo(GitCommands):

    def __init__(self, path):
        self.path = Path(path)
        self.working_dir = Path(path)

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    @property
    def hex(self):
        hex = subprocess.check_output(
            ["git", "log", "-n", "1", "--pretty=%H"], encoding="utf-8", cwd=self.path
        ).strip()
        if hex:
            return hex.strip()

    def _get_submodules(self):
        submodules = (
            subprocess.check_output(
                ["git", "submodule--helper", "list"], encoding="utf-8", cwd=self.path
            )
            .strip()
            .splitlines()
        )
        for line in submodules:
            splitted = line.strip().split("\t", 3)
            yield Submodule(self.path / splitted[-1], self.path)

    def get_submodule(self, path, force=False):
        if force:
            return Submodule(self.path / path, self.path)

        for submodule in self._get_submodules():
            if str(submodule.path.relative_to(self.path)) == str(Path(path)):
                return submodule
        raise Exception(f"Path not found: {path}")

    def get_submodules(self):
        return list(self._get_submodules())

    def fetch(self, remote=None, ref=None):
        self.X("git", "fetch", remote, ref or None)

    def remove_remote(self, remote):
        self.X("git", "remote", "rm", remote)

    def add_remote(self, name, url):
        self.X("git", "remote", "add", name, url)

    def pull(self, remote=None, ref=None):
        self.X("git", "pull", "--no-edit", remote, ref)

    def full_clean(self):
        self.X("git", "checkout", "-f")
        self.X("git", "clean", "-xdff")

    @property
    @yieldlist
    def remotes(self):
        result = {}
        for line in self.out("git", "remote", "-v").splitlines():
            name, url = line.strip().split("\t")
            v = result.setdefault(name, url)
            if v != url:
                raise NotImplementedError(
                    (
                        "Different urls for push and fetch for remote {name}\n"
                        f"{url} != {v}"
                    )
                )
        return result

    @yieldlist
    def filterout_submodules(self, filelist):
        submodules = self.get_submodules()
        for file in filelist:
            for submodule in submodules:
                if safe_relative_to(file, submodule.path):
                    break
            else:
                yield file


class Remote(object):
    def __init__(self, repo, name, ref):
        self.repo = repo
        self.name = name
        self.ref = ref

class Submodule(Repo):
    def __init__(self, path, parent_path):
        self.path = Path(path)
        self.parent_path = Path(parent_path)
        assert self.path.relative_to(self.parent_path)

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    def equals(self, other):
        relpath = str(self.path.relative_to(self.parent_path))
        if isinstance(other, str):
            return relpath == other
        if isinstance(other, Path):
            return self.path.absolute() == other.path.absolute()
        raise NotImplementedError(other)

    def checkout(self, ref, force=False):
        self.X("git", "checkout", "-f" if force else None, ref)
