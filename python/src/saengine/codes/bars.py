"""Bar sizes of the code pack in force (alpha 9 C26): the nominal mass of a bar.

A pack's ``concrete.barDiameters`` give each bar size by a key that is its nominal diameter
[mm] in most standards (BNBC, EN 10080, IS 1786) and a designation in others (ASTM A615M
No. 10 is a 9.5 mm bar). The pack's ``concrete.barMasses`` give the standard's nominal mass of
such sizes; every other size weighs d²/162 kg/m (7850 kg/m³), as before. The bill of
quantities, the bar bending schedules, the precast pieces and the BVBS files all read
:func:`bar_mass`.
"""

from __future__ import annotations

import threading
from typing import Any

#: d² / DIVISOR [kg/m] with d [mm]: a round bar of steel at 7850 kg/m³.
DIVISOR = 162

_MEMO: tuple[Any, dict[str, float]] | None = None
_LOCK = threading.Lock()


def pack_bar_masses() -> dict[str, float]:
    """The nominal bar masses of the code pack in force (``concrete.barMasses``) by size key;
    {} when it gives none (or no pack is in force)."""
    global _MEMO
    try:
        from saengine.codes import context as code_context

        pack = code_context.current()
        memo = _MEMO
        if memo is not None and memo[0] is pack:
            return memo[1]
        masses = getattr(code_context.pack_table("concrete"), "barMasses", None) or {}
    except Exception:  # noqa: BLE001 - no pack in force, or one without a concrete table
        return {}
    found = {str(k): float(v) for k, v in masses.items()}
    with _LOCK:
        _MEMO = (pack, found)
    return found


def bar_mass(dia: float) -> float:
    """Mass of a bar [kg/m] of size ``dia`` (its key in the pack's ``barDiameters`` [mm]): the
    pack's nominal mass of the size where it gives one, else d²/162 (7850 kg/m³)."""
    found = pack_bar_masses().get(f"{dia:g}")
    return found if found is not None else dia * dia / DIVISOR
