"""Unit tests for gimera.tools pure helpers.

These tests don't need real git repos and run fast.
"""
import os
import time
from pathlib import Path

import pytest

from ..tools import (
    _strip_paths,
    file_age,
    filter_files_to_folders,
    files_relative_to,
    get_url_type,
    is_empty_dir,
    is_forced,
    path1inpath2,
    prepare_dir,
    reformat_url,
    remember_cwd,
    rmtree,
    safe_relative_to,
    split_every,
    try_rm_tree,
    temppath,
    verbose,
    yieldlist,
    retry,
    _raise_error,
    replace_dir_with,
    assert_exception_no_exit,
    confirm,
)


def test_is_forced_default():
    os.environ.pop("GIMERA_FORCE", None)
    assert is_forced() is False


def test_is_forced_true():
    os.environ["GIMERA_FORCE"] = "1"
    try:
        assert is_forced() is True
    finally:
        os.environ["GIMERA_FORCE"] = "0"


def test_yieldlist_wraps_generator():
    @yieldlist
    def gen():
        yield 1
        yield 2
        yield 3

    assert gen() == [1, 2, 3]


def test_strip_paths_normalizes():
    result = list(_strip_paths(["./a/b", "c/d/"]))
    assert result == [str(Path("./a/b")), str(Path("c/d/"))]


def test_safe_relative_to_ok(tmp_path):
    child = tmp_path / "foo"
    child.mkdir()
    res = safe_relative_to(child, tmp_path)
    assert res == Path("foo")


def test_safe_relative_to_fail(tmp_path):
    other = Path("/tmp/_gimera_unrelated_xyz")
    assert safe_relative_to(other, tmp_path) is False


def test_is_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert is_empty_dir(d)
    (d / "f").write_text("x")
    assert not is_empty_dir(d)


