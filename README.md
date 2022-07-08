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
repos:
    # make ordinary git submodule:
    - url: "https://github.com/foo/bar"
      branch: branch1
      path: roles/sub1
      patches: []
      type: submodule


    # instead of submodule put the content directly in the repository;
    # apply patches from local git repository
    - url: "https://github.com/foo/bar"
      branch: branch1
      path: roles2/sub1
      patches:
          - 'roles2/sub1_patches'
      type: integrated

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

## How to fetch only one or more repo:

```bash
gimera apply repo_path repo_path2 repo_path3`
```
## How to fetch latest versions:

```bash
gimera apply --update
```

Latest versions are pulled and patches are applied.


## Contributors
  * Michael Tietz (mtietz@mt-software.de)
  * Walter Saltzmann


## install directly

```bash
pip install git+https://github.com/marcwimmer/gimera
```
