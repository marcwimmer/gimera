#!/usr/bin/env python3
"""
Determine next version from changelog fragment types and run towncrier.

Fragment filenames follow towncrier convention: ``<name>.<type>.md``.
Supported types drive the SemVer bump:

  remove -> major
  new    -> minor
  imp    -> minor
  fix    -> patch

The highest-priority bump among all fragments wins. The new version is
written to ``setup.cfg`` and ``VERSION``, then ``towncrier build`` is
invoked to compile the fragments into ``CHANGELOG.md``.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGES = ROOT / "changes"

BUMP_BY_TYPE = {
    "remove": "major",
    "new": "minor",
    "imp": "minor",
    "fix": "patch",
}
BUMP_PRIORITY = {"major": 3, "minor": 2, "patch": 1}


def _get_highest_tag():
    """Find the highest existing semver tag (with or without v prefix)."""
    try:
        out = subprocess.check_output(
            ["git", "tag", "--list"], cwd=ROOT, text=True
        )
    except subprocess.CalledProcessError:
        return None
    best = None
    for tag in out.splitlines():
        tag = tag.strip().lstrip("v")
        parts = tag.split(".")
        if len(parts) != 3:
            continue
        try:
            nums = tuple(map(int, parts))
        except ValueError:
            continue
        if best is None or nums > best:
            best = nums
    return best


def _current_version():
    setup_cfg = ROOT / "setup.cfg"
    content = setup_cfg.read_text()
    match = re.findall(r"version = (.*)", content)
    cfg = tuple(map(int, match[-1].strip().split(".")))
    tag = _get_highest_tag()
    return max(cfg, tag) if tag else cfg


def _detect_bump():
    """Scan fragment filenames and return the highest-priority bump."""
    highest = None
    for path in CHANGES.glob("*.md"):
        if path.name == "README.md":
            continue
        # expect name.<type>.md
        parts = path.name.rsplit(".", 2)
        if len(parts) != 3:
            continue
        ftype = parts[1].lower()
        bump = BUMP_BY_TYPE.get(ftype)
        if not bump:
            continue
        if highest is None or BUMP_PRIORITY[bump] > BUMP_PRIORITY[highest]:
            highest = bump
    return highest


def _apply_bump(version, bump):
    major, minor, patch = version
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def _update_setup_cfg(new_version):
    setup_cfg = ROOT / "setup.cfg"
    content = setup_cfg.read_text()
    content = re.sub(
        r"^version = .*$",
        f"version = {new_version}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    setup_cfg.write_text(content)


def main():
    bump = _detect_bump()
    if not bump:
        print("No changelog fragments found — skipping version bump and changelog.")
        return

    current = _current_version()
    new = _apply_bump(current, bump)
    new_version = ".".join(map(str, new))
    print(
        f"Bump type: {bump}. "
        f"Version: {'.'.join(map(str, current))} -> {new_version}"
    )

    _update_setup_cfg(new_version)
    (ROOT / "VERSION").write_text(new_version + "\n")

    subprocess.check_call(
        ["towncrier", "build", "--yes", "--version", new_version],
        cwd=ROOT,
    )
    print(f"Changelog compiled for version {new_version}")


if __name__ == "__main__":
    main()
