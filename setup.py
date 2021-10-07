#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Note: To use the 'upload' functionality of this file, you must:
#   $ pipenv install twine --dev

import io
import os
import sys
from shutil import rmtree
from pathlib import Path

from setuptools import find_packages, setup, Command
from setuptools.command.install import install
from subprocess import check_call, check_output



# Package meta-data.
NAME = 'gimera'
DESCRIPTION = 'Handling git submodules and patches.'
URL = 'https://github.com/marcwimmer/gimera'
EMAIL = 'marc@itewimmer.de'
AUTHOR = 'Marc-Christian Wimmer'
REQUIRES_PYTHON = '>=3.6.0'
VERSION = '0.3.17'

# What packages are required for this module to be executed?
REQUIRED = [
	"gitpython", "click", "inquirer", "pyyaml", "pathlib"
]

# What packages are optional?
EXTRAS = {
    # 'fancy feature': ['django'],
}

# The rest you shouldn't have to touch too much :)
# ------------------------------------------------
# Except, perhaps the License and Trove Classifiers!
# If you do change the License, remember to change the Trove Classifier for that!

here = os.path.abspath(os.path.dirname(__file__))

# Import the README and use it as the long-description.
# Note: this will only work if 'README.md' is present in your MANIFEST.in file!
try:
    with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
        long_description = '\n' + f.read()
except FileNotFoundError:
    long_description = DESCRIPTION

# Load the package's __version__.py module as a dictionary.
about = {}
if not VERSION:
    project_slug = NAME.lower().replace("-", "_").replace(" ", "_")
    with open(os.path.join(here, project_slug, '__version__.py')) as f:
        exec(f.read(), about)
else:
    about['__version__'] = VERSION


class UploadCommand(Command):
    """Support setup.py upload."""

    description = 'Build and publish the package.'
    user_options = []

    @staticmethod
    def status(s):
        """Prints things in bold."""
        print('\033[1m{0}\033[0m'.format(s))

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            self.status('Removing previous builds…')
            rmtree(os.path.join(here, 'dist'))
        except OSError:
            pass

        self.status('Building Source and Wheel (universal) distribution…')
        os.system('{0} setup.py sdist bdist_wheel --universal'.format(sys.executable))

        self.status('Uploading the package to PyPI via Twine…')
        os.system('twine upload dist/*')

        self.status('Pushing git tags…')
        os.system('git tag v{0}'.format(about['__version__']))
        os.system('git push --tags')

        sys.exit()

def setup_click_autocompletion():

    def setup_for_bash():
        path = Path("/etc/bash_completion.d")
        done_bash = False
        if path.exists():
            if os.access(path, os.W_OK):
                os.system(f"_{NAME.upper()}_COMPLETE=bash_source {NAME} > '{path / NAME}'")
                done_bash = True
        if not done_bash:
            if not (path / NAME).exists():
                bashrc = Path(os.path.expanduser("~")) / '.bashrc'
                complete_file = bashrc.parent / f'.{NAME}-completion.sh'
                os.system(f"_{NAME.upper()}_COMPLETE=bash_source {NAME} > '{complete_file}'")
                if complete_file.name not in bashrc.read_text():
                    content = bashrc.read_text()
                    content += '\nsource ' + complete_file.name
                    bashrc.write_text(content)
    setup_for_bash()

    

class InstallCommand(install):
    """Post-installation for installation mode."""
    def run(self):
        install.run(self)
        setup_click_autocompletion()

# Where the magic happens:
setup(
    name=NAME,
    version=about['__version__'],
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type='text/markdown',
    author=AUTHOR,
    author_email=EMAIL,
    python_requires=REQUIRES_PYTHON,
    url=URL,
    # packages=find_packages(exclude=["tests", "*.tests", "*.tests.*", "tests.*"]),
    # If your package is a single module, use this instead of 'packages':
    py_modules=['gimera'],

    entry_points={
        'console_scripts': ['gimera=gimera:gimera'],
    },
    data_files=[
    ],
    install_requires=REQUIRED,
    extras_require=EXTRAS,
    include_package_data=True,
    license='MIT',
    classifiers=[
        # Trove classifiers
        # Full list: https://pypi.python.org/pypi?%3Aaction=list_classifiers
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy'
    ],
    # $ setup.py publish support.
    cmdclass={
        'upload': UploadCommand,
        'install': InstallCommand,
    },
)
