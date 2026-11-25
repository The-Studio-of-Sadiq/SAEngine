"""Independent known-answer tests for FEM CFD Turbulence, Connections, and Time Series calculators."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── CFD Turbulence (fem_cfd_turbulence.py: 20) ───────────────────────────────────────────────────


def test_fem_cfd_turbulence_blend_factor() -> None:
    # Menter SST F2: arg2 = max(2*sqrt(k)/(0.09*omega*d), 500*nu/(d^2*omega)), nu = 1.5e-5 m2/s
    # term1 = 2 * sqrt(0.81) / (0.09 * 10 * 2.0) = 1.8 / 1.8 = 1.0
    # term2 = 500 * 1.5e-5 / (4.0 * 10) = 0.0001875 -> arg2 = 1.0
    # F2 = tanh(1.0^2) = 0.761594
    res = features.run(
        "femCfdTurbulence.blendFactor",
        None,
        {"wallDistM": 2.0, "kM2s2": 0.81, "omega1s": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["arg2"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["f2Blend"] == pytest.approx(0.761594, rel=0.01)


def test_fem_cfd_turbulence_boundary_layers() -> None:
    # Geometric prism growth with r = 1.2, dy1 = 5 mm = 0.005 m, n = 5 layers:
    # H = 0.005 * (1.2^5 - 1) / (1.2 - 1) = 0.005 * 1.48832 / 0.2 = 0.037208 m
    # Coverage = 100 * 0.037208 / 0.5 = 7.4416%
    res = features.run(
        "femCfdTurbulence.boundaryLayers",
        None,
        {"delta99M": 0.5, "firstCellMm": 5.0, "nLayers": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["prismHeightM"] == pytest.approx(0.037208, rel=0.01)
    assert res["summary"]["coveragePercent"] == pytest.approx(7.4416, rel=0.01)


def test_fem_cfd_turbulence_curvature_correction() -> None:
    # r* = S / Omega = 10 / 15 = 0.66667
    # fr1 = min(1.25, 2 * r* / (1 + r*)) = 2 * (2/3) / (5/3) = 4/5 = 0.80
    res = features.run(
        "femCfdTurbulence.curvatureCorrection",
        None,
        {"strainRate1s": 10.0, "vorticity1s": 15.0, "enabled": True},
    )
    assert res["problems"] == []
    assert res["summary"]["strainOverVorticity"] == pytest.approx(0.66667, rel=0.01)
    assert res["summary"]["fr1Multiplier"] == pytest.approx(0.80, rel=0.01)


def test_fem_cfd_turbulence_des_detached() -> None:
    # l_LES = C_DES * Delta_max = 0.65 * 0.8 = 0.52 m < l_RANS = 1.5 m -> l_DES = 0.52 m (LES)
    res = features.run(
        "femCfdTurbulence.desDetached",
        None,
        {"lRansM": 1.5, "maxCellM": 0.8, "cDes": 0.65},
    )
    assert res["problems"] == []
    assert res["summary"]["lDesM"] == pytest.approx(0.52, rel=0.01)
    assert res["summary"]["activeMode"] == "LES Mode (Wake)"


def test_fem_cfd_turbulence_dissipation_rate() -> None:
    # nu_t = 1000 * 1.5e-5 = 0.015 m2/s
    # eps = 0.09 * 3.0^2 / 0.015 = 54.0 m2/s3; omega = 3.0 / 0.015 = 200.0 1/s
    res = features.run(
        "femCfdTurbulence.dissipationRate",
        None,
        {"kM2s2": 3.0, "eddyViscosityRatio": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nuTM2s"] == pytest.approx(0.015, rel=0.01)
    assert res["summary"]["epsilonM2s3"] == pytest.approx(54.0, rel=0.01)
    assert res["summary"]["omega1s"] == pytest.approx(200.0, rel=0.01)


def test_fem_cfd_turbulence_filter_width() -> None:
    # Delta_vol = (0.5 * 1.0 * 2.0)^(1/3) = 1.0 m; Delta_max = 2.0 m; aspect = 2.0 / 0.5 = 4.0
    res = features.run(
        "femCfdTurbulence.filterWidth",
        None,
        {"dxM": 0.5, "dyM": 1.0, "dzM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["cubeRootFilterM"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["maxEdgeFilterM"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["aspectRatio"] == pytest.approx(4.0, rel=0.01)


def test_fem_cfd_turbulence_gust_profile() -> None:
    # k = 0.5 * (4^2 + 3^2 + 2^2) = 0.5 * (16 + 9 + 4) = 14.5 m2/s2
    res = features.run(
        "femCfdTurbulence.gustProfile",
        None,
        {"sigmaUMs": 4.0, "sigmaVMs": 3.0, "sigmaWMs": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["kAnisotropicM2s2"] == pytest.approx(14.5, rel=0.01)


def test_fem_cfd_turbulence_inlet_profile() -> None:
    # Richards-Hoxey ABL (kappa=0.41, Cmu=0.09) at H=20 m, z0=0.1 m, Uref=20 m/s:
    # u* = 0.41 * 20 / ln(20.1 / 0.1) = 8.2 / 5.303305 = 1.5462 m/s
    # k = 1.5462^2 / 0.3 = 7.9692 m2/s2
    # eps = 1.5462^3 / (0.41 * 20.1) = 0.4486 m2/s3
    # omega = eps / (0.09 * k) = 0.6254 1/s
    res = features.run(
        "femCfdTurbulence.inletProfile",
        None,
        {"z0M": 0.1, "heightM": 20.0, "uRefMs": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ustar"] == pytest.approx(1.5462, rel=0.01)
    assert res["summary"]["k"] == pytest.approx(7.9692, rel=0.01)
    assert res["summary"]["epsilon"] == pytest.approx(0.4486, rel=0.01)
    assert res["summary"]["omega"] == pytest.approx(0.6254, rel=0.01)


def test_fem_cfd_turbulence_kinetic_energy() -> None:
    # k_eq = u*^2 / sqrt(0.09) = 1.5^2 / 0.3 = 2.25 / 0.3 = 7.5 m2/s2
    res = features.run(
        "femCfdTurbulence.kineticEnergy",
        None,
        {"z0M": 0.1, "ustarMs": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["equilibriumKM2s2"] == pytest.approx(7.5, rel=0.01)


def test_fem_cfd_turbulence_length_scale() -> None:
    # l_mix = 0.41 * (19.9 + 0.1) = 8.2 m
    # eps = 0.09^0.75 * 4.0^1.5 / 8.2 = 0.164317 * 8.0 / 8.2 = 0.16031 m2/s3
    # omega = sqrt(4.0) / (0.09^0.25 * 8.2) = 2.0 / (0.547723 * 8.2) = 0.44530 1/s
    res = features.run(
        "femCfdTurbulence.lengthScale",
        None,
        {"heightM": 19.9, "z0M": 0.1, "kM2s2": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["mixingLengthM"] == pytest.approx(8.2, rel=0.01)
    assert res["summary"]["epsilonM2s3"] == pytest.approx(0.16031, rel=0.01)
    assert res["summary"]["omega1s"] == pytest.approx(0.44530, rel=0.01)


def test_fem_cfd_turbulence_les_setup() -> None:
    # Smagorinsky Cs = 0.168; Nyquist cutoff wavenumber kappa_c = pi / 0.5 = 6.28319 1/m
    res = features.run(
        "femCfdTurbulence.lesSetup",
        None,
        {"sgsModel": "Smagorinsky", "cellSizeM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["sgsModel"] == "Smagorinsky"
    assert res["summary"]["modelConstant"] == pytest.approx(0.168, rel=0.01)
    assert res["summary"]["cutoffWavenumber"] == pytest.approx(6.28319, rel=0.01)


def test_fem_cfd_turbulence_production_limiter() -> None:
    # Menter SST cap = 10 * 0.09 * k * omega = 0.9 * 4.0 * 20.0 = 72.0 m2/s3
    # rawPk = 100.0 > 72.0 -> appliedPk = 72.0
    res = features.run(
        "femCfdTurbulence.productionLimiter",
        None,
        {"kM2s2": 4.0, "omega1s": 20.0, "rawPk": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["capPk"] == pytest.approx(72.0, rel=0.01)
    assert res["summary"]["appliedPk"] == pytest.approx(72.0, rel=0.01)


def test_fem_cfd_turbulence_realizability_constraint() -> None:
    # T_std = k / eps = 6.0 / 2.0 = 3.0 s
    # T_cap = 1 / (sqrt(6) * 0.09 * 10.0) = 1 / 2.20454 = 0.45361 s < 3.0 s -> capped
    res = features.run(
        "femCfdTurbulence.realizabilityConstraint",
        None,
        {"kM2s2": 6.0, "strainRate1s": 10.0, "epsilonM2s3": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["boundedTimeScaleS"] == pytest.approx(0.45361, rel=0.01)
    assert res["summary"]["isCapped"] is True


def test_fem_cfd_turbulence_thermal_transport() -> None:
    # Ri_b = (9.81 * (6.0 / 298.15) * 40.0) / 4.0^2 = 7.89670 / 16.0 = 0.49354 -> Mixed convection
    res = features.run(
        "femCfdTurbulence.thermalTransport",
        None,
        {"prandtlTurb": 0.9, "deltaTC": 6.0, "heightScaleM": 40.0, "windSpeedMs": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["bulkRichardson"] == pytest.approx(0.49354, rel=0.01)
    assert res["summary"]["regime"] == "Mixed convection"


def test_fem_cfd_turbulence_transition_model() -> None:
    # Langtry-Menter correlation for Tu = 4.0% (> 1.3%):
    # Re_theta_c = 331.5 / (4.0 - 0.5658)^0.671 = 331.5 / 2.28844 = 144.8587
    res = features.run(
        "femCfdTurbulence.transitionModel",
        None,
        {"turbulenceIntensityPct": 4.0, "reynoldsNumber": 2.0e6},
    )
    assert res["problems"] == []
    assert res["summary"]["reThetaCrit"] == pytest.approx(144.8587, rel=0.01)
    assert res["summary"]["tuPercent"] == pytest.approx(4.0, rel=0.01)


def test_fem_cfd_turbulence_turbulence_intensity() -> None:
    # k = 1.5 * (20.0 * 0.10)^2 = 1.5 * 4.0 = 6.0 m2/s2
    res = features.run(
        "femCfdTurbulence.turbulenceIntensity",
        None,
        {"uMeanMs": 20.0, "intensityPct": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["kM2s2"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["intensityPct"] == pytest.approx(10.0, rel=0.01)


def test_fem_cfd_turbulence_viscosity_ratio() -> None:
    # nu_t = 0.09 * 3.0^2 / 0.5 = 1.62 m2/s; nu_t / nu = 1.62 / 1.5e-5 = 108,000
    res = features.run(
        "femCfdTurbulence.viscosityRatio",
        None,
        {"kM2s2": 3.0, "epsilonM2s3": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["eddyViscosityM2s"] == pytest.approx(1.62, rel=0.01)
    assert res["summary"]["viscosityRatio"] == pytest.approx(108000.0, rel=0.01)


def test_fem_cfd_turbulence_wall_function() -> None:
    # Smooth building facade with low-Re y+ = 2.0 (< 5) selects nutLowReWallFunction.
    res = features.run(
        "femCfdTurbulence.wallFunction",
        None,
        {"surface": "building", "yPlus": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["patch"] == "building"
    assert res["summary"]["nutBC"] == "nutLowReWallFunction"


def test_fem_cfd_turbulence_wall_roughness() -> None:
    # Blocken consistency: ks = 9.793 * 0.1 / 0.5 = 1.9586 m; zp = 0.5 * 4.0 = 2.0 m >= ks -> True
    res = features.run(
        "femCfdTurbulence.wallRoughness",
        None,
        {"z0M": 0.1, "firstCellHeightM": 4.0, "cs": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["ksM"] == pytest.approx(1.9586, rel=0.01)
    assert res["summary"]["zpM"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["passesBlockenCheck"] is True


def test_fem_cfd_turbulence_y_plus_target() -> None:
    # zp = y+ * nu / u_tau = 40 * 1.5e-5 / 1.2 = 0.0005 m -> dy1 = 2 * zp * 1000 = 1.0 mm
    res = features.run(
        "femCfdTurbulence.yPlusTarget",
        None,
        {"targetYPlus": 40.0, "uTauMs": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredFirstLayerMm"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["targetYPlus"] == pytest.approx(40.0, rel=0.01)


# ── Design Connections (fem_design_connections.py: 20) ───────────────────────────────────────────


def test_fem_design_connections_anchor_bolt() -> None:
    # Default fc = 28 MPa; hef = 250 mm, da = 24 mm:
    # Concrete breakout: phi*Ncb = 0.70 * 10 * sqrt(28) * 250^1.5 / 1000 = 146.4155 kN
    # Steel tension: phi*Nsa = 0.75 * 580 * (0.75 * pi * 24^2 / 4) / 1000 = 147.5920 kN
    # Governing = 146.4155 kN -> DCR = 80.0 / 146.4155 = 0.5464
    res = features.run(
        "femDesignConnections.anchorBolt",
        None,
        {"tensionDemandKn": 80.0, "embedmentMm": 250.0, "boltDiameterMm": 24.0},
    )
    assert res["problems"] == []
    assert res["summary"]["breakoutCapKn"] == pytest.approx(146.4155, rel=0.01)
    assert res["summary"]["steelCapKn"] == pytest.approx(147.5920, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.5464, rel=0.01)


def test_fem_design_connections_base_plate() -> None:
    # Default fc = 28 MPa, fy = 250 MPa; A1 = 500 * 400 = 200,000 mm2, ratio = 1.6 (< 2.0):
    # Pp = 0.85 * 28 * 200,000 * 1.6 / 1000 = 7616.0 kN; phi*Pp = 0.65 * 7616.0 = 4950.4 kN
    # DCR = 1200 / 4950.4 = 0.2424
    # q = 1,200,000 / 200,000 = 6.0 MPa; m = 0.25 * 500 = 125 mm
    # t_req = 125 * sqrt(2 * 6.0 / (0.9 * 250)) = 125 * 0.23094 = 28.8675 mm
    res = features.run(
        "femDesignConnections.basePlate",
        None,
        {
            "axialKn": 1200.0,
            "plateLengthMm": 500.0,
            "plateWidthMm": 400.0,
            "pedestalAreaRatio": 1.6,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["bearingCapacityKn"] == pytest.approx(4950.4, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.2424, rel=0.01)
    assert res["summary"]["requiredThicknessMm"] == pytest.approx(28.8675, rel=0.01)


def test_fem_design_connections_bolt_check() -> None:
    # Default pack A325N (threads included): Fnv = 330 MPa, Fnt = 620 MPa, phi = 0.75, d = 24 mm:
    # Ab = pi * 24^2 / 4 = 452.3893 mm2
    # phi*Rv = 0.75 * 330 * 452.3893 / 1000 = 111.9664 kN; rv = 60 / 111.9664 = 0.53588
    # phi*Rt = 0.75 * 620 * 452.3893 / 1000 = 210.3610 kN; rt = 80 / 210.3610 = 0.38030
    # Elliptical interaction = 0.53588^2 + 0.38030^2 = 0.43179 <= 1.0
    res = features.run(
        "femDesignConnections.boltCheck",
        None,
        {"grade": "A325", "diameterMm": 24.0, "shearDemandKn": 60.0, "tensionDemandKn": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["boltShearCapKn"] == pytest.approx(111.9664, rel=0.01)
    assert res["summary"]["boltTensionCapKn"] == pytest.approx(210.3610, rel=0.01)
    assert res["summary"]["interactionRatio"] == pytest.approx(0.43179, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_cyclic_loading() -> None:
    # Loop energy = 4 * Mp * theta_p * 0.85 = 4 * 300 * 0.05 * 0.85 = 51.0 kJ; 0.05 >= 0.04 -> True
    res = features.run(
        "femDesignConnections.cyclicLoading",
        None,
        {"peakMomentKnm": 300.0, "plasticRotationRad": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["energyPerCycleKj"] == pytest.approx(51.0, rel=0.01)
    assert res["summary"]["meetsSpecialFrame4Pct"] is True


def test_fem_design_connections_dowelled_joint() -> None:
    # Johansen timber embedment: f_h,k = 0.082 * (1 - 0.01 * 20) * 400 = 26.24 MPa
    # M_y,k = 0.3 * 500 * 20^2.6 = 362,050.58 N·mm
    # R_k = min(26.24 * 100 * 20, sqrt(2 * 362050.58 * 26.24 * 20)) / 1000
    #     = min(52.48, 19.4938) = 19.4938 kN
    res = features.run(
        "femDesignConnections.dowelledJoint",
        None,
        {"dowelDiaMm": 20.0, "memberThicknessMm": 100.0, "timberDensityKgM3": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["embedmentStrengthMpa"] == pytest.approx(26.24, rel=0.01)
    assert res["summary"]["dowelShearCapacityKn"] == pytest.approx(19.4938, rel=0.01)


def test_fem_design_connections_edge_distance() -> None:
    # Default pack rolled edge Table 6.10.12 for M24: minEdge = 30.0 mm
    # Max edge = min(12 * 12, 150) = 144.0 mm; provided = 40.0 mm in [30, 144] -> True
    res = features.run(
        "femDesignConnections.edgeDistance",
        None,
        {"boltDiameterMm": 24.0, "plateThicknessMm": 12.0, "providedEdgeMm": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minEdgeMm"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["maxEdgeMm"] == pytest.approx(144.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_embed_plate() -> None:
    # Default fc = 28 MPa, Ec = 4700 * sqrt(28) = 24,870.06 MPa; d = 20 mm -> Asa = pi * 100 = 314.1593 mm2
    # Concrete term = 0.5 * 314.1593 * sqrt(28 * 24870.06) / 1000 = 131.0803 kN
    # Steel term = 314.1593 * 450 / 1000 = 141.3717 kN -> Qn = 131.0803 kN
    # Total phi*Vn = 0.75 * 6 * 131.0803 = 589.8612 kN; DCR = 120 / 589.8612 = 0.2034
    res = features.run(
        "femDesignConnections.embedPlate",
        None,
        {"shearKn": 120.0, "studs": 6, "studDiameterMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalCapacityKn"] == pytest.approx(589.8612, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.2034, rel=0.01)


def test_fem_design_connections_fatigue_check() -> None:
    # N_allow = 2,000,000 * (80 / 100)^3 = 2,000,000 * 0.512 = 1,024,000 cycles
    # Miner damage D = 500,000 / 1,024,000 = 0.48828 <= 1.0 -> passes
    res = features.run(
        "femDesignConnections.fatigueCheck",
        None,
        {"stressRangeMpa": 100.0, "cycles": 500000.0, "detailCategoryMpa": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["allowableCycles"] == pytest.approx(1024000.0, rel=0.01)
    assert res["summary"]["minerDamage"] == pytest.approx(0.48828, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_glued_splice() -> None:
    # Bond area = pi * 20 * 300 = 18,849.5559 mm2; F_ax,Rk = 18849.5559 * 5.0 / 1000 = 94.2478 kN
    res = features.run(
        "femDesignConnections.gluedSplice",
        None,
        {"bondLengthMm": 300.0, "rodDiameterMm": 20.0, "bondStrengthMpa": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["bondAreaMm2"] == pytest.approx(18849.5559, rel=0.01)
    assert res["summary"]["charPulloutKn"] == pytest.approx(94.2478, rel=0.01)


def test_fem_design_connections_hole_layout() -> None:
    # Default pack M24: min_edge = 30.0 mm, min_spacing = 2.6667 * 24 = 64.0008 mm <= pitch 80 mm
    # Plate H = 2 * 30 + (5 - 1) * 80 = 380.0 mm; Plate W = 2 * 30 + (3 - 1) * 80 = 220.0 mm
    res = features.run(
        "femDesignConnections.holeLayout",
        None,
        {"boltDiameterMm": 24.0, "rows": 5, "columns": 3, "pitchMm": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minPlateHeightMm"] == pytest.approx(380.0, rel=0.01)
    assert res["summary"]["minPlateWidthMm"] == pytest.approx(220.0, rel=0.01)
    assert res["summary"]["spacingOk"] is True


def test_fem_design_connections_joint_stiffness() -> None:
    # EI / L = 30,000 / 5.0 = 6000 kN·m; Sj / (EI/L) = 60,000 / 6000 = 10.0 >= 8.0 (braced) -> Rigid
    res = features.run(
        "femDesignConnections.jointStiffness",
        None,
        {"sjInitialKnmRad": 60000.0, "beamEI": 30000.0, "beamSpanM": 5.0, "bracedFrame": True},
    )
    assert res["problems"] == []
    assert res["summary"]["normalizedStiffness"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["classification"] == "Rigid"


def test_fem_design_connections_moment_connection() -> None:
    # Default fy = 250 MPa; lever = (480 + 20) / 1000 = 0.50 m -> Puf = 250 / 0.50 = 500.0 kN
    # Ag = 220 * 20 = 4400 mm2 -> phi*Tn = 0.90 * 250 * 4400 / 1000 = 990.0 kN
    # DCR = 500 / 990 = 0.50505 <= 1.0
    res = features.run(
        "femDesignConnections.momentConnection",
        None,
        {"momentKnm": 250.0, "beamDepthMm": 480.0, "plateThicknessMm": 20.0, "plateWidthMm": 220.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flangeForceKn"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["plateCapacityKn"] == pytest.approx(990.0, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.50505, rel=0.01)
    assert res["summary"]["ok"] is True


def test_fem_design_connections_plate_bearing() -> None:
    # Default Fu = 410 MPa, phi = 0.75; d = 24, t = 12, lc = 30:
    # Tear-out 1.2 * lc * t * Fu = 1.2 * 30 * 12 * 410 = 177.12 kN
    # Bearing 2.4 * d * t * Fu = 2.4 * 24 * 12 * 410 = 283.392 kN -> Rn = 177.12 kN
    # phi*Rn = 0.75 * 177.12 = 132.84 kN; DCR = 80 / 132.84 = 0.60223
    res = features.run(
        "femDesignConnections.plateBearing",
        None,
        {
            "boltDiameterMm": 24.0,
            "plateThicknessMm": 12.0,
            "clearEdgeMm": 30.0,
            "boltShearKn": 80.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["bearingCapacityKn"] == pytest.approx(132.84, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.60223, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_rebar_development() -> None:
    # Default pack (BNBC 2020) hooked development: fc = 28 MPa, fy = 420 MPa, db = 25 mm:
    # ldh = max(0.24 * 420 * 25 / sqrt(28), 8 * 25, 150) = max(476.2352, 200, 150) = 476.2352 mm
    # Available = 600 - 50 = 550.0 mm >= 476.2352 mm -> passes True
    res = features.run(
        "femDesignConnections.rebarDevelopment",
        None,
        {"barDiameterMm": 25.0, "availableDepthMm": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredHookMm"] == pytest.approx(476.2352, rel=0.01)
    assert res["summary"]["availableMm"] == pytest.approx(550.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_shear_connection() -> None:
    # Default pack Grade 10.9 (A490N): Fnv = 414 MPa, phi = 0.75, d = 24 mm, 6 bolts:
    # Per bolt = 0.75 * 414 * (pi * 24^2 / 4) / 1000 = 140.4669 kN
    # Group = 6 * 140.4669 = 842.8013 kN; DCR = 240 / 842.8013 = 0.28476
    res = features.run(
        "femDesignConnections.shearConnection",
        None,
        {"shearKn": 240.0, "bolts": 6, "boltDiameterMm": 24.0, "boltGrade": "10.9"},
    )
    assert res["problems"] == []
    assert res["summary"]["groupCapacityKn"] == pytest.approx(842.8013, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.28476, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_shear_key() -> None:
    # Default fc = 28 MPa; interface shear cap = 0.75 * min(0.20 * 28, 5.5) * 40,000 / 1000
    # = 0.75 * 5.5 * 40 = 165.0 kN; DCR = 150 / 165 = 0.90909 <= 1.0
    res = features.run(
        "femDesignConnections.shearKey",
        None,
        {"shearKn": 150.0, "keyAreaMm2": 40000.0, "muFriction": 0.6},
    )
    assert res["problems"] == []
    assert res["summary"]["shearKeyCapacityKn"] == pytest.approx(165.0, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.90909, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_splice_connection() -> None:
    # Default fy = 250 MPa; lever = 415 - 15 = 400 mm:
    # P_flange = 500 * 0.4 + 120 * 1000 / 400 = 200 + 300 = 500.0 kN
    # Cap = 0.90 * 250 * 3000 / 1000 = 675.0 kN; DCR = 500 / 675 = 0.74074
    res = features.run(
        "femDesignConnections.spliceConnection",
        None,
        {
            "axialKn": 500.0,
            "momentKnm": 120.0,
            "sectionDepthMm": 415.0,
            "flangePlateAreaMm2": 3000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["flangeDemandKn"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["plateCapacityKn"] == pytest.approx(675.0, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.74074, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_connections_stiffener_design() -> None:
    # Default fy = 250 MPa; excess = 900 - 360 = 540.0 kN
    # A_req = 540,000 / (0.90 * 250) = 2400 mm2; t_req = 2400 / (2 * 80) = 15.0 mm (> 10 mm min)
    res = features.run(
        "femDesignConnections.stiffenerDesign",
        None,
        {"flangeForceKn": 900.0, "columnWebCapKn": 360.0, "stiffenerWidthMm": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stiffenersRequired"] is True
    assert res["summary"]["excessForceKn"] == pytest.approx(540.0, rel=0.01)
    assert res["summary"]["minThicknessMm"] == pytest.approx(15.0, rel=0.01)


def test_fem_design_connections_toothed_plate() -> None:
    # Rk = 18 * 64^1.5 * (350 / 350) / 1000 = 18 * 512 / 1000 = 9.216 kN
    res = features.run(
        "femDesignConnections.toothedPlate",
        None,
        {"plateDiameterMm": 64.0, "timberDensityKgM3": 350.0},
    )
    assert res["problems"] == []
    assert res["summary"]["connectorCapacityKn"] == pytest.approx(9.216, rel=0.01)


def test_fem_design_connections_weld_check() -> None:
    # phi*Rn/mm = 0.75 * 0.6 * 500 * 0.707 * 8 / 1000 = 1.2726 kN/mm
    # Total = 1.2726 * 200 = 254.52 kN; DCR = 200 / 254.52 = 0.78579
    res = features.run(
        "femDesignConnections.weldCheck",
        None,
        {
            "legSizeMm": 8.0,
            "electrodeFexxMpa": 500.0,
            "weldLengthMm": 200.0,
            "appliedForceKn": 200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["capacityKnPerMm"] == pytest.approx(1.2726, rel=0.01)
    assert res["summary"]["totalCapacityKn"] == pytest.approx(254.52, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.78579, rel=0.01)
    assert res["summary"]["passes"] is True


# ── Charts Time Series (fem_charts_time_series.py: 16) ───────────────────────────────────────────


def test_fem_charts_time_series_baseline_correct() -> None:
    # Pure constant acceleration bias a(t) = 0.25 g has quadratic displacement drift 0.125*t^2.
    # Order-2 polynomial baseline removal removes the entire constant bias -> correctedMean = 0.0.
    series = ", ".join(["0.25"] * 20)
    res = features.run(
        "femChartsTimeSeries.baselineCorrect",
        None,
        {"series": series, "dtS": 0.05, "polyOrder": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["rawMean"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["correctedMean"] == pytest.approx(0.0, abs=1e-4)


def test_fem_charts_time_series_coherence_plot() -> None:
    # Two-tone signal x(t) and noiseless scaled copy y(t) = 2.5 * x(t):
    # Linear noiseless relation has magnitude-squared coherence gamma^2(f) = 1.0 at active bins.
    x = [
        round(
            3.0 * math.cos(2.0 * math.pi * 2 * n / 16) + 5.0 * math.cos(2.0 * math.pi * 6 * n / 16),
            8,
        )
        for n in range(16)
    ]
    y = [round(2.5 * v, 8) for v in x]
    res = features.run(
        "femChartsTimeSeries.coherencePlot",
        None,
        {
            "seriesA": ", ".join(str(v) for v in x),
            "seriesB": ", ".join(str(v) for v in y),
            "dtS": 0.05,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["peakCoherence"] == pytest.approx(1.0, rel=0.01)


def test_fem_charts_time_series_cursor_read() -> None:
    # Linear ramp y(t) = 2.0 + 5.0*t sampled every dt = 0.1 s:
    # At t* = 0.25 s: y(0.25) = 2.0 + 5.0 * 0.25 = 3.25; slope dy/dt = 5.0 /s.
    res = features.run(
        "femChartsTimeSeries.cursorRead",
        None,
        {"series": "2.0, 2.5, 3.0, 3.5, 4.0, 4.5", "dtS": 0.1, "cursorTimeS": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["interpolatedValue"] == pytest.approx(3.25, rel=0.01)
    assert res["summary"]["slopePerS"] == pytest.approx(5.0, rel=0.01)


def test_fem_charts_time_series_damping_fit() -> None:
    # Rayleigh C = alpha*M + beta*K at f1 = 1 Hz (w1 = 2*pi, z1 = 0.04) and f2 = 4 Hz (w2 = 8*pi, z2 = 0.06):
    # beta = 2 * (0.06*8*pi - 0.04*2*pi) / (64*pi^2 - 4*pi^2) = 0.8 / (60*pi) = 0.004244
    # alpha = 2 * 2*pi * 0.04 - 0.004244 * 4*pi^2 = 0.33510
    res = features.run(
        "femChartsTimeSeries.dampingFit",
        None,
        {"freq1Hz": 1.0, "freq2Hz": 4.0, "damping1": 0.04, "damping2": 0.06},
    )
    assert res["problems"] == []
    assert res["summary"]["massAlpha"] == pytest.approx(0.33510, rel=0.01)
    assert res["summary"]["stiffnessBeta"] == pytest.approx(0.004244, rel=0.02)


def test_fem_charts_time_series_difference_plot() -> None:
    # A - B = [3, 4, 3, 4] -> maxAbsDiff = 4.0, RMSE = sqrt((9+16+9+16)/4) = sqrt(12.5) = 3.53553
    res = features.run(
        "femChartsTimeSeries.differencePlot",
        None,
        {"seriesA": "4.0, 6.0, 8.0, 10.0", "seriesB": "1.0, 2.0, 5.0, 6.0", "dtS": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["samples"] == 4
    assert res["summary"]["maxAbsDiff"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["rmse"] == pytest.approx(3.53553, rel=0.01)


def test_fem_charts_time_series_fft_spectrum() -> None:
    # Pure cosine 4.0 * cos(2*pi*2.5*t) over N = 16 samples at dt = 0.05 s (exact 2 cycles):
    # dominantFreqHz = 2.5 Hz, single-sided amplitude = 4.0.
    sig = ", ".join(str(round(4.0 * math.cos(2.0 * math.pi * 2 * n / 16), 8)) for n in range(16))
    res = features.run("femChartsTimeSeries.fftSpectrum", None, {"series": sig, "dtS": 0.05})
    assert res["problems"] == []
    assert res["summary"]["dominantFreqHz"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["peakAmplitude"] == pytest.approx(4.0, rel=0.01)


def test_fem_charts_time_series_filter_signal() -> None:
    # x(t) = 3.0*cos(2*pi*2.5*t) + 5.0*cos(2*pi*7.5*t) (N=16, dt=0.05 s) -> rawPeak = 3 + 5 = 8.0.
    # Ideal low-pass at 5.0 Hz removes 7.5 Hz tone -> filteredPeak = 3.0.
    sig = ", ".join(
        str(
            round(
                3.0 * math.cos(2.0 * math.pi * 2 * n / 16)
                + 5.0 * math.cos(2.0 * math.pi * 6 * n / 16),
                8,
            )
        )
        for n in range(16)
    )
    res = features.run(
        "femChartsTimeSeries.filterSignal",
        None,
        {"series": sig, "dtS": 0.05, "band": "lowpass", "cutoffHz": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["rawPeak"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["filteredPeak"] == pytest.approx(3.0, rel=0.01)


def test_fem_charts_time_series_half_power() -> None:
    # bw = 4.2 - 3.8 = 0.4 Hz; xi = 0.4 / (2 * 4.0) = 0.05 (5.0%); Q = 1 / (2 * 0.05) = 10.0
    res = features.run(
        "femChartsTimeSeries.halfPower",
        None,
        {"fResonanceHz": 4.0, "fLowHz": 3.8, "fHighHz": 4.2},
    )
    assert res["problems"] == []
    assert res["summary"]["bandwidthHz"] == pytest.approx(0.4, rel=0.01)
    assert res["summary"]["dampingRatio"] == pytest.approx(0.05, rel=0.01)
    assert res["summary"]["dampingPct"] == pytest.approx(5.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["qualityFactorQ"] == pytest.approx(10.0, rel=0.01)


def test_fem_charts_time_series_log_decrypt() -> None:
    # delta = (1 / 4) * ln(20 / 5) = ln(4) / 4 = 0.346574
    # xi = 0.346574 / sqrt(4 * pi^2 + 0.346574^2) = 0.346574 / 6.29274 = 0.055075 (5.5075%)
    res = features.run(
        "femChartsTimeSeries.logDecrypt",
        None,
        {"peak1": 20.0, "peakN": 5.0, "cycles": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["logDecrement"] == pytest.approx(0.346574, rel=0.01)
    assert res["summary"]["dampingRatio"] == pytest.approx(0.055075, rel=0.01)
    assert res["summary"]["dampingPct"] == pytest.approx(5.5075, rel=0.01)


def test_fem_charts_time_series_power_spectrum() -> None:
    # Pure cosine A=4.0 at f0=2.5 Hz over N=16, dt=0.05 s (T=0.8 s, df=1.25 Hz):
    # Variance = A^2 / 2 = 8.0 -> one-sided periodogram PSD peak = 8.0 / df = 8.0 * 0.8 = 6.4 unit^2/Hz.
    sig = ", ".join(str(round(4.0 * math.cos(2.0 * math.pi * 2 * n / 16), 8)) for n in range(16))
    res = features.run("femChartsTimeSeries.powerSpectrum", None, {"series": sig, "dtS": 0.05})
    assert res["problems"] == []
    assert res["summary"]["peakFreqHz"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["peakPsd"] == pytest.approx(6.4, rel=0.01)


def test_fem_charts_time_series_response_spectrum() -> None:
    # SDOF step response to a0 = 0.5 g (xi = 0.05):
    # Analytical peak overshoot = a0 * (1 + exp(-pi*xi/sqrt(1 - xi^2))) = 0.5 * 1.85449 = 0.9272 g.
    # At T = 0.8 s: Sd = Sa * 9806.65 * (0.8 / (2*pi))^2 = 0.9272 * 9806.65 * 0.016211 = 147.41 mm.
    step_acc = ", ".join(["0.0"] + ["0.5"] * 100)
    res = features.run(
        "femChartsTimeSeries.responseSpectrum",
        None,
        {"series": step_acc, "dtS": 0.01, "damping": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["peakSaG"] == pytest.approx(0.9272, rel=0.01)
    row_08 = _row_by(res, "periodS", 0.8)
    assert row_08["saG"] == pytest.approx(0.9272, rel=0.01)
    assert row_08["sdMm"] == pytest.approx(147.41, rel=0.01)


def test_fem_charts_time_series_sample_rate() -> None:
    # dt = 0.005 s -> fs = 1 / 0.005 = 200 Hz, f_Nyq = 100 Hz
    res = features.run("femChartsTimeSeries.sampleRate", None, {"dtS": 0.005})
    assert res["problems"] == []
    assert res["summary"]["samplingRateHz"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["nyquistFreqHz"] == pytest.approx(100.0, rel=0.01)


def test_fem_charts_time_series_smooth_series() -> None:
    # Centered 3-point boxcar of [0, 3, 6, 9, 6, 3, 0] with zero-padded ends:
    # smoothed = [1, 3, 6, 7, 6, 3, 1]; mean = 27/7 = 3.85714
    # variance = (2*(2.8571^2 + 0.8571^2 + 2.1429^2) + 3.1429^2) / 7 = 5.26531 -> std = 2.29463
    res = features.run(
        "femChartsTimeSeries.smoothSeries",
        None,
        {"series": "0.0, 3.0, 6.0, 9.0, 6.0, 3.0, 0.0", "dtS": 0.05, "windowSamples": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["windowSamples"] == 3
    assert res["summary"]["smoothedStd"] == pytest.approx(2.29463, rel=0.01)
    assert res["tables"][0]["rows"][3]["smoothed"] == pytest.approx(7.0, rel=0.01)


def test_fem_charts_time_series_time_peak_summary() -> None:
    # [0, 3, 4, -5, 0] at dt = 0.1 s: maxPos = 4.0 at t = 0.2 s, minNeg = -5.0 at t = 0.3 s
    # RMS = sqrt((0 + 9 + 16 + 25 + 0) / 5) = sqrt(10) = 3.16228
    res = features.run(
        "femChartsTimeSeries.timePeakSummary",
        None,
        {"series": "0.0, 3.0, 4.0, -5.0, 0.0", "dtS": 0.1},
    )
    assert res["problems"] == []
    assert res["summary"]["maxPos"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["minNeg"] == pytest.approx(-5.0, rel=0.01)
    assert res["summary"]["tMaxPosS"] == pytest.approx(0.2, rel=0.01)
    assert res["summary"]["tMinNegS"] == pytest.approx(0.3, rel=0.01)
    assert _row_by(res, "metric", "RMS")["value"] == pytest.approx(3.16228, rel=0.01)


def test_fem_charts_time_series_time_window() -> None:
    # [1, 3, -4, 0, 2, 10] at dt = 0.1 s; window [0.1, 0.4] keeps indices 1..4: [3, -4, 0, 2]
    # samplesKept = 4; peak = 4.0; RMS = sqrt((9 + 16 + 0 + 4) / 4) = sqrt(7.25) = 2.69258
    res = features.run(
        "femChartsTimeSeries.timeWindow",
        None,
        {"series": "1.0, 3.0, -4.0, 0.0, 2.0, 10.0", "dtS": 0.1, "tStartS": 0.1, "tEndS": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["samplesKept"] == 4
    assert res["summary"]["windowPeak"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["windowRms"] == pytest.approx(2.69258, rel=0.01)


def test_fem_charts_time_series_transfer_function() -> None:
    # Output y(t) = 2.5 * x(t) (pure scalar amplification, zero phase lag) -> |H(f)| = 2.5, phase = 0 deg.
    x = [
        round(
            3.0 * math.cos(2.0 * math.pi * 2 * n / 16) + 5.0 * math.cos(2.0 * math.pi * 6 * n / 16),
            8,
        )
        for n in range(16)
    ]
    y = [round(2.5 * v, 8) for v in x]
    res = features.run(
        "femChartsTimeSeries.transferFunction",
        None,
        {
            "inputSeries": ", ".join(str(v) for v in x),
            "outputSeries": ", ".join(str(v) for v in y),
            "dtS": 0.05,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["samples"] == 16
    assert res["summary"]["maxGain"] == pytest.approx(2.5, rel=0.01)
    row_2p5 = _row_by(res, "freqHz", 2.5)
    assert row_2p5["gain"] == pytest.approx(2.5, rel=0.01)
    assert row_2p5["phaseDeg"] == pytest.approx(0.0, abs=1e-3)
