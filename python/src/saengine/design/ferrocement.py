"""Ferrocement beams and columns: thin mortar sections with layers of steel mesh, designed as
layered reinforced sections with the code pack's ``ferrocement`` table (with the bnbc2020
pack: BNBC 2020 Part 6 Chapter 12).

The member is a rectangle profile: width b (``xDim``) by thickness h (``yDim``), bent about
its width axis. Its mesh layers (the type's :class:`FerrocementMember`) are spread evenly
through the thickness between the covers, each with the effective area η Vf b h of its volume
fraction Vf (from the wires, or from the mesh weight) and the global efficiency factor η of the
loading direction; skeletal bars, if any, at mid-thickness.

- Strength (the pack's strength combinations, as the concrete members): strain compatibility
  with the rectangular stress block over β1 c and the mortar strain limit, the mesh linear up to
  fy (capped) with its effective modulus; φ of the factors table, from the compression value to
  the tension-controlled one with the strain of the extreme layer; the uniform compression of
  the mortar alone caps the axial strength. The demand (Pu, Mu) is read on the φ interaction
  curve along its ray.
- Service loads (the allowable stress combinations): the cracked transformed section with one
  modular ratio Er/Ec; the mesh tension at most the share of fy (or the liquid retaining
  limit), the mortar compression at most its share of f'c, the stress range for fatigue when
  asked. The crack width limit is reported; the code gives no way to predict it.
- Detailing: cover, mesh opening, layers, water retaining volume fraction and specific
  surface, skeletal steel, mortar strength.

Shear and slenderness: the chapter gives no provision; notes say so.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.ductile_members import _row
from saengine.design.timber.members import _flag, asd_pieces, code_name

__all__ = [
    "FerroSection",
    "FerrocementDesignError",
    "check_service",
    "check_strength",
    "design_aid_moment",
    "design_ferrocement_member",
    "is_ferrocement",
    "method",
    "volume_fraction",
]


class FerrocementDesignError(ValueError):
    """A ferrocement member that cannot be checked."""


def _table() -> Any:
    return code_context.pack_table("ferrocement")


def covered() -> bool:
    """Whether the code pack in force covers ferrocement (its chain has the table)."""
    return code_context.current().has("ferrocement")


def clause(key: str) -> str:
    text = (getattr(_table(), "clauses", None) or {}).get(key, "")
    return f"{code_name()} {text}".strip()


def method() -> list[str]:
    text = (
        f"Ferrocement members: {clause('chapter')}, as layered reinforced sections. Effective "
        f"area of each mesh layer η Vf b h ({clause('efficiency')}), fy and Er of the mesh "
        f"({clause('meshes')}); strength under the strength combinations by strain "
        f"compatibility ({clause('flexure')}; {clause('strength')}), the mortar alone in "
        f"compression ({clause('compression')}); service load stresses on the cracked "
        f"transformed section ({clause('service')}; {clause('steelStress')}; "
        f"{clause('mortarStress')}), the crack width limit ({clause('crackWidth')}) and the "
        f"detailing rules ({clause('cover')}-{clause('layers')})."
    )
    return [text]


def is_ferrocement(material: Any) -> bool:
    category = getattr(getattr(material, "category", None), "value", None)
    return category == "ferrocement" and getattr(material, "ferrocement", None) is not None


def volume_fraction(member: Any, h: float) -> float:
    """Vf of one mesh layer in a section ``h`` thick (both directions, Appendix U): from the
    wires of a square or rectangular mesh, else from the mesh weight."""
    mesh = _table().meshes[member.mesh]
    db = float(member.wireDiameter)
    if mesh.volumeFraction == "wires":
        if not member.spacing:
            raise FerrocementDesignError(f"{mesh.label}: give the wire spacing")
        dl = float(member.spacing)
        dt = float(member.spacingTransverse or member.spacing)
        return math.pi * db**2 / (4 * h) * (1 / dl + 1 / dt)
    if not member.meshWeight:
        raise FerrocementDesignError(f"{mesh.label}: give the mesh weight per unit area")
    # Wm [N/m²] / (γm [kN/m³] h [mm]): the 10⁻⁶ of both units cancel.
    return float(member.meshWeight) / (float(_table().steelUnitWeight) * h)


def design_aid_moment(vf: float, fy: float, fc: float, b: float, h: float, eta: float) -> float:
    """Mn of the pack's design aid [N·mm]: (a + b X - c X²) f'c b h² η, X = Vf fy / f'c."""
    aid = _table().designAid
    x = vf * fy / fc
    return (float(aid.a) + float(aid.b) * x - float(aid.c) * x**2) * fc * b * h**2 * eta


