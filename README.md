# Welcome to GIMERA


## How to install:

  * pip install gimera



## How to use:

Put gimera.yml into your root folder of your project:

```yaml
repos:
    - url: "https://github.com/marcwimmer/gimera"
      branch: branch1
      path: roles/sub1
      patches: []
      type: submodule
    - url: "https://github.com/marcwimmer/gimera"
      branch: branch1
      path: roles2/sub1
      patches: 
          - 'roles2/sub1_patches'
      remotes:
          gimera-mt: https://github.com/mt-software-de/gimera.git
      merges:
          - gimera-mt main
          - origin refs/pull/1/head
      type: integrated
```

Then execute:

`>  gimera apply`

## How to make a patchfile:

From the example above: 

  * edit roles2/sub1/file1.txt
  * `>  gimera apply`

Then a patch file is created as suggestion in roles2/sub1_patches which you may commit and push.
## How to fetch only one or more repo:

  * `>  gimera apply repo_path repo_path2 repo_path3`
## How to fetch latest versions:

  * `>  gimera apply --update`

Latest versions are pulled and patches are applied.

## How to upload new version

  * increase version in setup.py
  * rm -Rf dist
  * rm -Rf gimera.egg-info
  * python setup.py sdist
  * twine upload dist/*


## install directly

pip install git+https://github.com/marcwimmer/gimera
