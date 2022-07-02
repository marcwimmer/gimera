import subprocess
from .gitcommands import GitCommands
from pathlib import Path
from .tools import yieldlist, X, safe_relative_to, _raise_error


class Repo(GitCommands):
    def __init__(self, path):
        self.path = Path(path)
        self.working_dir = Path(path)

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    def force_remove_submodule(self, path):
        # https://github.com/jeremysears/scripts/blob/master/bin/git-submodule-rewrite
        self.X(
            "git",
            "config",
            "-f",
            ".gitmodules",
            "--remove-section",
            f"submodule.{path}",
        )
        if self.out(
            "git", "config", "-f", ".git/config", "--get", f"submodule.{path}.url"
        ):
            self.X(
                "git",
                "config",
                "-f",
                ".git/config",
                "--remove-section",
                f"submodule.{path}",
            )

        self.X("rm", "-rf", path)
        self.X("git", "add", "-A", path, ".gitmodules")
        self.X("git", "commit", "-m", f"removed submodule {path}")
        self.X("rm", "-rf", f".git/modules/{path}")

    @property
    def hex(self):
        hex = subprocess.check_output(
            ["git", "log", "-n", "1", "--pretty=%H"], encoding="utf-8", cwd=self.path
        ).strip()
        if hex:
            return hex.strip()

    @property
    def next_module_root(self):
        if not self.path.exists():
            return None

        p = self.path
        for i in range(len(p.parts)):
            if (p / ".gitmodules").exists():
                return p
            if (p / ".git").is_dir():
                return p
            p = p.parent
        return self.path

    @yieldlist
    def get_submodules(self):
        submodules = self.out("git", "submodule--helper", "list").splitlines()
        for line in submodules:
            splitted = line.strip().split("\t", 3)
            yield Submodule(self.next_module_root / splitted[-1], self.next_module_root)

    def get_submodule(self, path, force=False):
        if force:
            return Submodule(self.path / path, self.path)

        for submodule in self.get_submodules():
            if str(submodule.path.relative_to(self.path)) == str(Path(path)):
                return submodule
        raise ValueError(f"Path not found: {path}")

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

    def please_no_staged_files(self):
        if not (staged := self.staged_files):
            return
        _raise_error(
            "For the operation there mustnt be " f"any staged files like {staged}"
        )

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
        self.relpath = self.path.relative_to(self.parent_path)

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    def get_url(self):
        url = Repo(self.parent_path).out(
            "git", "config", "-f", ".gitmodules", f"submodule.{self.relpath}.url"
        )
        return url

    def equals(self, other):
        relpath = str(self.path.relative_to(self.parent_path))
        if isinstance(other, str):
            return relpath == other
        if isinstance(other, Path):
            return self.path.absolute() == other.absolute()
        raise NotImplementedError(other)

    def checkout(self, ref, force=False):
        self.X("git", "checkout", "-f" if force else None, ref)
