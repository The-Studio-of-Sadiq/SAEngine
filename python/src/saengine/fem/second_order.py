"""Elastic second-order (P-Delta) analysis and the cracked-section stiffness of the analysis
model (Project Settings -> Analysis: ``secondOrder``, ``stiffness``, ``crackedFor``).

:func:`apply_second_order` takes the derived project (``08 FEM/model.osmodel``,
:func:`saengine.fem.derive.derive_fem`, after the soil springs) and returns the modified one,
the notes and a summary; ``"none"`` with ``"gross"`` returns it unchanged.

Stiffness (BNBC 2020 Part 6 Sec 6.3.10.4.1, p 912, the same table as ACI 318-19 6.6.3.1.1):
for an elastic second-order analysis the members may have E of Sec 6.1.7.1, area 1.0 Ag and
moments of inertia columns 0.70 Ig, walls 0.70 Ig (uncracked) or 0.35 Ig (cracked), beams
0.35 Ig, flat plates and flat slabs 0.25 Ig. Sec 6.1.10.2 (p 893) uses the same properties for
the lateral deflections under factored lateral loads, and the response spectrum model of Sec
2.5.9.1 (a) (p 634) "shall consider the effects of cracked sections" of concrete and masonry
elements: a project analysed by response spectrum should use ``stiffness = "aci"``.
How each element takes it in OpenSees Studio:

- frames (``ElasticBeamColumn`` on an ``ElasticSection``): ``Iz`` and ``Iy`` times the factor
  (a member more vertical than 45° is a column, others beams); ``A`` and ``J`` unchanged;
- slabs (shells whose plane is within 45° of horizontal, ``ElasticMembranePlateSection``):
  ``Ep_mod`` = 0.25, the plate (bending) stiffness alone, the membrane (diaphragm) stiffness
  stays gross;
- walls (shells in a vertical plane): their in-plane flexure is membrane action, so ``E`` times
  0.70 (or 0.35 cracked), which also scales their in-plane axial and shear stiffness (the
  section has one isotropic E; ETABS users do the same with f11/f22 modifiers);
- only concrete sections (``concrete_sections``, from the object types' materials; without it,
  sections with E up to 50 GPa), never the embedding struts of solids nor the springs.

A section shared by members of two kinds (a column type used as a brace) is split so each kind
gets its factor. ``crackedFor = "all"``: the model's sections are the cracked ones (as ETABS
property modifiers), except the temperature case T, which keeps the gross sections as
``section_overrides`` (its equivalent loads and add-backs, fem/thermal.py, are computed from
the gross E I and plate thickness). ``"lateral"``: the model keeps the gross sections for the gravity cases,
and the lateral cases (wind and earthquake static cases, modal, response spectrum, time
histories) carry the cracked sections as ``section_overrides``.

Second order (BNBC 2020 Part 6 Sec 2.5.7.9, p 632-633, and Sec 6.3.10.4, p 912): with
``secondOrder = "pDelta"`` the vertical members get the ``PDelta`` geometric transformation
(the beams stay ``Linear``) and the model gets a preload case "PDelta", the gravity loads
``pDeltaFactors`` (by default 1.2D + 1.2SD + 1.2F + 1.0L, the gravity part of the BNBC seismic
combination 1.2D + 1.0E + 1.0L) applied in one Newton step and locked. Every other static case,
and the modal case (so the response spectrum), is then solved on the tangent stiffness of that
preloaded structure, the geometric stiffness of its axial forces included, and reports the
increment from it. This is the "P-Delta from a load combination" of ETABS: one geometric
stiffness for all cases, so the results stay linear in each case's loads and the design load
combinations superpose as before (:mod:`saengine.fem.combinations` unchanged). A second-order
analysis per combination would follow each combination's own axial forces, but it cannot be
superposed and gives nothing for the response spectrum cases; for buildings the storey
P-Delta is governed by the total gravity load above a storey, which the preload carries.
What it does not include:

- P-small-delta along a member (each column is one element per storey and the ``PDelta``
  transformation is a chord rotation): the nonsway moment magnification of BNBC Sec 6.3.10.6
  (ACI 6.6.4.5) still applies to the columns (BNBC Sec 6.3.10.2.2, p 912);
- shells: walls have no geometric stiffness (their P-Delta is left out, reported);
- the construction-sequence dead load (a Staged case sums linear stages: it runs first order,
  ``linear_geometry``), the temperature case (``release_diaphragms``, a different structure);
- time histories run Newton from their own dead-load preload, so they are second order with
  the ``PDelta`` columns under their own gravity loads (D + SD, no live load).

With ``firstOrderReference`` (default) each lateral static case also runs first order (no
preload) as ``<case>-1``, so :func:`drift_amplification` can report the storey drifts with and
without P-Delta, their ratio (the measured amplification, about 1 / (1 - θ) for the preload's
gravity loads) and, for the earthquake cases, the stability coefficient θ of BNBC Eq 6.2.48
computed as BNBC defines it (unfactored Px, the drift of the centres of mass, δxe / I; p 631-633).

Response spectrum forces from the modes: the modes (and the RS peaks) are found on the
preloaded, cracked stiffness. A static run loaded with a mode's ω²·M·φ (to get its member
forces) must use the same stiffness, or it returns (1 - K⁻¹ K_G) φ (about 0.70 φ with the
lateral-only cracked sections): :func:`match_modal_stiffness` gives such a model the modal
case's preload and section overrides.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

#: Moment of inertia factors of BNBC 2020 Part 6 Sec 6.3.10.4.1 (ACI 318-19 Table 6.6.3.1.1(a)).
ACI_FACTORS = {
    "column": 0.70,
    "beam": 0.35,
    "wallUncracked": 0.70,
    "wallCracked": 0.35,
    "slab": 0.25,
}
#: The gravity loads of the P-Delta preload: the gravity part of 1.2D + 1.0E + 1.0L (BNBC 2020
#: Part 6 Sec 2.7.3.1); D's factor also applies to SD and F (as in the combinations).
DEFAULT_PDELTA_FACTORS = {"D": 1.2, "SD": 1.2, "F": 1.2, "L": 1.0}
#: The lateral cases (their first-order references are ``<code>-1``).
LATERAL_CASES = ("WX", "WY", "EX", "EY")
#: Every static lateral case that takes the cracked "lateral" sections: the four above plus the
#: accidental-eccentricity cases (saengine.fem.derive.ECCENTRIC_CASES) and the wind torsion cases
#: (saengine.fem.loads.WIND_TORSION_CASES). Leaving these out solved them on gross sections.
CRACKED_LATERAL_CASES = (*LATERAL_CASES, "EXP", "EXN", "EYP", "EYN", "WTX", "WTY")
PRELOAD_CODE = "PDelta"
THERMAL_CODE = "T"  # saengine.fem.thermal.CASE
REFERENCE_SUFFIX = "-1"
#: Sections up to this E [Pa] count as concrete when the caller does not say which are.
CONCRETE_E_MAX = 50e9
#: A frame more vertical than this (|dz| / L) is a column; a shell whose normal is more vertical
#: than this (|nz|) is a slab.
VERTICAL = math.sin(math.radians(45))


@dataclass
class SecondOrderOptions:
    """``settings.analysis``: ``secondOrder``, ``stiffness``, ``crackedFor``,
    ``wallsCracked``, ``pDeltaFactors``, ``firstOrderReference``."""

    secondOrder: Literal["none", "pDelta"] = "none"
    stiffness: Literal["gross", "aci"] = "gross"
    crackedFor: Literal["all", "lateral"] = "all"
    wallsCracked: bool = False
    pDeltaFactors: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PDELTA_FACTORS))
    firstOrderReference: bool = True


@dataclass
class SecondOrderModel:
    """The modified project, its notes and a summary (``08 FEM/second-order.json``)."""

    project: dict[str, Any]
    notes: list[str]
    summary: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {"notes": self.notes, "summary": self.summary}


def options_from_settings(settings: Any) -> SecondOrderOptions:
    """The options of ``settings.analysis``, their defaults where it has none."""
    analysis = getattr(settings, "analysis", None)
    factors = getattr(analysis, "pDeltaFactors", None)
    return SecondOrderOptions(
        secondOrder=getattr(analysis, "secondOrder", "none") or "none",
        stiffness=getattr(analysis, "stiffness", "gross") or "gross",
        crackedFor=getattr(analysis, "crackedFor", "all") or "all",
        wallsCracked=bool(getattr(analysis, "wallsCracked", False)),
        pDeltaFactors=dict(factors) if factors else dict(DEFAULT_PDELTA_FACTORS),
        firstOrderReference=bool(getattr(analysis, "firstOrderReference", True)),
    )


def _code(name: str) -> str:
    return str(name).split(":")[0].strip()


def _frame_role(element: dict[str, Any], coords: dict[int, np.ndarray]) -> str:
    a, b = (coords[n] for n in element["nodes"][:2])
    length = float(np.linalg.norm(b - a))
    return "column" if length > 0 and abs(b[2] - a[2]) / length >= VERTICAL else "beam"


def _shell_role(element: dict[str, Any], coords: dict[int, np.ndarray]) -> str:
    p = [coords[n] for n in element["nodes"][:3]]
    normal = np.cross(p[1] - p[0], p[2] - p[0])
    size = float(np.linalg.norm(normal))
    return "slab" if size > 0 and abs(normal[2]) / size >= VERTICAL else "wall"


def _is_embed(element: dict[str, Any], section: dict[str, Any] | None) -> bool:
    return "/embed" in str(element.get("name", "")) or (
        section is not None and str(section.get("name", "")).endswith("embedding strut")
    )


def _cracked(
    section: dict[str, Any],
    role: str,
    options: SecondOrderOptions,
    keep: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """The section with the code's cracked factors; ``keep``: properties the engineer's
    stiffness modifiers set (they replace the cracked factor of that property)."""
    out = dict(section)
    if role in ("column", "beam"):
        factor = ACI_FACTORS[role]
        for key in ("Iz", "Iy"):
            if out.get(key) is not None and key not in keep:
                out[key] = out[key] * factor
    elif role == "slab":
        if "Ep_mod" not in keep:
            out["Ep_mod"] = ACI_FACTORS["slab"] * out.get("Ep_mod", 1.0)
    elif role == "wall" and "E" not in keep:
        out["E"] = (
            out["E"] * ACI_FACTORS["wallCracked" if options.wallsCracked else "wallUncracked"]
        )
    return out


def _merged_pattern(
    project: dict[str, Any], factors: dict[str, float], pattern_id: int
) -> tuple[dict[str, Any], list[str]]:
    """One plain pattern: the factored sum of the patterns named after the cases of
    ``factors`` (the derived model names each case's pattern by its code)."""
    by_name = {p.get("name"): p for p in project.get("load_patterns", [])}
    nodal: dict[int, np.ndarray] = {}
    element: dict[int, np.ndarray] = {}
    used: list[str] = []
    for code, factor in factors.items():
        pattern = by_name.get(code)
        if pattern is None or not factor or pattern.get("type", "Plain") != "Plain":
            continue
        used.append(f"{factor:g}{code}")
        for load in pattern.get("nodal_loads", []):
            forces = np.asarray(load["forces"], dtype=float) * factor
            nodal[load["node_id"]] = nodal.get(load["node_id"], 0.0) + forces
        for load in pattern.get("element_loads", []):
            w = np.array([load.get("wx", 0.0), load.get("wy", 0.0), load.get("wz", 0.0)]) * factor
            element[load["element_id"]] = element.get(load["element_id"], 0.0) + w
    pattern = {
        "id": pattern_id,
        "name": f"{PRELOAD_CODE} gravity",
        "type": "Plain",
        "time_series_id": 1,
        "nodal_loads": [
            {"node_id": n, "forces": [round(float(f), 3) for f in v]}
            for n, v in sorted(nodal.items())
        ],
        "element_loads": [
            {
                "element_id": e,
                "wx": round(float(v[0]), 3),
                "wy": round(float(v[1]), 3),
                "wz": round(float(v[2]), 3),
            }
            for e, v in sorted(element.items())
        ],
    }
    return pattern, used


def apply_second_order(
    project: dict[str, Any],
    options: SecondOrderOptions,
    concrete_sections: set[int] | None = None,
    modified: dict[int, set[str]] | None = None,
) -> SecondOrderModel:
    """``project`` with the cracked stiffness and the P-Delta analysis of ``options``.

    ``concrete_sections``: the ids of the concrete (and masonry) sections, whose stiffness the
    ACI factors reduce; None takes the sections with E up to :data:`CONCRETE_E_MAX`.
    ``modified``: per section id the properties set by stiffness modifiers ("Iz", "Iy", "E",
    "Ep_mod"), which keep their value (no cracked factor on top).
    The input is not changed.
    """
    notes: list[str] = []
    summary: dict[str, Any] = {
        "secondOrder": options.secondOrder,
        "stiffness": options.stiffness,
        "crackedFor": options.crackedFor if options.stiffness == "aci" else None,
        "pDeltaColumns": 0,
        "crackedSections": {},
        "preloadCaseId": None,
        "preloadFactors": None,
        "referenceCases": {},
    }
    if options.secondOrder == "none" and options.stiffness == "gross":
        return SecondOrderModel(project=project, notes=notes, summary=summary)
    p = copy.deepcopy(project)
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in p.get("nodes", [])}
    sections = {s["id"]: s for s in p.get("sections", [])}

    # ── which kind of member each frame and shell is ──
    roles: dict[int, str | None] = {}
    for e in p.get("elements", []):
        section = sections.get(e.get("section_id"))
        if e.get("type") == "ElasticBeamColumn":
            roles[e["id"]] = None if _is_embed(e, section) else _frame_role(e, coords)
        elif e.get("type") == "Shell":
            roles[e["id"]] = _shell_role(e, coords)

    # ── cracked stiffness ──
    overrides: list[dict[str, Any]] = []
    if options.stiffness == "aci":

        def concrete(section: dict[str, Any]) -> bool:
            if concrete_sections is not None:
                return section["id"] in concrete_sections
            return float(section.get("E", 0.0)) <= CONCRETE_E_MAX

        # One role per section: a section shared by two kinds of member is split (a gross
        # copy under a new id for the second kind).
        role_of: dict[int, str] = {}
        keep_of: dict[int, set[str]] = {k: set(v) for k, v in (modified or {}).items()}
        split: dict[tuple[int, str], int] = {}
        next_id = max(sections, default=0) + 1
        for e in p.get("elements", []):
            role = roles.get(e["id"])
            sid = e.get("section_id")
            if role is None or sid not in sections:
                continue
            if role_of.setdefault(sid, role) == role:
                continue
            key = (sid, role)
            if key not in split:
                twin = dict(sections[sid], id=next_id, name=f"{sections[sid]['name']} ({role})")
                p["sections"].append(twin)
                sections[next_id] = twin
                role_of[next_id] = role
                if sid in keep_of:
                    keep_of[next_id] = keep_of[sid]
                split[key] = next_id
                next_id += 1
            e["section_id"] = split[key]
        if split:
            notes.append(
                f"cracked stiffness: {len(split)} section(s) shared by members of two kinds "
                "were split so each kind gets its factor"
            )
        counts: dict[str, int] = {}
        gross_copies: list[dict[str, Any]] = []
        for sid, role in sorted(role_of.items()):
            section = sections[sid]
            if section.get("type") not in ("ElasticSection", "ElasticMembranePlateSection"):
                continue
            if not concrete(section):
                continue
            cracked = _cracked(section, role, options, keep_of.get(sid, set()))
            counts[role] = counts.get(role, 0) + 1
            if options.crackedFor == "all":
                gross_copies.append(copy.deepcopy(section))
                section.clear()
                section.update(cracked)
            else:
                overrides.append(cracked)
        summary["crackedSections"] = counts
        # The temperature case's equivalent loads and add-backs (fem/thermal.py, thermal.json)
        # were built from the gross E, I and plate thickness: it keeps the gross sections, or
        # its thermal curvatures would come out Ig/Ieff times the free value.
        if gross_copies:
            for a in p.get("analyses", []):
                if _code(a.get("name", "")) == THERMAL_CODE or a.get("release_diaphragms"):
                    a["section_overrides"] = copy.deepcopy(gross_copies)
                    notes.append(
                        "cracked stiffness: the temperature case T keeps the gross sections "
                        "its equivalent loads were computed with"
                    )
        wall = ACI_FACTORS["wallCracked" if options.wallsCracked else "wallUncracked"]
        notes.append(
            "cracked stiffness (BNBC 2020 Part 6 Sec 6.3.10.4.1): columns 0.70 Ig, beams "
            f"0.35 Ig, walls {wall:.2f} Ig (E x {wall:.2f}: in a shell a wall's in-plane flexure "
            "is membrane action, so its in-plane axial and shear stiffness are reduced too), "
            "slabs 0.25 Ig in bending (their membrane stiffness stays gross), area 1.0 Ag, "
            "torsion gross; "
            + (
                "for every case"
                if options.crackedFor == "all"
                else "for the lateral cases (wind, earthquake, modal, response spectrum, time "
                "histories), the gravity cases with the gross sections"
            )
        )
        if not counts:
            notes.append("cracked stiffness: no concrete frame or shell section to reduce")

    lateral_overrides = overrides if options.crackedFor == "lateral" else []

    def is_lateral(analysis: dict[str, Any]) -> bool:
        code = _code(analysis.get("name", ""))
        code = code.removesuffix(REFERENCE_SUFFIX)
        return code in CRACKED_LATERAL_CASES or analysis.get("type") in (
            "Modal",
            "ResponseSpectrum",
            "Transient",
        )

    analyses = p.setdefault("analyses", [])

    # ── P-Delta ──
    if options.secondOrder == "pDelta":
        for e in p.get("elements", []):
            if roles.get(e["id"]) == "column":
                e["geom_transf"] = "PDelta"
                summary["pDeltaColumns"] += 1
        if not summary["pDeltaColumns"]:
            notes.append("P-Delta: the model has no vertical frame member")
        patterns = p.setdefault("load_patterns", [])
        pattern, used = _merged_pattern(
            p, options.pDeltaFactors, max((q["id"] for q in patterns), default=0) + 1
        )
        if not used:
            notes.append(
                "P-Delta: none of the gravity cases of the preload "
                f"({', '.join(options.pDeltaFactors)}) has loads; the columns use PDelta "
                "transformations, but no case is preloaded"
            )
        else:
            patterns.append(pattern)
            preload_id = max((a["id"] for a in analyses), default=0) + 1
            title = " + ".join(used)
            # A reference copy of each lateral static case, first order (no preload).
            references: list[dict[str, Any]] = []
            if options.firstOrderReference:
                for a in analyses:
                    if a.get("type") == "Static" and _code(a.get("name", "")) in LATERAL_CASES:
                        code, _, rest = str(a["name"]).partition(":")
                        references.append(
                            {
                                **copy.deepcopy(a),
                                "name": f"{code.strip()}{REFERENCE_SUFFIX}:{rest}, first order "
                                "(P-Delta reference)",
                            }
                        )
            for a in analyses:
                kind = a.get("type")
                if kind == "Static" and not a.get("release_diaphragms") or kind == "Modal":
                    a["preload_case_ids"] = [preload_id]
                elif kind == "Staged":
                    a["linear_geometry"] = True
            analyses.append(
                {
                    "id": preload_id,
                    "name": f"{PRELOAD_CODE}: gravity preload of the P-Delta analysis, {title}",
                    "type": "Static",
                    "pattern_ids": [pattern["id"]],
                    "n_steps": 1,
                    "load_factor_increment": 1.0,
                    "system": "BandGeneral",
                    "constraints": "Plain",
                    "integrator": "LoadControl",
                    "algorithm": "Newton",
                    "test": "NormDispIncr",
                    "tolerance": 1e-8,
                    "max_iter": 50,
                }
            )
            for reference in references:
                reference["id"] = max(a["id"] for a in analyses) + 1
                analyses.append(reference)
                summary["referenceCases"][_code(reference["name"])] = reference["id"]
            summary["preloadCaseId"] = preload_id
            summary["preloadFactors"] = {
                k: v for k, v in options.pDeltaFactors.items() if f"{v:g}{k}" in used
            }
            notes.append(
                f"P-Delta (BNBC 2020 Part 6 Sec 2.5.7.9, Sec 6.3.10.4): {summary['pDeltaColumns']} "
                f"vertical members with PDelta transformations; every static case and the modal "
                f"case are solved on the stiffness of the structure under {title} (the case "
                f"'{PRELOAD_CODE}', one Newton step, then held), and report the increment from it, "
                "so the load combinations superpose as before. P-small-delta along the columns "
                "is not modelled (one element per storey): their nonsway moment magnification "
                "still applies"
            )
            if any(
                e.get("type") == "Shell" and roles.get(e["id"]) == "wall" for e in p["elements"]
            ):
                notes.append(
                    "P-Delta: walls (shells) have no geometric stiffness here; the P-Delta of a "
                    "wall structure is not included"
                )
            if any(a.get("type") == "Staged" for a in analyses):
                notes.append(
                    "P-Delta: the construction-sequence dead load D runs first order (its "
                    "stages are summed); D0 and the other cases are second order"
                )
            if any(a.get("type") == "Static" and a.get("release_diaphragms") for a in analyses):
                notes.append("P-Delta: the temperature case T runs first order")
            if any(a.get("type") == "Transient" for a in analyses):
                notes.append(
                    "P-Delta: the time histories are second order under their own dead-load "
                    "preload (D + SD)"
                )
            if any(a.get("type") == "ResponseSpectrum" for a in analyses):
                notes.append(
                    "P-Delta: the response spectrum modes are found on the preloaded stiffness; "
                    "the design's member forces from the modes are solved on it too "
                    "(saengine.fem.seismic_design.spectrum_stiffness)"
                )

    if lateral_overrides:
        for a in analyses:
            if is_lateral(a):
                a["section_overrides"] = copy.deepcopy(lateral_overrides)
        # The P-Delta preload of a lateral case runs on that case's (cracked) model.
    return SecondOrderModel(project=p, notes=notes, summary=summary)


