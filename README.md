# Welcome to GIMERA

Advanced handling of submodules by integrating them or handling as submodules as you know
but provide auto merge functions of hotfixes from other repositories or inside.

Rule of thumb:

 * no data is lost, it is safe to call gimera.
If there are staged files, gimera wont continue.

During run of gimera commits are done for example after pulling submodules or updating
local paths.


## How to install:

```bash
pipx install gimera
gimera completion  (Follow instructions)
```



## How to use:

Put gimera.yml into your root folder of your project:

```yaml
common:
  vars:
    VERSION: '15.0'
repos:
    # make ordinary git submodule:
    - url: "https://github.com/foo/bar"
      branch: branch1_${VERSION}
      path: roles/sub1
      patches:
        - patches/foo/bar
      # patches can also be configures as dictionaries with extra infos:
      patches:
        - path: patches/foo/bar
          chdir: foo  # if you get patch files from others you can switch the executing
                      # current working directory
      type: submodule

      # default True
      enabled: True
      # if true, then on gimera apply -u the SHA is not updated
      freeze_sha: False


    # instead of submodule put the content directly in the repository;
    # apply patches from local git repository
    - url: "https://github.com/foo/bar"
      branch: branch1
      path: roles2/sub1
      patches:
          - 'roles2/sub1_patches'
      type: integrated
      ignored_patchfiles:
        - file1.patch
        - roles2/sub1_patches/file1.patch

    # keep the vendored files out of the parent repository
    - url: "https://github.com/odoo/enterprise"
      branch: '16.0'
      path: odoo/enterprise
      type: integrated
      dont_commit: True

    # apply patches from another remote repository
    #
    - url: "https://github.com/foo/bar"
      branch: branch1
      path: roles2/sub1
      remotes:
          remote2: https://github.com/foo2/bar2
      merges:
          - remote2 main
          - origin refs/pull/1/head
      type: integrated

```

Patches and remote merges may be combined.

Then execute:

```bash
gimera apply
```

## How to make a patchfile:

From the example above:

  * edit roles2/sub1/file1.txt

```bash
gimera apply
```

Then a patch file is created as suggestion in roles2/sub1_patches which you may commit and push.

> **Note:** gimera auto-applies **unified diffs** only (as produced by `git
> diff` / `git format-patch`). The strip level (`-p1`..`-p4`) and working
> directory are detected from the patch headers. Context diffs, ed scripts,
> binary patches and rename-/mode-only diffs (no unified body) are refused
> rather than applied, as are patches referencing absolute, `..` or paths
> that resolve outside the sub-repo through a symlink, that write into
> `.git/`, or that create a symlink.

### Re-Edit patch file:

```bash
gimera edit-patch file1.patch file2.patch
```

  * by this, you can combine several patch files into one again


## Integrated repos that must not land in the parent repository

Some paths have to be there for running the project, but must never be
committed - odoo.sh projects are the typical case, they carry
`odoo/enterprise` in their `.gitignore`.

You do not need to configure anything for that: if the path of an integrated
repo is gitignored and not tracked yet, `gimera apply` pulls the files as usual
and leaves them untracked. It says so while applying.

Deliberately, this looks at the index as well - a path that is **tracked** in
the parent repository today counts as not ignored, and updates keep being
committed. Otherwise a `.gitignore` entry added later would silently stop
updating the copy in the repository, and everybody pulling it would keep stale
content without a hint.

So for the case "the path is tracked today and shall stop being tracked",
say it explicitly:

```yaml
repos:
    - url: "https://github.com/odoo/enterprise"
      branch: '16.0'
      path: odoo/enterprise
      type: integrated
      dont_commit: True
```

The files then stay out of any commit gimera makes. Removing them from the
index is up to you (`git rm -r --cached odoo/enterprise`), gimera does not
delete other people's history for them. `dont_commit` only applies to
`type: integrated`; a submodule is a gitlink in the parent repository by
definition.

## How to fetch only one or more repo:

```bash
gimera apply repo_path repo_path2 repo_path3`
```
## How to fetch latest versions:

```bash
gimera apply --update
```

Latest versions are pulled and patches are applied.

## Force Integrated or Submodule mode for repo and subrepositories

Use Case: you have an integrated repository. Now you want to turn it into submodule,
to easily commit and push changes. Then you do:

```bash
gimera apply <path> -S
```

Now although it is configured as integrated, it is now a submodule.

After that you can go back to default settings or force integrated mode.
You should call update to pull the latest version.

```bash
gimera apply <path> -I --update
```

### Note:

This way is ok for small sized patches. If patches grow and grow one useful recommendation is to use
github workflows to rebase version branches from main automatically again and apply all changes.

This is a sample workflow github:
```
name: Deploy fixes to other versions with rebase main

