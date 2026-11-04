"""The design basis of the steel member and connection checks (alpha 9 C3): load and resistance
factor design (LRFD: φ Rn against the strength combinations) or allowable strength design (ASD:
Rn / Ω against the allowable stress combinations), as the code pack's ``steel`` table chooses
(``designMethod``, overridable per project).

Every steel check writes its available strength as ``factor × Rn``: :func:`factor` gives φ
under LRFD and 1 / Ω under ASD, with Ω from the pack's ``omega`` (by the keys of ``phi``) or
``omegaFromPhi`` / φ. A pack without ``omegaFromPhi`` does not cover ASD: the checks stay LRFD
and the run says so (:func:`basis_note`).

ASD is used for a member only where SAEngine's other steel modules can follow it: not for the
members of a steel seismic force-resisting system, composite members or under the direct
analysis method (those are LRFD only); :func:`member_basis` says which and why.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from saengine.codes import context as code_context

LRFD = "LRFD"
ASD = "ASD"

#: The basis of the check in progress (set by :func:`using` around one member's checks).
_CURRENT: ContextVar[str] = ContextVar("steel_basis", default=LRFD)


def _table() -> Any | None:
    try:
        return code_context.table("steel")
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation): LRFD
        return None


def chosen() -> str:
    """The basis the pack (or the project's override) chooses: "LRFD" or "ASD"; "LRFD" when the
    pack sets ASD but cannot give Ω (no ``omegaFromPhi``)."""
    table = _table()
    if table is None or getattr(table, "designMethod", LRFD) != ASD:
        return LRFD
    return ASD if getattr(table, "omegaFromPhi", None) is not None else LRFD


def basis_note() -> str | None:
    """The run's note when the pack's choice of ASD cannot be followed (no Ω): None otherwise."""
    table = _table()
    if table is None or getattr(table, "designMethod", LRFD) != ASD:
        return None
    if getattr(table, "omegaFromPhi", None) is None:
        return (
            "steel: the design method is set to ASD, but the code pack gives no safety factors "
            "Ω (omegaFromPhi): the steel members are checked by LRFD"
        )
    return None


def current() -> str:
    """The basis of the check in progress."""
    return _CURRENT.get()


@contextlib.contextmanager
def using(basis: str) -> Iterator[None]:
    """Run the enclosed checks on ``basis`` ("LRFD" or "ASD")."""
    token = _CURRENT.set(basis)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def omega(name: str, phi: float) -> float:
    """Ω of limit state ``name`` (φ ``phi``): the pack's ``omega[name]``, else
    ``omegaFromPhi`` / φ."""
    table = _table()
    listed = (getattr(table, "omega", None) or {}).get(name) if table is not None else None
    if listed is not None:
        return float(listed)
    ratio = getattr(table, "omegaFromPhi", None) if table is not None else None
    if phi <= 0:
        return 1.0
    return float(ratio) / phi if ratio else 1.0 / phi


def factor(name: str, phi: float) -> float:
    """The factor on Rn of limit state ``name``: φ under LRFD, 1 / Ω under ASD."""
    if current() != ASD:
        return phi
    return 1.0 / omega(name, phi)


def symbol() -> str:
    """How notes name the factor: "φ" (LRFD) or "1/Ω" (ASD)."""
    return "1/Ω" if current() == ASD else "φ"


def member_basis(object_type: Any, seismic: bool, direct: bool) -> tuple[str, str]:
    """``(basis, why)`` of one steel member: the pack's choice, except that a composite member,
    a member of a steel seismic force-resisting system (``seismic``: its provisions apply) or a
    run by the direct analysis method (``direct``) stays LRFD (SAEngine practice: those modules
    work with φ and the strength combinations); ``why`` says so ("" when nothing changed)."""
    wanted = chosen()
    if wanted != ASD:
        return LRFD, ""
    if getattr(object_type, "composite", None) is not None:
        return LRFD, "checked by LRFD (composite members are designed by LRFD only)"
    if seismic:
        return LRFD, (
            "checked by LRFD (the steel seismic provisions apply: SAEngine designs their "
            "members by LRFD only)"
        )
    if direct:
        return LRFD, (
            "checked by LRFD (the direct analysis method runs on the strength combinations)"
        )
    return ASD, ""
