import tempfile
import inquirer
import click
import sys
from pathlib import Path
from .repo import Repo
from .tools import _get_main_repo
from .consts import gitcmd as git
from .tools import prepare_dir
from .config import Config
from .patches import _apply_patchfile
from .patches import _technically_make_patch
from .patches import _if_ignored_move_to_separate_dir


def _commit(repo, branch, message, preview):
    config = Config()
    repo = config.get_repos(Path(repo))
    common_vars = config.yaml_config.get("common", {}).get("vars", {})
    path2 = Path(tempfile.mktemp(suffix="."))
    main_repo = _get_main_repo()
    assert len(repo) == 1
    repo = repo[0]

    with prepare_dir(path2) as path2:
        path2 = path2 / "repo"
        gitrepo = Repo(path2)
        main_repo.X(*(git + ["clone", repo.url, path2]))

        if not branch:
            res = click.confirm(
                f"\n\n\nCommitting to branch {repo.branch} - continue?", default=True
            )
            if not res:
                sys.exit(-1)
            branch = repo.branch

        gitrepo.X(*(git + ["checkout", "-f", branch]))

        # If the repo path is gitignored/untracked in the main repo, the main
        # repo offers no diff base — _if_ignored_move_to_separate_dir builds a
        # temp repo at the configured upstream state and rsyncs the local
        # changes over it, so the patch is the actual delta against upstream.
        with _if_ignored_move_to_separate_dir(
            None, main_repo, repo, common_vars
        ) as (patch_repo, _is_temp_path):
            src_path = patch_repo.path / repo.path
            # the temp repo received a copy of the main .gitignore
            with patch_repo.temporary_unignore(src_path):
                patch_content = _technically_make_patch(patch_repo, src_path)

        patchfile = gitrepo.path / "1.patch"
        patchfile.write_text(patch_content)

        _apply_patchfile(patchfile, gitrepo.path, error_ok=False)

        patchfile.unlink()
        gitrepo.X(*(git + ["add", "."]))
        if preview:
            # everything is staged at this point — plain `git diff` would
            # show nothing
            gitrepo.X(*(git + ["diff", "--cached"]))
            doit = inquirer.confirm("Commit this?", default=True)
            if not doit:
                return
        gitrepo.X(*(git + ["commit", "--no-verify", "-m", message]))
        gitrepo.X(*(git + ["push"]))
