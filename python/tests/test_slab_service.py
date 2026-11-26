"""Cracked long-term deflection and crack widths of FE slabs (saengine.design.slab_service, #302)
against hand calculations: a one-way simply supported slab strip, 5 m span, 200 mm thick,
f'c 25 MPa, Ø12 bottom bars, dead 6 and live 3 kN/m².

- Immediate cracked deflection by the default pack's Ie (Eq. 6.6.1: Branson's cubic form) and
  the long-term part λΔ = ξ/(1 + 50 ρ') (Eq. 6.6.4), worked by hand below.
- Crack widths by each method a pack picks: EN 1992-1-1 7.3.4 (Eurocodes), IS 456 Annex F,
  GB 50010 7.1.2 (ψ), and the default pack's bar spacing at the service steel stress.
- The collection from a shell mesh: the strip's mid-span moment and its deflection relative to
  the supports match wL²/8 and 5wL⁴/(384 EI).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import slab as slab_design
from saengine.design import slab_service as ss

H, FC, FY, ES = 200.0, 25.0, 420.0, 200_000.0
EC = 4700 * math.sqrt(FC)  # 23 500 MPa
SPAN = 5000.0
WD, WL = 6.0, 3.0  # N/mm per metre width (kN/m²)
IG = 1000 * H**3 / 12  # mm⁴/m
EI = EC * IG  # the analysis's plate stiffness per metre (uncracked)
COVER = 20.0


def elastic(w: float) -> float:
    return 5 * w * SPAN**4 / (384 * EI)


def layer(dia: float, spacing: float) -> ss.LayerData:
    return ss.LayerData(dia, spacing, H - COVER - dia / 2)


def one_way(
    bottom: ss.LayerData, top: ss.LayerData | None = None, ec: float = EC, fc: float = FC
) -> ss.SlabServiceData:
    span = ss.SpanData(
        "X strip",
        "X",
        "strip",
        SPAN,
        False,
        0,
        (WD * SPAN**2 / 8, WL * SPAN**2 / 8),
        (),
        (elastic(WD), elastic(WL)),
    )
    return ss.SlabServiceData(
        "S1",
        H,
        fc,
        FY,
        ES,
        ec,
        EI,
        False,
        {"bottomX": bottom, "bottomY": None, "topX": top, "topY": None},
        [span],
    )


def pack(pack_id: str):
    return code_context.using(registry.load(pack_id))


def cracked(b: float, d: float, n: float, a_s: float, a_s2: float = 0.0, d2: float = 0.0):
    """(c, Icr) of a rectangle by hand: b c²/2 + (n - 1) As' (c - d') = n As (d - c)."""
    qa, qb, qc = b / 2, n * a_s + (n - 1) * a_s2, -(n * a_s * d + (n - 1) * a_s2 * d2)
    c = (-qb + math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
    icr = b * c**3 / 3 + n * a_s * (d - c) ** 2 + (n - 1) * a_s2 * (c - d2) ** 2
    return c, icr


# ─────────────────────────────── deflection ───────────────────────────────


def test_immediate_cracked_deflection_by_hand() -> None:
    """Ø12 @ 150, d = 174: Mcr = 0.62 √25 Ig / 100 = 20.67 kN·m/m; MD = 18.75 (uncracked),
    MD+L = 28.13 kN·m/m; Ie = (Mcr/Ma)³ Ig + (1 - (Mcr/Ma)³) Icr."""
    bottom = layer(12, 150)
    a_s = math.pi * 36 * 1000 / 150  # 754 mm²/m
    n = ES / EC
    _, icr = cracked(1000, bottom.d, n, a_s)
    mcr = 0.62 * math.sqrt(FC) * IG / (H / 2)
    assert mcr / 1e6 == pytest.approx(20.67, abs=0.01)

    def ie(m: float) -> float:
        if m <= mcr:
            return IG
        r = (mcr / m) ** 3
        return r * IG + (1 - r) * icr

    md, ml = WD * SPAN**2 / 8, WL * SPAN**2 / 8
    d_d, d_l = elastic(WD), elastic(WL)
    assert d_d == pytest.approx(3.117, abs=0.002)
    i_dead = d_d * IG / ie(md)
    i_total = (d_d + d_l) * IG / ie(md + ml)
    psi = 0.25
    i_sus = (d_d + psi * d_l) * IG / ie(md + psi * ml)
    data = one_way(bottom)
    with pack("bnbc2020"):
        result = ss.span_deflection(data.spans[0], data, ss.Inputs(sustained=psi, months=60))
    assert result.method == "effectiveInertia"
    assert i_dead == pytest.approx(d_d)  # MD < Mcr: uncracked
    assert result.immediate == pytest.approx(i_total, rel=1e-6)
    # Known answer: c = 41.3 mm, Icr = 1.364e8, (Mcr/Ma)³ = 0.397, Ie = 3.47e8 mm⁴/m.
    assert result.immediate == pytest.approx(8.99, abs=0.01)
    live = i_total - i_dead
    # λΔ = 2.0 / (1 + 0) for 5 years, no top bars.
    assert result.long_term == pytest.approx(2.0 * i_sus, rel=1e-6)
    assert result.after == pytest.approx(2.0 * i_sus + live, rel=1e-6)
    names = [c[0] for c in result.checks]
    assert names[0].startswith("Deflection: immediate, live load")
    assert result.checks[0][2] == pytest.approx(SPAN / 360)
    assert result.checks[1][2] == pytest.approx(SPAN / 480)


def test_long_term_multiplier_with_compression_bars() -> None:
    """Ø10 @ 200 top bars: ρ' = 392.7 / (1000 × 174) = 0.00226; 12 months: ξ = 1.4,
    λΔ = 1.4 / (1 + 50 ρ') = 1.258; the long-term part λΔ × the immediate sustained one
    (the compression bars in Icr by (n - 1) As')."""
    bottom, top = layer(12, 150), layer(10, 200)
    a_s = math.pi * 36 * 1000 / 150
    a_s2 = math.pi * 25 * 1000 / 200
    d2 = H - top.d  # the top bars' depth from the top face
    n = ES / EC
    _, icr = cracked(1000, bottom.d, n, a_s, a_s2, d2)
    rho_prime = a_s2 / (1000 * bottom.d)
    lam = 1.4 / (1 + 50 * rho_prime)
    assert lam == pytest.approx(1.258, abs=0.001)
    mcr = 0.62 * math.sqrt(FC) * IG / (H / 2)
    psi = 0.5
    m = (WD + psi * WL) * SPAN**2 / 8
    r = (mcr / m) ** 3
    ie = r * IG + (1 - r) * icr
    i_sus = (elastic(WD) + psi * elastic(WL)) * IG / ie
    data = one_way(bottom, top)
    with pack("bnbc2020"):
        result = ss.span_deflection(data.spans[0], data, ss.Inputs(sustained=psi, months=12))
    assert result.long_term == pytest.approx(lam * i_sus, rel=1e-4)


def test_eurocode_interpolation_and_creep() -> None:
    """ζ = 1 - 0.5 (Mcr/M)² under the quasi-permanent load with Ec,eff = Ec / (1 + 2.5)."""
    bottom = layer(12, 150)
    data = one_way(bottom, ec=31_000.0, fc=30.0)
    psi = 0.3
    with pack("eurocodes"):
        from saengine.design import design_strength

        fctm = design_strength.properties(30.0).fctm
        result = ss.span_deflection(data.spans[0], data, ss.Inputs(sustained=psi))
    assert fctm == pytest.approx(0.30 * 30 ** (2 / 3), rel=1e-3)
    ec_eff = 31_000.0 / 3.5
    n = ES / ec_eff
    _, icr = cracked(1000, bottom.d, n, math.pi * 36 * 1000 / 150)
    mcr = fctm * IG / (H / 2)
    m = (WD + psi * WL) * SPAN**2 / 8
    zeta = 1 - 0.5 * (mcr / m) ** 2 if m > mcr else 0.0
    ie = 1 / (zeta / icr + (1 - zeta) / IG)
    final = (elastic(WD) + psi * elastic(WL)) * EI / (ec_eff * ie)
    assert result.method == "interpolation"
    assert result.total == pytest.approx(final, rel=1e-6)
    assert result.checks[0][2] == pytest.approx(SPAN / 250)
    assert result.checks[1][2] == pytest.approx(SPAN / 500)


# ─────────────────────────────── crack widths ───────────────────────────────


def test_crack_width_en1992_by_hand() -> None:
    """EN 1992-1-1 7.3.4: Ø12 @ 125 (≤ 5 (c + φ/2) = 130 mm), c = 20, fck 30, M = 20 kN·m/m."""
    bottom = layer(12, 125)
    data = one_way(bottom, ec=EC, fc=30.0)
    m = 20e6
    with pack("eurocodes"):
        from saengine.design import design_strength

        p = design_strength.properties(30.0)
        found = ss.crack_width(data, "X", False, m, ss.Inputs(exposure="XC1"))
    a_s = math.pi * 36 * 1000 / 125
    ae = ES / p.ecm
    x, icr = cracked(1000, bottom.d, ae, a_s)
    sigma = ae * m * (bottom.d - x) / icr
    hc = min(2.5 * (H - bottom.d), (H - x) / 3, H / 2)
    rho = a_s / (1000 * hc)
    strain = max((sigma - 0.4 * p.fctm / rho * (1 + ae * rho)) / ES, 0.6 * sigma / ES)
    sr = 3.4 * COVER + 0.8 * 0.5 * 0.425 * 12 / rho
    assert found is not None and found.method == "directWidth"
    assert found.value == pytest.approx(sr * strain, rel=1e-6)
    assert found.limit == pytest.approx(0.4)  # XC1


def test_crack_width_is456_annex_f_by_hand() -> None:
    """IS 456 Annex F at the point midway between bars on the soffit: acr = √((s/2)² +
    (c + φ/2)²) - φ/2, cmin = c; εm = ε1 - b (h - x)² / (3 Es As (d - x))."""
    bottom = layer(12, 150)
    ec = 5000 * math.sqrt(FC)
    data = one_way(bottom, ec=ec)
    m = 25e6
    with pack("is-codes"):
        found = ss.crack_width(data, "X", False, m, ss.Inputs(exposure="moderate"))
    a_s = math.pi * 36 * 1000 / 150
    n = ES / ec
    x, icr = cracked(1000, bottom.d, n, a_s)
    fs = n * m * (bottom.d - x) / icr
    eps1 = fs / ES * (H - x) / (bottom.d - x)
    eps_m = eps1 - 1000 * (H - x) ** 2 / (3 * ES * a_s * (bottom.d - x))
    acr = math.hypot(75, COVER + 6) - 6
    w = 3 * acr * eps_m / (1 + 2 * (acr - COVER) / (H - x))
    assert found is not None and found.method == "strainSpacing"
    assert found.value == pytest.approx(w, rel=1e-6)
    assert found.limit == pytest.approx(0.3)


def test_crack_width_gb50010_by_hand() -> None:
    """GB 50010 7.1.2: ρte = As / (0.5 b h) >= 0.01, σs = Mq / (0.87 h0 As), ψ = 1.1 - 0.65 ftk /
    (ρte σs), wmax = 1.9 ψ σs/Es (1.9 cs + 0.08 deq/ρte)."""
    bottom = layer(12, 150)
    data = one_way(bottom, fc=30.0)
    mq = 15e6
    with pack("china-gb"):
        from saengine.design import design_strength

        ftk = design_strength.properties(30.0).fctk005
        found = ss.crack_width(data, "X", False, mq, ss.Inputs())
    a_s = math.pi * 36 * 1000 / 150
    rho_te = max(a_s / (0.5 * 1000 * H), 0.01)
    sigma = mq / (0.87 * bottom.d * a_s)
    psi = min(max(1.1 - 0.65 * ftk / (rho_te * sigma), 0.2), 1.0)
    cs = min(max(COVER, 20), 65)
    w = 1.9 * psi * sigma / ES * (1.9 * cs + 0.08 * 12 / rho_te)
    assert found is not None and found.method == "effectiveTensionRatio"
    assert found.value == pytest.approx(w, rel=1e-6)


def test_bar_spacing_at_service_stress_by_hand() -> None:
    """The default pack: s <= 380 (280/fs) - 2.5 cc and <= 300 (280/fs), fs of the cracked
    section under D + L (28.13 kN·m/m)."""
    bottom = layer(12, 150)
    data = one_way(bottom)
    m = (WD + WL) * SPAN**2 / 8
    with pack("bnbc2020"):
        found = ss.crack_width(data, "X", False, m, ss.Inputs())
    n = ES / EC
    x, icr = cracked(1000, bottom.d, n, math.pi * 36 * 1000 / 150)
    fs = n * m * (bottom.d - x) / icr
    allowed = min(380 * 280 / fs - 2.5 * COVER, 300 * 280 / fs)
    assert found is not None and found.method == "barSpacing"
    assert found.value == 150
    assert found.limit == pytest.approx(allowed, rel=1e-6)


def test_not_provided_and_round_trip() -> None:
    data = one_way(layer(12, 150), layer(10, 200))
    again = ss.SlabServiceData.from_dict(data.to_dict())
    assert again == data
    with pack("bnbc2020"):
        result = ss.evaluate(data, ss.Inputs())
    assert {c["name"] for c in result.checks} >= {
        "Deflection: immediate, live load (FE slab, cracked)",
        "Crack control: bar spacing at service (FE slab)",
    }
    assert result.to_json()["deflectionMethod"] == "effectiveInertia"
    with pack("bnbc2020"):
        none = ss.evaluate(data, ss.Inputs(), deflection=False)
    assert none.deflection_method is None and not none.spans


# ─────────────────────────────── collection from a mesh ───────────────────────────────


def test_collect_one_way_mesh() -> None:
    """A 5 × 2 m one-way slab on two walls (x = 0 and 5 m), 0.25 m shells, its moments and
    deflections those of a simply supported beam: the strip's mid-span moment wL²/8 and its
    deflection 5wL⁴/(384 EI) relative to the walls."""
    size, nx, ny = 0.25, 20, 8
    l_m = SPAN / 1e3

    def moment(x: float, w: float) -> float:  # N·m/m with w in kN/m² → N/m²
        return w * 1e3 * x * (l_m - x) / 2

    def sag(x: float, w: float) -> float:  # m
        ei = EI * 1e-6  # N·mm² per metre width → N·m² per metre
        return w * 1e3 * x * (l_m**3 - 2 * l_m * x**2 + x**3) / (24 * ei)

    coords: dict[int, np.ndarray] = {}
    node = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            k = len(coords) + 1
            node[i, j] = k
            coords[k] = np.array([i * size, j * size, 3.0])
    shells, nodes_of = [], {}
    for i in range(nx):
        for j in range(ny):
            ids = [node[i, j], node[i + 1, j], node[i + 1, j + 1], node[i, j + 1]]
            sid = len(shells) + 1
            nodes_of[sid] = ids
            pts = slab_design.integration_points([coords[n] for n in ids], 4)
            forces = [
                np.array([[moment(p[0], w), 0.0, 0.0, 0.0, 0.0] for p in pts]) for w in (WD, WL)
            ]
            shells.append(
                slab_design.ShellPoint(
                    sid, f"S1#{sid}", pts, forces, slab_design.integration_areas(
                        [coords[n] for n in ids], 4
                    )
                )
            )  # fmt: skip
    displacement = {
        case: {k: np.array([0, 0, -sag(c[0], w), 0, 0, 0]) for k, c in coords.items()}
        for case, w in (("D", WD), ("L", WL))
    }
    walls = [
        slab_design.LineSupport("W1", (0.0, 0.0), (0.0, 2000.0), 200.0, "wall"),
        slab_design.LineSupport("W2", (5000.0, 0.0), (5000.0, 2000.0), 200.0, "wall"),
    ]
    context = slab_design.SlabContext(
        boundary=[(0, 0), (5000, 0), (5000, 2000), (0, 2000)], supports=walls
    )
    frame = slab_design.PlanFrame(context.axes)
    layout = slab_design.design_strips("X", frame, (0, 5000, 0, 2000), [], walls, 250.0)
    context.strips = layout.strips
    data = ss.collect(
        "S1", context, shells, nodes_of, coords, displacement, H, FC, FY, ES, EC, EI,
        {"bottomX": slab_design.Layer("bottomX", 12, 150, 174), "bottomY": None,
         "topX": None, "topY": None},
        False,
    )  # fmt: skip
    assert data.spans
    span = data.spans[0]
    assert span.span == pytest.approx(SPAN)
    assert not span.cantilever
    # The bay runs between the walls' faces; mid-span is at its middle.
    assert span.mid[0] == pytest.approx(WD * SPAN**2 / 8, rel=0.02)
    assert span.delta[0] == pytest.approx(elastic(WD), rel=0.02)
    assert span.delta[1] == pytest.approx(elastic(WL), rel=0.02)
    assert len(data.shells) == nx * ny


# ─────────────────────────────── a design run, end to end ───────────────────────────────


def test_design_run_and_ribbon_features(tmp_path) -> None:
    """A one-way slab on deep beams analysed as shells (test_design_slab's): the design report
    holds the cracked deflection and crack widths of its strips, the governing rows join its
    checks, and the ribbon's features work them again from the saved report."""
    import json

    from test_design_slab import analyse, generate, narrow_plan, objects, planar, shell_settings

    from saengine import features

    slab = {"thickness": 150, "system": "oneWay", "reinforcement": planar().model_dump(mode="json")}
    report = analyse(
        tmp_path, generate(narrow_plan(), "s"), objects(slab, beam_depth=1000),
        shell_settings("One way"),
    )  # fmt: skip
    entry = next(e for e in report["elements"] if e["id"] == "S1")
    service = entry["service"]
    assert service["deflectionMethod"] == "effectiveInertia"
    assert service["crackMethod"] == "barSpacing"
    spans = service["spans"]
    assert spans and all(s["total"] >= s["immediate"] >= 0 for s in spans)
    # The slab spans along Y (2.5 m): its deflection is small and positive.
    assert 0 < max(s["total"] for s in spans) < 25
    assert service["deflection"] and set(service["deflection"]) <= {
        str(m) for m in entry["members"]
    }
    names = {c["name"] for c in entry["checks"]}
    assert "Deflection: after attachment of nonstructural elements (FE slab, cracked)" in names
    # The ribbon's features from the saved report.
    out = tmp_path / "08 FEM" / "model.results" / "design-report.json"
    out.write_text(json.dumps(report), encoding="utf-8")
    shown = features.run("design.crackedDeflection", str(tmp_path), {"sustained": 0.5})
    assert shown["tables"][0]["rows"], shown
    cracks = features.run("design.crackWidths", str(tmp_path), {})
    assert cracks["summary"]["stations"] > 0, cracks


def test_report_section_lists_governing_bays() -> None:
    """The design report's slab section: each slab's governing bays and crack check."""
    from saengine.report.build import _slab_service

    data = one_way(layer(12, 150))
    with pack("bnbc2020"):
        found = ss.evaluate(data, ss.Inputs())
    element = {
        "id": "S1",
        "kind": "slab",
        "service": {"inputs": {"sustained": 0.25}, **found.to_json()},
    }
    section = _slab_service({"elements": [element]})
    assert [r[0] for r in section["rows"]] == ["S1", "S1"]
    assert section["rows"][0][6].startswith("Deflection:")
    assert section["rows"][1][6] == "Bar spacing at service"
    assert section["methods"]["quantity"] == "stress"
