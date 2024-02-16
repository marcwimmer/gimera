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
      patches: []
      type: submodule

      # default True
      enabled: True


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

### Re-Edit patch file:

```bash
gimera edit-patch file1.patch file2.patch
```

  * by this, you can combine several patch files into one again


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

## Deliver Patches with reused submodules.

In the submodule:
```yaml
gimera.yml

common:
  patches:
    - patches/${VERSION}

```

The main gimera which integrates the submodule should be:
```yaml
common:
  vars:
    VERSION: 15.0
repos:
  type: integrated
  url: .....
  path: sub1
```

After that a recursive gimera is required.
```
gimera apply -r
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

## Contributors
  * Marc Wimmer (marc@zebroo.de)
  * Michael Tietz (mtietz@mt-software.de)
  * Walter Saltzmann


## install directly

```bash
pip install git+https://github.com/marcwimmer/gimera
```
