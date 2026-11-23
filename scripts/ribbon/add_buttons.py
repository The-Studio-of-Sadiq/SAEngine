"""Adds researched buttons to scripts/ribbon/ribbon_catalog.json.

    python scripts/ribbon/add_buttons.py additions1.json [additions2.json ...]

Each file is a JSON array of ``{"tabId", "group", "buttons": [{"label", "size", "description"}]}``
(the "fill every tab" research round, 2026-11-23). A button joins its group (or a new group
of the tab); a label already in the same scope (window or sub-window) is skipped, so nothing
shows twice in one window. Run gen_ribbon_catalog.py afterwards.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

CATALOG = Path(__file__).parent / "ribbon_catalog.json"
# Labels that name a design code or another program: the code pack decides (code independence).
FORBIDDEN = re.compile(r"\b(ASCE|Eurocode|BNBC|ACI|AISC|ETABS|SAP2000|STAAD|IS 456|EN 19\d\d)\b")


def main(paths: list[str]) -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    scopes: dict[str, str] = catalog["scopes"]
    tab_labels = {t["id"]: t["label"].lower() for t in catalog["tabs"]}
    seen: dict[str, set[str]] = collections.defaultdict(set)
    for tab_id, label in tab_labels.items():
        seen[scopes[tab_id]].add(label)
    groups: dict[tuple[str, str], dict] = {}
    for group in catalog["groups"]:
        groups[(group["tab"], group["group"].lower())] = group
        for button in group["buttons"]:
            seen[scopes[group["tab"]]].add(button["label"].lower())
    added = skipped = 0
    for path in paths:
        for item in json.loads(Path(path).read_text(encoding="utf-8")):
            tab = item.get("tabId")
            if tab not in scopes:
                skipped += len(item.get("buttons", []))
                continue
            scope = scopes[tab]
            key = (tab, item["group"].lower())
            group = groups.get(key)
            if group is None:
                group = {"tab": tab, "group": item["group"], "buttons": []}
                groups[key] = group
                catalog["groups"].append(group)
            for button in item["buttons"]:
                label = button["label"].strip()
                if (
                    label.lower() in seen[scope]
                    or FORBIDDEN.search(label)
                    or len(label.split()) > 4
                ):
                    skipped += 1
                    continue
                seen[scope].add(label.lower())
                group["buttons"].append(
                    {
                        "label": label,
                        "size": "large" if button.get("size") == "large" else "small",
                        "description": button.get("description") or f"{label}.",
                        "inspiredBy": "",
                    }
                )
                added += 1
    catalog["groups"] = [g for g in catalog["groups"] if g["buttons"]]
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"added {added}, skipped {skipped}")


if __name__ == "__main__":
    main(sys.argv[1:])
