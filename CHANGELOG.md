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
