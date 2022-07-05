import subprocess
import shutil
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

    @property
    def root_repo(self):
        path = self.path
        for i in path.parts:
            if (path / '.git').is_dir():
                return Repo(path)
            path = path.parent
        else:
            return None

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
            "git", "config", "-f", self.configdir / 'config', "--get", f"submodule.{path}.url"
        ):
            self.X(
                "git",
                "config",
                "-f",
                self.configdir / 'config',
                "--remove-section",
                f"submodule.{path}",
            )

        self.X("rm", "-rf", path)
        self.X("git", "add", "-A", path, ".gitmodules")
        self.X("git", "commit", "-m", f"removed submodule {path}")
        self.X("rm", "-rf", f".git/modules/{path}")

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
        self.X("git", "fetch", remote and remote.name or None, ref or None)

    def get_remote(self, name):
        return [x for x in self.remotes if x.name == name][0]

    def remove_remote(self, remote):
        self.X("git", "remote", "rm", remote and remote.name or None)

    def add_remote(self, repo):
        self.X("git", "remote", "add", repo.name, repo.url)

    def pull(self, remote=None, ref=None):
        self.X("git", "pull", "--no-edit", remote and remote.name or None, ref)

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
            url = url.split("(")[0].rstrip()
            v = result.setdefault(name, url)
            if str(v) != str(url):
                raise NotImplementedError(
                    (
                        "Different urls for push and fetch for remote {name}\n"
                        f"{url} != {v}"
                    )
                )
            yield Remote(self, name, url)
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

    def clear_empty_subpaths(self, config):
        """
        If subrepo is at ./path1/path2/path3 and it is removed,
        then path1/path2 stays. This leads to dirty files and unneeded files causing
        problems at switch submodules to integrated and back.

        Be careful to integrate gitignore patterns.
        """
        check = self.path / config['path']
        dont_go_beyond = self.path / Path(config['path']).parts[0]
        while check.exists():
            # removing untracked and ignored files
            # there may also be the case of "excluded" files - never used this,
            # but possible;
            self.X("git", "clean", "-fd", self.path / check)
            if not safe_relative_to(check, dont_go_beyond):
                break
            if not check.exists():
                check = check.parent
                continue
            if not list(check.iterdir()):
                shutil.rmtree(check)
            check = check.parent
            if not safe_relative_to(check, self.path):
                break


class Remote(object):
    def __init__(self, repo, name, url):
        self.repo = repo
        self.name = name
        self.url = url


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
