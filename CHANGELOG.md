# 0.13.0

  * [IMPROVED] The golden cache is no longer mirrored into a second copy on disk. Every repository in `~/.cache/gimera` was kept twice — once as the bare clone that is actually used, and once more as a `.tar` of that same clone, written on every update and only ever read to rebuild the clone it was made from. On a machine with a few large repositories that is tens of gigabytes of duplicate that nobody asked for; one report had it at 16 GB. Restoring now re-clones from the remote instead, which is the same work the tarball path did after an invalidation anyway. A tarball left behind by an older gimera is deleted on the next run, with a note saying how much space that freed — otherwise it would sit there forever with no hint of where it came from. `--clear-zip-cache` still exists so scripts keep working, but it does nothing now and says so.
# 0.12.2

  * [FIXED] A stale `gimera.lock` left behind by a killed process is recognised and removed again. `FileLock` appends `.lock` to the name it is given, so the file that actually appeared was `gimera.lock.lock`, while `wait_git_lock` watched and cleaned up `gimera.lock` — a name nothing ever creates. Recovery therefore never triggered: after a `SIGKILL` (which runs no `__del__`) the next run on that repository blocked the full hour and then failed with "Timeout occured.". Mutual exclusion itself was never affected, both sides derived the same doubled name. Also fixed: `FileLock.__init__` now sets its attributes before validating its arguments, so `__del__` no longer dies with `AttributeError` on a half-built object (Python swallows that, which on a lock-holding object would mean the lockfile stays behind), and `os.getcwd()` is only consulted for relative names — it raises once the current directory has been deleted.
# 0.12.1

  * [FIXED] Der Test fuer eine kaputte ~/.gimera erwartete einen SystemExit, obwohl die Testumgebung Abbrueche als Exception meldet (GIMERA_EXCEPTION_THAN_SYSEXIT). Er schlug dadurch in der CI fehl und blockierte das Release.
# 0.12.0

  * [IMPROVED] Golden cache of integrated repos is cloned with `--filter=blob:none`, so it holds the history but only the file contents of the snapshots actually used. On odoo/odoo that is 1.4 GB instead of ~17 GB, and a pin bump of 300 commits adds ~100 MB. Submodule repos keep a full cache (a partial clone cannot serve `git submodule update`), existing caches are left alone, and `GIMERA_FULL_CLONE=1` turns the filter off.
  * [FIXED] Test fixtures no longer leak `GIMERA_EXCEPTION_THAN_SYSEXIT` (and the other `GIMERA_*` switches) into the rest of the pytest process. Setting them via plain `os.environ` assignment made `test_broken_json_aborts_loudly` pass or fail depending on how pytest-xdist happened to shard the run — it expects the default `sys.exit` behaviour, which the leaked flag replaces with a plain exception. That is why CI went green on a pull request and red on `main`, which in turn skipped the release job and held back the previous version bump.
# 0.11.2

  * [FIXED] CI: Die Concurrency-Gruppe des Test-Jobs bricht laufende Release-Laeufe nicht mehr ab. Bisher teilten sich alle Laeufe eines Branches eine Gruppe mit `cancel-in-progress`, wodurch ein schnell nachgeschobener Push (oder ein manueller Start) den Test-Job eines Pushes auf main abwuergen konnte — und mit ihm das daran haengende Release. Ab jetzt loesen sich nur noch PR-Laeufe gegenseitig ab; Pushes auf main und manuelle Laeufe bekommen eine eigene Gruppe je Run.
