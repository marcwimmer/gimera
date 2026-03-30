# Changelog Fragments (Town Crier)

Jeder Pull Request muss eine Changelog-Fragment-Datei in diesem Verzeichnis enthalten.

## Format

Erstelle eine neue `.md` Datei mit einem beschreibenden Namen, z.B.:

```
changes/fix-submodule-checkout.md
changes/add-snapshot-feature.md
```

## Inhalt

Jede Datei enthält eine kurze Beschreibung der Änderung:

```markdown
* [FIX] Submodule checkout failed when path contained spaces
```

Prefixes: `[FIX]`, `[IMP]`, `[NEW]`, `[REMOVE]`

## Was passiert damit?

Beim Release auf `main` werden alle Fragmente automatisch in die `CHANGELOG.md`
kompiliert und die Fragment-Dateien gelöscht.

## Pre-commit Hook

Der Pre-commit Hook prüft, ob mindestens ein Fragment vorhanden ist.
Zum Überspringen (z.B. bei reinen Refactorings):

```bash
SKIP=changelog-fragment git commit -m "..."
```
