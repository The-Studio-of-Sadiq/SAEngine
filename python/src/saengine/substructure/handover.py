"""The hand-over of the footings from Part 8 to Part 9.

Before Part 9, footings were drawn in the floor plan, became ``FootingElement``s of the building
model and were designed by Part 8's design report. Now the foundations live in
``09 Substructure/substructure.json`` and Part 9 designs them; Part 8 designs the superstructure
only (its analysis keeps fixed column bases: there is no soil-structure interaction).

A project from before Part 9 keeps working:

- its ``substructure.json`` is still the placeholder of a new project. While it is, the bill of
  quantities and the IFC take the footings of the building model as before
  (:func:`authoritative_substructure` returns None);
- the first time Part 9 is opened, or Run All designs the substructure, :func:`ensure_migrated`
  writes the building model's footings into ``substructure.json``
  (:func:`saengine.substructure.migrate.migrate`). The building model, the floor plan and the
  object types are left as they are: nothing is lost, and the footings drawn in the floor plan
  stay there, no longer measured or designed;
- from then on the substructure is the only source of the foundations.

A placeholder file whose building model has no footings is left alone: there is nothing to move.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from saengine.library.substructure import SUBSTRUCTURE_FILE, Substructure, is_placeholder, parse

BIM_FILE = "06 BIM/bim.json"


def authoritative_substructure(text: str | None) -> Substructure | None:
    """The substructure of ``text`` when it is the source of the project's foundations; None
    for a missing, empty or placeholder file (the building model's footings then still count).
    Raises ``ValueError`` for an invalid file."""
    if text is None or not text.strip():
        return None
    data = json.loads(text)
    if is_placeholder(data):
        return None
    return parse(text)


def needs_migration(project_root: str | Path) -> bool:
    """Whether the project's substructure is still the placeholder (or missing) while its
    building model has footings."""
    root = Path(project_root)
    try:
        text = (root / SUBSTRUCTURE_FILE).read_text(encoding="utf-8")
    except OSError:
        text = None
    try:
        if authoritative_substructure(text) is not None:
            return False
    except ValueError:
        return False  # an invalid file is the engineer's to fix, never overwritten
    try:
        bim = json.loads((root / BIM_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    elements = bim.get("elements", []) if isinstance(bim, dict) else []
    return any(isinstance(e, dict) and e.get("kind") == "footing" for e in elements)


def ensure_migrated(project_root: str | Path) -> dict[str, Any]:
    """Moves the building model's footings into ``substructure.json`` when it is still the
    placeholder (see the module's docstring). Returns ``{"migrated": bool, "count", "notes"}``;
    ``"problems"`` when the building model or the object types cannot be read."""
    from saengine.substructure.migrate import migrate_project

    root = Path(project_root)
    if not needs_migration(root):
        return {"migrated": False, "count": 0, "notes": []}
    try:
        result = migrate_project(root)
    except (OSError, ValueError) as error:
        return {
            "migrated": False,
            "count": 0,
            "notes": [],
            "problems": [f"The footings of 6 BIM could not be moved to 9 Substructure: {error}"],
        }
    path = root / SUBSTRUCTURE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(substructure_text(result["substructure"]), encoding="utf-8", newline="\n")
    return {"migrated": True, "count": result["count"], "notes": list(result["notes"])}


def substructure_text(data: Any) -> str:
    """The file text of a substructure's JSON data, as the Substructure editor writes it (tabs;
    whole numbers without a decimal point)."""

    def tidy(value: Any) -> Any:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {k: tidy(v) for k, v in value.items()}
        if isinstance(value, list):
            return [tidy(v) for v in value]
        return value

    return json.dumps(tidy(data), indent="\t", ensure_ascii=False) + "\n"
