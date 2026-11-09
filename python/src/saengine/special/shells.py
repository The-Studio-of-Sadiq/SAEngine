"""Silos, chimneys and cooling towers: shells of revolution under the loads the code pack gives
for them (its ``shellStructures`` table), designed by its concrete or steel methods.

Silos (``silos``, Janssen's theory for slender silos): z0 = A / (K μ U) = D / (4 K μ), on
filling ph(z) = γ K z0 (1 - e^(-z/z0)), pw = μ ph, pv = ph / K, on discharge ph × Ch and pw × Cw.
The horizontal pressure takes K upper (Km aK) and μ lower (μm / aμ); the wall friction K upper
and μ upper (μm aμ). The wall's hoop tension n = ph r per m of height, × the table's γF, against
the hoop bars of both faces at the pack's design yield (fyd, or φ fy); the wall's vertical
compression from the friction (n = ∫ pw dz) and its own weight against the pack's design
compressive strength. Not covered: hoppers, eccentric filling and discharge, patch loads,
squat silos, thermal and settlement effects, the roof.

Chimneys: a tapering tube, a cantilever from its base. Its first frequency from a beam model
(EI = E π D³ t / 8, its mass and lining) unless given. Along-wind: w(z) = qz G Cf D with Cf of the
pack's wind table for chimneys (round, by h/D and D√qz) and qz of the site, giving the base
shear, moment and the shell's stress. Vortex shedding (the table's ``chimneys`` group, the
effective correlation length method): vcrit = b n1 / St with b the mean diameter of the top
third; when vcrit < speedMargin × vm (vm from qz at the top, √(2 qz / ρ): on the safe side) the
largest amplitude yF = b K Kw clat / (St² Sc), Sc = 2 δs me / (ρ b²), clat of the table at Re =
b vcrit / ν, Kw = 3 (Lj/b)/λ [1 - (Lj/b)/λ + ((Lj/b)/λ)² / 3] at most kwMax, Lj/b from yF/b
(iterated), and the inertia forces m (2π n1)² Φ yF give the base moment. Steel shells are checked
by the pack's steel method (elastic moment and axial resistance of the tube), concrete ones for
the compression stress of the uncracked tube against the pack's design strength (the vertical
bars are not designed). Not covered: ovalling, the across-wind of groups, CICIND's own rules,
liners and temperature.

Cooling towers: a hyperboloid shell of four-node shell elements (OpenSees ShellMITC4, its local
1 axis round the shell, 2 up the meridian) fixed at its base, under its weight and the wind:
p = qz(z) (cp(α) - cpi), cp of the pack's distribution around a circular cylinder (1 at the
windward line, the least cpmin at αmin, the base pressure from the separation αA, a cos² shape
between the code's points: SAEngine practice), interpolated by the Reynolds number at the throat.
The meridional and hoop forces under the pack's strength combinations, and the steel they need
at the rebar's design yield. Not covered: buckling, temperature, the columns and ring beams,
end effects (ψλα = 1).

Units: m, kN, kN/m, MPa.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.special import common

G = 9.80665


def _rules(group: str) -> tuple[Any, str]:
    """The pack's ``shellStructures.<group>`` and its clause; ValueError when not covered."""
    pack = code_context.current()
    code = code_context.code_name(pack)
    table = pack.table("shellStructures") if pack.has("shellStructures") else None
    found = getattr(table, group, None) if table is not None else None
    if found is None:
        raise ValueError(f"{group}: not covered by the code pack {code}")
    clause = str((table.clauses or {}).get(group, ""))
    return found, f"{code} {clause}".strip()


def _material(materials: Any, material_id: str) -> Any:
    found = next((m for m in materials.materials if m.id == material_id), None)
    if found is None:
        raise ValueError(f"material '{material_id}' is not in 03 Materials")
    return found


def bar_strength(fy: float) -> float:
    """The design tension strength of bars [MPa]: fyd with partial factors, else φ fy."""
    from saengine.design import design_strength, rc

    if design_strength.partial_factors():
        return float(design_strength.fyd(fy))
    return float(rc.value("PHI_TENSION")) * fy