def match_modal_stiffness(project: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """``model`` (static cases built from the modes of ``project``, e.g.
    :func:`saengine.fem.seismic_design.modal_force_model`, whose load ω²·M·φ gives a mode's
    peak response) with the stiffness the modes were found on: the P-Delta preload and the
    cracked ``section_overrides`` of ``project``'s response spectrum / modal case.

    A mode solved on (K - K_G) loaded by ω²·M·φ returns φ only on (K - K_G); solved on K the
    displacements and member forces come out (1 - K⁻¹ K_G) times too small, and on the gross
    sections when the modes were cracked about 0.70 times. So every static case of ``model``
    gets the preload cases of the modal case (copied in with their patterns, under new ids)
    as ``preload_case_ids`` and the overrides as ``section_overrides``. ``model`` is not
    changed; with neither, it is returned as it is."""
    analyses = project.get("analyses", [])
    by_id = {a["id"]: a for a in analyses}
    spectrum = next((a for a in analyses if a.get("type") == "ResponseSpectrum"), None)
    modal = by_id.get(spectrum.get("modal_case_id")) if spectrum else None
    if modal is None:
        modal = next((a for a in analyses if a.get("type") == "Modal"), None)
    if modal is None:
        return model
    overrides = (spectrum or {}).get("section_overrides") or modal.get("section_overrides") or []
    preloads = [by_id[i] for i in modal.get("preload_case_ids", []) if i in by_id]
    if not overrides and not preloads:
        return model
    out = copy.deepcopy(model)
    patterns = out.setdefault("load_patterns", [])
    cases = out.setdefault("analyses", [])
    series = {t["id"] for t in out.get("time_series", [])}
    source_patterns = {q["id"]: q for q in project.get("load_patterns", [])}
    next_pattern = max((q["id"] for q in patterns), default=0) + 1
    next_case = max((a["id"] for a in cases), default=0) + 1
    new_ids: list[int] = []
    for preload in preloads:
        pattern_ids = []
        for pid in preload.get("pattern_ids", []):
            pattern = copy.deepcopy(source_patterns[pid])
            pattern["id"] = next_pattern
            if pattern.get("time_series_id") not in series and series:
                pattern["time_series_id"] = min(series)
            patterns.append(pattern)
            pattern_ids.append(next_pattern)
            next_pattern += 1
        case = {
            k: copy.deepcopy(v)
            for k, v in preload.items()
            if k not in ("preload_case_ids", "section_overrides")
        }
        case.update(id=next_case, pattern_ids=pattern_ids)
        new_ids.append(next_case)
        next_case += 1
        cases.append(case)
    for case in cases:
        if case["id"] in new_ids or case.get("type") != "Static":
            continue
        if new_ids:
            case["preload_case_ids"] = list(new_ids)
        if overrides:
            case["section_overrides"] = copy.deepcopy(overrides)
    return out


def is_second_order(project: dict[str, Any]) -> bool:
    """Whether the static cases of ``project`` are second order (P-Delta from a preload): the
    design then takes the sway moment magnification as done (BNBC Sec 6.3.10.4)."""
    return any(
        _code(a.get("name", "")) == PRELOAD_CODE for a in project.get("analyses", [])
    ) and any(e.get("geom_transf") == "PDelta" for e in project.get("elements", []))


def _levels(project: dict[str, Any]) -> list[float]:
    """Storey levels [m] when the caller gives none: the floors of the rigid diaphragms, the
    lowest support and the top of the highest column (a roof without a diaphragm); without
    diaphragms, the ends of the vertical frame members. The caller should pass the building's
    stories where it has them (a column split at a beam between floors adds a level here)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    floors = {
        round(float(coords[mp["retained_node"]][2]), 3)
        for mp in project.get("mp_constraints", [])
        if mp.get("type") == "RigidDiaphragm" and mp.get("retained_node") in coords
    }
    supports = [
        float(coords[n["id"]][2]) for n in project.get("nodes", []) if all(n.get("restraint") or [])
    ]
    zs: set[float] = set()
    for e in project.get("elements", []):
        if e.get("type") != "ElasticBeamColumn" or "/embed" in str(e.get("name", "")):
            continue
        if _frame_role(e, coords) == "column":
            zs.update(round(float(coords[n][2]), 3) for n in e["nodes"][:2])
    if floors and supports:
        top = {max(zs)} if zs and max(zs) > max(floors) else set()
        return sorted(floors | {round(min(supports), 3)} | top)
    return sorted(zs)


def storey_drifts(
    project: dict[str, Any],
    displacement: dict[int, Any],
    axis: int,
    levels: list[float] | None = None,
) -> list[dict[str, Any]]:
    """The largest drift ratio of each storey along ``axis`` (0 X, 1 Y): the difference of
    the displacements of nodes on the storey's two levels at the same plan position, over the
    storey height. ``displacement``: node id -> displacement row (6 values). ``levels`` [m]:
    the building's storey elevations (by default the diaphragm floors and the base)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    levels = sorted(levels) if levels else _levels(project)
    at: list[dict[tuple[int, int], int]] = []
    for z in levels:
        here = {}
        for node, xyz in coords.items():
            if abs(xyz[2] - z) < 1e-3 and node in displacement:
                here[(round(xyz[0] * 1e3), round(xyz[1] * 1e3))] = node
        at.append(here)
    rows = []
    for k in range(1, len(levels)):
        height = levels[k] - levels[k - 1]
        best: tuple[float, tuple[int, int] | None] = (0.0, None)
        for position, node in at[k].items():
            below = at[k - 1].get(position)
            if below is None:
                continue
            drift = abs(float(displacement[node][axis]) - float(displacement[below][axis]))
            if drift / height > best[0] or best[1] is None:
                best = (drift / height, position)
        if best[1] is not None:
            rows.append(
                {
                    "from": levels[k - 1],
                    "to": levels[k],
                    "drift": best[0],
                    "at": [best[1][0] / 1e3, best[1][1] / 1e3],
                }
            )
    return rows


def _frame_axes(
    a: np.ndarray, b: np.ndarray, vecxz: Any = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A frame's local axes as OpenSees Studio's runner builds them (the element's own
    ``vecxz`` when it has one, else (1, 0, 0) for a member closer to Z than to X, else
    (0, 0, 1); y = vecxz × x, z = x × y)."""
    x = (b - a) / float(np.linalg.norm(b - a))
    if vecxz is not None:
        vecxz = np.asarray(vecxz, dtype=float)
    else:
        vecxz = np.array([1.0, 0.0, 0.0]) if abs(x[2]) > abs(x[0]) else np.array([0.0, 0.0, 1.0])
    y = np.cross(vecxz, x)
    y /= float(np.linalg.norm(y))
    return x, y, np.cross(x, y)


def loads_above(project: dict[str, Any], factors: dict[str, float], z: float) -> np.ndarray:
    """The resultant force [N] (global X, Y, Z) of the patterns named in ``factors`` (times
    their factors) applied above the elevation ``z`` [m]: nodal loads at nodes above it and
    the uniform loads of frames whose middle is above it (local loads turned global)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    elements = {e["id"]: e for e in project.get("elements", [])}
    by_name = {p.get("name"): p for p in project.get("load_patterns", [])}
    total = np.zeros(3)
    for code, factor in factors.items():
        pattern = by_name.get(code)
        if pattern is None or not factor:
            continue
        for load in pattern.get("nodal_loads", []):
            if coords[load["node_id"]][2] > z + 1e-3:
                total += factor * np.asarray(load["forces"], dtype=float)[:3]
        for load in pattern.get("element_loads", []):
            element = elements.get(load["element_id"])
            if element is None:
                continue
            a, b = (coords[n] for n in element["nodes"][:2])
            if (a[2] + b[2]) / 2 <= z + 1e-3:
                continue
            x, y, zl = _frame_axes(a, b, element.get("vecxz"))
            w = load.get("wx", 0.0) * x + load.get("wy", 0.0) * y + load.get("wz", 0.0) * zl
            total += factor * w * float(np.linalg.norm(b - a))
    return total


def level_displacement(
    project: dict[str, Any], displacement: dict[int, Any], z: float, axis: int
) -> float | None:
    """The displacement along ``axis`` of the centre of mass of the level at ``z`` [m]: the
    mass-weighted mean of its nodes' displacements (exact for a rigid floor, whose
    displacement is linear in plan), the plain mean where the level has no mass, 0 at a
    level of supports; None without nodes there."""
    rows = [
        (n, float(np.asarray(n.get("mass") or [0.0] * 6, dtype=float)[axis]))
        for n in project.get("nodes", [])
        if abs(float(n["coords"][2]) - z) < 1e-3 and n["id"] in displacement
    ]
    if not rows:
        return None
    weight = sum(m for _, m in rows)
    if weight > 0:
        return sum(m * float(displacement[n["id"]][axis]) for n, m in rows) / weight
    return sum(float(displacement[n["id"]][axis]) for n, _ in rows) / len(rows)


#: Load factors of Px in BNBC 2020 Part 6 Eq 6.2.48 (p 632: "no individual load factor need
#: exceed 1.0").
STABILITY_GRAVITY_FACTORS = {"D": 1.0, "SD": 1.0, "F": 1.0, "L": 1.0}


def drift_amplification(
    project: dict[str, Any],
    out_dir: str | Path,
    levels: list[float] | None = None,
    importance: float | None = None,
    cd: float | None = None,
    gravity_factors: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Storey drifts of each lateral case with P-Delta (``EX``) and first order (``EX-1``) and
    their ratio second / first; for the earthquake cases also the stability coefficient θ of
    BNBC 2020 Part 6 Sec 2.5.7.9 (p 632-633); for the report's seismic chapter and the design.

    Per storey: ``firstOrder``, ``secondOrder`` the largest drift ratio at any plan position
    (:func:`storey_drifts`), ``ratio`` second / first, ``impliedTheta`` = 1 - 1 / ratio (the
    amplification measured, ratio = 1 / (1 - impliedTheta); not BNBC's θ). ``theta`` (EX, EY,
    with ``importance``): Eq 6.2.48 θ = Px Δ / (Vx hsx Cd) with Δ = Cd δxe / I (Eq 6.2.45,
    6.2.46: the drift of the centres of mass, p 631), so θ = Px δxe / (I Vx hsx); δxe the
    first-order elastic drift (the ``-1`` case) at the centres of mass
    (:func:`level_displacement`), Px the gravity load above the storey with the factors
    ``gravity_factors`` (default 1.0, "no individual load factor need exceed 1.0"), Vx the
    storey shear of the case's loads (:func:`loads_above`). With ``cd``: ``thetaMax`` =
    0.5 / (β Cd) ≤ 0.25 with β = 1.0 (Eq 6.2.49, β "permitted to be conservatively taken as
    1.0", p 633). θ ≤ 0.10: P-Delta need not be considered; 0.10 < θ ≤ θmax: by analysis or
    1 / (1 - θ); θ > θmax: redesign (p 633).

    Returns ``{"cases": [{"case", "storeys": [{"from", "to", "firstOrder", "secondOrder",
    "ratio", "impliedTheta", "theta", "thetaMax", "Px", "Vx", "centreOfMassDrift"}],
    "maxRatio", "maxTheta"}], "notes": [...]}``; empty cases without the results.
    ``levels`` [m]: the storey elevations (the building's stories / 1000), see
    :func:`storey_drifts`.
    """
    gravity = dict(gravity_factors or STABILITY_GRAVITY_FACTORS)
    theta_max = min(0.5 / cd, 0.25) if cd else None
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    out: dict[str, Any] = {"cases": [], "notes": []}
    try:
        manifest = load_manifest(out_dir)
    except (OSError, ValueError) as error:
        out["notes"].append(f"no analysis results: {error}")
        return out
    by_code: dict[str, Any] = {}
    for entry in manifest.get("cases", []):
        code = _code(entry.get("case_name", ""))
        if code in LATERAL_CASES or code[: -len(REFERENCE_SUFFIX)] in LATERAL_CASES:
            results = load_results(entry, out_dir)
            if isinstance(results, StaticResults):
                by_code[code] = results
    for code in LATERAL_CASES:
        second, first = by_code.get(code), by_code.get(code + REFERENCE_SUFFIX)
        if second is None or first is None:
            continue
        axis = 0 if code.endswith("X") else 1

        def last(results: Any) -> dict[int, Any]:
            return {n: np.asarray(rows[-1], dtype=float) for n, rows in results.node_disp.items()}

        u1 = last(first)
        d2 = {(r["from"], r["to"]): r for r in storey_drifts(project, last(second), axis, levels)}
        d1 = {(r["from"], r["to"]): r for r in storey_drifts(project, u1, axis, levels)}
        seismic = code.startswith("E") and importance is not None and importance > 0
        storeys = []
        for key, r1 in d1.items():
            r2 = d2.get(key)
            if r2 is None:
                continue
            ratio = r2["drift"] / r1["drift"] if r1["drift"] > 0 else None
            row: dict[str, Any] = {
                "from": key[0],
                "to": key[1],
                "firstOrder": r1["drift"],
                "secondOrder": r2["drift"],
                "ratio": ratio,
                "impliedTheta": (1 - 1 / ratio) if ratio else None,
                "theta": None,
                "thetaMax": theta_max if code.startswith("E") else None,
                "Px": None,
                "Vx": None,
                "centreOfMassDrift": None,
            }
            top = level_displacement(project, u1, key[1], axis)
            bottom = level_displacement(project, u1, key[0], axis)
            if top is not None and bottom is not None:
                row["centreOfMassDrift"] = abs(top - bottom) / (key[1] - key[0])
            if seismic and row["centreOfMassDrift"] is not None:
                px = -float(loads_above(project, gravity, key[0])[2])
                vx = abs(float(loads_above(project, {code: 1.0}, key[0])[axis]))
                row["Px"], row["Vx"] = px, vx
                if vx > 0:  # θ = Px δxe / (I Vx hsx), δxe / hsx the drift ratio
                    row["theta"] = px * row["centreOfMassDrift"] / (importance * vx)
            storeys.append(row)
        ratios = [s["ratio"] for s in storeys if s["ratio"] is not None]
        thetas = [s["theta"] for s in storeys if s["theta"] is not None]
        out["cases"].append(
            {
                "case": code,
                "storeys": storeys,
                "maxRatio": max(ratios) if ratios else None,
                "maxTheta": max(thetas) if thetas else None,
            }
        )
    if not out["cases"]:
        out["notes"].append(
            "no lateral case has both its P-Delta and its first-order results (EX and EX-1)"
        )
    elif importance is None:
        out["notes"].append(
            "the stability coefficient θ (BNBC Eq 6.2.48) needs the importance factor I"
        )
    return out


__all__ = [
    "ACI_FACTORS",
    "DEFAULT_PDELTA_FACTORS",
    "STABILITY_GRAVITY_FACTORS",
    "SecondOrderModel",
    "SecondOrderOptions",
    "apply_second_order",
    "drift_amplification",
    "is_second_order",
    "level_displacement",
    "loads_above",
    "match_modal_stiffness",
    "options_from_settings",
    "storey_drifts",
]
