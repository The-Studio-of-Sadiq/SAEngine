"""List every installed package and the templates they offer (SAEngine SDK example).

python list_packages.py [project folder]
"""

from __future__ import annotations

import sys
from pathlib import Path

from saengine import api


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(f"saengine.api {api.API_VERSION}")
    for pack in api.list_packages(root, kind=None):
        state = "" if pack.usable else "  (has errors)"
        print(f"{pack.id:28} {pack.kind:18} {pack.scope:8} {pack.version or '':8}{state}")
    presets = api.structure_presets(root)["presets"]
    print(f"\n{len(presets)} structure presets:")
    for preset in presets:
        coded = " (coded)" if preset.get("coded") else ""
        print(f"  {preset['packageName']}: {preset['name']}{coded}")
    for template in api.building_templates(root)["templates"]:
        print(f"building template: {template['name']} ({template['type']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
