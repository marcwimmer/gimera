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


def test_broken_json_aborts_loudly():
    """Silently ignoring a typo would mean 18 GB land on the machine anyway."""
    _write_config("{ no_cache: [")
    with pytest.raises(SystemExit):
        load_user_config()


def test_normalize():
    assert _normalize("git@github.com:odoo/odoo.git") == "github.com/odoo/odoo"
    assert _normalize("https://github.com/Odoo/Odoo") == "github.com/odoo/odoo"
