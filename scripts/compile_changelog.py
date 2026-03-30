#!/usr/bin/env python3
"""
Compile changelog fragments into CHANGELOG.md and increment version.

Called during the release workflow on main branch.
Reads all .md files from changes/ (except README.md), prepends them
to CHANGELOG.md under the new version header, then removes the fragments.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def increment_version():
    setup_cfg = ROOT / "setup.cfg"
    content = setup_cfg.read_text()
    match = re.findall(r"version = (.*)", content)
    old_version = match[-1].strip()
    parts = list(map(int, old_version.split(".")))
    parts[-1] += 1
    new_version = ".".join(map(str, parts))

    content = content.replace(
        f"version = {old_version}",
        f"version = {new_version}",
    )
    setup_cfg.write_text(content)
    (ROOT / "VERSION").write_text(new_version + "\n")

    print(f"Version: {old_version} -> {new_version}")
    return new_version


def compile_changelog(version):
    changes_dir = ROOT / "changes"
    fragments = sorted(changes_dir.glob("*.md"))
    fragments = [f for f in fragments if f.name != "README.md"]

    if not fragments:
        print("No changelog fragments found - skipping changelog update.")
        return

    entries = []
    for fragment in fragments:
        text = fragment.read_text().strip()
        if text:
            entries.append(text)
        fragment.unlink()
        print(f"  Processed: {fragment.name}")

    # Build new section
    lines = [f"# {version}"]
    for entry in entries:
        for line in entry.splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith(("*", "-")):
                line = f"* {line}"
            lines.append(f"  {line}")
    lines.append("")

    new_section = "\n".join(lines) + "\n"

    changelog = ROOT / "CHANGELOG.md"
    existing = changelog.read_text() if changelog.exists() else ""
    changelog.write_text(new_section + existing)

    print(f"Changelog updated with {len(entries)} entries for version {version}")


def main():
    version = increment_version()
    compile_changelog(version)


if __name__ == "__main__":
    main()
