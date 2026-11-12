"""The part files the actions read and edit, relative to the project folder
(:mod:`saengine.pipeline.project`)."""

from __future__ import annotations

from saengine.pipeline.project import part_by_id


def _path(part_id: str) -> str:
    relative = part_by_id(part_id).relative
    assert relative is not None
    return relative


SOIL = _path("soil")
SETTINGS = _path("settings")
MATERIALS = _path("materials")
OBJECTS = _path("objects")
FLOOR_PLAN = _path("floorPlan")
LOADS = _path("loads")
BIM = _path("bim")
MEP = _path("mep")
SUBSTRUCTURE = _path("substructure")
BOQ = _path("boq")

#: Path -> part id.
PART_OF_PATH = {
    SOIL: "soil",
    SETTINGS: "settings",
    MATERIALS: "materials",
    OBJECTS: "objects",
    FLOOR_PLAN: "floorPlan",
    LOADS: "loads",
    BIM: "bim",
    MEP: "mep",
    SUBSTRUCTURE: "substructure",
    BOQ: "boq",
}
