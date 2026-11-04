"""Which design method the code pack in force picks for each area of concrete and foundation
design: the hook points every pack's methods plug into.

A pack names its methods by id in its method tables (``concreteMethods``,
``geotechnicalMethods``): ``concreteMethods.torsion.method = "thinWalledVariableStrut"`` and so
on. The design modules ask :func:`concrete` (or :func:`geotechnical`) for the area they design
and run the method of that id; ``None`` means the default: the strength design with φ that
SAEngine's default pack (BNBC 2020) uses, unchanged. Nothing here tests a code's name.

Areas and their ids (the generic modules that compute them):

=================  =====================================  ==========================================
area               ids                                    module
=================  =====================================  ==========================================
``ultimate``       ``partialFactors``                     design_strength (and rc through it)
``shear``          ``variableStrut``                      strut_shear
``torsion``        ``thinWalledVariableStrut``            strut_shear, limit_state_rows
``punching``       ``controlPerimeter``                   perimeter_punching
``cracking``       ``directWidth``                        crack_control
``serviceStress``  ``stressLimits``                       crack_control
``deflection``     ``spanDepthK``                         crack_control, limit_state_rows
``slenderness``    ``nominalCurvature``                   limit_state_rows
``cover``          ``exposureClass``                      bar_rules
``anchorage``      ``bondStress``                         bar_rules (detailing, bar schedule)
``memberSteel``    ``memberSteel``                        bar_rules (checks and the proposal)
``seismic``        ``curvatureDuctility``                 curvature_ductility, capacity_design
``bearing``        ``effectiveArea``                      limit_state_geotechnics, limit_state_footings
``sliding``        ``interfaceFriction``                  limit_state_geotechnics, limit_state_footings
``piles``          ``correlationFactors``                 limit_state_geotechnics (ξ of piles)
=================  =====================================  ==========================================

The member kinds follow from these: slabs, stairs and walls take ``ultimate``, ``shear``,
``memberSteel`` and (walls) ``seismic``; beam-column joints and the capacity-design shear take
``seismic``; Design Reinforcement sizes with ``ultimate``, ``shear`` and ``memberSteel``.

Every concrete area but ``ultimate`` needs the partial factors (its resistances are written on
fcd and fyd): without ``ultimate`` none is selected.

Per project, any area can be set back to the default method with the override
``concreteMethods.parentMethods`` (or ``geotechnicalMethods.parentMethods``): a list of area
names designed by the parent (default) method.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

#: The concrete areas whose group in ``concreteMethods`` carries no ``method`` field: the id
#: the group's presence selects.
_IMPLIED = {"memberSteel": "memberSteel", "serviceStress": "stressLimits"}

#: The geotechnical areas: (group of ``geotechnicalMethods``, id when it has no ``method``).
_GEOTECHNICAL = {
    "bearing": ("bearing", None),
    "sliding": ("sliding", None),
    "piles": ("correlation", "correlationFactors"),
}


def _table(name: str) -> Any | None:
    pack = code_context.current()
    return pack.table(name) if pack.has(name) else None


def _method_of(table: Any, group: str, implied: str | None) -> str | None:
    found = getattr(table, group, None)
    if found is None:
        return None
    if group in (getattr(table, "parentMethods", None) or ()):
        return None
    return str(getattr(found, "method", None) or implied or "") or None


def concrete(area: str) -> str | None:
    """The method id the pack in force picks for concrete design ``area`` (see the module
    notes), or None for the default strength design with φ."""
    table = _table("concreteMethods")
    if table is None:
        return None
    if area in (getattr(table, "parentMethods", None) or ()):
        return None
    if area != "ultimate" and _method_of(table, "ultimate", None) is None:
        return None
    return _method_of(table, area, _IMPLIED.get(area))


def geotechnical(area: str) -> str | None:
    """The method id the pack in force picks for foundation design ``area`` (``bearing``,
    ``sliding``, ``piles``), or None for the default allowable-stress design."""
    table = _table("geotechnicalMethods")
    if table is None or area in (getattr(table, "parentMethods", None) or ()):
        return None
    group, implied = _GEOTECHNICAL[area]
    found = getattr(table, group, None)
    if found is None:
        return None
    return str(getattr(found, "method", None) or implied)


def uses(area: str, method: str) -> bool:
    """True when the pack in force picks ``method`` for concrete ``area``."""
    return concrete(area) == method


def summary() -> dict[str, str | None]:
    """Every area's method id in force (None: the default), for the report and tests."""
    areas = (
        "ultimate", "shear", "torsion", "punching", "cracking", "serviceStress", "deflection",
        "slenderness", "cover", "anchorage", "memberSteel", "seismic",
    )  # fmt: skip
    out: dict[str, str | None] = {a: concrete(a) for a in areas}
    out.update({a: geotechnical(a) for a in _GEOTECHNICAL})
    return out
