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

Alpha 9 C5c areas: ``strutAndTie`` ``designStressLimits`` (stress_fields: deep beams, corbels,
pile caps), ``interfaceShear`` ``interfaceShear`` (rc_detailing: construction joints), ``ties``
``tieForces`` (limit_state_members), ``footingPunching`` ``reducedPerimeter``
(perimeter_punching: footings, pile caps, rafts), ``wallSlenderness`` ``columnAnalogy``
(limit_state_members: walls out of their plane), ``barShapes`` ``barShapes`` (drawings.detailing:
bends, hooks, compression laps) and the geotechnical ``retaining`` ``limitStates``
(limit_state_retaining). The slabs' and stairs' span/depth ratio is the ``deflection`` area's
method, the confinement of columns and walls the ``seismic`` one's.

A group holds one method, chosen by its id (:func:`saengine.codes.method_tables.chosen` is the
same test for a module that reads its own group). The IS 456 type methods of track C8 are
further ids of the same groups: ``shear`` ``tabulatedStress``, ``torsion`` ``equivalentShear``,
``punching`` ``rootStress``, ``deflection`` ``spanDepthModification``, ``cracking``
``strainSpacing``, ``cover`` ``exposureCondition``, ``anchorage`` ``bondStressTable``,
``seismic`` ``ductileDetailing`` (modules ``tabulated_shear``, ``span_depth_factors``,
``ductile_detailing`` ...), with their own groups ``memberLimits``, ``columns``
(additional moments), ``twoWaySlabs``, ``flatSlabs``, ``walls``, ``footings``. Each hook runs
the method of the id in force; the partial-factor strip, section and sizing functions
(``ultimate`` ``partialFactors``) serve both families, the tabulated methods' own rules first.

Alpha 9 C20b ids of the tabulated family (GB 50010 type): ``torsion`` ``plasticModulus``
(plastic_torsion), ``cracking`` ``effectiveTensionRatio`` and ``deflection`` ``longTermStiffness``
(tension_stiffening), ``columns.slenderness`` ``endMomentMagnifier`` (end_moment_magnifier), the
group ``shearSpanWalls`` ``shearSpanRatio`` (shear_span_walls) and the ``rootStress`` punching's
``strength`` "tensile"; the seismic grade in the member design is the seismic table's
``gradeDesign`` (seismic_grades).

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
    "retaining": ("retaining", "limitStates"),  # Alpha 9 C5c
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
    ``sliding``, ``piles``, ``retaining``), or None for the default allowable-stress design."""
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


#: The ids of the partial-factor methods whose rows :mod:`saengine.design.limit_state_rows`
#: and :mod:`saengine.design.capacity_design` build (the Eurocodes pack's); another pack's
#: methods of the same area (IS 456's tabulated ones, ``tabulated_shear`` ...) are other ids.
LIMIT_STATE_IDS = {
    "torsion": "thinWalledVariableStrut",
    "deflection": "spanDepthK",
    "cracking": "directWidth",
    "serviceStress": "stressLimits",
    "slenderness": "nominalCurvature",
    "punching": "controlPerimeter",
    "memberSteel": "memberSteel",
    "seismic": "curvatureDuctility",
    "anchorage": "bondStress",
    "shear": "variableStrut",
    # Alpha 9 C5c.
    "strutAndTie": "designStressLimits",
    "interfaceShear": "interfaceShear",
    "ties": "tieForces",
    "footingPunching": "reducedPerimeter",
    "wallSlenderness": "columnAnalogy",
    "barShapes": "barShapes",
}


def limit_state_areas() -> dict[str, str | None]:
    """Per area of :data:`LIMIT_STATE_IDS`, its id where the pack in force picks that method
    (None: another method, or the default)."""
    return {a: (m if uses(a, m) else None) for a, m in LIMIT_STATE_IDS.items()}


def summary() -> dict[str, str | None]:
    """Every area's method id in force (None: the default), for the report and tests."""
    areas = (
        "ultimate", "shear", "torsion", "punching", "cracking", "serviceStress", "deflection",
        "slenderness", "cover", "anchorage", "memberSteel", "seismic",
        "strutAndTie", "interfaceShear", "ties", "footingPunching", "wallSlenderness",
        "barShapes",
    )  # fmt: skip
    out: dict[str, str | None] = {a: concrete(a) for a in areas}
    out.update({a: geotechnical(a) for a in _GEOTECHNICAL})
    return out
