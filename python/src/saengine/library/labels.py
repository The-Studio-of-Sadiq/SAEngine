"""Display labels for library fields.

They become the JSON Schema ``title``s, which the visual editors show as field labels.
Fields not listed get their name split into words ("flightWidth" -> "Flight width").
"""

from __future__ import annotations

import re

LABELS: dict[str, str] = {
    "id": "ID",
    "E": "Young's modulus E",
    "nu": "Poisson's ratio ν",
    "alpha": "Thermal expansion α",
    "fc": "Compressive strength f'c",
    "ft": "Tensile strength fr",
    "fy": "Yield strength fy",
    "fu": "Tensile strength fu",
    "fm": "Masonry strength f'm",
    "maxAggregate": "Max. aggregate size",
    "waterCement": "Water/cement ratio",
    "fineAggregate": "Fine aggregate (sand)",
    "xDim": "Width",
    "yDim": "Depth",
    "dia": "Bar diameter",
    "count": "Number of bars",
    "legs": "Legs",
    "bottomX": "Bottom layer, X",
    "bottomY": "Bottom layer, Y",
    "topX": "Top layer, X",
    "topY": "Top layer, Y",
    "pileCount": "Number of piles",
    "pile": "Pile type",
    "material": "Material",
    "schema": "Schema",
}


def field_title(name: str, *_: object) -> str:
    if name in LABELS:
        return LABELS[name]
    if name.isupper():
        return name  # load case and code symbols ("SD", "WX") stay as they are
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", name).split()
    return " ".join([words[0].capitalize(), *(w.lower() for w in words[1:])])
