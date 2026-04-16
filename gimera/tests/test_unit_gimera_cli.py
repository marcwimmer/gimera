"""Unit tests for gimera.py CLI commands and helpers.

Uses Click's CliRunner and a minimal gimera.yml fixture so we don't need
full remote git repos.
"""
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from ..consts import gitcmd as git
from ..gimera import (
    cli,
    clean_branch_names,
    _expand_repos,
    _get_available_repos,
    _check_all_submodules_initialized,
)


MINIMAL_YAML = {
    "repos": [
        {
            "url": "https://example.invalid/a.git",
            "branch": "main",
            "path": "vendor/a",
            "type": "integrated",
        },
        {
            "url": "https://example.invalid/b.git",
            "branch": "main",
            "path": "vendor/b",
            "type": "submodule",
        },
    ]
}


@pytest.fixture
def main_repo(tmp_path, monkeypatch):
    """Initialise a bare-minimum git repo with a gimera.yml and chdir there."""
    repo = tmp_path / "work"
    repo.mkdir()
    subprocess.check_call(git + ["init", "-q", "--initial-branch=main"], cwd=repo)
    subprocess.check_call(git + ["config", "user.email", "t@t"], cwd=repo)
    subprocess.check_call(git + ["config", "user.name", "t"], cwd=repo)
    subprocess.check_call(git + ["config", "commit.gpgsign", "false"], cwd=repo)
    (repo / "gimera.yml").write_text(yaml.dump(MINIMAL_YAML))
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "init"], cwd=repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    monkeypatch.setenv("GIMERA_NON_INTERACTIVE", "1")
    return repo


def test_clean_branch_names_strips_and_removes_star():
    out = list(clean_branch_names(["  main ", "* feature", "develop"]))
    assert out == ["main", "feature", "develop"]


def test_expand_repos_exact_match(main_repo):
    result = _expand_repos(["vendor/a"])
    assert result == ["vendor/a"]


def test_expand_repos_trailing_slash(main_repo):
    result = _expand_repos(["vendor/a/"])
    assert result == ["vendor/a"]


def test_expand_repos_glob(main_repo):
    result = sorted(_expand_repos(["vendor/*"]))
    assert result == ["vendor/a", "vendor/b"]


def test_get_available_repos_completion(main_repo):
    res = _get_available_repos(None, None, "vend")
    # pattern 'vend' without slash becomes '*vend*'
    assert any("vendor" in x for x in res)


def test_combine_patch_prints_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["combine-patch"])
    assert res.exit_code == 0
    assert "patchutils" in res.output


def test_completion_print_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".bashrc").write_text("# existing\n")
    runner = CliRunner()
    res = runner.invoke(cli, ["completion"])
    assert res.exit_code == 0
    assert "Insert into" in res.output
    # no --execute → file untouched
    assert (tmp_path / ".bashrc").read_text() == "# existing\n"


def test_completion_execute_inserts(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = tmp_path / ".bashrc"
    rc.write_text("# existing\n")
    runner = CliRunner()
    res = runner.invoke(cli, ["completion", "-x"])
    assert res.exit_code == 0
    content = rc.read_text()
    assert "_GIMERA_COMPLETE=bash_source" in content


def test_completion_execute_skips_when_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = tmp_path / ".bashrc"
    rc.write_text('eval "$(_GIMERA_COMPLETE=bash_source gimera)"\n')
    runner = CliRunner()
    res = runner.invoke(cli, ["completion", "-x"])
    assert res.exit_code == 0
    assert "already existed" in res.output


def test_abort_clears_edit_patchfile(main_repo):
    # Seed edit_patchfile in gimera.yml
    data = yaml.safe_load((main_repo / "gimera.yml").read_text())
    data["repos"][0]["edit_patchfile"] = "patches/foo.patch"
    data["repos"][0]["patches"] = [{"path": "patches"}]
    (main_repo / "gimera.yml").write_text(yaml.dump(data))
    subprocess.check_call(git + ["add", "gimera.yml"], cwd=main_repo)
    subprocess.check_call(git + ["commit", "-q", "-m", "edit"], cwd=main_repo)

    runner = CliRunner()
    res = runner.invoke(cli, ["abort"])
    assert res.exit_code == 0
    data = yaml.safe_load((main_repo / "gimera.yml").read_text())
    assert data["repos"][0].get("edit_patchfile", "") == ""


def test_status_lists_missing_repos(main_repo):
    runner = CliRunner()
    res = runner.invoke(cli, ["status"])
    assert res.exit_code == 0
    assert "vendor/a" in res.output
    assert "vendor/b" in res.output


def test_list_snapshots_empty(main_repo):
    runner = CliRunner()
    res = runner.invoke(cli, ["list-snapshots"])
    assert res.exit_code == 0


def test_purge_removes_existing_dirs(main_repo):
    (main_repo / "vendor").mkdir()
    (main_repo / "vendor" / "a").mkdir()
    (main_repo / "vendor" / "a" / "f").write_text("x")
    (main_repo / "vendor" / "b").mkdir()
    runner = CliRunner()
    res = runner.invoke(cli, ["purge"])
    assert res.exit_code == 0
    assert not (main_repo / "vendor" / "a").exists()
    assert not (main_repo / "vendor" / "b").exists()


def test_add_new_repo_entry(main_repo):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "add",
            "-u",
            "https://example.invalid/c.git",
            "-b",
            "main",
            "-p",
            "vendor/c",
            "-t",
            "integrated",
        ],
    )
    assert res.exit_code == 0, res.output
    data = yaml.safe_load((main_repo / "gimera.yml").read_text())
    paths = [r["path"] for r in data["repos"]]
    assert "vendor/c" in paths


def test_add_updates_existing_repo_entry(main_repo):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "add",
            "-u",
            "https://example.invalid/a2.git",
            "-b",
            "develop",
            "-p",
            "vendor/a",
            "-t",
            "integrated",
        ],
    )
    assert res.exit_code == 0, res.output
    data = yaml.safe_load((main_repo / "gimera.yml").read_text())
    a = next(r for r in data["repos"] if r["path"] == "vendor/a")
    assert a["branch"] == "develop"
    assert a["url"] == "https://example.invalid/a2.git"


def test_apply_rejects_conflicting_flags(main_repo):
    runner = CliRunner()
    res = runner.invoke(cli, ["apply", "-G", "-S", "--raise-exception"])
    # conflicting flags → _raise_error
    assert res.exit_code != 0


def test_check_all_submodules_initialized_no_submodules(main_repo):
    # no submodules checked out → True (nothing to check)
    assert _check_all_submodules_initialized() is True


def test_check_all_submodules_initialized_command(main_repo):
    runner = CliRunner()
    res = runner.invoke(cli, ["check-all-submodules-initialized"])
    assert res.exit_code == 0