# ─────────────────────────────────────── the section ───────────────────────────────────────


@dataclass(frozen=True)
class Layer:
    """A reinforcement layer ``y`` from the top face [mm]: effective area [mm²], fy, Er."""

    y: float
    area: float
    fy: float
    er: float


@dataclass(frozen=True)
class FerroSection:
    b: float
    h: float
    fc: float
    ec: float
    layers: tuple[Layer, ...]
    eta: float
    vf: float
    sr: float | None
    cover: float
    fy: float
    mesh: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, profile: Any, material: Any, member: Any) -> FerroSection:
        if getattr(profile, "shape", None) != "rectangle":
            raise FerrocementDesignError(
                "ferrocement members are designed as rectangles (width x thickness)"
            )
        if member is None:
            raise FerrocementDesignError("the member type gives no mesh layers")
        table = _table()
        b, h = float(profile.xDim), float(profile.yDim)
        fc = float(material.ferrocement.fc)
        ec = float(material.mechanical.E)
        mesh = table.meshes[member.mesh]
        notes: list[str] = []
        fy = float(member.fy or mesh.fy)
        fy_max = float(table.strength.fyMax)
        if fy > fy_max:
            notes.append(f"fy {fy:g} MPa capped at {fy_max:g} MPa ({clause('strength')})")
            fy = fy_max
        eta = float(mesh.eta[member.direction])
        er = float(mesh.Erl if member.direction == "longitudinal" else (mesh.Ert or mesh.Erl))
        if member.direction == "diagonal":
            er = min(float(mesh.Erl), float(mesh.Ert or mesh.Erl))
        vf_layer = volume_fraction(member, h)
        n = int(member.layers)
        db = float(member.wireDiameter)
        cover = float(member.cover) if member.cover else _least_cover(h, db)
        if not member.cover:
            notes.append(f"cover {cover:g} mm: the least the code asks")
        first, last = cover + db, h - cover - db
        if last < first:
            raise FerrocementDesignError(f"{h:g} mm is too thin for the covers and the mesh")
        ys = [h / 2] if n == 1 else list(np.linspace(first, last, n))
        layers = [Layer(float(y), eta * vf_layer * b * h, fy, er) for y in ys]
        bars = member.bars
        if bars is not None:
            row = table.bars
            bar_fy = min(float(row.fy), fy_max)
            area = math.pi * float(bars.diameter) ** 2 / 4 * b / float(bars.spacing)
            layers.append(Layer(h / 2, float(row.eta.longitudinal) * area, bar_fy, float(row.Erl)))
        vf = vf_layer * n
        sr = 4 * vf / db if mesh.volumeFraction == "wires" else None
        return cls(b, h, fc, ec, tuple(layers), eta, vf, sr, cover, fy, mesh.label, tuple(notes))

    @property
    def phis(self) -> tuple[float, float]:
        """(compression φ, tension-controlled φ) of the factors table, as the pack names them."""
        s = _table().strength
        phi = code_context.pack_table("factors").phi
        return float(phi[s.phiCompression]), float(phi[s.phiFlexure])


def _least_cover(h: float, db: float) -> float:
    d = _table().detailing
    if h < float(d.thinSection):
        return float(d.thinCover)
    return float(d.coverWireFactor) * db


# ─────────────────────────────────────── strength ───────────────────────────────────────


def _beta1(fc: float) -> float:
    from saengine.design.rc import beta1

    return beta1(fc)


def nominal(section: FerroSection, c: float) -> tuple[float, float, float]:
    """(Pn [N] compression positive, Mn [N·mm] about mid-thickness, εt of the deepest layer)
    with the neutral axis ``c`` below the top face."""
    s = _table().strength
    ecu = float(s.strainLimit)
    a = min(_beta1(section.fc) * c, section.h)
    cc = float(s.stressBlock) * section.fc * a * section.b
    p = cc
    m = cc * (section.h / 2 - a / 2)
    for layer in section.layers:
        strain = ecu * (c - layer.y) / c
        f = max(-layer.fy, min(layer.fy, layer.er * strain)) * layer.area
        p += f
        m += f * (section.h / 2 - layer.y)
    deepest = max(layer.y for layer in section.layers)
    return p, m, ecu * (deepest - c) / c