def concrete_strength(fc: float) -> float:
    """The design compressive strength of a wall in axial compression [MPa]: fcd with partial
    factors, else φ × the squash share × f'c."""
    from saengine.design import design_strength, rc

    if design_strength.partial_factors():
        return float(design_strength.fcd(fc))
    return float(rc.value("PHI_TIED")) * rc.squash_share(fc) * fc


# ───────────────────────────────────── silos ─────────────────────────────────────


def janssen(diameter: float, weight: float, k: float, mu: float, z: np.ndarray) -> dict[str, Any]:
    """Janssen's pressures in a circular silo [kPa]: ``ph``, ``pw``, ``pv`` at depths ``z`` [m]
    below the solid's surface, with z0 [m] and the wall friction per m of circumference ``nz``
    [kN/m] carried down to each depth."""
    z0 = diameter / (4 * k * mu)
    yj = 1 - np.exp(-z / z0)
    ph = weight * k * z0 * yj
    pw = mu * ph
    nz = mu * weight * k * z0 * (z - z0 * yj)
    return {"z0": z0, "ph": ph, "pw": pw, "pv": ph / k, "nz": nz}


def analyse_silo(silo: Any, materials: Any) -> dict[str, Any]:
    rules, clause = _rules("silos")
    solid = rules.solids.get(silo.solid)
    if solid is None:
        raise ValueError(f"silo {silo.id}: no stored solid '{silo.solid}' in the code pack")
    mu_m = solid.mu.get(silo.wall)
    if mu_m is None:
        raise ValueError(f"silo {silo.id}: no wall friction for wall type {silo.wall}")
    k_up = solid.k * solid.aK
    mu_low, mu_up = mu_m / solid.aMu, mu_m * solid.aMu
    z = np.linspace(0.0, silo.height, 11)
    normal = janssen(silo.diameter, solid.weight, k_up, mu_low, z)
    friction = janssen(silo.diameter, solid.weight, k_up, mu_up, z)
    r = silo.diameter / 2 + silo.wallThickness / 2000
    ph_e = rules.dischargeHorizontal * normal["ph"]
    hoop = rules.loadFactor * ph_e * r  # kN/m of height
    concrete = _material(materials, silo.concrete)
    rebar = _material(materials, silo.rebar)
    fy = float(rebar.steel.fy)
    fc = float(concrete.concrete.fc)
    area = 2 * math.pi * silo.hoopDiameter**2 / 4 * 1000 / silo.hoopSpacing  # mm²/m, two faces
    capacity = area * bar_strength(fy) / 1000  # kN/m
    t = silo.wallThickness / 1000
    gamma_c = ((concrete.mechanical.density if concrete.mechanical else None) or 2400) * G / 1000
    n_fric = rules.loadFactor * rules.dischargeFriction * friction["nz"][-1]
    n_dead = 1.35 * gamma_c * t * silo.height  # SAEngine practice γG on the wall's weight
    stress = (n_fric + n_dead) / t / 1000  # MPa
    rows = [
        {
            "name": "Hoop tension at the base of the wall (discharge)",
            "demand": round(float(hoop[-1]), 1),
            "capacity": round(capacity, 1),
            "unit": "kN/m",
            "ratio": round(float(hoop[-1]) / capacity, 3) if capacity else None,
            "note": f"γF {rules.loadFactor:g} × Ch {rules.dischargeHorizontal:g} × ph × r; hoop "
            f"bars Ø{silo.hoopDiameter:g} @ {silo.hoopSpacing:g} each face",
        },
        {
            "name": "Wall compression at the base (friction and weight)",
            "demand": round(stress, 2),
            "capacity": round(concrete_strength(fc), 2),
            "unit": "MPa",
            "ratio": round(stress / concrete_strength(fc), 3),
            "note": f"γF Cw Σpw = {n_fric:.0f} kN/m with the wall's weight × 1.35 (practice)",
        },
    ]
    for row in rows:
        row["ok"] = row["ratio"] is not None and row["ratio"] <= 1.0
    return {
        "rows": rows,
        "pressures": [
            {
                "z": round(float(zv), 2),
                "ph": round(float(a), 2),
                "pw": round(float(b), 2),
                "pv": round(float(c), 2),
                "phDischarge": round(float(d), 2),
            }
            for zv, a, b, c, d in zip(
                z, normal["ph"], friction["pw"], normal["pv"], ph_e, strict=True
            )
        ],
        "notes": [
            (
                f"Janssen ({clause}): {solid.label}, γ {solid.weight:g} kN/m³, K = {k_up:.3f}, "
                f"μ {mu_low:.3f} / {mu_up:.3f} (wall {silo.wall}), z0 = {normal['z0']:.2f} m"
            ),
            (
                "not covered: hoppers, eccentric filling and discharge, patch loads, squat "
                "silos, thermal effects, the roof"
            ),
        ],
    }


