"""Unit tests for patch strip-level / cwd auto-detection in patches.py.

No git repos needed — the helpers operate on plain files plus the system
`patch` binary.
"""
from pathlib import Path

import pytest

from ..patches import (
    _PATCH_REFUSED,
    _apply_patchfile,
    _extract_git_header_paths,
    _extract_patch_file_pairs,
    _find_working_patch_args,
    _strip_level_fits,
)


@pytest.fixture(autouse=True)
def _non_interactive(monkeypatch):
    """Patch failures normally prompt via inquirer.confirm; default every
    test in this module to non-interactive so a test that reaches a failure
    path can never hang under `pytest -n auto`. A test that wants to assert
    interactive behaviour can monkeypatch the env back."""
    monkeypatch.setenv("GIMERA_NON_INTERACTIVE", "1")


def _write_mod_patch(patch_path, old_header, new_header):
    patch_path.write_text(
        f"--- {old_header}\n"
        f"+++ {new_header}\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
    )


# ------------------------------------------------------------------
# _extract_patch_file_pairs
# ------------------------------------------------------------------


def test_extract_pairs_basic(tmp_path):
    p = tmp_path / "x.patch"
    p.write_text(
        "diff --git a/foo.txt b/foo.txt\n"
        "--- a/foo.txt\t2026-01-01 00:00:00\n"
        "+++ b/foo.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
        "--- /dev/null\n"
        "+++ b/new.txt\n"
        "@@ -0,0 +1 @@\n"
        "+created\n"
    )
    assert _extract_patch_file_pairs(p) == [
        ("a/foo.txt", "b/foo.txt"),
        (None, "b/new.txt"),
    ]


def test_extract_pairs_no_headers(tmp_path):
    p = tmp_path / "x.patch"
    p.write_text("this is not a patch\n")
    assert _extract_patch_file_pairs(p) == []


@pytest.mark.parametrize(
    "old,new",
    [
        ("a/../evil.txt", "b/../evil.txt"),
        ("/etc/passwd", "/etc/passwd"),
        ("a/sub/../../evil.txt", "b/evil.txt"),
    ],
)
def test_extract_pairs_rejects_unsafe_paths(tmp_path, old, new):
    p = tmp_path / "x.patch"
    _write_mod_patch(p, old, new)
    assert _extract_patch_file_pairs(p) is None


# ------------------------------------------------------------------
# _find_working_patch_args — phase 1 (strip level in requested cwd)
# ------------------------------------------------------------------


def test_classic_p1(tmp_path):
    (tmp_path / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/foo.txt", "b/foo.txt")
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path)


def test_parent_root_prefix_p2(tmp_path):
    # authored from the parent repo root: paths carry the sub-repo prefix
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/sub/foo.txt", "b/sub/foo.txt")
    assert _find_working_patch_args(patch, sub)[:2] == (2, sub)


def test_no_prefix_patch_still_applies(tmp_path):
    # `git format-patch --no-prefix` style headers: patch falls back to
    # the basename for -p1; must keep working (legacy probe allowed it)
    (tmp_path / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "foo.txt", "foo.txt")
    args = _find_working_patch_args(patch, tmp_path)
    assert args is not None
    assert args[1] == tmp_path


def test_new_file_patch_p1(tmp_path):
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- /dev/null\n"
        "+++ b/new.txt\n"
        "@@ -0,0 +1 @@\n"
        "+created\n"
    )
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path)
    assert _apply_patchfile(patch, tmp_path)
    assert (tmp_path / "new.txt").read_text() == "created\n"


def test_ambiguous_strip_levels_choose_lowest_and_warn(tmp_path, capsys):
    # both x/y/file.txt (-p1) and y/file.txt (-p2) exist with matching
    # content: deterministic choice is -p1, loudly
    (tmp_path / "x" / "y").mkdir(parents=True)
    (tmp_path / "y").mkdir()
    (tmp_path / "x" / "y" / "file.txt").write_text("hello\n")
    (tmp_path / "y" / "file.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/x/y/file.txt", "b/x/y/file.txt")
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path)
    assert "several strip levels" in capsys.readouterr().out


