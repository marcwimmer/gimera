import inquirer
gitcmd = ["git", "-c", "protocol.file.allow=always"]
inquirer_theme = inquirer.themes.GreenPassion()

REPO_TYPE_INT = "integrated"
REPO_TYPE_SUB = "submodule"