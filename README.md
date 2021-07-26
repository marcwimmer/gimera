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

`gimera apply`


## How to upload new version

  * increase version in setup.py
  * rm -Rf dist
  * rm -Rf gimera.egg-info
  * python setup.py sdist
  * twine upload dist/*