def test_equivalent_strip_levels_no_warning(tmp_path, capsys):
    # -p2..-p4 on a/foo.txt all collapse to the same basename — that is
    # equivalence, not ambiguity
    (tmp_path / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/foo.txt", "b/foo.txt")
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path)
    assert "several strip levels" not in capsys.readouterr().out


# ------------------------------------------------------------------
# _find_working_patch_args — phase 2 (relocation)
# ------------------------------------------------------------------


def test_relocation_patch_authored_deeper(tmp_path):
    # the motivating case: patch authored inside odoo/odoo/ while gimera
    # manages odoo/
    deeper = tmp_path / "odoo" / "addons"
    deeper.mkdir(parents=True)
    (deeper / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/addons/foo.txt", "b/addons/foo.txt")
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path / "odoo")
    assert _apply_patchfile(patch, tmp_path)
    assert (deeper / "foo.txt").read_text() == "world\n"


def test_relocation_anchors_on_all_pairs_not_just_first(tmp_path):
    # git orders sections alphabetically: the first pair creates a new file
    # (no on-disk anchor); relocation must still anchor on the later
    # existing file rather than giving up
    deeper = tmp_path / "odoo" / "addons"
    deeper.mkdir(parents=True)
    (deeper / "zzz.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- /dev/null\n"
        "+++ b/addons/aaa_new.txt\n"
        "@@ -0,0 +1 @@\n"
        "+created\n"
        "--- a/addons/zzz.txt\n"
        "+++ b/addons/zzz.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
    )
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path / "odoo")
    assert _apply_patchfile(patch, tmp_path)
    assert (deeper / "aaa_new.txt").read_text() == "created\n"
    assert (deeper / "zzz.txt").read_text() == "world\n"


def test_returned_pairs_match_patch(tmp_path):
    # the 3rd return element (pairs) is reused by the apply gate — verify it
    (tmp_path / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/foo.txt", "b/foo.txt")
    strip, cwd, pairs = _find_working_patch_args(patch, tmp_path)
    assert (strip, cwd) == (1, tmp_path)
    assert pairs == [("a/foo.txt", "b/foo.txt")]


def test_git_header_symlink_target_containment(tmp_path):
    # a hand-crafted patch whose git `diff --git` header names an in-tree
    # symlink out of the repo, while the unified header names a safe file:
    # the apply gate must containment-check the git-header path and refuse
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.txt").write_text("secret\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.txt").write_text("hello\n")
    (repo / "evil.txt").symlink_to(outside / "evil.txt")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/evil.txt b/evil.txt\n"
        "--- a/real.txt\n"
        "+++ b/real.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
    )
    _apply_patchfile(patch, repo, error_ok=True)
    assert (outside / "evil.txt").read_text() == "secret\n"


def test_relocation_with_new_file(tmp_path):
    # a relocated patch that modifies one file AND creates another —
    # the not-yet-existing target must not veto the candidate
    deeper = tmp_path / "odoo" / "addons"
    deeper.mkdir(parents=True)
    (deeper / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- a/addons/foo.txt\n"
        "+++ b/addons/foo.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
        "--- /dev/null\n"
        "+++ b/addons/new.txt\n"
        "@@ -0,0 +1 @@\n"
        "+created\n"
    )
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path / "odoo")
    assert _apply_patchfile(patch, tmp_path)
    assert (deeper / "foo.txt").read_text() == "world\n"
    assert (deeper / "new.txt").read_text() == "created\n"


def test_relocation_ambiguity_deterministic_and_warns(tmp_path, capsys):
    # two directories match the patch layout: shallowest/sorted-first wins,
    # with a loud warning — never a filesystem-order coin flip
    for d in ("d1", "d2"):
        (tmp_path / d / "foo").mkdir(parents=True)
        (tmp_path / d / "foo" / "bar.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/foo/bar.txt", "b/foo/bar.txt")
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path / "d1")
    assert "matches several directories" in capsys.readouterr().out


def test_relocation_skips_pruned_dirs(tmp_path):
    pruned = tmp_path / "node_modules" / "foo"
    pruned.mkdir(parents=True)
    (pruned / "bar.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/foo/bar.txt", "b/foo/bar.txt")
    assert _find_working_patch_args(patch, tmp_path) is None


