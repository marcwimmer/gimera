import inquirer
gitcmd = ["git", "-c", "protocol.file.allow=always"]
try:
    inquirer_theme = inquirer.themes.GreenPassion()
except:
    inquirer_theme = None

REPO_TYPE_INT = "integrated"
REPO_TYPE_SUB = "submodule"