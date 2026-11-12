"""Make the DWG test fixtures: SAEngine's own plan geometry, saved by AutoCAD in each version.

    python -I make_fixtures.py [--acad "C:\\Program Files\\Autodesk\\AutoCAD 2027\\accoreconsole.exe"]

Writes ``plan.dxf`` (ezdxf: a small floor plan drawn here, in mm, on known layers within a known
extent) and, with ``--acad``, ``plan-r<version>.dwg`` for each of :data:`VERSIONS`: the licensed
AutoCAD's headless console opens the DXF and runs its documented SAVEAS command with a file
format (one script per version). Nothing else of AutoCAD is used; the DWGs hold only this
geometry. The tests (``test_dwg.py``) read the committed files and never need AutoCAD.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The drawing's extent [mm] and layers, which the tests check after a round trip.
EXTENT = ((0.0, 0.0), (12000.0, 9000.0))
LAYERS = ("A-WALL", "A-DOOR", "A-GRID", "A-TEXT")
#: SAVEAS file formats of AutoCAD's command line, by the fixture's name.
VERSIONS = {
    "r2000": "2000",
    "r2004": "2004",
    "r2007": "2007",
    "r2010": "2010",
    "r2013": "2013",
    "r2018": "2018",
}


def make_dxf(path: Path) -> None:
    import ezdxf

    doc = ezdxf.new("R2018", setup=False, units=4)  # 4: mm
    for i, name in enumerate(LAYERS):
        doc.layers.add(name, color=i + 1)
    msp = doc.modelspace()
    (x0, y0), (x1, y1) = EXTENT
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                       dxfattribs={"layer": "A-WALL"})  # fmt: skip
    msp.add_lwpolyline([(250, 250), (11750, 250), (11750, 8750), (250, 8750)], close=True,
                       dxfattribs={"layer": "A-WALL"})  # fmt: skip
    msp.add_line((6000, 250), (6000, 8750), dxfattribs={"layer": "A-WALL"})
    msp.add_line((250, 4500), (6000, 4500), dxfattribs={"layer": "A-WALL"})
    for x in (1000.0, 6000.0, 11000.0):
        msp.add_line((x, 500), (x, 8500), dxfattribs={"layer": "A-GRID"})
    for y in (1000.0, 8000.0):
        msp.add_line((500, y), (11500, y), dxfattribs={"layer": "A-GRID"})
    msp.add_arc((6000, 2000), 900, 90, 180, dxfattribs={"layer": "A-DOOR"})
    msp.add_line((6000, 2000), (6000, 2900), dxfattribs={"layer": "A-DOOR"})
    msp.add_circle((3000, 6500), 300, dxfattribs={"layer": "A-DOOR"})
    msp.add_text("BED ROOM", height=250, dxfattribs={"layer": "A-TEXT", "insert": (2000, 6000)})
    msp.add_text("LIVING", height=250, dxfattribs={"layer": "A-TEXT", "insert": (8000, 4000)})
    doc.saveas(path)


def make_dwgs(acad: Path, dxf: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="saengine-dwg-") as tmp:
        work = Path(tmp)
        for name, fmt in VERSIONS.items():
            out = work / f"plan-{name}.dwg"
            script = work / f"{name}.scr"
            script.write_text(f'FILEDIA 0\n_.SAVEAS {fmt} "{out}"\n', encoding="ascii")
            subprocess.run(
                [str(acad), "/i", str(dxf), "/s", str(script), "/l", "en-US"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                timeout=300,
                check=False,
            )
            if not out.is_file():
                print(f"{name}: AutoCAD wrote no {out.name}", file=sys.stderr)
                continue
            shutil.copy2(out, HERE / out.name)
            print(f"{name}: {out.stat().st_size} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--acad", type=Path, help="AutoCAD's accoreconsole.exe")
    args = parser.parse_args()
    dxf = HERE / "plan.dxf"
    make_dxf(dxf)
    if args.acad:
        make_dwgs(args.acad, dxf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