def test_relocation_does_not_follow_symlinks_outside(tmp_path):
    # layout reachable only through a symlink pointing outside the cwd
    outside = tmp_path / "outside" / "foo"
    outside.mkdir(parents=True)
    (outside / "bar.txt").write_text("hello\n")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / "link").symlink_to(tmp_path / "outside")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/foo/bar.txt", "b/foo/bar.txt")
    assert _find_working_patch_args(patch, cwd) is None
    assert (outside / "bar.txt").read_text() == "hello\n"


# ------------------------------------------------------------------
# regression: patch targets the `+++` side (rename / .orig-style diff)
# ------------------------------------------------------------------


def test_modification_anchored_on_new_side(tmp_path):
    # `diff -u foo.txt.orig foo.txt` style: only the +++ target exists
    (tmp_path / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "foo.txt.orig", "foo.txt")
    args = _find_working_patch_args(patch, tmp_path)
    assert args is not None and args[1] == tmp_path
    assert _apply_patchfile(patch, tmp_path)
    assert (tmp_path / "foo.txt").read_text() == "world\n"


def test_rename_patch_anchored_on_existing_target(tmp_path):
    # rename: old name gone, new name present on disk
    (tmp_path / "new.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/old.txt", "b/new.txt")
    args = _find_working_patch_args(patch, tmp_path)
    assert args is not None and args[1] == tmp_path


# ------------------------------------------------------------------
# regression: hunk-body lines that start with ---/+++ are not headers
# ------------------------------------------------------------------


def test_hunk_body_dashes_not_misparsed(tmp_path):
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- a/foo.txt\n"
        "+++ b/foo.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " keep\n"
        "--- ../build/out\n"
        "+++ added line\n"
    )
    # the body lines must NOT be read as a header pair, and the bogus
    # `../build/out` must NOT trigger a security refusal
    assert _extract_patch_file_pairs(patch) == [("a/foo.txt", "b/foo.txt")]


def test_header_without_hunk_marker_ignored(tmp_path):
    patch = tmp_path / "x.patch"
    patch.write_text("--- a/foo.txt\n+++ b/foo.txt\nnot a hunk\n")
    assert _extract_patch_file_pairs(patch) == []


# ------------------------------------------------------------------
# regression: git rename/copy header paths are safety-checked
# ------------------------------------------------------------------


def test_git_rename_unsafe_target_refused(tmp_path):
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/old.txt b/../../escaped.txt\n"
        "similarity index 100%\n"
        "rename from old.txt\n"
        "rename to ../../escaped.txt\n"
    )
    assert _extract_patch_file_pairs(patch) is None


def test_git_copy_unsafe_target_refused(tmp_path):
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/old.txt b/old.txt\n"
        "copy from old.txt\n"
        "copy to /etc/evil.txt\n"
    )
    assert _extract_patch_file_pairs(patch) is None


def test_git_quoted_octal_path_refused(tmp_path):
    # git octal-escapes special bytes; \056\056 decodes to `..` → refused
    patch = tmp_path / "x.patch"
    patch.write_text(
        '--- "a/\\056\\056/escaped.txt"\n'
        '+++ "b/\\056\\056/escaped.txt"\n'
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    assert _extract_patch_file_pairs(patch) is None


def test_git_quoted_umlaut_decoded(tmp_path):
    # a git-quoted non-ASCII path (core.quotepath default) is DECODED, not
    # refused — GNU patch applies it, so gimera must understand it too
    patch = tmp_path / "x.patch"
    patch.write_text(
        '--- "a/\\303\\274mlaut.txt"\n'
        '+++ "b/\\303\\274mlaut.txt"\n'
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
    )
    assert _extract_patch_file_pairs(patch) == [
        ("a/ümlaut.txt", "b/ümlaut.txt")
    ]


def test_unquoted_umlaut_applies(tmp_path):
    # unquoted UTF-8 path (what gimera now emits via core.quotepath=false)
    # applies portably on both BSD/Apple and GNU patch
    (tmp_path / "ümlaut.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/ümlaut.txt", "b/ümlaut.txt")
    assert _apply_patchfile(patch, tmp_path)
    assert (tmp_path / "ümlaut.txt").read_text() == "world\n"


def test_git_directory_write_refused(tmp_path):
    # a patch writing into .git/ (e.g. an executable hook → RCE) is refused
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- /dev/null\n"
        "+++ b/.git/hooks/post-merge\n"
        "@@ -0,0 +1 @@\n"
        "+#!/bin/sh\n"
    )
    assert _find_working_patch_args(patch, tmp_path) is _PATCH_REFUSED


