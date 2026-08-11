#!/bin/bash
# Pre-commit hook: Check that at least one changelog fragment exists in changes/
# Fragments are .md files in changes/ (excluding README.md)

set -e

# Check for existing fragment files (tracked or staged)
existing_fragments=$(find changes/ -maxdepth 1 -name "*.md" ! -name "README.md" 2>/dev/null || true)
staged_fragments=$(git diff --cached --name-only --diff-filter=ACM -- 'changes/*.md' | grep -v README.md 2>/dev/null || true)

if [ -n "$existing_fragments" ] || [ -n "$staged_fragments" ]; then
    exit 0
fi

echo ""
echo "=========================================================="
echo "  ERROR: Kein Changelog-Fragment gefunden!"
echo "=========================================================="
echo ""
echo "  Bitte erstelle eine Datei in changes/ (Typ im Dateinamen):"
echo ""
echo "    echo 'Beschreibung der Aenderung' > changes/meine-aenderung.imp.md"
echo ""
echo "  Typen (steuern SemVer-Bump):"
echo "    *.remove.md  -> major  (breaking change)"
echo "    *.new.md     -> minor  (neues Feature)"
echo "    *.imp.md     -> minor  (Verbesserung)"
echo "    *.fix.md     -> patch  (Bugfix)"
echo ""
echo "  Zum Ueberspringen:"
echo "    SKIP=changelog-fragment git commit -m '...'"
echo ""
echo "=========================================================="
echo ""
exit 1
