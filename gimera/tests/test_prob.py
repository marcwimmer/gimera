from .fixtures import *  # required for all
import itertools
import yaml
from contextlib import contextmanager
from ..repo import Repo
import os
import subprocess
import inspect
import os
from pathlib import Path
from .tools import gimera_apply
from ..tools import rsync
from . import temppath
from .tools import _make_remote_repo
from .tools import clone_and_commit
from .tools import gimera_commit

from ..consts import gitcmd as git
import time

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)