def test_symlink_creating_patch_refused(tmp_path):
    # a `new file mode 120000` hunk would materialise a symlink that could
    # point out of the sub-repo — refused
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/link b/link\n"
        "new file mode 120000\n"
        "index 0000000..1234567\n"
        "--- /dev/null\n"
        "+++ b/link\n"
        "@@ -0,0 +1 @@\n"
        "+/etc\n"
    )
    assert _extract_patch_file_pairs(patch) is None
    assert _find_working_patch_args(patch, tmp_path) is _PATCH_REFUSED


def test_rename_patch_warns(tmp_path, capsys):
    # `patch` cannot rename; warn so "Applied" is not mistaken for a rename
    (tmp_path / "old.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/old.txt b/new.txt\n"
        "rename from old.txt\n"
        "rename to new.txt\n"
        "--- a/old.txt\n"
        "+++ b/new.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
    )
    _apply_patchfile(patch, tmp_path, error_ok=True)
    assert "does not rename" in capsys.readouterr().out


def test_gitignore_not_refused(tmp_path):
    # `.gitignore` / `.github` are not the `.git` dir and must apply
    (tmp_path / ".gitignore").write_text("old\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/.gitignore", "b/.gitignore")
    assert _apply_patchfile(patch, tmp_path)
    assert (tmp_path / ".gitignore").read_text() == "world\n"


# ------------------------------------------------------------------
# regression: hunk-aware parsing (zero-context / diff-of-a-diff)
# ------------------------------------------------------------------


def test_zero_context_diff_single_pair(tmp_path):
    # body lines that render as ---/+++ followed by the next hunk's @@
    # must not be mis-read as a second file header
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1 +1 @@\n"
        "--- line one\n"
        "+--- changed\n"
        "@@ -3 +3 @@ keep\n"
        "-+plus tail\n"
        "++++ changed\n"
    )
    assert _extract_patch_file_pairs(patch) == [("a/f.txt", "b/f.txt")]


def test_diff_of_a_diff_not_misparsed(tmp_path):
    # a patch that edits a .diff file: embedded diff content in the hunk
    # body (incl. an embedded `..` path) must neither create a spurious
    # pair nor trigger a security refusal
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- a/sample.diff\n"
        "+++ b/sample.diff\n"
        "@@ -1,3 +1,3 @@\n"
        " context\n"
        "---- a/../../etc/passwd\n"
        "+--- a/inner.txt\n"
        " trailing\n"
    )
    assert _extract_patch_file_pairs(patch) == [("a/sample.diff", "b/sample.diff")]


# ------------------------------------------------------------------
# regression: non-unified patches are refused (not blindly applied -p1)
# ------------------------------------------------------------------


def test_context_diff_refused(tmp_path, capsys):
    # context diffs (***/---) carry no unified header → no enumerable,
    # containment-checkable target → must be refused, never blind -p1
    (tmp_path / "foo.txt").write_text("secret\n")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "*** a/foo.txt\t2020-01-01\n"
        "--- a/foo.txt\t2020-01-01\n"
        "***************\n"
        "*** 1 ****\n"
        "! secret\n"
        "--- 1 ----\n"
        "! changed\n"
    )
    assert _find_working_patch_args(patch, tmp_path) is _PATCH_REFUSED
    assert "no unified-diff file headers" in capsys.readouterr().out


# ------------------------------------------------------------------
# regression: symlink-traversing target paths cannot escape cwd
# ------------------------------------------------------------------


def test_target_through_intree_symlink_refused(tmp_path):
    # an in-tree symlink pointing outside the cwd must not let a patch
    # write through it (is_file() alone would follow the link)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.txt").write_text("secret\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sub").symlink_to(outside)
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/sub/target.txt", "b/sub/target.txt")
    assert _find_working_patch_args(patch, repo) is None
    assert (outside / "target.txt").read_text() == "secret\n"


