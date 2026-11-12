"""The backend's version is the SAEngine release's: archives and the CLI report it."""

import json
from pathlib import Path

import saengine

PACKAGE_JSON = Path(__file__).resolve().parents[2] / "workbench" / "package.json"


def test_backend_version_is_the_app_release():
    app = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]
    assert saengine.__version__ == app, (
        f"saengine.__version__ is {saengine.__version__} but workbench/package.json is {app}: "
        "bump python/src/saengine/__init__.py with every release"
    )
