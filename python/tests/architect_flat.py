"""A synthetic architect-style DXF of a two-bedroom flat on a 3 x 2 bay grid (4 m bays across,
4.5 m bays deep), drawn as architects in Bangladesh draw a typical floor: 250 mm outer and grid
walls and 125 mm partitions as double lines stopping at the columns, door blocks with swings,
window blocks, room names with their sizes, and the layers around them (columns, grid, hatch,
dimensions, furniture, title). Made by ezdxf for the DWG/DXF import tests and walkthroughs; it is
no client's drawing.

    python tests/architect_flat.py <out.dxf>
"""

from __future__ import annotations

import itertools
import math
import sys

import ezdxf
from shapely.geometry import LineString, box
from shapely.ops import unary_union

#: Where grid A-1 is in the architect's drawing [mm] (an architect's own origin).
ORIGIN = (52000.0, 31000.0)
GRID_X = {"A": 0, "B": 4000, "C": 8000, "D": 12000}
GRID_Y = {"1": 0, "2": 4500, "3": 9000}
#: Columns 300 x 500 mm (500 deep along y) at every grid point.
COLUMN = (300, 500)

#: Wall centre lines (plan mm, grid A-1 at 0, 0) and thicknesses.
WALLS = [
    (((0, 0), (12000, 0)), 250),
    (((12000, 0), (12000, 9000)), 250),
    (((12000, 9000), (0, 9000)), 250),
    (((0, 9000), (0, 0)), 250),
    (((0, 4500), (12000, 4500)), 250),  # on grid 2
    (((9000, 0), (9000, 4500)), 125),  # kitchen
    (((5000, 0), (5000, 1500)), 125),  # living / dining: a 1.5 m opening, no door
    (((5000, 3000), (5000, 4500)), 125),
    (((4500, 4500), (4500, 9000)), 125),  # bed room 1
    (((6500, 4500), (6500, 9000)), 125),  # bed room 2
    (((4500, 6500), (6500, 6500)), 125),  # lobby / toilet 1
    (((10000, 4500), (10000, 9000)), 125),  # bed room 2 / store, toilet 2
    (((10000, 6500), (12000, 6500)), 125),  # store / toilet 2
]

#: Doors: block, wall (by its centre line), hinge and jamb (plan mm), side it swings to (+1: left
#: of the hinge-to-jamb direction).
DOORS = [
    ("DOOR-1000", (5400, 0), (6400, 0), 1),  # main door, into the dining room
    ("DOOR-900", (5300, 4500), (6200, 4500), 1),  # dining to the lobby
    ("DOOR-900", (4500, 4800), (4500, 5700), 1),  # bed room 1 (swings into it, -x)
    ("DOOR-900", (6500, 5700), (6500, 4800), 1),  # bed room 2 (swings into it, +x)
    ("DOOR-750", (5000, 6500), (5750, 6500), 1),  # toilet 1, from the lobby
    ("DOOR-750", (10000, 7000), (10000, 7750), -1),  # toilet 2, from bed room 2
    ("DOOR-750", (10000, 4800), (10000, 5550), -1),  # store, from bed room 2
    ("DOOR-900", (9000, 1500), (9000, 2400), -1),  # kitchen, from the dining room
]
#: Windows: start and end along their wall (plan mm).
WINDOWS = [
    ((1000, 0), (2500, 0)),  # living
    ((0, 1500), (0, 3000)),
    ((6550, 0), (7750, 0)),  # dining
    ((10200, 0), (11400, 0)),  # kitchen
    ((12000, 1500), (12000, 2700)),
    ((0, 6000), (0, 7500)),  # bed room 1
    ((1500, 9000), (3000, 9000)),
    ((8300, 9000), (9500, 9000)),  # bed room 2
    ((5200, 9000), (5800, 9000)),  # toilet 1 ventilator
    ((10700, 9000), (11300, 9000)),  # toilet 2 ventilator
]
ROOMS = [
    ("LIVING", "15'-0\" x 14'-0\"", (2300, 2500)),
    ("DINING", "12'-6\" x 14'-0\"", (7000, 2600)),
    ("KITCHEN", "9'-6\" x 14'-0\"", (10500, 2600)),
    ("MASTER BED", "14'-0\" x 14'-0\"", (2200, 6900)),
    ("LOBBY", None, (5500, 5300)),
    ("TOILET-1", "6'-0\" x 7'-6\"", (5500, 7600)),
    ("BED ROOM-2", "11'-0\" x 14'-0\"", (8200, 6900)),
    ("STORE", None, (11000, 5500)),
    ("TOILET-2", "6'-0\" x 7'-6\"", (11000, 7700)),
]