def _phi(section: FerroSection, eps_t: float) -> float:
    low, high = section.phis
    ecu = float(_table().strength.strainLimit)
    layer = max(section.layers, key=lambda x: x.y)
    eps_y = layer.fy / layer.er
    if eps_t <= eps_y:
        return low
    if eps_t >= eps_y + ecu:
        return high
    return low + (high - low) * (eps_t - eps_y) / ecu


def interaction(section: FerroSection) -> list[tuple[float, float]]:
    """The φ interaction curve (φPn, φMn ≥ 0), from pure tension to the capped compression."""
    s = _table().strength
    low, high = section.phis
    p_max = low * float(s.compressionShare) * section.fc * section.b * section.h
    t = -sum(x.area * x.fy for x in section.layers)
    points = [(high * t, 0.0)]
    for c in np.geomspace(1e-3 * section.h, 50 * section.h, 160):
        p, m, eps_t = nominal(section, float(c))
        phi = _phi(section, eps_t)
        pp, mm = phi * p, max(phi * m, 0.0)
        if pp >= p_max:
            points.append((p_max, mm))
            break
        points.append((pp, mm))
    points.append((p_max, 0.0))
    return points


def capacity_ratio(curve: list[tuple[float, float]], pu: float, mu: float) -> float:
    """Demand over capacity along the ray from the origin through (Pu, |Mu|)."""
    mu = abs(mu)
    if abs(pu) < 1e-9 and mu < 1e-9:
        return 0.0
    for (p1, m1), (p2, m2) in itertools.pairwise(curve):
        # Solve t (pu, mu) = (p1, m1) + u (p2 - p1, m2 - m1), t > 0, 0 <= u <= 1.
        det = pu * (m1 - m2) - mu * (p1 - p2)
        if abs(det) < 1e-12:
            continue
        t = (p1 * (m1 - m2) - m1 * (p1 - p2)) / det
        u = (pu * m1 - mu * p1) / det
        if t > 0 and -1e-9 <= u <= 1 + 1e-9:
            return 1.0 / t
    return math.inf


def check_strength(section: FerroSection, stations: Sequence[Any]) -> list[dict[str, Any]]:
    curve = interaction(section)
    best: dict[str, Any] | None = None
    for st in stations:
        for j in range(len(st.s)):
            pu, mu = float(st.P[j]), float(st.Mx[j])
            ratio = capacity_ratio(curve, pu, mu)
            if best is None or ratio > best["ratio"]:
                best = {"ratio": ratio, "pu": pu, "mu": mu, "name": st.combination}
    if best is None:
        return []
    return [
        _row(
            f"Axial force and bending, φ strength ({clause('flexure')}; {clause('compression')})",
            best["ratio"],
            1.0,
            "",
            best["name"],
            f"Pu = {best['pu'] / 1e3:.2f} kN, Mu = {best['mu'] / 1e6:.3f} kN·m",
        )
    ]


# ─────────────────────────────────────── service loads ───────────────────────────────────────


def cracked(section: FerroSection) -> tuple[float, float]:
    """(neutral axis x from the top [mm], Icr [mm⁴]) of the cracked transformed section in
    pure bending, every layer with n = Er / Ec."""

    def moment(x: float) -> float:
        return section.b * x**2 / 2 + sum(
            (layer.er / section.ec) * layer.area * (x - layer.y) for layer in section.layers
        )

    lo, hi = 1e-6, section.h
    for _ in range(80):
        mid = (lo + hi) / 2
        if moment(mid) > 0:
            hi = mid
        else:
            lo = mid
    x = (lo + hi) / 2
    icr = section.b * x**3 / 3 + sum(
        (layer.er / section.ec) * layer.area * (layer.y - x) ** 2 for layer in section.layers
    )
    return x, icr


