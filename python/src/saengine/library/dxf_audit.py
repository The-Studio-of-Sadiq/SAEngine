"""DXF files checked and repaired with ezdxf's auditor before they leave SAEngine.

The floor plans the app exports (11 Exports/Floor Plan) are written by the CAD editor's DXF
writer (mlightcad), which leaves entity transparency "ByLayer" as an invalid value, MTEXT
without a text style and its object dictionaries' owner handles pointing at the template's
(walkthrough 3, OI-7): ezdxf, LibreCAD and AutoCAD repair them on every open. :func:`clean_dxf`
reads such a file with ezdxf's recover mode, lets the auditor repair it and writes it back,
so the file passes an audit with no fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def audit_dxf(path: str | Path) -> dict[str, Any]:
    """``{"errors", "fixes"}``: the numbers ezdxf's auditor reports for the file as it is."""
    import ezdxf

    auditor = ezdxf.readfile(str(path)).audit()
    return {"errors": len(auditor.errors), "fixes": len(auditor.fixes)}


def clean_dxf(path: str | Path) -> dict[str, Any]:
    """Repairs the DXF at ``path`` in place (ezdxf recover + audit, written back in its own
    DXF version): ``{"path", "fixed", "errors"}`` with the repairs made and the errors left."""
    from ezdxf import recover

    target = Path(path)
    doc, auditor = recover.readfile(str(target))
    fixed = len(auditor.fixes)
    second = doc.audit()
    fixed += len(second.fixes)
    if fixed:
        doc.saveas(str(target))
    return {"path": str(target), "fixed": fixed, "errors": len(second.errors)}


def rpc_clean_dxf(params: dict[str, Any]) -> dict[str, Any]:
    """``cad/cleanDxf`` ``{paths}`` -> ``{ok, files: [{path, fixed, errors}]}``; a file that
    cannot be read is reported with its message (``ok`` false), the others are still cleaned."""
    files = []
    ok = True
    for path in params.get("paths") or []:
        try:
            files.append(clean_dxf(path))
        except Exception as error:  # noqa: BLE001 - reported per file
            ok = False
            files.append({"path": str(path), "message": str(error)})
    return {"ok": ok, "files": files}
