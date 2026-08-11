# Changelog Fragments (Towncrier)

Jeder Pull Request muss eine Changelog-Fragment-Datei in diesem Verzeichnis enthalten.
Wir nutzen [towncrier](https://towncrier.readthedocs.io/); der Fragment-Typ steckt im
Dateinamen und steuert den SemVer-Bump beim Release.

## Dateinamen-Konvention

Format: `<name>.<type>.md`

| Typ      | Beschreibung                                    | SemVer-Bump |
|----------|-------------------------------------------------|-------------|
| `remove` | Breaking Change / entfernte Funktionalität      | major       |
| `new`    | Neues Feature                                   | minor       |
| `imp`    | Verbesserung an bestehendem Feature             | minor       |
| `fix`    | Bugfix                                          | patch       |

Beispiele:

```
changes/fix-submodule-checkout.fix.md
changes/add-snapshot-feature.new.md
changes/refactor-repo-api.imp.md
changes/drop-python36.remove.md
```

## Inhalt

Einfache Beschreibung ohne Prefix (der Typ steckt im Dateinamen):

```markdown
Submodule checkout failed when path contained spaces
```

## Was passiert damit?

Beim Release auf `main`:

1. `scripts/compile_changelog.py` ermittelt den höchsten vorkommenden Typ unter
   allen Fragmenten und leitet daraus den SemVer-Bump ab.
2. Version in `setup.cfg` und `VERSION` wird aktualisiert.
3. `towncrier build` kompiliert die Fragmente in `CHANGELOG.md` und löscht sie.
4. Commit + Tag + PyPI-Release.

## Pre-commit Hook

Der Pre-commit Hook prüft, ob mindestens ein Fragment vorhanden ist.
Zum Überspringen (z.B. bei reinen Refactorings):

```bash
SKIP=changelog-fragment git commit -m "..."
```
