# FreeCAD profile table

`profiles.csv` is the table of standard structural profiles (I/H, channels, angles, tees,
rectangular and circular hollow sections) from FreeCAD's BIM workbench, unmodified. SAEngine
uses it to give dimensions to the library steel shapes that ETABS writes by name only
(`SHAPE "W14X90"`): see `saengine.importers.shapes` and `docs/import.md`.

| | |
| --- | --- |
| Source | https://github.com/FreeCAD/FreeCAD/blob/68f4a30a1b4be46176b883fcdab55a9de8c2433d/src/Mod/BIM/Presets/profiles.csv |
| Commit | `68f4a30a1b4be46176b883fcdab55a9de8c2433d` |
| Copyright | the FreeCAD contributors |
| Licence | LGPL-2.1-or-later (GNU Lesser General Public License version 2.1 or later), the licence of FreeCAD; its text is in `LICENSE` |
| SHA-256 of `profiles.csv` | `f02b6c83af626b7a73861e61b60ada0cbf976d7ae0da6113e0c883b04ed1cbf6` |

The file is data, read as text; it is shipped as it is (no part of it is modified), so it is its
own source. Rows are `Category,Name,class,dimensions in mm`; the classes and the order of their
dimensions are described in `saengine.importers.shapes`. There are no root radii: the import
report says so ("from the FreeCAD profile table, root radius ignored").

The installer copies `profiles.csv` into the bundled backend
(`saengine/importers/data/freecad-profiles.csv`, `scripts/installer/bundle-python.ps1`) and
lists it in the third-party notices (`scripts/installer/write_notices.py`).

To update it, replace `profiles.csv` with the file of a newer FreeCAD commit, and update the
commit, the source link and the SHA-256 above (a test checks the SHA-256).