# 0.11.1

  * [FIXED] CI: Der Workflow laesst sich jetzt manuell starten (`workflow_dispatch`, Button „Run workflow" im Actions-Tab bzw. `gh workflow run CI --ref main`). Hilfreich, wenn ein Push-Event verloren geht — etwa waehrend einer GitHub-Actions-Stoerung — und bisher nur ein leerer Commit als Ersatz-Trigger blieb. Der Release-Job bleibt absichtlich an `push` gebunden und laeuft bei manuellem Start nicht mit.
# 0.11.0

  * [NEW] `~/.gimera` (JSON) can now list repos under `no_cache` that never go into the golden cache — gimera fetches exactly the needed state instead (`--single-branch --depth=1`). For odoo/odoo that is ~1.1 GB instead of ~18 GB of history, which matters on build servers and hosting instances where nobody ever looks at the past. `GIMERA_NO_CACHE=1` still turns it on for every repo.
  * [FIXED] CI: `actions/checkout` und `actions/setup-python` auf die Node-24-Majors (v7) angehoben. Die bisher genutzten v4/v5 laufen auf Node 20, das ab 16.09.2026 von den GitHub-Runnern entfernt wird — die Workflows wären danach kaputt gegangen.
# 0.10.3

  * [FIXED] `gimera commit --preview` now shows the staged diff (`git diff --cached`) — the preview was always empty because everything was already staged
  * [FIXED] apply patches with `patch -E` so file deletions actually remove the file — without it GNU patch left an empty file behind for every deletion hunk
  * [FIXED] restore in-memory sha and `.gitignore` reliably even when temp-repo patch creation fails (`temporary_unignore` now uses try/finally and skips the no-op rewrite); treat a failing `ls-files` probe as untracked
# 0.10.2

  * [FIXED] harden `_temporarily_move_gimera` against exceptions (config file pointer is now always restored) and strengthen `gimera commit` test coverage (untracked-not-ignored path, exact-content assertions)
# 0.10.1

  * [FIXED] `gimera commit` now works when the integrated path is gitignored or untracked in the main repo: the patch is built against the upstream state via a temporary repo instead of the main repo's index (previously `git add` crashed on ignored paths, and untracked paths produced unappliable whole-file-is-new patches)
# 0.10.0

  * [NEW] auto-detect patch strip level so patches from any source apply
  * [FIXED] harden patch strip-level/cwd auto-detection: derive strip level from a hunk-aware parse of the unified-diff headers (anchoring on whichever of the `---`/`+++` names exists, so rename and `.orig`-style diffs still apply; hunk bodies are consumed by their line counts so zero-context `-U0` diffs and patches that edit diff files are no longer misread), refuse patches with absolute/`..`/git-quoted-escaped paths in unified or git rename/copy headers, refuse non-unified patches (context diffs, ed scripts, binary/rename-only) instead of blindly running `patch -p1` on them, refuse targets that traverse an in-tree symlink out of the sub-repo with a final containment gate before the write, never relocate outside the sub-repo, try strip level -p0 too (no-prefix and `.orig`-style patches need it on GNU patch, which does not fall back to the basename like BSD/Apple patch), deterministic choice plus warning only on genuinely different ambiguous matches, support relocation of patches that create new files, refuse patches that write into `.git/` or create a symlink (which could escape the sub-repo or, via a `.git/hooks` write, run code), decode git-quoted (`core.quotepath`) non-ASCII paths instead of refusing them and emit unquoted UTF-8 paths when making patches, warn when a git rename is applied (`patch` changes content but cannot rename), prune node_modules/.venv during candidate search, emit verbose diagnostics at each decision point, raise a clear error when the `patch` binary is missing, and always report failures instead of silently returning
# 0.8.5

  * [FIXED] CI fails on push to main when no changelog fragment is present
  * [FIXED] fetch configured branch explicitly before fetchall in _ensure_sha
# 0.8.4

  * [FIXED] * [FIX] setup.cfg: install_requires war fälschlich unter [options.packages.find] statt [options], dadurch wurden Abhängigkeiten (click, inquirer, pyyaml, pudb, urwid) seit 0.8.0 nicht mehr mitinstalliert.
# 0.8.3

  * [FIXED] test: guard against deleted-cwd fixture failures in parallel xdist workers
# 0.9.0

  * [IMPROVED] show per-repo progress during `gimera apply` (Fetching, Applying, extracting, committing) so long-running operations aren't silent
  * [IMPROVED] ~3x faster `gimera apply`: consolidate `all_dirty_files` into a single git-status parse, replace redundant `git ls-remote` with `FETCH_HEAD`, and skip `make_patches` when no patch dirs are configured
  * [IMPROVED] skip git-archive + rsync extraction for integrated modules when the configured sha already matches the working tree (huge speedup for large repos like odoo)
  * [IMPROVED] add unit test suite covering filelock, tools, gitcommands, repo, config, cachedir, snapshot, patches helpers and CLI commands
  * [FIXED] recover from interrupted submodule→integrated conversions: handle orphaned gitlinks (no .gitmodules entry) and leftover staged files from crashed runs
# 0.8.2

  * [FIXED] recognize uninitialized submodules + add CLI help texts
# 0.8.1

  * [FIXED] Release workflow: re-enabled test job with `needs: test` guard; release commit now carries the version and compiled changelog entries in its message
# 0.8.0

  * [NEW] Town Crier Patch Notes: PRs erfordern Changelog-Fragmente in changes/, automatische Kompilierung beim Release, Pre-commit Hook Validierung, eigene VERSION Datei
# 0.7.95
  * removed: Deliver Patches with reused submodules. - too complicated; githubworkflow used for branching
  * patchdirs: allows chdir - if you get patchfiles from third parties to make them compatible
# 0.7.61
  * [IMP] stronger force mode at ignored paths and turning submodule to integrated

# 0.7.53
  * fetch more stable: sometimes all branches cannot be fetched, then just trying the one needed
  * using rsync progress2 information update

# 0.7.34
  * gimera apply addons_tools/ works and fetches all repositories from that parent url
    gimera apply addons_tools/* did not work out of the box; zsh complains about expanding
    '*'

# 0.7.32
  * download may fail for git@... addresses; retries with https:; example for 
    https://github.com/OCA/queue

# 0.7.30
  * gimera commit command to easily commit sub modules to branches

# 0.7.27
  * fixed switching integrated/submodule and loosing file; added test with level 1
    modules and module of module (two levels)
  * parallel downloading / fetching subrepo updates even for gitsubmodules
  * cloning submodules from local cache and changing url to internet source
  
# 0.6.55
  * [NEW] strict at patchs of patch files
# 0.6.54
  * [FIX] submodule path resolving
    [NEW] --strict option integrated modules force submodules usually to also be integrated; with strict, the gimera file is used
# 0.6.51
  * [FIX] helping rsync --delete-after with non empty directories

# 0.6.50
  * [FIX] wild life stable switch between integrated and submodule: deleting invalid cached modules in .git/modules when they are not bare
# 0.6.39

  * If submodule's sha matches the branch then the branch is checked out instead of the pure sha. Advantage: no fiddling at commit and pushing.

# 0.6.8

Tested the switching between submodule and integrated in real world
repositories and fixed a lot of stuff like remaining directories with
certain marker in git.
https://stackoverflow.com/questions/4185365/no-submodule-mapping-found-in-gitmodule-for-a-path-thats-not-a-submodule

# 0.6.2

* Handling gitignores when switching submodule to integrated repos
# 0.6.0

* added  thousand lines of tests
* rewritten shell commands with generic wrapper
* abstract some more git classes like remotes

# 0.5.23

* get rid of annoying message about changed files - ignoring updated gimera.yml
# 0.3.17

- added completion for: bash

# 0.3.8

- added force option at adding submodules