# ───────────────────────────────────── chimneys ─────────────────────────────────────


def _chimney_beam(chimney: Any, material: Any, segments: int = 20) -> dict[str, Any]:
    """Stations, diameters, thicknesses, EI [N·m²] and mass [kg/m] along a chimney."""
    z = np.linspace(0.0, chimney.height, segments + 1)
    d = chimney.baseDiameter + (chimney.topDiameter - chimney.baseDiameter) * z / chimney.height
    t = (
        chimney.baseThickness + (chimney.topThickness - chimney.baseThickness) * z / chimney.height
    ) / 1000
    e = ((material.mechanical.E if material.mechanical else None) or 30000) * 1e6
    density = (material.mechanical.density if material.mechanical else None) or 2400
    ei = e * math.pi * d**3 * t / 8
    mass = density * math.pi * d * t + chimney.liningWeight * 1000 / G
    return {"z": z, "d": d, "t": t, "ei": ei, "mass": mass, "e": e, "density": density}


def first_mode(beam: dict[str, Any]) -> tuple[float, np.ndarray]:
    """(frequency [Hz], mode shape at the stations, 1 at the top) of the cantilever."""
    from scipy.linalg import eigh

    z = beam["z"]
    n = len(z)
    size = 2 * n
    k = np.zeros((size, size))
    m = np.zeros((size, size))
    for e in range(n - 1):
        length = z[e + 1] - z[e]
        ei = 0.5 * (beam["ei"][e] + beam["ei"][e + 1])
        mu = 0.5 * (beam["mass"][e] + beam["mass"][e + 1])
        a = length
        ke = (
            ei
            / a**3
            * np.array(
                [
                    [12, 6 * a, -12, 6 * a],
                    [6 * a, 4 * a * a, -6 * a, 2 * a * a],
                    [-12, -6 * a, 12, -6 * a],
                    [6 * a, 2 * a * a, -6 * a, 4 * a * a],
                ]
            )
        )
        me = (
            mu
            * a
            / 420
            * np.array(
                [
                    [156, 22 * a, 54, -13 * a],
                    [22 * a, 4 * a * a, 13 * a, -3 * a * a],
                    [54, 13 * a, 156, -22 * a],
                    [-13 * a, -3 * a * a, -22 * a, 4 * a * a],
                ]
            )
        )
        dofs = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
        k[np.ix_(dofs, dofs)] += ke
        m[np.ix_(dofs, dofs)] += me
    free = list(range(2, size))  # the base held
    values, vectors = eigh(k[np.ix_(free, free)], m[np.ix_(free, free)])
    omega = math.sqrt(max(float(values[0]), 0.0))
    shape = np.concatenate([[0.0], vectors[0::2, 0]])
    shape = shape / shape[-1] if shape[-1] else shape
    return omega / (2 * math.pi), shape


def _interp_log(points: list[tuple[float, float]], x: float) -> float:
    xs = [math.log10(p[0]) for p in points]
    ys = [p[1] for p in points]
    return float(np.interp(math.log10(max(x, 1.0)), xs, ys))


