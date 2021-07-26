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
      type: integrated
```

Then execute:

`>  gimera apply`

## How to make a patchfile:

From the example above: 

  * edit roles2/sub1/file1.txt
  * `>  gimera apply`

Then a patch file is created as suggestion in roles2/sub1_patches which you may commit and push.

## How to fetch latest versions:

  * `>  gimera apply --update`

Latest versions are pulled and patches are applied.

## How to upload new version

  * increase version in setup.py
  * rm -Rf dist
  * rm -Rf gimera.egg-info
  * python setup.py sdist
  * twine upload dist/*