def test_file_age_returns_positive(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    age = file_age(f)
    assert age >= 0
    assert age < 60


def test_file_age_missing_file_returns_zero(tmp_path):
    assert file_age(tmp_path / "missing") == 0


def test_path1inpath2_true(tmp_path):
    child = tmp_path / "a" / "b"
    assert path1inpath2(child, tmp_path)


def test_path1inpath2_false(tmp_path):
    assert not path1inpath2(Path("/etc"), tmp_path)


def test_get_url_type_http():
    assert get_url_type("https://x/y") == "http"
    assert get_url_type("http://x/y") == "http"


def test_get_url_type_git():
    assert get_url_type("git@github.com:foo/bar.git") == "git"


def test_get_url_type_file():
    assert get_url_type("/tmp/repo") == "file"
    assert get_url_type("file:///tmp/repo") == "file"


def test_get_url_type_raises():
    with pytest.raises(NotImplementedError):
        get_url_type("ftp://whatever")


def test_reformat_url_noop():
    url = "https://github.com/foo/bar.git"
    assert reformat_url(url, "http") == url


def test_reformat_url_git_to_http():
    res = reformat_url("git@github.com:foo/bar.git", "http")
    assert res == "https://github.com/foo/bar.git"


def test_reformat_url_http_to_git():
    res = reformat_url("https://github.com/foo/bar.git", "git")
    assert res == "git@github.com:foo/bar.git"


def test_reformat_url_invalid_pair_raises():
    with pytest.raises(NotImplementedError):
        reformat_url("/tmp/repo", "http")


def test_verbose_silent(capsys):
    os.environ.pop("GIMERA_VERBOSE", None)
    verbose("should not show")
    assert capsys.readouterr().out == ""


def test_verbose_prints(capsys):
    os.environ["GIMERA_VERBOSE"] = "1"
    try:
        verbose("hello")
        out = capsys.readouterr().out
        assert "hello" in out
    finally:
        os.environ.pop("GIMERA_VERBOSE", None)


def test_filter_files_to_folders():
    files = [Path("a/x.txt"), Path("b/y.txt"), Path("a/z.txt")]
    folders = [Path("a")]
    res = list(filter_files_to_folders(files, folders))
    assert res == [Path("a/x.txt"), Path("a/z.txt")]


def test_files_relative_to(tmp_path):
    base = tmp_path
    files = [base / "sub/a", base / "sub/b", Path("/etc")]
    res = list(files_relative_to(files, base))
    assert Path("sub/a") in res
    assert Path("sub/b") in res
    # /etc shouldn't be relative to tmp_path
    assert len(res) == 2


def test_split_every_exact():
    res = list(split_every(2, [1, 2, 3, 4]))
    assert res == [(1, 2), (3, 4)]


def test_split_every_remainder():
    res = list(split_every(2, [1, 2, 3, 4, 5]))
    assert res == [(1, 2), (3, 4), (5,)]


def test_split_every_list():
    res = list(split_every(2, [1, 2, 3], piece_maker=list))
    assert res == [[1, 2], [3]]


def test_retry_ok_first_try():
    calls = {"n": 0}

    def f():
        calls["n"] += 1

    retry(f, attempts=3, sleep=0)
    assert calls["n"] == 1


def test_retry_eventual_success():
    calls = {"n": 0}

    def f():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")

    retry(f, attempts=3, sleep=0)
    assert calls["n"] == 2


def test_retry_all_fail_raises():
    def f():
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        retry(f, attempts=2, sleep=0)


def test_remember_cwd_restores(tmp_path):
    start = Path.cwd()
    with remember_cwd(tmp_path) as p:
        assert Path.cwd() == tmp_path.resolve()
        assert p == tmp_path
    assert Path.cwd() == start


def test_temppath_auto_cleanup():
    with temppath() as p:
        assert p.exists()
        path = p
    assert not path.exists()


def test_temppath_no_mkdir():
    with temppath(mkdir=False) as p:
        assert not p.exists()


def test_try_rm_tree_missing_is_noop(tmp_path):
    try_rm_tree(tmp_path / "does-not-exist")


def test_try_rm_tree_removes(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "f").write_text("a")
    try_rm_tree(d)
    assert not d.exists()


def test_prepare_dir_creates_and_replaces(tmp_path):
    target = tmp_path / "target"
    with prepare_dir(target) as t:
        (t / "file.txt").write_text("ok")
    assert target.exists()
    assert (target / "file.txt").read_text() == "ok"


def test_prepare_dir_overwrites_existing(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "old").write_text("old")
    with prepare_dir(target) as t:
        (t / "new").write_text("new")
    assert (target / "new").exists()
    assert not (target / "old").exists()


def test_prepare_dir_rolls_back_on_exception(tmp_path):
    target = tmp_path / "target"
    with pytest.raises(RuntimeError):
        with prepare_dir(target) as t:
            assert t.exists()
            raise RuntimeError("boom")
    assert not target.exists()


def test_replace_dir_with(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "marker").write_text("src")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "old").write_text("old")
    replace_dir_with(src, dest)
    assert (dest / "marker").exists()
    assert not (dest / "old").exists()


def test_replace_dir_with_when_dest_missing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "m").write_text("x")
    dest = tmp_path / "dest"
    replace_dir_with(src, dest)
    assert (dest / "m").read_text() == "x"


def test_raise_error_exception_mode():
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "1"
    with pytest.raises(Exception, match="boom"):
        _raise_error("boom")


def test_raise_error_sysexit_mode():
    old = os.environ.get("GIMERA_EXCEPTION_THAN_SYSEXIT", "0")
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "0"
    try:
        with pytest.raises(SystemExit):
            _raise_error("bye")
    finally:
        os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = old


def test_assert_exception_no_exit_restores_env():
    os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] = "0"
    with assert_exception_no_exit():
        assert os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] == "1"
    assert os.environ["GIMERA_EXCEPTION_THAN_SYSEXIT"] == "0"


def test_confirm_non_interactive_auto_true():
    os.environ["GIMERA_NON_INTERACTIVE"] = "1"
    try:
        assert confirm("anything") is True
    finally:
        os.environ["GIMERA_NON_INTERACTIVE"] = "0"
