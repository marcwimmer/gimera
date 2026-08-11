"""Inspect and prune the golden cache under ~/.cache/gimera.

Why this is a separate, manual command instead of something `apply` does on
its own: gimera only ever sees the one repository it is working on. From a
single run it cannot conclude that some other entry is unused -- the same URL
may well be pinned in a gimera.yml elsewhere on the same machine. So nothing
here removes a cache entry unless the user says so.

The one exception is the leftover tarball of gimera <= 0.12.x. That one is
provably dead: no version reads it any more.

Entries also go stale without anybody noticing, which is what makes this
worth having (see issue #25):

  * The naming scheme changed -- `_` and the `user@` part are dropped now, so
    an entry written as `git@github.com_odoo_odoo` is never looked up again
    under its new name `github.com-odoo-odoo`. It just stays, at full size.
  * The source is gone. Temp and test repositories carry their path in the
    cache name (`file----tmp-gimeratest-repo1`); once the path is deleted the
    entry can never match anything again.

Neither case can be recognised from the mangled directory name -- `-` stands
for `/`, `_`, `:` and more, so the original URL cannot be reconstructed
reliably. Age is used as the proxy instead, and the user confirms.
"""

import os
import shutil
import time
from pathlib import Path

import click

from .cachedir import _legacy_tarfile
from .cachedir import cache_root

# Deliberately not tools.rmtree: that one calls sys.exit(-1) when it fails,
# which would abandon the rest of the cleanup half-done.

# Files git touches when a cache entry is fetched into. The directory's own
# mtime does not move for a fetch, so it alone would make every entry look
# untouched since the day it was cloned.
_ACTIVITY_MARKERS = ["FETCH_HEAD", "packed-refs", "refs", "objects", "HEAD"]


def format_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024 or unit == "TB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024


def dir_size(path):
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def last_used(path):
    """Newest mtime among the files git writes on fetch.

    Only ever a hint: a cache that is read but never updated (the pin did not
    move) does not look recent. That is why nothing is deleted on this number
    alone.
    """
    newest = 0
    for candidate in [path] + [path / x for x in _ACTIVITY_MARKERS]:
        try:
            newest = max(newest, candidate.stat().st_mtime)
        except OSError:
            continue
    return newest


def iter_entries(root=None):
    """Every cache entry, with its size, age and leftover tarball."""
    root = Path(root) if root else cache_root()
    if not root.exists():
        return
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        tar = _legacy_tarfile(path)
        try:
            tar_size = tar.stat().st_size if tar.exists() else 0
        except OSError:
            tar_size = 0
        yield {
            "path": path,
            "name": path.name,
            "size": dir_size(path),
            "tarball": tar if tar_size else None,
            "tar_size": tar_size,
            "last_used": last_used(path),
        }


def stray_tarballs(root=None):
    """Tarballs whose cache directory is already gone.

    Nothing will ever look at these again, not even to delete them: the
    automatic cleanup runs from _get_cache_dir, which is only reached for a
    URL that is still in use.
    """
    root = Path(root) if root else cache_root()
    if not root.exists():
        return []
    found = []
    for path in sorted(root.glob("*.tar.gz")):
        if not Path(str(path)[: -len(".tar.gz")]).is_dir():
            found.append(path)
    return found


def _age_days(timestamp, now=None):
    if not timestamp:
        return None
    return ((now or time.time()) - timestamp) / 86400


def print_listing(root=None, now=None):
    entries = list(iter_entries(root))
    strays = stray_tarballs(root)
    if not entries and not strays:
        click.secho(f"Cache is empty: {Path(root) if root else cache_root()}")
        return entries, strays

    click.secho(
        f"{'SIZE':>10}  {'TARBALL':>10}  {'IDLE':>8}  NAME", bold=True
    )
    for entry in sorted(entries, key=lambda x: x["size"], reverse=True):
        age = _age_days(entry["last_used"], now)
        click.secho(
            f"{format_size(entry['size']):>10}  "
            f"{(format_size(entry['tar_size']) if entry['tar_size'] else '-'):>10}  "
            f"{(f'{age:.0f}d' if age is not None else '?'):>8}  "
            f"{entry['name']}"
        )

    total = sum(x["size"] for x in entries)
    total_stray = sum(_safe_size(x) for x in strays)
    # The tarball sits next to its cache directory, not inside it, so it is
    # not part of `total` -- keep the two apart rather than letting the sum
    # look smaller than what `du` reports for the same directory.
    total_tar = sum(x["tar_size"] for x in entries) + total_stray
    click.secho(
        f"\n{len(entries)} entries, {format_size(total)}"
        + (
            f" plus {format_size(total_tar)} in tarballs "
            f"= {format_size(total + total_tar)}"
            if total_tar
            else ""
        ),
        bold=True,
    )
    if total_tar:
        click.secho(
            "The tarballs are leftovers from gimera <= 0.12.x and nothing "
            "reads them any more. They go away by themselves the next time "
            "gimera touches the repository in question, or right now with "
            "`gimera cache clean`.",
            fg="yellow",
        )
    if strays:
        click.secho(
            f"{len(strays)} tarball(s) without a cache directory, "
            f"{format_size(total_stray)}. Those never go away on their own - "
            "the automatic cleanup only runs for repositories still in use.",
            fg="yellow",
        )
    return entries, strays


def _safe_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def clean(root=None, unused_for=None, force=False, now=None):
    """Remove the provably dead, and optionally entries idle for too long.

    Returns the number of bytes freed.
    """
    entries = list(iter_entries(root))
    freed = 0

    for path in stray_tarballs(root):
        freed += _remove_file(path)
    for entry in entries:
        if entry["tarball"]:
            freed += _remove_file(entry["tarball"])

    if unused_for is not None:
        stale = [
            x
            for x in entries
            if (_age_days(x["last_used"], now) or 0) >= unused_for
        ]
        freed += _remove_entries(stale, unused_for, force)

    if not freed:
        click.secho("Nothing to remove.", fg="green")
    else:
        click.secho(f"Freed {format_size(freed)}.", fg="green")
    return freed


def _remove_entries(stale, unused_for, force):
    if not stale:
        click.secho(
            f"No cache entry has been idle for {unused_for} days.", fg="green"
        )
        return 0

    click.secho(
        f"\n{len(stale)} entr(ies) not updated for {unused_for} days:",
        fg="yellow",
    )
    for entry in stale:
        click.secho(f"  {format_size(entry['size']):>10}  {entry['name']}")
    click.secho(
        "Deleting these costs a fresh clone the next time the URL is used - "
        "no data is lost, only time.",
    )

    if not force and os.getenv("GIMERA_NON_INTERACTIVE") != "1":
        if not click.confirm("Remove them?", default=False):
            click.secho("Kept.", fg="yellow")
            return 0

    freed = 0
    for entry in stale:
        size = entry["size"]
        try:
            shutil.rmtree(entry["path"])
        except OSError as ex:
            click.secho(f"Could not remove {entry['path']}: {ex}", fg="red")
            continue
        click.secho(f"Removed {entry['name']}", fg="yellow")
        freed += size
    return freed


def _remove_file(path):
    size = _safe_size(path)
    try:
        path.unlink()
    except OSError as ex:
        click.secho(f"Could not remove {path}: {ex}", fg="red")
        return 0
    click.secho(f"Removed {path.name} ({format_size(size)})", fg="yellow")
    return size
