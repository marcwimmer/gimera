import os
import inquirer
gitcmd = ["git", "-f", "-c", "protocol.file.allow=always"]
try:
    inquirer_theme = inquirer.themes.GreenPassion()
except:
    inquirer_theme = None

REPO_TYPE_INT = "integrated"
REPO_TYPE_SUB = "submodule"