def analyse_chimney(chimney: Any, settings: Any, materials: Any) -> dict[str, Any]:
    from saengine.fem.loads import wind_factor, wind_overrides
    from saengine.fem.open_wind import chimney_cf

    material = _material(materials, chimney.material)
    beam = _chimney_beam(chimney, material)
    notes: list[str] = []
    if chimney.frequency:
        n1 = float(chimney.frequency)
        shape = (beam["z"] / chimney.height) ** 2
        notes.append(f"first frequency {n1:g} Hz as given; mode shape (z/h)²")
    else:
        n1, shape = first_mode(beam)
        notes.append(f"first frequency {n1:.3f} Hz from the tube's stiffness and mass")
    qz, wind_notes = common.wind_pressure(settings)
    notes += wind_notes
    if qz is None:
        raise ValueError(f"chimney {chimney.id}: the site has no wind speed")
    pack = code_context.current()
    table = getattr(pack.table("wind"), "chimneys", None) if pack.has("wind") else None
    with wind_overrides(settings.wind):
        gust = float(wind_factor("gust"))
    z, d = beam["z"], beam["d"]
    q = np.array([qz(float(v)) for v in z])  # kPa
    h_over_d = chimney.height / float(np.mean(d))
    if table is not None:
        cf = np.array(
            [
                chimney_cf(table, "round", "moderatelySmooth", h_over_d, dv * math.sqrt(qv * 1e3))
                for dv, qv in zip(d, q, strict=True)
            ]
        )
    else:
        cf = np.full(len(z), 0.7)
        notes.append("Cf 0.7 of a smooth round section (SAEngine practice: no chimney table)")
    w = q * gust * cf * d  # kN/m
    shear = float(np.trapezoid(w, z))
    moment = float(np.trapezoid(w * z, z))
    weight = float(np.trapezoid(beam["mass"], z)) * G / 1000
    r_base, t_base = d[0] / 2, beam["t"][0]
    area = 2 * math.pi * r_base * t_base
    modulus = math.pi * r_base**2 * t_base
    pairs, how = common.strength_pairs(settings, pack)
    w_factor = max((p[2] for p in pairs if p[2] > 0), default=1.0)
    d_factor = max((p[1] for p in pairs if p[2] > 0), default=1.0)
    rows: list[dict[str, Any]] = []
    vortex: dict[str, Any] = {}
    try:
        rules, clause = _rules("chimneys")
    except ValueError as error:
        rules = None
        notes.append(f"vortex shedding: {error}")
    m_vortex = 0.0
    if rules is not None:
        third = z >= 2 * chimney.height / 3
        b = float(np.mean(d[third]))
        me = float(np.mean(beam["mass"][third]))
        delta = rules.damping.get(chimney.kind)
        if delta is None:
            delta = min(rules.damping.values())
            notes.append(f"vortex shedding: no damping for '{chimney.kind}'; δs {delta:g} taken")
        vcrit = b * n1 / rules.strouhal
        vm = math.sqrt(2 * q[-1] * 1000 / rules.airDensity)
        vortex = {"b": round(b, 3), "vcrit": round(vcrit, 2), "vm": round(vm, 2)}
        if vcrit < rules.speedMargin * vm:
            sc = 2 * delta * me / (rules.airDensity * b * b)
            re = b * vcrit / rules.kinematicViscosity
            clat = _interp_log(rules.lateral, re)
            slender = chimney.height / b
            ratio = 0.05
            lj = rules.correlation[0]
            for _ in range(20):
                if ratio < 0.1:
                    lj = rules.correlation[0]
                elif ratio < 0.6:
                    lj = 4.8 + rules.correlation[1] * ratio
                else:
                    lj = rules.correlation[2]
                u = min(lj / slender, 1.0)
                kw = min(rules.kwMax, 3 * u * (1 - u + u * u / 3))
                new = rules.modeFactor * kw * clat / (rules.strouhal**2 * sc)
                if abs(new - ratio) < 1e-6:
                    ratio = new
                    break
                ratio = new
            y_f = ratio * b
            inertia = beam["mass"] * (2 * math.pi * n1) ** 2 * shape * y_f / 1000  # kN/m
            m_vortex = float(np.trapezoid(inertia * z, z))
            vortex.update(
                {
                    "Sc": round(sc, 2),
                    "Re": round(re),
                    "clat": round(clat, 3),
                    "Kw": round(kw, 3),
                    "LjOverB": round(lj, 2),
                    "yF": round(y_f * 1000, 1),
                    "baseMoment": round(m_vortex, 1),
                }
            )
            notes.append(
                f"vortex shedding ({clause}): vcrit {vcrit:.1f} m/s < {rules.speedMargin:g} vm; "
                f"yF = {y_f * 1000:.0f} mm, base moment {m_vortex:.0f} kN·m"
            )
        else:
            notes.append(
                f"vortex shedding ({clause}): vcrit {vcrit:.1f} m/s above {rules.speedMargin:g} × "
                f"vm ({vm:.1f} m/s): no check needed"
            )
    governing = max(moment * w_factor, m_vortex * (rules.loadFactor if rules else 1.0))
    sigma_n = d_factor * weight / area / 1000  # MPa
    sigma_m = governing / modulus / 1000
    category = getattr(material.category, "value", material.category)
    if category == "steel":
        from saengine.design.steel.members import Steel
        from saengine.design.steel.pack_resistance import axial, elastic_moment
        from saengine.design.steel.properties import shape_properties
        from saengine.library.objects import CircleHollowProfile

        tube = shape_properties(
            CircleHollowProfile(radius=r_base * 1000, wallThickness=t_base * 1000), erw=False
        )
        steel = Steel.of(material)
        n_rd, _, _ = axial(tube, steel, chimney.height * 2000, chimney.height * 2000, True)
        m_rd, _, _ = elastic_moment(tube, steel)
        ratio = d_factor * weight * 1000 / n_rd + governing * 1e6 / m_rd
        rows.append(
            {
                "name": "Base of the shell: axial force and moment (steel tube)",
                "demand": round(governing, 1),
                "capacity": round(m_rd / 1e6, 1),
                "unit": "kN·m",
                "ratio": round(ratio, 3),
                "ok": ratio <= 1.0,
                "note": "N/NRd + M/MRd by the pack's steel method (K L = 2 h)",
            }
        )
    else:
        fc = float(material.concrete.fc) if material.concrete else 30.0
        cap = concrete_strength(fc)
        stress = sigma_n + sigma_m
        rows.append(
            {
                "name": "Base of the shell: compression stress (uncracked tube)",
                "demand": round(stress, 2),
                "capacity": round(cap, 2),
                "unit": "MPa",
                "ratio": round(stress / cap, 3),
                "ok": stress <= cap,
                "note": f"tension {max(sigma_m - sigma_n, 0):.2f} MPa needs vertical bars "
                "(not designed)",
            }
        )
    notes.append(
        f"along-wind: base shear {shear:.0f} kN, moment {moment:.0f} kN·m (G {gust:g}); "
        f"combinations: {how}"
    )
    notes.append(
        "not covered: ovalling, across-wind of chimney groups, liners and temperature, the "
        "vertical bars of concrete shells"
    )
    return {
        "frequency": round(n1, 4),
        "alongWind": {
            "shear": round(shear, 1),
            "moment": round(moment, 1),
            "weight": round(weight, 1),
        },
        "vortex": vortex,
        "rows": rows,
        "notes": notes,
    }


