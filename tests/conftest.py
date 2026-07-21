import os
import sys

# Ensure both the repository root and app directory are in sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
app_dir = os.path.join(repo_root, "app")

if app_dir not in sys.path:
    sys.path.insert(0, app_dir)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
