"""Writes the feature registry for the workbench build.

    python -m saengine.features.export scripts/ribbon/features.json

scripts/ribbon/gen_ribbon_catalog.py reads the file: a catalog button with a feature here gets
its input panel instead of the planned-feature page.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from saengine.features import INDEX, describe, module_index


def main(out: str) -> None:
    features = describe()
    Path(out).write_text(
        json.dumps(features, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # The package's own index: a run imports only the feature's module.
    INDEX.write_text(json.dumps(module_index(), indent=0) + chr(10), encoding="utf-8")
    print(f"{len(features)} features -> {out} and {INDEX.name}")


if __name__ == "__main__":
    main(sys.argv[1])