# ───────────────────────────────────── cooling towers ─────────────────────────────────


def pressure_coefficient(alpha: float, row: Any) -> float:
    """cp at ``alpha`` [°] from the windward line (SAEngine's cos² shape between the code's
    points)."""
    a = abs(alpha) % 360
    a = 360 - a if a > 180 else a
    if a <= row.alphaMin:
        return 1 - (1 - row.cpMin) * math.sin(math.radians(90 * a / row.alphaMin)) ** 2
    if a <= row.alphaA:
        s = math.sin(math.radians(90 * (a - row.alphaMin) / (row.alphaA - row.alphaMin))) ** 2
        return row.cpMin + (row.cpBase - row.cpMin) * s
    return float(row.cpBase)


def _row_for(rows: list[Any], reynolds: float) -> Any:
    """The table row at ``reynolds`` (log-linear between rows, the end rows outside)."""
    ordered = sorted(rows, key=lambda r: r.reynolds)
    if reynolds <= ordered[0].reynolds:
        return ordered[0]
    if reynolds >= ordered[-1].reynolds:
        return ordered[-1]
    for lo, hi in itertools.pairwise(ordered):
        if lo.reynolds <= reynolds <= hi.reynolds:
            t = (math.log10(reynolds) - math.log10(lo.reynolds)) / (
                math.log10(hi.reynolds) - math.log10(lo.reynolds)
            )
            return type(lo)(
                reynolds=reynolds,
                alphaMin=lo.alphaMin + t * (hi.alphaMin - lo.alphaMin),
                cpMin=lo.cpMin + t * (hi.cpMin - lo.cpMin),
                alphaA=lo.alphaA + t * (hi.alphaA - lo.alphaA),
                cpBase=lo.cpBase + t * (hi.cpBase - lo.cpBase),
            )
    return ordered[-1]


