"""User configuration for gimera: ~/.gimera (JSON).

Machine-wide settings that do not belong into a project's gimera.yml, because
they describe the machine and not the project. Example: a build server or a
hosting instance never wants odoo/odoo's full history in its cache, while a
developer machine very much does.

Format (JSON so it stays easy to extend):

    {
      "no_cache": ["odoo/odoo", "github.com/odoo/enterprise"]
    }

Unknown keys are ignored on purpose - an older gimera should not refuse to
run because a newer one writes a key it does not know yet.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

import click

from .tools import _raise_error
from .tools import reformat_url

CONFIG_ENV = "GIMERA_CONFIG"
DEFAULT_CONFIG_PATH = "~/.gimera"


def config_path():
    return Path(os.path.expanduser(os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG_PATH))


@lru_cache(maxsize=1)
def load_user_config():
    """The parsed ~/.gimera, or an empty dict if there is none.

    A broken config aborts instead of being skipped: silently ignoring it
    would mean the settings do not apply and nobody notices - which is the
    worst of both worlds when the setting is there to keep 18 GB of history
    off a machine.
    """
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as ex:
        _raise_error(f"{path} is not valid JSON: {ex}")
        return {}
    if not isinstance(data, dict):
        _raise_error(f"{path} must contain a JSON object, got {type(data).__name__}.")
        return {}
    return data


def _normalize(url):
    """host/owner/repo, lowercase, without protocol, user and .git suffix.

    Both spellings of the same repo (git@github.com:odoo/odoo and
    https://github.com/odoo/odoo.git) must compare equal - otherwise the
    setting would work for one gimera.yml and not for the next.
    """
    try:
        # "http" is reformat_url's name for the https form
        url = reformat_url(url, "http")
    except Exception:
        pass
    url = str(url).strip()
    for prefix in ("https://", "http://", "ssh://", "git://"):
        if url.startswith(prefix):
            url = url[len(prefix) :]
            break
    url = url.split("@")[-1]  # user@host -> host
    url = url.replace(":", "/", 1) if ":" in url.split("/")[0] else url
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url.strip("/").lower()


def is_no_cache(url):
    """True if this repo must never go into the golden cache.

    Matching is on the normalized form and accepts a suffix, so "odoo/odoo"
    in the config catches "github.com/odoo/odoo" without anyone having to
    spell out the host. A full "github.com/odoo/odoo" works too and is the
    precise form if the same owner/repo exists on two hosts.
    """
    if os.getenv("GIMERA_NO_CACHE", "") == "1":
        return True
    patterns = load_user_config().get("no_cache") or []
    if isinstance(patterns, str):
        patterns = [patterns]
    if not isinstance(patterns, list):
        _raise_error(f"{config_path()}: 'no_cache' must be a list of repo names.")
        return False
    target = _normalize(url)
    for pattern in patterns:
        pattern = _normalize(pattern)
        if not pattern:
            continue
        if target == pattern or target.endswith("/" + pattern):
            return True
    return False


def explain_no_cache(url):
    click.secho(
        f"{url}: shallow checkout, no cache "
        f"(no_cache in {config_path()} or GIMERA_NO_CACHE=1)",
        fg="yellow",
    )
