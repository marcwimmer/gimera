import json
import os

import pytest

from ..userconfig import _normalize
from ..userconfig import is_no_cache
from ..userconfig import load_user_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """Every test starts without a config and without the env override."""
    monkeypatch.delenv("GIMERA_NO_CACHE", raising=False)
    # Pinned rather than assumed: _raise_error swaps sys.exit for a plain
    # Exception when this is "1", and other test modules set it. Deleting it
    # here makes this module independent of what ran before it in the same
    # pytest-xdist worker.
    monkeypatch.delenv("GIMERA_EXCEPTION_THAN_SYSEXIT", raising=False)
    monkeypatch.setenv("GIMERA_CONFIG", str(tmp_path / ".gimera"))
    load_user_config.cache_clear()
    yield
    load_user_config.cache_clear()


def _write_config(content):
    path = os.environ["GIMERA_CONFIG"]
    with open(path, "w") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))
    load_user_config.cache_clear()


def test_no_config_means_cache_as_before():
    assert not is_no_cache("git@github.com:odoo/odoo")


def test_env_switch_still_wins():
    os.environ["GIMERA_NO_CACHE"] = "1"
    try:
        assert is_no_cache("git@github.com:odoo/odoo")
    finally:
        del os.environ["GIMERA_NO_CACHE"]


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:odoo/odoo",
        "git@github.com:odoo/odoo.git",
        "https://github.com/odoo/odoo",
        "https://github.com/odoo/odoo.git",
    ],
)
def test_short_pattern_matches_every_spelling(url):
    """The same repo written four ways must behave the same."""
    _write_config({"no_cache": ["odoo/odoo"]})
    assert is_no_cache(url)


def test_host_qualified_pattern():
    _write_config({"no_cache": ["github.com/odoo/odoo"]})
    assert is_no_cache("git@github.com:odoo/odoo")
    assert not is_no_cache("git@gitlab.com:odoo/odoo")


def test_other_repos_keep_their_cache():
    _write_config({"no_cache": ["odoo/odoo"]})
    assert not is_no_cache("git@github.com:OCA/queue")
    # kein Praefix-Treffer: "foo/odoo/odoo" ist ein anderes Repo
    assert not is_no_cache("https://github.com/foo/odoo-odoo")


def test_unknown_keys_are_ignored():
    """An older gimera must not choke on a key a newer one writes."""
    _write_config({"no_cache": ["odoo/odoo"], "something_new": {"a": 1}})
    assert is_no_cache("git@github.com:odoo/odoo")


def test_broken_json_aborts_loudly(monkeypatch):
    """Silently ignoring a typo would mean 18 GB land on the machine anyway.

    How the abort happens depends on the environment: normally _raise_error
    calls sys.exit, but with GIMERA_EXCEPTION_THAN_SYSEXIT=1 it raises an
    exception instead -- which is what the test suite runs with, so that an
    abort does not end the whole test run. The test used to expect SystemExit
    and therefore failed whenever that variable was set. What matters here is
    that the broken config is not swallowed, so pin the mode and check the
    message."""
    _write_config("{ no_cache: [")
    monkeypatch.setenv("GIMERA_EXCEPTION_THAN_SYSEXIT", "1")
    with pytest.raises(Exception) as exc:
        load_user_config()
    assert "not valid JSON" in str(exc.value)


def test_normalize():
    assert _normalize("git@github.com:odoo/odoo.git") == "github.com/odoo/odoo"
    assert _normalize("https://github.com/Odoo/Odoo") == "github.com/odoo/odoo"
