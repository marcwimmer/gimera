# gimera — Claude Instructions

## Release-Workflow (KRITISCH)

**Bei JEDER Code-Änderung MUSS ein towncrier-Fragment in [changes/](changes/) angelegt werden.**
Ohne Fragment passiert beim Push auf `main` kein Version-Bump und kein PyPI-Release.

### Fragment anlegen

Format: `changes/<kurz-name>.<type>.md`

| Typ      | SemVer | Wann                                      |
|----------|--------|-------------------------------------------|
| `remove` | major  | Breaking Change / entfernte Funktionalität |
| `new`    | minor  | Neues Feature                             |
| `imp`    | minor  | Verbesserung an bestehendem Feature       |
| `fix`    | patch  | Bugfix                                    |

Inhalt: einzeilige Beschreibung **ohne** Prefix (Typ steckt im Dateinamen).

```bash
echo 'recognize uninitialized submodules' > changes/uninit-submodules.fix.md
```

Höchster Typ unter allen Fragmenten gewinnt für den Bump. Details in [changes/README.md](changes/README.md).

### Was beim Release passiert

1. Push auf `main` → CI ([.github/workflows/gimera-pytest.yml](.github/workflows/gimera-pytest.yml))
2. Tests müssen grün sein
3. [scripts/compile_changelog.py](scripts/compile_changelog.py): Bump-Typ ableiten, `VERSION` + `setup.cfg` updaten, `CHANGELOG.md` bauen
4. sdist bauen → commit `chore(release): X.Y.Z` → tag → push → PyPI-Upload

## Versionierung

`VERSION`, `setup.cfg` und der höchste Git-Tag werden vom Release-Script automatisch synchronisiert. **Nicht manuell editieren** — nur Fragment anlegen.

## Tests

`pytest -n auto` — laufen lokal und in CI auf ubuntu-latest mit Python 3.10.
