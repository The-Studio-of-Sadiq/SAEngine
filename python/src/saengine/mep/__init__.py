"""MEP coordination (Part 7): equipment loads, sleeve and opening checks, clashes with the
structure. The model is :mod:`saengine.library.mep` (``07 MEP/mep.json``)."""

from __future__ import annotations

from typing import Any


def mep_report(project_root: Any, out_dir: Any = None, mep_text: str | None = None) -> dict:
    """:func:`saengine.mep.report.mep_report`."""
    from saengine.mep.report import mep_report as report

    return report(project_root, out_dir, mep_text)


def mep_suggest_sleeves(
    project_root: Any, allowance: float = 25.0, mep_text: str | None = None
) -> dict[str, Any]:
    """:func:`saengine.mep.report.mep_suggest_sleeves`."""
    from saengine.mep.report import mep_suggest_sleeves as suggest

    return suggest(project_root, allowance, mep_text)


def mep_import_ifc(project_root: Any, path: Any, copy: bool = False) -> dict[str, Any]:
    """:func:`saengine.mep.ifc_import.mep_import_ifc`."""
    from saengine.mep.ifc_import import mep_import_ifc as inspect

    return inspect(project_root, path, copy)


__all__ = ["mep_import_ifc", "mep_report", "mep_suggest_sleeves"]
