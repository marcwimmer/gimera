import click

class RuntimeState:
    mode = None
    flags = {}

runtime_state = {
    'temppaths': {
    }
}

from . import consts
from . import gimera
from . import repo
from . import gitcommands
from . import tools
from . import snapshot