def analyse_cooling_tower(tower: Any, settings: Any, materials: Any) -> dict[str, Any]:
    import openseespy.opensees as ops

    from saengine.library.shapes import revolution_radius

    rules, clause = _rules("coolingTowers")
    qz, notes = common.wind_pressure(settings)
    if qz is None:
        raise ValueError(f"cooling tower {tower.id}: the site has no wind speed")
    concrete = _material(materials, tower.concrete)
    e = (
        (concrete.mechanical.E if concrete.mechanical else None)
        or 4700 * math.sqrt(concrete.concrete.fc)
    ) * 1e6
    nu = (concrete.mechanical.nu if concrete.mechanical else None) or 0.2
    gamma = ((concrete.mechanical.density if concrete.mechanical else None) or 2400) * G
    t = tower.thickness / 1000
    nr, ns = tower.rings, tower.segments
    zs = np.linspace(0.0, tower.height, nr + 1)
    radii = np.array(
        [
            revolution_radius(
                "hyperboloid",
                float(zv),
                tower.height,
                tower.baseRadius,
                tower.topRadius,
                tower.throatRadius,
                tower.throatHeight,
            )
            for zv in zs
        ]
    )
    thetas = np.linspace(0.0, 2 * math.pi, ns, endpoint=False)
    v_top = math.sqrt(2 * qz(tower.height) * 1000 / 1.25)
    row = _row_for(rules.rows, 2 * tower.throatRadius * v_top / 1.5e-5)

    def tag(k: int, j: int) -> int:
        return k * ns + (j % ns) + 1

    def build() -> None:
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        for k in range(nr + 1):
            for j in range(ns):
                ops.node(
                    tag(k, j),
                    float(radii[k] * math.cos(thetas[j])),
                    float(radii[k] * math.sin(thetas[j])),
                    float(zs[k]),
                )
        for j in range(ns):
            ops.fix(tag(0, j), 1, 1, 1, 1, 1, 1)
        ops.section("ElasticMembranePlateSection", 1, e, nu, t, 0.0)
        for k in range(nr):
            for j in range(ns):
                ops.element(
                    "ShellMITC4",
                    k * ns + j + 1,
                    tag(k, j),
                    tag(k, j + 1),
                    tag(k + 1, j + 1),
                    tag(k + 1, j),
                    1,
                )

    def nodal_loads(kind: str) -> dict[int, np.ndarray]:
        out: dict[int, np.ndarray] = {}
        dtheta = 2 * math.pi / ns
        for k in range(nr + 1):
            below = zs[k] - zs[k - 1] if k > 0 else 0.0
            above = zs[k + 1] - zs[k] if k < nr else 0.0
            dr = (radii[min(k + 1, nr)] - radii[max(k - 1, 0)]) / (
                zs[min(k + 1, nr)] - zs[max(k - 1, 0)]
            )
            slant = math.sqrt(1 + dr * dr)
            for j in range(ns):
                area = radii[k] * dtheta * (below + above) / 2 * slant
                if kind == "G":
                    out[tag(k, j)] = np.array([0.0, 0.0, -gamma * t * area, 0, 0, 0])
                    continue
                th = thetas[j]
                alpha = math.degrees(abs(math.pi - th))  # windward line at θ = 180° (wind +x)
                p = qz(float(zs[k])) * 1000 * (pressure_coefficient(alpha, row) - rules.internal)
                normal = np.array([math.cos(th), math.sin(th), -dr]) / slant  # outward
                out[tag(k, j)] = np.concatenate([-p * area * normal, np.zeros(3)])
        return out

    forces: dict[str, np.ndarray] = {}
    try:
        for case in ("G", "W"):
            build()
            ops.timeSeries("Linear", 1)
            ops.pattern("Plain", 1, 1)
            for node, values in nodal_loads(case).items():
                ops.load(node, *(float(v) for v in values))
            ops.constraints("Plain")
            ops.numberer("RCM")
            ops.system("UmfPack")
            ops.integrator("LoadControl", 1.0)
            ops.algorithm("Linear")
            ops.analysis("Static")
            if ops.analyze(1) != 0:
                raise ValueError(f"cooling tower {tower.id}: the shell model could not be solved")
            values = np.zeros((nr * ns, 2))
            for el in range(nr * ns):
                found = np.asarray(ops.eleResponse(el + 1, "stresses"), dtype=float)
                if found.size >= 8:
                    gp = found.reshape(-1, 8)
                    values[el] = [gp[:, 0].mean(), gp[:, 1].mean()]  # hoop, meridional [N/m]
            forces[case] = values
    finally:
        ops.wipe()
    pairs, how = common.strength_pairs(settings, code_context.current())
    worst = {"tension": 0.0, "compression": 0.0, "hoop": 0.0, "hoopCompression": 0.0}
    for _, d, w in pairs:
        n = d * forces["G"] + w * forces["W"]
        worst["tension"] = max(worst["tension"], float(n[:, 1].max()))
        worst["compression"] = min(worst["compression"], float(n[:, 1].min()))
        worst["hoop"] = max(worst["hoop"], float(n[:, 0].max()))
        worst["hoopCompression"] = min(worst["hoopCompression"], float(n[:, 0].min()))
    rows = []
    fc = float(concrete.concrete.fc)
    cap = concrete_strength(fc) * t * 1000  # kN/m
    comp = -worst["compression"] / 1000
    rows.append(
        {
            "name": "Meridional compression",
            "demand": round(comp, 1),
            "capacity": round(cap, 1),
            "unit": "kN/m",
            "ratio": round(comp / cap, 3),
            "ok": comp <= cap,
            "note": "the shell's design compressive strength × t; buckling not checked",
        }
    )
    if tower.rebar:
        rebar = _material(materials, tower.rebar)
        fyd = bar_strength(float(rebar.steel.fy))
        for name, value in (("Meridional", worst["tension"]), ("Hoop", worst["hoop"])):
            need = max(value, 0.0) / fyd  # mm²/m (N/m ÷ MPa)
            rows.append(
                {
                    "name": f"{name} tension: steel needed",
                    "demand": round(value / 1000, 1),
                    "capacity": None,
                    "unit": "kN/m",
                    "ratio": None,
                    "ok": None,
                    "note": f"{need:.0f} mm²/m at fyd {fyd:.0f} MPa (both faces)",
                }
            )
    notes += [
        (
            f"wind pressure around the shell ({clause}): cp from 1 to {row.cpMin:.2f} at "
            f"{row.alphaMin:.0f}° and {row.cpBase:.2f} beyond {row.alphaA:.0f}°, internal "
            f"{rules.internal:g}; combinations: {how}"
        ),
        f"shell: {nr} × {ns} ShellMITC4 elements, t = {tower.thickness:g} mm, fixed base ring",
        "not covered: buckling, temperature, the columns and ring beams, end effects",
    ]
    return {
        "forces": {k: round(v / 1000, 1) for k, v in worst.items()},
        "rows": rows,
        "notes": notes,
    }
