import uuid
import os
import subprocess
import click
import shutil
from .gitcommands import GitCommands
from pathlib import Path
from .tools import yieldlist, X, safe_relative_to, _raise_error, rmtree
from .consts import gitcmd as git
from contextlib import contextmanager
from .tools import is_forced
from .tools import temppath
from .tools import filter_files_to_folders
from .tools import split_every


class Repo(GitCommands):
    def __init__(self, path):
        super().__init__(path)
        self.is_submodule = False

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    def is_path_a_submodule(self, path):
        assert not str(path).startswith("/")
        for subm in self.get_submodules():
            if subm.path == self.path / path:
                return subm
        return False

    def contain_commit(self, commit):
        try:
            self.X(*(git + ["cat-file", "-t", commit]))
            return True
        except Exception as ex:
            return False

    def contains_branch(self, branch):
        try:
            self.X(
                *(git + ["rev-parse", "--verify", branch]),
                output=True,
            )
            return True
        except Exception as ex:
            return False

    def get_branch(self):
        try:
            res = self.X(
                *(git + ["symbolic-ref", "--short", "HEAD"]),
                output=True,
                env={
                    "PAGER": "",
                    "GIT_PAGER": "",
                },
            )
            return res.splitlines()[0]
        except Exception as ex:
            return None

    def get_commit(self):
        try:
            res = self.X(
                *(git + ["log", "-n", "1", "--format=%H"]),
                output=True,
                env={
                    "PAGER": "",
                    "GIT_PAGER": "",
                },
            )
            return res
        except Exception as ex:
            return False

    def contains(self, commit):
        try:
            self.X(
                *(git + ["branch", "--contains", commit]),
                env={
                    "PAGER": "",
                    "GIT_PAGER": "",
                },
            )
            return True
        except Exception as ex:
            return False

    @property
    def is_bare(self):
        answer = self.out(*(git + ["rev-parse", "--is-bare-repository"]))
        return answer.strip() == "true"

    @property
    def rel_path_to_root_repo(self):
        assert str(self.path).startswith("/")
        return self.path.relative_to(self.root_repo.path)

    @property
    def root_repo(self):
        path = self.path
        for _ in path.parts:
            if (path / ".git").is_dir():
                return Repo(path)
            path = path.parent
        return None

    @property
    def _git_path(self):
        return self.path / ".git"

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
                self.out(*(git + ["ls-files"] + params)).splitlines(),
            )
        )
        return files

    def force_remove_submodule(self, path):
        # https://github.com/jeremysears/scripts/blob/master/bin/git-submodule-rewrite
        self.please_no_staged_files()

        # if there are dirty files, then abort to not destroy data
        dirty_files = list(
            filter_files_to_folders(
                self.all_dirty_files_absolute,
                [self.path_absolute / path],
            )
        )
        if dirty_files:
            if not is_forced():
                _raise_error(f"Path is dirty: {path}. Changes would be lost.")
        fullpath = self.path / path
        if fullpath.exists():
            self.X(
                *(
                    git
                    + [
                        "config",
                        "-f",
                        ".gitmodules",
                        "--remove-section",
                        f"submodule.{path}",
                    ]
                ),
                allow_error=True,
            )
            if self.out(
                *(
                    git
                    + [
                        "config",
                        "-f",
                        self.configdir / "config",
                        "--get",
                        f"submodule.{path}.url",
                    ]
                ),
                allow_error=True,
            ):
                self.X(
                    *(
                        git
                        + [
                            "config",
                            "-f",
                            self.configdir / "config",
                            "--remove-section",
                            f"submodule.{path}",
                        ]
                    )
                )

        subrepo = Repo(self.path / path)
        self.X("rm", "-rf", path)
        if fullpath.exists():
            self.X(*(git + ["add", "-A", path]))
        if self.lsfiles(fullpath.relative_to(self.path)):
            self.X(*(git + ["add", "-f", "-A", path]))
        if (self.path_absolute / ".gitmodules") in self.all_dirty_files_absolute:
            self.X(*(git + ["add", "-A", ".gitmodules"]))

        if self.staged_files:
            self.X(*(git + ["commit", "-q", "-m", f"removed submodule {path}"]))
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

    def get_submodules_with_new_commits(self):
        submodules = self.out(*(git + ["submodule", "status"])).splitlines()
        for line in submodules:
            splitted = line.strip().split(" ")
            if line.startswith("+") or splitted[1] == "./":
                yield Submodule(
                    self.next_module_root / splitted[1], self.next_module_root
                )

    @yieldlist
    def get_submodules(self):
        submodules = self.out(*(git + ["submodule", "status"])).splitlines()
        # no entry found for x in .gitmodules
        for line in submodules:
            splitted = line.strip().split(" ")
            if line.startswith("-") or splitted[1] == "./":
                # means, that path does not exist right now; path info is misleading ./
                continue
            yield Submodule(self.next_module_root / splitted[1], self.next_module_root)

    def check_ignore(self, path):
        try:
            self.X(*(git + ["check-ignore", "-q", path]), allow_error=False)
        except subprocess.CalledProcessError:
            return False
        else:
            return True

    def _fix_to_remove_subdirectories(self, config):
        # https://stackoverflow.com/questions/4185365/no-submodule-mapping-found-in-gitmodule-for-a-path-thats-not-a-submodule
        # commands may block
        # git submodule--helper works and shows something
        # git submodule says: fatal: no submodule mapping found in .gitmodules
        # there is special folder with id 16000 then, then must be removed with git rm
        # then; not tested, because then it suddenly worked
        lines = [
            x
            for x in self.out(*(git + ["ls-files", "--stage"])).splitlines()
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
                    self.X(*(git + ["add", ".gitmodules"]))
                    self.X(
                        *(
                            git
                            + [
                                "commit",
                                "-q",
                                "-m",
                                "gimera fix to removed subdirs: .gitmodules",
                            ]
                        )
                    )
                self.X(*(git + ["rm", "-f", linepath]))
                self.X(
                    *(git + ["commit", "-q", "-m", f"removed invalid subrepo: {linepath}"])
                )

    def get_submodule(self, path):
        for submodule in self.get_submodules():
            if str(submodule.path.relative_to(self.path)) == str(Path(path)):
                return submodule
        raise ValueError(f"Path not found: {path}")

    def fetch(self, remote=None, ref=None):
        self.X(*(git + ["fetch", remote and remote.name or None, ref or None]))

    def get_remote(self, name):
        return [x for x in self.remotes if x.name == name][0]

    def set_remote_url(self, name, url):
        remote = Remote(self, name, url)
        # do not fetch; could point to https form which requires authentication
        self.add_remote(remote, exist_ok=True, no_set_url=True, fetch=False)
        self.X(
            *(git + ["remote", "set-url", name, url]), env={"GIT_TERMINAL_PROMPT": "0"}
        )

    def remove_remote(self, remote):
        self.X(
            *(
                git
                + [
                    "remote",
                    "rm",
                    remote and remote.name or None,
                ]
            ),
            env={"GIT_TERMINAL_PROMPT": "0"},
        )

    def add_remote(self, remote, exist_ok=False, no_set_url=False, fetch=True):
        output = self.out(
            *(git + ["remote"]), env={"GIT_TERMINAL_PROMPT": "0"}
        ).splitlines()
        if [x for x in output if x.strip() == remote.name]:
            if not no_set_url:
                self.set_remote_url(remote.name, remote.url)
        else:
            self.X(
                *(
                    git
                    + [
                        "remote",
                        "add",
                        remote.name,
                        remote.url,
                    ]
                ),
                env={"GIT_TERMINAL_PROMPT": "0"},
            )
        if fetch:
            self.X(*(git + ["fetch", remote.name]), env={"GIT_TERMINAL_PROMPT": "0"})

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

        self.X(*(git + ["pull", "--no-edit", "--no-rebase", remote, ref]))

    def full_clean(self):
        self.X(*(git + ["checkout", "-f"]))
        self.X(*(git + ["clean", "-xdff"]))

    def please_no_staged_files(self):
        staged = self.staged_files
        if not staged:
            return
        _raise_error(
            "For the operation there mustnt be " f"any staged files like {staged}"
        )

    @property
    def remotes(self):
        result = {}
        for line in self.out(*(git + ["remote", "-v"])).splitlines():
            name, url = line.strip().split("\t")
            url = url.split("(")[0].rstrip()
            repo = Remote(self, name, url)
            v = result.setdefault(name, repo)
            if str(v.url) != str(url):
                raise NotImplementedError(
                    (
                        "Different urls for push and fetch for remote {name}\n"
                        f"{url} != {v}"
                    )
                )
            result[name] = repo
        return result.values()

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
            self.X(*(git + ["clean", "-fd", self.path / check]))
            if not safe_relative_to(check, dont_go_beyond):
                break
            if not check.exists():
                check = check.parent
                continue
            if not list(check.iterdir()):
                rmtree(check)
            check = check.parent
            if not safe_relative_to(check, self.path):
                break

    def lsfiles(self, path):
        files = list(map(Path, self.out(*(git + ["ls-files", path])).splitlines()))
        return files

    def commit_dir_if_dirty(self, rel_path, commit_msg, force=False):
        # commit updated directories
        ammend = False
        if any(
            map(
                lambda filepath: safe_relative_to(filepath, self.path / rel_path),
                self.all_dirty_files_absolute,
            )
        ):
            add_cmd = git + ["add"]
            if force:
                add_cmd += ["-f"]
            add_cmd += [rel_path]
            self.X(*add_cmd)
            # if there are no staged files, it can be, that below that, there is a
            # submodule which changed files; then after git add it is not added
            if self.staged_files:
                gitcmd = [
                            "commit",
                            "-q",
                            "--no-verify",
                            "-m",
                            commit_msg,
                        ]
                self.X(
                    *(
                        git
                        + gitcmd
                    )
                )
                ammend = True

                self.run_precommit_if_installed(rel_path, ammend=ammend)

    def run_precommit_if_installed(self, rel_path, ammend=False):
        if os.getenv("GIMERA_NO_PRECOMMIT") == "1":
            return
        if self.is_precommit_used():
            if not shutil.which('pre-commit'):
                print(f"Command 'pre-commit' not found in PATH")
            self.X(
                *tuple(
                    ["pre-commit", "run", "--from-ref", "HEAD~1", "--to-ref", "HEAD"]
                ),
                allow_error=True,
            )

            gitcmd = ["commit", "-q", "--no-verify"]
            if ammend:
                gitcmd += ["--amend", "--no-edit"]
            else:
                gitcmd += ["-m", f"pre-commit run for {rel_path}"]

            dirty_files = list(
                filter_files_to_folders(
                    self.all_dirty_files_absolute,
                    [self.path_absolute / rel_path],
                )
            )
            if dirty_files:
                self.X(*(git + ["add", rel_path]))
                self.X(*(git + gitcmd))

    def is_precommit_used(self):
        candidates = [
            self.root_repo.path / ".pre-commit-config.yaml",
            self.root_repo.path / ".pre-commit-config.yml",
        ]
        return any(x.exists() for x in candidates)

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
        except subprocess.CalledProcessError as ex:
            rel_path_repo = safe_relative_to(self.path, self.root_repo.path)
            # self._remove_internal_submodule_clone(self.rel_path_to_root_repo / rel_path)
            self._remove_internal_submodule_clone(rel_path_repo / rel_path.parts[0])
            if (self.path / rel_path).exists():
                rmtree(self.path / rel_path)
            self.out(*commands)

    def _remove_internal_submodule_clone(self, rel_path_to_root):
        # switching integrated/submodule often makes weird conflicts;
        repo = self.root_repo
        root = repo.path / ".git" / "modules"
        # if root.exists():
        #     shutil.rmtree(root)
        #     return
        parts = list(rel_path_to_root.parts)
        next_path = root
        while parts:
            part = parts.pop(0)
            if not parts:
                # kill
                if next_path.exists():
                    rmtree(next_path)
                else:
                    _raise_error(
                        f"Could not delete submodule {part} in {root} - not found"
                    )

            else:
                next_path = next_path / part / "modules"
                if not next_path.exists():
                    next_path = next_path.parent

    @contextmanager
    def stay_at_commit(self, enabled):
        commit = self.hex
        try:
            yield
        finally:
            if enabled:
                self.X(*(git + ["reset", "--soft"]), commit)

    @contextmanager
    def worktree(self, commit):
        with temppath() as tmpfolder:
            repo_folder = tmpfolder / str(uuid.uuid4())
            repo_folder.parent.mkdir(exist_ok=True, parents=True)
            try:
                repo = Repo(repo_folder)
                self.X(*(git + ["worktree", "add", "--force", repo_folder, commit]))
                yield repo
            except Exception as ex:
                click.secho(f"Error occurred at repo {self.path}", fg="red")
                raise
            finally:
                repo.X(*(git + ["worktree", "remove", "--force", repo_folder]))
                rmtree(tmpfolder)

    def move_worktree_content(self, dest_path):
        if dest_path.exists():
            rmtree(dest_path)
        # faster than rsync
        shutil.move(self.path, dest_path)
        gitdir = dest_path / ".git"
        if gitdir.exists():
            self.path.mkdir()
            shutil.move(gitdir, self.path / ".git")


class Remote(object):
    def __init__(self, repo, name, url):
        self.repo = repo
        self.name = name
        self.url = url


class Submodule(Repo):
    def __init__(self, path, parent_path):
        self.path = Path(path)
        self.path_absolute = path.absolute()
        self.parent_path = Path(parent_path)
        self.relpath = self.path.relative_to(self.parent_path)
        self.is_submodule = True

    @property
    def is_git_submodule(self):
        gitmodules = self.parent_path / ".gitmodules"
        if not gitmodules.exists():
            return False
        module = [
            x
            for x in gitmodules.read_text().splitlines()
            if x.startswith("[submodule")
            if f'"{self.relpath}"]' in x
        ]
        return bool(module)

    def __repr__(self):
        return f"{self.path}"

    def __str__(self):
        return f"{self.path}"

    def get_url(self, noerror=True):
        try:
            url = Repo(self.parent_path).out(
                *(
                    git
                    + ["config", "-f", ".gitmodules", f"submodule.{self.relpath}.url"]
                ),
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