def check_service(
    section: FerroSection,
    stations: Sequence[Any],
    exposure: str = "noncorrosive",
    fatigue: str = "none",
) -> list[dict[str, Any]]:
    table = _table()
    sv = table.service
    x, icr = cracked(section)
    deepest = max(section.layers, key=lambda layer: layer.y)
    shallowest = min(section.layers, key=lambda layer: layer.y)
    n_t = deepest.er / section.ec
    area_steel = sum(layer.area for layer in section.layers)
    area_tr = section.b * section.h + sum(
        (layer.er / section.ec - 1) * layer.area for layer in section.layers
    )
    # Symmetric layers: a moment either way puts the same layer depth in tension.
    kt = n_t * (deepest.y - x) / icr
    kc = (shallowest.er / section.ec) * (x - shallowest.y) / icr
    allow_s = (
        float(sv.liquidRetaining)
        if exposure == "waterRetaining"
        else float(sv.steelShare) * section.fy
    )
    allow_c = float(sv.mortarShare) * section.fc
    rows: dict[str, dict[str, Any]] = {}

    def offer(key: str, row: dict[str, Any]) -> None:
        if key not in rows or row["utilisation"] > rows[key]["utilisation"]:
            rows[key] = row

    count = min((len(st.s) for st in stations), default=0)
    ranges = [[] for _ in range(count)]
    for st in stations:
        for j in range(len(st.s)):
            p, m = float(st.P[j]), float(st.Mx[j])
            fs = kt * abs(m) + (max(-p, 0.0) / area_steel)
            fcm = abs(m) * x / icr + max(p, 0.0) / area_tr
            offer(
                "fs",
                _row(
                    f"Mesh tension at service loads ({clause('steelStress')})",
                    fs,
                    allow_s,
                    "MPa",
                    st.combination,
                    f"M = {m / 1e6:.3f} kN·m, cracked section x = {x:.1f} mm",
                ),
            )
            offer(
                "fc",
                _row(
                    f"Mortar compression at service loads ({clause('mortarStress')})",
                    fcm,
                    allow_c,
                    "MPa",
                    st.combination,
                    f"{float(sv.mortarShare):g} f'c",
                ),
            )
            if j < count:
                # The bottom layer's stress: tension when M stretches the bottom (M < 0).
                ranges[j].append(kt * -m if m < 0 else -kc * m)
    out = list(rows.values())
    if fatigue != "none" and ranges:
        limit = float(table.fatigue[fatigue])
        swing = max((max(r) - min(r) for r in ranges if r), default=0.0)
        out.append(
            _row(
                f"Mesh stress range for fatigue ({clause('fatigue')})",
                swing,
                limit,
                "MPa",
                None,
                "over the service combinations",
            )
        )
    return out


# ─────────────────────────────────────── detailing ───────────────────────────────────────


def check_detailing(section: FerroSection, member: Any) -> list[dict[str, Any]]:
    table = _table()
    d = table.detailing
    db = float(member.wireDiameter)
    out = [
        _row(
            f"Cover to the first mesh layer ({clause('cover')})",
            _least_cover(section.h, db),
            section.cover,
            "mm",
            None,
            "about twice the wire diameter (2 mm below 25 mm)",
            utilisation=_least_cover(section.h, db) / section.cover,
        ),
        _row(
            f"Mesh layers ({clause('layers')})",
            float(d.minLayers),
            float(member.layers),
            "",
            None,
            "at least",
            utilisation=float(d.minLayers) / float(member.layers),
        ),
    ]
    if member.spacing:
        opening = float(member.spacing)
        out.append(
            _row(f"Mesh opening ({clause('opening')})", opening, section.h, "mm", None, "≤ h")
        )
    if member.exposure == "waterRetaining":
        out.append(
            _row(
                f"Volume fraction, water retaining ({clause('waterRetaining')})",
                float(d.waterVolumeFraction) * 100,
                section.vf * 100,
                "%",
                None,
                "at least",
                utilisation=float(d.waterVolumeFraction) / max(section.vf, 1e-12),
            )
        )
        if section.sr is not None:
            out.append(
                _row(
                    f"Specific surface, water retaining ({clause('waterRetaining')})",
                    float(d.waterSpecificSurface),
                    section.sr,
                    "mm²/mm³",
                    None,
                    "at least",
                    utilisation=float(d.waterSpecificSurface) / max(section.sr, 1e-12),
                )
            )
    if member.bars is not None:
        out.append(
            _row(
                f"Skeletal steel in the thickness ({clause('skeletal')})",
                2 * float(member.bars.diameter),
                float(d.skeletalShare) * section.h,
                "mm",
                None,
                "bars both ways",
            )
        )
    if section.fc < float(d.minMortarStrength):
        out.append(
            _flag(
                _row(
                    f"Mortar strength for most applications ({clause('mortar')})",
                    float(d.minMortarStrength),
                    section.fc,
                    "MPa",
                    None,
                    "advisory",
                    utilisation=float(d.minMortarStrength) / section.fc,
                )
            )
        )
    if section.h > float(table.strength.efficiencyThickness):
        out.append(
            _flag(
                _row(
                    f"Efficiency factor of the table, sections up to "
                    f"{float(table.strength.efficiencyThickness):g} mm ({clause('efficiency')})",
                    section.h,
                    float(table.strength.efficiencyThickness),
                    "mm",
                    None,
                    "thicker: η from tests",
                )
            )
        )
    return out


