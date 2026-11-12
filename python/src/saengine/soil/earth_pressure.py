"""Lateral earth pressure coefficients (soil mechanics, not a design-code value).

The at-rest coefficient of ground tanks (Jaky's K0 = 1 - sin φ') is in
:mod:`saengine.plumbing.tanks`, which applies it layer by layer; this module holds the active
pressure of a wall that may move away from the soil (a cantilever retaining wall). The code
asks for the lateral soil pressure without prescribing the theory (the default pack's BNBC
2020 Part 6 Sec 2.6.5).
"""

from __future__ import annotations

import math


def rankine_active(phi_deg: float) -> float:
    """Ka = (1 - sin φ) / (1 + sin φ) = tan²(45° - φ/2): Rankine's active coefficient of a
    level backfill against a smooth vertical back."""
    s = math.sin(math.radians(phi_deg))
    return (1 - s) / (1 + s)


def rankine_passive(phi_deg: float) -> float:
    """Kp = 1 / Ka of a level ground."""
    return 1 / rankine_active(phi_deg)
