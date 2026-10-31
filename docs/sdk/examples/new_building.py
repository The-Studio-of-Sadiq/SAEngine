"""Generate a building from a specification and print what was made (SAEngine SDK example).

The New Building wizard does the same, then writes the parts into a new project folder; the
command line's ``saengine new-building`` writes the project too.

    python new_building.py
"""

from __future__ import annotations

import json
import sys

from saengine import api


def main() -> int:
    # Start from the built-in building template the wizard uses, then change it.
    start = next(t for t in api.building_templates()["templates"] if t["type"] == "spec")
    spec = api.BuildingSpec.model_validate({**start["spec"], "name": "Clinic", "storyCount": 4})
    parts = api.generate_building(spec)
    print(json.dumps(parts["summary"], indent=2))
    for note in parts["notes"]:
        print("note:", note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