on:
  push:
    branches:
      - main

permissions: write-all

jobs:
  deploy-subversions:
    uses: Odoo-Ninjas/git-workflows/.github/workflows/deploy_to_subversions.yml@v1
    with:
      branches: "11.0 12.0 13.0 14.0 15.0 16.0"
```


# Demo Videos

## Edit existing patch file and update it

[![Patching Gimera]](https://youtu.be/WQU9db5z9IY)


## gimera commit command

Case: you change code inside an integrated submodule and want to easily commit this.
Just do

```
git commit path branch message
```

How it works:
  * a patch file is created
  * the repo is cloned
  * patch file is applied
  * if something conflicts, then it is reported and you have to decide what to do

## Machine settings: ~/.gimera

Settings that belong to the machine, not to a project. JSON, so it stays easy
to extend:

```json
{
  "no_cache": ["odoo/odoo", "github.com/odoo/enterprise"]
}
```

  * `no_cache` - repos that never go into the golden cache. Gimera fetches
    exactly the needed state instead (`--single-branch --depth=1`). For
    odoo/odoo that is the difference between a few hundred MB and ~18 GB of
    history - worth it on build servers and hosting instances, while a
    developer machine usually wants the cache.

    A short `owner/repo` matches on any host; write `host/owner/repo` if the
    same name exists on two hosts. Both URL spellings (`git@github.com:...`
    and `https://github.com/...`) match the same entry.

Unknown keys are ignored, so an older gimera keeps working with a config
written by a newer one. A broken config aborts instead of being skipped -
a setting that silently does nothing is worse than none.

The path can be overridden with `GIMERA_CONFIG`.

## Some environment variables

  * GIMERA_NON_THREADED=1 - non threaded fetch
  * GIMERA_IGNORE_FETCH_ERRORS=1 - ignore any fetch error at fetch
  * GIMERA_NO_SHA_UPDATE=1 - no shas updated in gimera file
  * GIMERA_QUIET=1 - rsyncing quiet and git
  * GIMERA_NO_PRECOMMIT=1 - do not execute pre commits
  * GIMERA_NO_CACHE=1 - no golden cache at all (like listing every repo in `no_cache`)
  * GIMERA_CONFIG=/path/to/config - use another file instead of ~/.gimera
  * GIMERA_FULL_CLONE=1 - cache the file contents of the whole history too (see below)

## The golden cache holds no old file contents

The cache of an `integrated` repo is cloned with `--filter=blob:none`: gimera
gets every commit and every tree, but file contents only for the snapshots it
actually checks out. `git archive <sha>` fetches those on the fly and keeps
them, so the cache grows along the pins you use instead of along the history.

Measured on odoo/odoo (all branches, bare): **1.2 GB** for the clone and 1.4 GB
after the first checkout, against ~17 GB unfiltered. A pin bump of 300 commits
adds about 100 MB. Once a snapshot is in, it needs no network again.

Two things it does not apply to:

  * `submodule` repos keep the complete cache. `git submodule update` clones
    *out of* the cache, and a partial clone cannot serve that - its upload-pack
    aborts with "could not fetch ... from promisor remote".
  * caches that already exist stay as they are. Only new ones are filtered, so
    nothing gets re-downloaded because of an upgrade. Delete a cache directory
    to have it come back small.

The remote must allow it (`uploadpack.allowFilter`, on by default at GitHub and
GitLab). A remote that does not simply sends everything; gimera says so rather
than letting the disk fill up unexplained. `GIMERA_FULL_CLONE=1` turns the
filter off everywhere.

## Running tests

Tests run in Docker to ensure a clean, isolated environment (no host cache interference, fast ext4 filesystem).

```bash
# full test suite
make test

# only core tests (fast, ~3 min)
make test-quick

# only snapshot tests (~15 min)
make test-snapshots
```

Requires Docker. The image is built automatically on first run.

## Authors:
  * Marc Wimmer (marc@zebroo.de)

## Contributors
  * Michael Tietz (mtietz@mt-software.de)
  * Walter Saltzmann


## install directly

```bash
pip install git+https://github.com/marcwimmer/gimera
```