# ─────────────────────────────────────── the member ───────────────────────────────────────


def design_ferrocement_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    strength_pieces: Sequence[Any],
    strength_names: Sequence[str],
    service_pieces: Sequence[Any] | None = None,
    service_names: Sequence[str] = (),
    turned: bool = False,
) -> dict[str, Any]:
    """The design report entry of one ferrocement beam or column: ``{id, kind, type, members,
    checks, utilisation, ok, material, ferrocement}``. Raises :class:`FerrocementDesignError`."""
    from saengine.design.steel.members import member_stations

    if not strength_pieces:
        raise FerrocementDesignError("not in the analysis results")
    member = getattr(object_type, "ferrocement", None)
    section = FerroSection.of(object_type.profile, material, member)
    checks = check_strength(section, member_stations(strength_pieces, strength_names, turned))
    notes = list(section.notes)
    if service_pieces and service_names:
        stations = member_stations(service_pieces, service_names, turned)
        checks += check_service(section, stations, member.exposure, member.fatigueCycles)
    else:
        notes.append("service load stresses not checked: no allowable stress combinations")
    checks += check_detailing(section, member)
    table = _table()
    limit = float(table.crackWidth[member.exposure])
    notes.append(
        f"crack width at most {limit:g} mm ({clause('crackWidth')}): the code gives no method "
        f"to predict it; the mesh stress limit stands for it ({clause('steelStress')})"
    )
    notes.append("shear and slenderness: the chapter gives no provision; not checked")
    notes.append("bending about the width axis (through the thickness) only")
    strength = [c for c in checks if not c["flag"]]
    aid = design_aid_moment(section.vf, section.fy, section.fc, section.b, section.h, section.eta)
    return {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in strength_pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        "ferrocement": {
            "label": f"{section.b:g} x {section.h:g} ferrocement, {member.layers} layers of "
            f"{section.mesh.lower()}",
            "fc": section.fc,
            "fy": section.fy,
            "eta": section.eta,
            "Vf": round(section.vf, 5),
            "Sr": round(section.sr, 4) if section.sr is not None else None,
            "cover": section.cover,
            "crackWidthLimit": limit,
            "designAidMn": round(aid / 1e6, 4),
            "code": code_name(),
            "clause": clause("chapter"),
            "notes": notes,
        },
    }


def design_members(
    todo: Sequence[tuple[str, Any, Any, Sequence[Any], bool]],
    strength_names: Sequence[str],
    case_forces: dict[str, Any],
    names: Sequence[str],
    factors: Sequence[dict[str, float]],
    checked: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> bool:
    """The ferrocement members of ``todo`` (``(id, object type, material, pieces, turned)``,
    the pieces with the strength combinations ``strength_names``' forces), their service
    stresses under the allowable stress combinations ``names``/``factors`` of ``case_forces``.
    True when one was checked."""
    seen = False
    for member_id, object_type, material, own, turned in todo:
        try:
            entry = design_ferrocement_member(
                member_id,
                object_type.kind,
                object_type,
                material,
                own,
                strength_names,
                asd_pieces(own, case_forces, factors) if names else None,
                names,
                turned,
            )
        except FerrocementDesignError as error:
            skipped.append(
                {
                    "id": member_id,
                    "kind": object_type.kind,
                    "type": object_type.id,
                    "reason": f"ferrocement not checked: {error}",
                }
            )
            continue
        checked.append(entry)
        seen = True
    return seen
