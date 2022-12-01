import subprocess
import click
import shutil
from .gitcommands import GitCommands
from pathlib import Path
from .tools import yieldlist, X, safe_relative_to, _raise_error
from .consts import gitcmd as git


class Repo(GitCommands):
    def __init__(self, path):
        self.path = Path(path)
        self.working_dir = Path(path)

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    @property
    def rel_path_to_root_repo(self):
        assert str(self.path).startswith("/")
        return self.path.relative_to(self.root_repo.path)
    
    @property
    def root_repo(self):
        path = self.path
        for i in path.parts:
            if (path / ".git").is_dir():
                return Repo(path)
            path = path.parent
        else:
            return None
    @property
    def _git_path(self):
        return (self.path / ".git")

    def ls_files_states(self, params):
        """
        e.g. ls_files_states("-dmosk" )
        """
        if "-t" not in params:
            params += ["-t"]

        def extract(line):
            if "\t" in line:
                return line.split("\t")[-1]
            return line[2:]

        files = list(
            map(
                lambda line: Path(extract(line)),
                self.out(*(["git", "ls-files"] + params)).splitlines(),
            )
        )
        return files

    def force_remove_submodule(self, path):
        # https://github.com/jeremysears/scripts/blob/master/bin/git-submodule-rewrite
        self.please_no_staged_files()

        # if there are dirty files, then abort to not destroy data
        dirty_files = self.ls_files_states(["-dmok"])
        dirty_files = list(
            filter(
                lambda file: not file.is_dir()
                and safe_relative_to(self.path / file, self.path / path),
                dirty_files,
            )
        )
        fullpath = self.path / path
        if fullpath.exists():
            self.X(
                "git",
                "config",
                "-f",
                ".gitmodules",
                "--remove-section",
                f"submodule.{path}",
                allow_error=True,
            )
            if self.out(
                "git",
                "config",
                "-f",
                self.configdir / "config",
                "--get",
                f"submodule.{path}.url",
                allow_error=True,
            ):
                self.X(
                    "git",
                    "config",
                    "-f",
                    self.configdir / "config",
                    "--remove-section",
                    f"submodule.{path}",
                )

        subrepo = Repo(self.path / path)
        self.X("rm", "-rf", path)
        if fullpath.exists():
            self.X("git", "add", "-A", path)
        if self.lsfiles(fullpath.relative_to(self.path)):
            self.X("git", "add", "-A", path)
        if (self.path / ".gitmodules") in self.all_dirty_files:
            self.X("git", "add", "-A", ".gitmodules")

        if self.staged_files:
            self.X("git", "commit", "-m", f"removed submodule {path}")
        self.X("rm", "-rf", f".git/modules/{subrepo.rel_path_to_root_repo}")

    @property
    def next_module_root(self):
        if not self.path.exists():
            return None

        p = self.path
        for i in range(len(p.parts)):
            if (p / ".git").exists():
                return p
            p = p.parent
        return self.path

    @yieldlist
    def get_submodules(self):
        submodules = self.out("git", "submodule", "status").splitlines()
        for line in submodules:
            splitted = line.strip().split(" ")
            yield Submodule(self.next_module_root / splitted[1], self.next_module_root)

    def _fix_to_remove_subdirectories(self, config):
        # https://stackoverflow.com/questions/4185365/no-submodule-mapping-found-in-gitmodule-for-a-path-thats-not-a-submodule
        # commands may block
        # git submodule--helper works and shows something
        # git submodule says: fatal: no submodule mapping found in .gitmodules
        # there is special folder with id 16000 then, then must be removed with git rm
        # then; not tested, because then it suddenly worked
        lines = [
            x
            for x in self.out("git", "ls-files", "--stage").splitlines()
            if x.strip().startswith("160000")
        ]
        # 160000 5e8add9536e584f73ea25d4cf51577832d480e90 0       addons_robot
        for line in lines:
            linepath = line.split("\t", 1)[1]
            path = self.path / linepath
            if path.exists():
                from .gimera import REPO_TYPE_SUB

                if not [
                    x
                    for x in config.repos
                    if x.path == path and x.ttype == REPO_TYPE_SUB
                ]:
                    continue
                self.please_no_staged_files()
                # if .gitmodules is dirty then commit that first, otherwise:
                # fatal: please stage your changes to .gitmodules or stash them to proceed
                if (self.path / ".gitmodules") in self.all_dirty_files:
                    self.X("git", "add", ".gitmodules")
                    self.X(
                        "git",
                        "commit",
                        "-m",
                        "gimera fix to removed subdirs: .gitmodules",
                    )
                self.X("git", "rm", "-f", linepath)
                self.X("git", "commit", "-m", f"removed invalid subrepo: {linepath}")

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

    def pull(self, remote=None, ref=None, repo_yml=None):
        """
        The git reset hard way was necessary in a live repository; local files
        had to be overridden that stand in the way

        This was too weak:
        self.X("git", "pull", "--no-edit", remote and remote.name or None, ref)


        "params remote": remote object

        """
        if repo_yml:
            assert not remote
            assert not ref
            remote = "origin"
            ref = repo_yml.branch

        if remote and not isinstance(remote, str):
            remote = remote.name

        if not remote and not ref:
            raise Exception("Requires remote and ref or yaml configuration.")

        self.X("git", "pull", "--no-edit", "--no-rebase", remote, ref)

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
        check = self.path / config.path
        dont_go_beyond = self.path / Path(config.path).parts[0]
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

    def lsfiles(self, path):
        files = list(
            map(lambda x: Path(x), self.out("git", "ls-files", path).splitlines())
        )
        return files

    def commit_dir_if_dirty(self, rel_path, commit_msg):
        # commit updated directories
        if any(
            map(
                lambda filepath: safe_relative_to(filepath, self.path / rel_path),
                self.all_dirty_files,
            )
        ):
            self.X("git", "add", rel_path)
            # if there are no staged files, it can be, that below that, there is a
            # submodule which changed files; then after git add it is not added
            if self.staged_files:
                self.X(
                    "git",
                    "commit",
                    "-m",
                    commit_msg,
                )

    def submodule_add(self, branch, url, rel_path):
        commands = git + [
            "submodule",
            "add",
            "--force",
            "-b",
            str(branch),
            url,
            rel_path,
        ]
        try:
            self.out(*commands)
        except subprocess.CalledProcessError:
            self._remove_internal_submodule_clone(self.rel_path_to_root_repo / rel_path)
            if (self.path / rel_path).exists():
                shutil.rmtree(self.path / rel_path)
            self.out(*commands)

    def _remove_internal_submodule_clone(self, rel_path_to_root):
        repo = self.root_repo
        root = repo.path / ".git" / "modules"
        parts = list(rel_path_to_root.parts)
        while parts:
            part = parts.pop(0)
            if not parts:
                # kill
                next_path = root / part
                if next_path.exists():
                    shutil.rmtree(next_path)
                else:
                    _raise_error(
                        f"Could not delete submodule {part} in {root} - not found"
                    )

            else:
                next_path = root / part / "modules"
                if next_path.exists():
                    root = next_path
                else:
                    _raise_error(f"Could not find submodule in .git for {part}")


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

    def get_url(self, noerror=True):
        try:
            url = Repo(self.parent_path).out(
                "git", "config", "-f", ".gitmodules", f"submodule.{self.relpath}.url"
            )
        except subprocess.CalledProcessError:
            if not noerror:
                raise
            url = ""
        return url

    def equals(self, other):
        relpath = str(self.path.relative_to(self.parent_path))
        if isinstance(other, str):
            return relpath == other
        if isinstance(other, Path):
            return self.path.absolute() == other.absolute()
        raise NotImplementedError(other)