def _segments(shape):
    for polygon in getattr(shape, "geoms", [shape]):
        for ring in [polygon.exterior, *polygon.interiors]:
            yield from itertools.pairwise(ring.coords)


def _thickness_at(point) -> float:
    for (a, b), t in WALLS:
        if LineString([a, b]).distance(LineString([point, point])) < 1:
            return t
    raise ValueError(point)


def make(path: str) -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    layers = {
        "A-WALL": 7,
        "A-WALL-PATT": 8,
        "A-DOOR": 30,
        "A-GLAZ": 4,
        "A-ROOM-NAME": 3,
        "A-ROOM-SIZE": 3,
        "A-FURN": 9,
        "A-DIMS": 1,
        "A-TITLE": 7,
        "S-COLS": 5,
        "S-GRID": 1,
    }
    for name, color in layers.items():
        doc.layers.add(name, color=color)

    def at(p):
        return (ORIGIN[0] + p[0], ORIGIN[1] + p[1])

    for width in (750, 900, 1000):
        block = doc.blocks.new(f"DOOR-{width}")
        block.add_line((0, 0), (0, width))
        block.add_arc((0, 0), width, 0, 90)
        block.add_line((0, 0), (0, -40))  # the frame at the hinge
        block.add_line((width, 0), (width, -40))
    window = doc.blocks.new("WINDOW")  # unit length, scaled to the width, for 250 walls
    for y in (-125, -25, 25, 125):
        window.add_line((0, y), (1, y))
    window.add_line((0, -125), (0, 125))
    window.add_line((1, -125), (1, 125))
    bed = doc.blocks.new("BED-DOUBLE")
    bed.add_lwpolyline([(0, 0), (1800, 0), (1800, 2000), (0, 2000)], close=True)
    bed.add_lwpolyline([(150, 1650), (800, 1650), (800, 1950), (150, 1950)], close=True)
    bed.add_lwpolyline([(1000, 1650), (1650, 1650), (1650, 1950), (1000, 1950)], close=True)

    walls = unary_union(
        [
            LineString([a, b]).buffer(t / 2, cap_style="square", join_style="mitre")
            for (a, b), t in WALLS
        ]
    )
    columns = [
        box(x - COLUMN[0] / 2, y - COLUMN[1] / 2, x + COLUMN[0] / 2, y + COLUMN[1] / 2)
        for x in GRID_X.values()
        for y in GRID_Y.values()
    ]
    cuts = list(columns)
    for _, hinge, jamb, _ in DOORS:
        cuts.append(
            LineString([hinge, jamb]).buffer(_thickness_at(hinge) / 2 + 5, cap_style="flat")
        )
    for a, b in WINDOWS:
        cuts.append(LineString([a, b]).buffer(130, cap_style="flat"))
    faces = walls.difference(unary_union(cuts)).simplify(0)
    msp = doc.modelspace()
    for a, b in _segments(faces):
        msp.add_line(at(a), at(b), dxfattribs={"layer": "A-WALL"})
    for polygon in getattr(faces, "geoms", [faces]):
        hatch = msp.add_hatch(color=8, dxfattribs={"layer": "A-WALL-PATT"})
        hatch.set_pattern_fill("ANSI31", scale=20)
        hatch.paths.add_polyline_path([at(p) for p in polygon.exterior.coords], is_closed=True)
    for column in columns:
        msp.add_lwpolyline(
            [at(p) for p in list(column.exterior.coords)[:-1]],
            close=True,
            dxfattribs={"layer": "S-COLS"},
        )

    for block, hinge, jamb, side in DOORS:
        t = _thickness_at(hinge)
        ux, uy = (
            (jamb[0] - hinge[0]) / math.dist(hinge, jamb),
            (jamb[1] - hinge[1]) / math.dist(hinge, jamb),
        )
        # The block's hinge on the face it swings from.
        face = (hinge[0] - uy * side * t / 2, hinge[1] + ux * side * t / 2)
        msp.add_blockref(
            block,
            at(face),
            dxfattribs={
                "layer": "A-DOOR",
                "rotation": math.degrees(math.atan2(uy, ux)),
                "yscale": side,
            },
        )
    for a, b in WINDOWS:
        msp.add_blockref(
            "WINDOW",
            at(a),
            dxfattribs={
                "layer": "A-GLAZ",
                "xscale": math.dist(a, b),
                "rotation": math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])),
            },
        )
    for name, size, point in ROOMS:
        msp.add_text(
            name, height=200, dxfattribs={"layer": "A-ROOM-NAME", "insert": at(point), "halign": 1}
        ).set_placement(at(point), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        if size:
            below = (point[0], point[1] - 350)
            msp.add_text(size, height=150, dxfattribs={"layer": "A-ROOM-SIZE"}).set_placement(
                at(below), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
            )
    msp.add_blockref("BED-DOUBLE", at((1300, 6500)), dxfattribs={"layer": "A-FURN"})
    msp.add_blockref("BED-DOUBLE", at((7300, 6700)), dxfattribs={"layer": "A-FURN"})
    msp.add_lwpolyline(
        [at((600, 600)), at((2900, 600)), at((2900, 1400)), at((600, 1400))],
        close=True,
        dxfattribs={"layer": "A-FURN"},
    )  # sofa

    for label, x in GRID_X.items():
        msp.add_line(
            at((x, -2000)), at((x, 10500)), dxfattribs={"layer": "S-GRID", "linetype": "CENTER"}
        )
        msp.add_circle(at((x, -2400)), 400, dxfattribs={"layer": "S-GRID"})
        msp.add_text(label, height=350, dxfattribs={"layer": "S-GRID"}).set_placement(
            at((x, -2400)), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        )
    for label, y in GRID_Y.items():
        msp.add_line(
            at((-2000, y)), at((13500, y)), dxfattribs={"layer": "S-GRID", "linetype": "CENTER"}
        )
        msp.add_circle(at((-2400, y)), 400, dxfattribs={"layer": "S-GRID"})
        msp.add_text(label, height=350, dxfattribs={"layer": "S-GRID"}).set_placement(
            at((-2400, y)), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        )
    for x0, x1 in itertools.pairwise(GRID_X.values()):
        dim = msp.add_linear_dim(
            base=at((0, -1200)),
            p1=at((x0, 0)),
            p2=at((x1, 0)),
            dxfattribs={"layer": "A-DIMS"},
            override={"dimtxt": 200, "dimasz": 150, "dimexo": 100},
        )
        dim.render()
    msp.add_text("TYPICAL FLOOR PLAN", height=400, dxfattribs={"layer": "A-TITLE"}).set_placement(
        at((6000, -3600)), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
    )
    msp.add_text("SCALE 1:100", height=200, dxfattribs={"layer": "A-TITLE"}).set_placement(
        at((6000, -4100)), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
    )
    doc.saveas(path)


if __name__ == "__main__":
    make(sys.argv[1])