def test_destination_through_symlink_no_escape(tmp_path):
    # the `+++`/rename destination need not exist yet — but if it resolves
    # through an in-tree symlink out of the repo, that strip level must not
    # fit, and end-to-end nothing may be written outside the repo
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.txt").write_text("old\n")
    (repo / "outlink").symlink_to(outside)
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/src.txt", "b/outlink/dest.txt")
    # -p1 would write through the symlink to the destination → rejected
    assert not _strip_level_fits([("a/src.txt", "b/outlink/dest.txt")], repo, 1)
    # end-to-end: the escaping destination is never created
    _apply_patchfile(patch, repo, error_ok=True)
    assert not (outside / "dest.txt").exists()


# ------------------------------------------------------------------
# regression: phase-2 same-file matches are not reported as ambiguous
# ------------------------------------------------------------------


def test_relocation_no_spurious_ambiguity_warning(tmp_path, capsys):
    # both -p1 in sub/ and -p2 in sub/deep/ resolve to the same file;
    # this is equivalence, not ambiguity — no warning
    deep = tmp_path / "sub" / "deep"
    deep.mkdir(parents=True)
    (deep / "foo.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/deep/foo.txt", "b/deep/foo.txt")
    args = _find_working_patch_args(patch, tmp_path)
    assert args is not None
    assert "matches several directories" not in capsys.readouterr().out


def test_deletion_patch_applies(tmp_path):
    # `+++ /dev/null`: a deletion anchors on its existing source
    (tmp_path / "gone.txt").write_text("bye\n")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- a/gone.txt\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-bye\n"
    )
    assert _find_working_patch_args(patch, tmp_path)[:2] == (1, tmp_path)
    assert _apply_patchfile(patch, tmp_path)
    # GNU patch removes the emptied file; BSD/Apple patch leaves it empty
    gone = tmp_path / "gone.txt"
    assert not gone.exists() or gone.read_text() == ""


def test_extract_git_header_paths_tokens(tmp_path):
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/old.txt b/new.txt\n"
        "rename from old.txt\n"
        "rename to new.txt\n"
    )
    paths = _extract_git_header_paths(patch.read_text().splitlines())
    assert "a/old.txt" in paths and "b/new.txt" in paths
    assert "old.txt" in paths and "new.txt" in paths


def test_git_header_escape_blocked_during_relocation(tmp_path):
    # the git-header containment gate must also fire when the patch is
    # relocated into a deeper directory
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.txt").write_text("secret\n")
    deeper = tmp_path / "odoo"
    deeper.mkdir()
    (deeper / "real.txt").write_text("hello\n")
    (deeper / "evil.txt").symlink_to(outside / "evil.txt")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/evil.txt b/evil.txt\n"
        "--- a/real.txt\n"
        "+++ b/real.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+world\n"
    )
    _apply_patchfile(patch, tmp_path, error_ok=True)
    assert (outside / "evil.txt").read_text() == "secret\n"


# ------------------------------------------------------------------
# _apply_patchfile — failure / security paths
# ------------------------------------------------------------------


def test_unsafe_patch_refused(tmp_path, capsys):
    (tmp_path / "repo").mkdir()
    (tmp_path / "evil.txt").write_text("hello\n")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/../evil.txt", "b/../evil.txt")
    assert _apply_patchfile(patch, tmp_path / "repo", error_ok=True) is False
    assert "Refusing patch" in capsys.readouterr().out
    assert (tmp_path / "evil.txt").read_text() == "hello\n"


def test_total_failure_reports_and_returns_false(tmp_path, capsys):
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/missing.txt", "b/missing.txt")
    assert _apply_patchfile(patch, tmp_path, error_ok=True) is False
    assert "Failed to apply patch" in capsys.readouterr().out


def test_total_failure_raises_without_error_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    patch = tmp_path / "x.patch"
    _write_mod_patch(patch, "a/missing.txt", "b/missing.txt")
    with pytest.raises(Exception, match="Error applying patch"):
        _apply_patchfile(patch, tmp_path, error_ok=False)
