"""Independent known-answer tests for standalone numeric calculators in the Materials window."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── Materials Library (materials_library.py: 16) ───────────────────────────────────────────────────


def test_materials_library_admixtures() -> None:
    # Superplasticizer: water_red = min(0.28, 0.14 * 1.5) = 0.21 (21%).
    # mass = 400 * 1.5 / 100 = 6.0 kg/m3; adj_water = 200 * (1 - 0.21) = 158.0 kg/m3; w/c = 158/400 = 0.395.
    res = features.run(
        "library.admixtures",
        None,
        {
            "admixtureType": "superplasticizer",
            "cementKgPerM3": 400.0,
            "waterKgPerM3": 200.0,
            "dosagePercent": 1.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["admixtureMassKgPerM3"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["waterReductionPercent"] == pytest.approx(21.0, rel=0.01)
    assert res["summary"]["effectiveWaterKgPerM3"] == pytest.approx(158.0, rel=0.01)
    assert res["summary"]["effectiveWaterCementRatio"] == pytest.approx(0.395, rel=0.01)


def test_materials_library_cement_types() -> None:
    # PSC-GGBS50 catalog: f28=0.92, r7=0.56, heat=210 kJ/kg.
    # fc28 = 40*0.92 = 36.8 MPa; fc7 = 36.8*0.56 = 20.608 MPa; heat = 210*400 = 84000 kJ/m3.
    res = features.run(
        "library.cementTypes",
        None,
        {"cementType": "PSC-GGBS50", "refStrengthMpa": 40.0, "binderKgPerM3": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["strength7DayMpa"] == pytest.approx(20.608, rel=0.01)
    assert res["summary"]["strength28DayMpa"] == pytest.approx(36.8, rel=0.01)
    assert res["summary"]["hydrationHeatKjPerM3"] == pytest.approx(84000.0, rel=0.01)


def test_materials_library_characteristic_strength() -> None:
    # Samples [20, 22, 24, 26, 28]: mean = 24.0, s = sqrt((16+4+0+4+16)/4) = sqrt(10) = 3.16228 MPa.
    # CoV = 3.16228 / 24 * 100 = 13.176%; fk (k=2.0) = 24 - 2*3.16228 = 17.6754 MPa.
    res = features.run(
        "library.characteristicStrength",
        None,
        {"samplesMpa": "20.0, 22.0, 24.0, 26.0, 28.0", "fractileK": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["sampleCount"] == 5
    assert res["summary"]["meanStrengthMpa"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["stdDevMpa"] == pytest.approx(math.sqrt(10.0), rel=0.01)
    assert res["summary"]["covPercent"] == pytest.approx(13.176, rel=0.01)
    assert res["summary"]["characteristicStrengthMpa"] == pytest.approx(17.6754, rel=0.01)


def test_materials_library_curing_class() -> None:
    # severe=10 d, slow=1.35x, temp=20 C (factor=(20+10)/(20+10)=1.0) -> req = ceil(13.5) = 14 d.
    # actual=10 d -> equiv20C = 10 d, surface = 0.55 + 0.45*(10/14) = 0.87143, adequate=False.
    res = features.run(
        "library.curingClass",
        None,
        {"exposure": "severe", "strengthGain": "slow", "ambientTempC": 20.0, "actualDays": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredCuringDays"] == pytest.approx(14.0, rel=0.01)
    assert res["summary"]["equivalent20CDays"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["surfaceStrengthFactor"] == pytest.approx(0.87143, rel=0.01)
    assert res["summary"]["adequate"] is False


def test_materials_library_density_table() -> None:
    # Default library C24.1 has density 2400 kg/m3; at g=9.80 m/s2 -> gamma = 2400*9.80/1000 = 23.52 kN/m3.
    res = features.run("library.densityTable", None, {"gravityMPerS2": 9.80})
    assert res["problems"] == []
    c24 = _row_by(res, "id", "C24.1")
    assert c24["densityKgPerM3"] == pytest.approx(2400.0, rel=0.01)
    assert c24["unitWeightKnPerM3"] == pytest.approx(23.52, rel=0.01)


def test_materials_library_design_strengths() -> None:
    # fd = 0.80 * 40 / 1.6 = 20.0 MPa; phi*fk = 0.70 * 40 = 28.0 MPa.
    res = features.run(
        "library.designStrengths",
        None,
        {
            "characteristicMpa": 40.0,
            "partialFactorGamma": 1.6,
            "sustainedFactor": 0.80,
            "resistancePhi": 0.70,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["designStrengthMpa"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["phiStrengthMpa"] == pytest.approx(28.0, rel=0.01)


def test_materials_library_elastic_modulus() -> None:
    # Default pack BNBC 2020 Part 6 Sec 6.1.7.1: siliceous normal-weight Ec = 4700 * sqrt(36) = 28200.0 MPa.
    # Chord test: 15.0 MPa / 500e-6 = 30000.0 MPa.
    res = features.run(
        "library.elasticModulus",
        None,
        {
            "fcMpa": 36.0,
            "densityKgPerM3": 2400.0,
            "aggregate": "siliceous",
            "testStressMpa": 15.0,
            "testStrainMicro": 500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["modulusMpa"] == pytest.approx(28200.0, rel=0.01)
    assert res["summary"]["measuredModulusMpa"] == pytest.approx(30000.0, rel=0.01)


def test_materials_library_kent_park_model() -> None:
    # K = 1 + 0.02*400/40 = 1.20 -> fcc = 48.0 MPa, eps_c0 = 0.0024.
    # eps_50u = (3 + 0.29*40)/(145*40 - 1000) = 14.6/4800 = 0.0030417.
    # eps_50h = 0.75 * 0.02 * sqrt(400/100) = 0.030 -> Zm = 0.5 / (0.0030417 + 0.030 - 0.0024) = 16.3176.
    # eps_cu = max(0.004 + 0.9*0.02*400/300, 0.006) = 0.028.
    res = features.run(
        "library.kentParkModel",
        None,
        {
            "fcMpa": 40.0,
            "rhoS": 0.02,
            "fyhMpa": 400.0,
            "hoopWidthMm": 400.0,
            "spacingMm": 100.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["enhancementK"] == pytest.approx(1.20, rel=0.01)
    assert res["summary"]["confinedStrengthMpa"] == pytest.approx(48.0, rel=0.01)
    assert res["summary"]["peakStrain"] == pytest.approx(0.0024, rel=0.01)
    assert res["summary"]["ultimateStrain"] == pytest.approx(0.028, rel=0.01)
    assert res["summary"]["softeningSlopeZm"] == pytest.approx(16.3176, rel=0.01)


def test_materials_library_mander_concrete() -> None:
    # fc=40, fl=4.0 (fl/fc=0.1):
    # fcc = 40 * (-1.254 + 2.254*sqrt(1 + 0.794) - 0.2) = 40 * 1.56501 = 62.600 MPa.
    # eps_cc = 0.002 * (1 + 5*0.56501) = 0.007650.
    # eps_cu = 0.004 + 1.4*0.02*400*0.09/62.600 = 0.020102.
    res = features.run(
        "library.manderConcrete",
        None,
        {
            "fcMpa": 40.0,
            "ecMpa": 30000.0,
            "epsC0": 0.002,
            "flEffMpa": 4.0,
            "rhoS": 0.02,
            "fyhMpa": 400.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["confinedStrengthMpa"] == pytest.approx(62.600, rel=0.01)
    assert res["summary"]["confinementRatio"] == pytest.approx(1.5650, rel=0.01)
    assert res["summary"]["confinedPeakStrain"] == pytest.approx(0.00765, rel=0.01)
    assert res["summary"]["ultimateStrain"] == pytest.approx(0.02010, rel=0.01)


def test_materials_library_material_units() -> None:
    # 40 MPa * 145.0377 = 5801.51 psi; 30000 MPa * 0.1450377 = 4351.13 ksi.
    # 2500 kg/m3 * 9.81/1000 = 24.525 kN/m3; 2500 * 0.062428 = 156.07 pcf.
    res = features.run(
        "library.materialUnits",
        None,
        {
            "stressMpa": 40.0,
            "modulusMpa": 30000.0,
            "densityKgPerM3": 2500.0,
            "alphaPerC": 1.2e-5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["stressPsi"] == pytest.approx(5801.51, rel=0.01)
    assert res["summary"]["modulusKsi"] == pytest.approx(4351.13, rel=0.01)
    assert res["summary"]["unitWeightKnPerM3"] == pytest.approx(24.525, rel=0.01)
    assert res["summary"]["densityPcf"] == pytest.approx(156.07, rel=0.01)


def test_materials_library_mix_design() -> None:
    # fc=25, s=3 -> fcm = 25 + 1.645*3 = 29.935 MPa.
    # Abrams: ln(29.935/98)/ln(0.045) = 0.3824 -> capped by maxWc=0.35 -> wc = 0.35.
    # water=175 -> cement = 175/0.35 = 500.0 kg/m3.
    # v_paste = 500/3150 + 175/1000 + 0.02 = 0.35373 -> v_agg = 0.64627 -> mass_agg = 1712.6 kg/m3.
    # wet_density = 500 + 175 + 1712.6 = 2387.6 kg/m3.
    res = features.run(
        "library.mixDesign",
        None,
        {
            "fcMpa": 25.0,
            "stdDevMpa": 3.0,
            "waterKgPerM3": 175.0,
            "maxWc": 0.35,
            "coarseFraction": 0.60,
            "airPercent": 2.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["targetMeanStrengthMpa"] == pytest.approx(29.935, rel=0.01)
    assert res["summary"]["waterCementRatio"] == pytest.approx(0.35, rel=0.01)
    assert res["summary"]["cementKgPerM3"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["wetDensityKgPerM3"] == pytest.approx(2387.6, rel=0.01)


def test_materials_library_new_material() -> None:
    # Validates explicit steel record creation and echoes E, density, category, 0 warnings.
    res = features.run(
        "library.newMaterial",
        None,
        {
            "materialId": "S355-TEST",
            "name": "Test Steel S355",
            "category": "steel",
            "strengthMpa": 355.0,
            "ultimateMpa": 510.0,
            "elasticModulusMpa": 210000.0,
            "poisson": 0.3,
            "densityKgPerM3": 7850.0,
            "alphaPerC": 1.2e-5,
            "exportDraft": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["materialId"] == "S355-TEST"
    assert res["summary"]["category"] == "steel"
    assert res["summary"]["modulusMpa"] == pytest.approx(210000.0, rel=0.01)
    assert res["summary"]["densityKgPerM3"] == pytest.approx(7850.0, rel=0.01)
    assert res["summary"]["warningCount"] == 0


def test_materials_library_poisson_ratio() -> None:
    # E=30000 MPa, nu=0.25 -> G = 30000/(2*1.25) = 12000.0 MPa, K = 30000/(3*0.5) = 20000.0 MPa.
    res = features.run(
        "library.poissonRatio",
        None,
        {"materialId": "", "elasticModulusMpa": 30000.0, "poisson": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["shearModulusMpa"] == pytest.approx(12000.0, rel=0.01)
    assert res["summary"]["bulkModulusMpa"] == pytest.approx(20000.0, rel=0.01)


def test_materials_library_ramberg_osgood_steel() -> None:
    # E0=200000, sigma_0.2=400, n=10, maxStressRatio=1.0 -> maxStress=400 MPa.
    # eps(400) = 400/200000 + 0.002*(400/400)^10 = 0.002 + 0.002 = 0.0040.
    res = features.run(
        "library.rambergOsgoodSteel",
        None,
        {
            "modulusMpa": 200000.0,
            "proofStressMpa": 400.0,
            "exponentN": 10.0,
            "maxStressRatio": 1.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["maxStressMpa"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["maxStrain"] == pytest.approx(0.0040, rel=0.01)


def test_materials_library_stress_strain_curve() -> None:
    # Steel elastic-plastic (1% hardening): fy=400, E0=200000 (eps_y=0.002), eps_u=0.10.
    # sigma(0.10) = 400 + 0.01 * 200000 * (0.10 - 0.002) = 400 + 196 = 596.0 MPa.
    res = features.run(
        "library.stressStrainCurve",
        None,
        {
            "modelKind": "steel",
            "strengthMpa": 400.0,
            "modulusMpa": 200000.0,
            "ultimateStrain": 0.10,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["peakStressMpa"] == pytest.approx(596.0, rel=0.01)


def test_materials_library_thermal_expansion() -> None:
    # alpha=1.2e-5, dT=50 C, L=20 m, E=200000 MPa:
    # strain = 600 microstrain, dL = 600e-6 * 20000 = 12.0 mm, sigma = -200000 * 600e-6 = -120.0 MPa.
    res = features.run(
        "library.thermalExpansion",
        None,
        {"alphaPerC": 1.2e-5, "deltaTC": 50.0, "lengthM": 20.0, "modulusMpa": 200000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["thermalStrainMicro"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["freeDisplacementMm"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["restrainedStressMpa"] == pytest.approx(-120.0, rel=0.01)


# ── Materials Compliance (materials_compliance.py: 5) ──────────────────────────────────────────────


def test_materials_compliance_code_equivalence() -> None:
    # Cylinder 32 MPa -> Cube 32*1.25 = 40.0 MPa; Cube 40 MPa -> Cylinder 40*0.80 = 32.0 MPa.
    r1 = features.run(
        "libraryCompliance.codeEquivalence",
        None,
        {
            "sourceSystem": "cylinder_strength",
            "targetSystem": "cube_limitstate",
            "concreteStrengthMpa": 32.0,
            "steelYieldMpa": 500.0,
        },
    )
    r2 = features.run(
        "libraryCompliance.codeEquivalence",
        None,
        {
            "sourceSystem": "cube_limitstate",
            "targetSystem": "cube_limitstate",
            "concreteStrengthMpa": 40.0,
            "steelYieldMpa": 500.0,
        },
    )
    assert r1["problems"] == [] and r2["problems"] == []
    assert r1["summary"]["equivalentCylinderFcMpa"] == pytest.approx(32.0, rel=0.01)
    assert r1["summary"]["equivalentCubeFcuMpa"] == pytest.approx(40.0, rel=0.01)
    assert r2["summary"]["equivalentCylinderFcMpa"] == pytest.approx(32.0, rel=0.01)
    assert r2["summary"]["equivalentCubeFcuMpa"] == pytest.approx(40.0, rel=0.01)


def test_materials_compliance_sampling_plan() -> None:
    # 240 m3 / 50 = ceil(4.8) = 5 concrete lots (15 cyl); 60 t / 25 = ceil(2.4) = 3 rebar lots (6 bars).
    # Total sample sets = 8; total specimens = 21.
    res = features.run(
        "libraryCompliance.samplingPlan",
        None,
        {
            "concreteVolumeM3": 240.0,
            "rebarMassTonnes": 60.0,
            "concreteFreqM3": 50.0,
            "rebarLotTonnes": 25.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalSampleSets"] == 8
    assert res["summary"]["totalSpecimens"] == 21


def test_materials_compliance_supplier_declaration() -> None:
    # Default library C24.1 has f'c = 24.1 MPa: 25.0 passes, 22.0 fails.
    ok_res = features.run(
        "libraryCompliance.supplierDeclaration",
        None,
        {
            "supplierName": "Plant X",
            "declarationId": "DOP-1",
            "materialId": "C24.1",
            "declaredStrengthMpa": 25.0,
            "declaredDensityKgPerM3": 2400.0,
        },
    )
    fail_res = features.run(
        "libraryCompliance.supplierDeclaration",
        None,
        {
            "supplierName": "Plant X",
            "declarationId": "DOP-2",
            "materialId": "C24.1",
            "declaredStrengthMpa": 22.0,
            "declaredDensityKgPerM3": 2400.0,
        },
    )
    assert ok_res["problems"] == [] and fail_res["problems"] == []
    assert ok_res["summary"]["meetsSpecification"] is True
    assert fail_res["summary"]["meetsSpecification"] is False


def test_materials_compliance_test_certificate_link() -> None:
    # B420DWR (nom fy=420): actual fy=500, fu=650 -> fu/fy = 1.30 >= 1.25 (BNBC 2020), overstrength=80 <= 125.
    res = features.run(
        "libraryCompliance.testCertificateLink",
        None,
        {
            "materialId": "B420DWR",
            "certificateNo": "MTC-99",
            "measuredYieldMpa": 500.0,
            "measuredUltimateMpa": 650.0,
            "elongationPct": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["fuFyRatio"] == pytest.approx(1.30, rel=0.01)
    assert res["summary"]["minRequiredRatio"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_materials_compliance_test_data_link() -> None:
    # C24.1 spec=24.1 MPa; tested=28.0 MPa -> compliant=True.
    res = features.run(
        "libraryCompliance.testDataLink",
        None,
        {"materialId": "C24.1", "labReportRef": "LAB-99", "testedMeanMpa": 28.0},
    )
    assert res["problems"] == []
    assert res["summary"]["specifiedMpa"] == pytest.approx(24.1, rel=0.01)
    assert res["summary"]["compliant"] is True


# ── Materials Concrete (materials_concrete.py: 23) ─────────────────────────────────────────────────


def test_materials_concrete_acceptance_criteria() -> None:
    # [32, 34, 36, 38]: mean = 35.0, s = sqrt((9+1+1+9)/3) = 2.5820 MPa.
    # req_mean = 30.0 + max(2.0, 0.825*2.5820) = 32.130 MPa; min=32 >= 27 -> accepted.
    res = features.run(
        "libraryConcrete.acceptanceCriteria",
        None,
        {
            "batchMpa": "32, 34, 36, 38",
            "specifiedMpa": 30.0,
            "marginMpa": 2.0,
            "individualToleranceMpa": 3.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["lotMeanMpa"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["requiredMeanMpa"] == pytest.approx(32.130, rel=0.01)
    assert res["summary"]["lotAccepted"] is True


def test_materials_concrete_aggregate_grading() -> None:
    # FM = sum(100 - passing on 4.75, 2.36, 1.18, 0.60, 0.30, 0.15) / 100
    #    = (50 + 60 + 70 + 80 + 90 + 100) / 100 = 4.50.
    # At 4.75 mm, Fuller (dmax=20) = 100*(4.75/20)^0.45 = 52.275% -> dev = 2.275%.
    res = features.run(
        "libraryConcrete.aggregateGrading",
        None,
        {
            "sievePassing": "20, 100\n4.75, 50\n2.36, 40\n1.18, 30\n0.60, 20\n0.30, 10\n0.15, 0",
            "maxSizeMm": 20.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["finenessModulus"] == pytest.approx(4.50, rel=0.01)
    row475 = _row_by(res, "sieveMm", 4.75)
    assert row475["idealPercent"] == pytest.approx(52.275, rel=0.01)


def test_materials_concrete_air_content() -> None:
    # dmax=20 -> target = 7.5 - 0.1*(20-10) = 6.5%.
    # meas=5.5 -> extra=4.0 -> retention = 1 - 0.05*4 = 0.80 -> adj_fc = 40 * 0.80 = 32.0 MPa.
    res = features.run(
        "libraryConcrete.airContent",
        None,
        {"measuredAirPct": 5.5, "maxAggMm": 20.0, "baseFcMpa": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["targetAirPercent"] == pytest.approx(6.5, rel=0.01)
    assert res["summary"]["adjustedStrengthMpa"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["withinTarget"] is True


def test_materials_concrete_bleeding_test() -> None:
    # bleed=40 mL / 500 cm2 = 0.08 mL/cm2.
    # sample water = (12 / 2400) * 200 * 1000 = 1000 mL -> bleed% = 40/1000 * 100 = 4.0%.
    res = features.run(
        "libraryConcrete.bleedingTest",
        None,
        {
            "bleedWaterMl": 40.0,
            "surfaceAreaCm2": 500.0,
            "specimenMassKg": 12.0,
            "mixWaterKgPerM3": 200.0,
            "mixDensityKgPerM3": 2400.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["bleedPerAreaMlPerCm2"] == pytest.approx(0.08, rel=0.01)
    assert res["summary"]["bleedPercentOfWater"] == pytest.approx(4.0, rel=0.01)


def test_materials_concrete_cement_replacement() -> None:
    # total = 200 + 100 + 50 + 50 = 400 kg/m3 -> replacement = 50.0%.
    # equiv = 200 + 0.75*100 + 0.40*50 + 2.0*50 = 395.0 kg/m3 -> eff_wb = 180/395 = 0.4557.
    res = features.run(
        "libraryConcrete.cementReplacement",
        None,
        {
            "opcKgPerM3": 200.0,
            "ggbsKgPerM3": 100.0,
            "flyAshKgPerM3": 50.0,
            "silicaFumeKgPerM3": 50.0,
            "waterKgPerM3": 180.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalBinderKgPerM3"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["replacementPercent"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["equivalentBinderKgPerM3"] == pytest.approx(395.0, rel=0.01)
    assert res["summary"]["effectiveWaterBinderRatio"] == pytest.approx(0.4557, rel=0.01)


def test_materials_concrete_chloride_limits() -> None:
    # 400 * 0.05% + 0.10 + 0.02 = 0.20 + 0.12 = 0.32 kg/m3 -> 0.32/400 = 0.08% > 0.06% (prestressed).
    res = features.run(
        "libraryConcrete.chlorideLimits",
        None,
        {
            "memberType": "prestressed",
            "cementKgPerM3": 400.0,
            "clCementPct": 0.05,
            "clAggKgPerM3": 0.10,
            "clAdmKgPerM3": 0.02,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalChlorideKgPerM3"] == pytest.approx(0.32, rel=0.01)
    assert res["summary"]["chloridePercentOfCement"] == pytest.approx(0.08, rel=0.01)
    assert res["summary"]["compliant"] is False


def test_materials_concrete_core_testing() -> None:
    # L/D = 150/100 = 1.5 -> f_ld = 0.87 + 0.13*0.5 = 0.935; f_dia=1.0, f_mc(dry)=0.96, f_dam=1.06.
    # combined = 0.935 * 0.96 * 1.06 = 0.951456; mean raw = 26.0 -> in-situ = 24.7379 MPa.
    res = features.run(
        "libraryConcrete.coreTesting",
        None,
        {"coreMpa": "25.0, 27.0", "lengthMm": 150.0, "diameterMm": 100.0, "moisture": "dry"},
    )
    assert res["problems"] == []
    assert res["summary"]["slendernessLD"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["combinedFactor"] == pytest.approx(0.951456, rel=0.01)
    assert res["summary"]["meanInSituFcMpa"] == pytest.approx(24.7379, rel=0.01)


def test_materials_concrete_cube_results() -> None:
    # [30, 36, 39, 45]: mean = 37.5 MPa, equiv cyl = 30.0 MPa, rolling-3 = [35.0, 40.0] -> min=35.0 MPa.
    res = features.run(
        "libraryConcrete.cubeResults",
        None,
        {"cubeMpa": "30.0, 36.0, 39.0, 45.0", "targetCubeMpa": 35.0},
    )
    assert res["problems"] == []
    assert res["summary"]["meanCubeMpa"] == pytest.approx(37.5, rel=0.01)
    assert res["summary"]["minRolling3Mpa"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["equivCylinderMeanMpa"] == pytest.approx(30.0, rel=0.01)


def test_materials_concrete_cylinder_results() -> None:
    # [26, 28, 30, 32], f'c=28: min_single = 24.5, rolling-3 = [28.0, 30.0] >= 28 -> mean=29.0, accepted=True.
    res = features.run(
        "libraryConcrete.cylinderResults",
        None,
        {"cylinderMpa": "26.0, 28.0, 30.0, 32.0", "specifiedFcMpa": 28.0},
    )
    assert res["problems"] == []
    assert res["summary"]["meanFcMpa"] == pytest.approx(29.0, rel=0.01)
    assert res["summary"]["minFcMpa"] == pytest.approx(26.0, rel=0.01)
    assert res["summary"]["accepted"] is True


def test_materials_concrete_embodied_carbon_mix() -> None:
    # BOQ default cement factor = 0.588 kgCO2e/kg:
    # 320*0.588 + 80*0.07 + 40*0.025 + 700*0.005 + 1000*0.008 = 188.16 + 5.6 + 1.0 + 3.5 + 8.0 = 206.26.
    # per MPa (32 MPa) = 206.26 / 32 = 6.4456.
    res = features.run(
        "libraryConcrete.embodiedCarbonMix",
        None,
        {
            "opcKgPerM3": 320.0,
            "ggbsKgPerM3": 80.0,
            "flyAshKgPerM3": 40.0,
            "fineKgPerM3": 700.0,
            "coarseKgPerM3": 1000.0,
            "fcMpa": 32.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalCarbonKgCo2ePerM3"] == pytest.approx(206.26, rel=0.01)
    assert res["summary"]["carbonPerMpaKgCo2e"] == pytest.approx(6.4456, rel=0.01)


def test_materials_concrete_epd_lookup() -> None:
    # Baseline = 500 * 0.588 = 294.0 kgCO2e/m3; declared = 220.5 -> reduction = (294-220.5)/294 = 25.0%.
    res = features.run(
        "libraryConcrete.epdLookup",
        None,
        {
            "epdReference": "EPD-TEST",
            "declaredCarbonKgCo2ePerM3": 220.5,
            "baselineCementKgPerM3": 500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["baselineKgCo2ePerM3"] == pytest.approx(294.0, rel=0.01)
    assert res["summary"]["reductionPercent"] == pytest.approx(25.0, rel=0.01)


def test_materials_concrete_exposure_classes() -> None:
    # Coastal: max_wc=0.40, min_cem=360, min_fc=35, min_cov=55; fc=40, cover=60 -> compliant=True.
    res = features.run(
        "libraryConcrete.exposureClasses",
        None,
        {"exposure": "coastal", "fcMpa": 40.0, "coverMm": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxWcRatio"] == pytest.approx(0.40, rel=0.01)
    assert res["summary"]["minFcMpa"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["minCoverMm"] == pytest.approx(55.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_materials_concrete_flexural_strength() -> None:
    # fr = PL/(bd^2) = 30000*450 / (150*150^2) = 4.0 MPa; code fr = 0.62*sqrt(36) = 3.72 MPa.
    res = features.run(
        "libraryConcrete.flexuralStrength",
        None,
        {"failureLoadKn": 30.0, "spanMm": 450.0, "widthMm": 150.0, "depthMm": 150.0, "fcMpa": 36.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flexuralStrengthMpa"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["codeRuptureMpa"] == pytest.approx(3.72, rel=0.01)
    assert res["summary"]["ratioToCode"] == pytest.approx(4.0 / 3.72, rel=0.01)


def test_materials_concrete_flow_table() -> None:
    # (680 + 720)/2 = 700 mm -> SF2; T500=1.8 s -> VS1.
    res = features.run(
        "libraryConcrete.flowTable",
        None,
        {"spread1Mm": 680.0, "spread2Mm": 720.0, "t500Sec": 1.8},
    )
    assert res["problems"] == []
    assert res["summary"]["meanSpreadMm"] == pytest.approx(700.0, rel=0.01)
    assert res["summary"]["slumpFlowClass"].startswith("SF2")
    assert res["summary"]["viscosityClass"].startswith("VS1")


def test_materials_concrete_maturity_method() -> None:
    # T0=-10: M = (20 - (-10))*10 + (25 - (-10))*20 = 300 + 700 = 1000 C-hr, totalHours=30.
    # m28 = 30*24*28 = 20160 -> est_fc = 40 * (1000 / (1000 + 0.12*20160)) * 1.12 = 13.1025 MPa.
    res = features.run(
        "libraryConcrete.maturityMethod",
        None,
        {"tempHistory": "10, 20\n20, 25", "datumTempC": -10.0, "fc28Mpa": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalHours"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["maturityIndexCHr"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["estimatedStrengthMpa"] == pytest.approx(13.1025, rel=0.01)


def test_materials_concrete_mix_cost() -> None:
    # 400*0.15 + 600*0.02 + 1200*0.03 + 4*2.0 = 60 + 12 + 36 + 8 = 116.0; cement share = 60/116*100 = 51.724%.
    res = features.run(
        "libraryConcrete.mixCost",
        None,
        {
            "cementKg": 400.0,
            "fineKg": 600.0,
            "coarseKg": 1200.0,
            "admixtureKg": 4.0,
            "cementRate": 0.15,
            "fineRate": 0.02,
            "coarseRate": 0.03,
            "admixtureRate": 2.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalCostPerM3"] == pytest.approx(116.0, rel=0.01)
    assert res["summary"]["cementSharePercent"] == pytest.approx(51.724, rel=0.01)
    assert res["summary"]["totalMassKgPerM3"] == pytest.approx(2204.0, rel=0.01)


def test_materials_concrete_modulus_test() -> None:
    # Ec = (13.5 - 1.5) / ((450 - 50)*1e-6) = 12 / 4e-4 = 30000.0 MPa.
    # Default pack (BNBC 2020) siliceous Ec(36) = 4700*6 = 28200.0 MPa -> diff = +6.383%.
    res = features.run(
        "libraryConcrete.modulusTest",
        None,
        {
            "stress1Mpa": 1.5,
            "strain1Micro": 50.0,
            "stress2Mpa": 13.5,
            "strain2Micro": 450.0,
            "fcMpa": 36.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["measuredModulusMpa"] == pytest.approx(30000.0, rel=0.01)
    assert res["summary"]["codeModulusMpa"] == pytest.approx(28200.0, rel=0.01)
    assert res["summary"]["differencePercent"] == pytest.approx(6.383, rel=0.01)


def test_materials_concrete_non_destructive_test() -> None:
    # R=40, V=4.0 km/s: SonReb = 0.0286 * 40^1.246 * 4^1.85 = 36.849 MPa.
    # Rebound-only = 0.015*1600 + 0.35*40 - 4 = 34.0 MPa; UPV=4.0 -> "Good".
    res = features.run(
        "libraryConcrete.nonDestructiveTest", None, {"reboundR": 40.0, "upvKmPerS": 4.0}
    )
    assert res["problems"] == []
    assert res["summary"]["sonrebStrengthMpa"] == pytest.approx(36.849, rel=0.01)
    assert res["summary"]["reboundOnlyMpa"] == pytest.approx(34.0, rel=0.01)
    assert res["summary"]["upvQuality"] == "Good"


def test_materials_concrete_slump_test() -> None:
    # S3 = [100, 150]; meas=175, tol=30 -> withinClass=False, withinTolerance=True.
    res = features.run(
        "libraryConcrete.slumpTest",
        None,
        {"measuredSlumpMm": 175.0, "targetClass": "S3", "toleranceMm": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["withinClass"] is False
    assert res["summary"]["withinTolerance"] is True


def test_materials_concrete_split_tensile() -> None:
    # fct = 2 * 150000 / (pi * 300 * 150) = 2.12207 MPa; est = 0.56*5 = 2.80 MPa.
    res = features.run(
        "libraryConcrete.splitTensile",
        None,
        {"failureLoadKn": 150.0, "diameterMm": 150.0, "lengthMm": 300.0, "fcMpa": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["splitTensileMpa"] == pytest.approx(2.12207, rel=0.01)
    assert res["summary"]["empiricalEstimateMpa"] == pytest.approx(2.80, rel=0.01)


def test_materials_concrete_sulfate_resistance() -> None:
    # gw=2000 mg/L (>1500) -> Severe (maxWc=0.45, minBinder=340); provided wc=0.42, binder=350 -> compliant=True.
    res = features.run(
        "libraryConcrete.sulfateResistance",
        None,
        {
            "groundwaterSo4MgPerL": 2000.0,
            "soilSo4Percent": 0.10,
            "wcRatio": 0.42,
            "binderKgPerM3": 350.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["severityClass"] == "Severe"
    assert res["summary"]["maxWcRatio"] == pytest.approx(0.45, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_materials_concrete_trial_mixes() -> None:
    # Target=38: mixes B (360 kg, 40 MPa) and C (400 kg, 45 MPa) pass -> B is lowest cement.
    res = features.run(
        "libraryConcrete.trialMixes",
        None,
        {
            "trialCsv": "mix,wc,cement_kg,fc7_mpa,fc28_mpa\nA,0.50,320,20,30\nB,0.45,360,28,40\nC,0.40,400,32,45",
            "targetMeanMpa": 38.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["passingCount"] == 2
    assert res["summary"]["recommendedMix"] == "B"
    assert res["summary"]["bestStrengthMpa"] == pytest.approx(45.0, rel=0.01)


def test_materials_concrete_water_cement_ratio() -> None:
    # binder = 320 + 80 = 400 kg/m3, w/b = 160/400 = 0.40 <= 0.45 (severe, min=320) -> compliant=True.
    # est_fc = 98 * 0.045^0.40 = 28.347 MPa.
    res = features.run(
        "libraryConcrete.waterCementRatio",
        None,
        {"waterKgPerM3": 160.0, "cementKgPerM3": 320.0, "scmKgPerM3": 80.0, "exposure": "severe"},
    )
    assert res["problems"] == []
    assert res["summary"]["waterBinderRatio"] == pytest.approx(0.40, rel=0.01)
    assert res["summary"]["binderKgPerM3"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["estimatedFcMpa"] == pytest.approx(28.347, rel=0.01)
    assert res["summary"]["compliant"] is True


# ── Materials Masonry, Timber & Composites (materials_masonry.py: 21) ─────────────────────────────


def test_materials_masonry_add_masonry() -> None:
    # Default pack BNBC 2020: clay brick fb=15 MPa + mortar M2 -> f'm = 7.1048 MPa, Em = 750*f'm = 5328.6 MPa, G = 0.4*Em = 2131.4 MPa.
    res = features.run(
        "libraryMasonry.addMasonry",
        None,
        {
            "materialId": "MSN-TEST",
            "unitName": "Clay brick",
            "unitKind": "clay",
            "units": "solid",
            "unitStrengthMpa": 15.0,
            "mortarGrade": "M2",
            "specialInspection": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedFmMpa"] == pytest.approx(7.1048, rel=0.01)
    assert res["summary"]["elasticModulusMpa"] == pytest.approx(5328.6, rel=0.01)
    assert res["summary"]["shearModulusMpa"] == pytest.approx(2131.4, rel=0.01)


def test_materials_masonry_add_timber() -> None:
    # Default pack BNBC 2020 Group B, inside, Grade I (factor=1.0): E=9800 MPa, fb=12.0 MPa, fc//=7.8 MPa.
    res = features.run(
        "libraryMasonry.addTimber",
        None,
        {
            "materialId": "TIM-TEST",
            "group": "B",
            "location": "inside",
            "grade": "I",
            "densityKgPerM3": 700.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["modulusMpa"] == pytest.approx(9800.0, rel=0.01)
    assert res["summary"]["bendingStrengthMpa"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["compressionParallelMpa"] == pytest.approx(7.8, rel=0.01)


def test_materials_masonry_anchorage_capacity() -> None:
    # d=16 mm -> Ab = pi*16^2/4 = 201.06 mm^2. Default pack BNBC 2020 (f'm=10, lb=150, edge=150, fy=250):
    # allowableShear = 4.270 kN, allowableTension = 8.941 kN.
    res = features.run(
        "libraryMasonry.anchorageCapacity",
        None,
        {
            "boltDiaMm": 16.0,
            "embedmentMm": 150.0,
            "edgeDistanceMm": 150.0,
            "fmMpa": 10.0,
            "fyMpa": 250.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["boltAreaMm2"] == pytest.approx(201.06, rel=0.01)
    assert res["summary"]["allowableShearKn"] == pytest.approx(4.270, rel=0.01)
    assert res["summary"]["allowableTensionKn"] == pytest.approx(8.941, rel=0.01)


def test_materials_masonry_bedding_mortar() -> None:
    # L=200, W=100, H=90, t=10, wastage=20%:
    # mod = 210*100*100 = 2.1e6 mm^3, unit = 200*100*90 = 1.8e6 mm^3 -> frac = 0.3/2.1 = 0.142857.
    # gross = 0.142857*1.2 = 0.171429; units/m3 = 1e9/2.1e6 = 476.19.
    res = features.run(
        "libraryMasonry.beddingMortar",
        None,
        {
            "unitLengthMm": 200.0,
            "unitWidthMm": 100.0,
            "unitHeightMm": 90.0,
            "jointThicknessMm": 10.0,
            "wastagePct": 20.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["mortarVolumeFraction"] == pytest.approx(0.142857, rel=0.01)
    assert res["summary"]["mortarM3PerM3Masonry"] == pytest.approx(0.171429, rel=0.01)
    assert res["summary"]["unitsPerM3"] == pytest.approx(476.19, rel=0.01)
    assert res["summary"]["jointThicknessOk"] is True


def test_materials_masonry_block_types() -> None:
    # 400x200x200, 50% hollow -> gross=80000, net=40000, netStrength=12/0.5=24.0 MPa, "hollow".
    res = features.run(
        "libraryMasonry.blockTypes",
        None,
        {
            "lengthMm": 400.0,
            "widthMm": 200.0,
            "heightMm": 200.0,
            "hollowPercent": 50.0,
            "grossStrengthMpa": 12.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["grossAreaMm2"] == pytest.approx(80000.0, rel=0.01)
    assert res["summary"]["netAreaMm2"] == pytest.approx(40000.0, rel=0.01)
    assert res["summary"]["netStrengthMpa"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["unitCategory"] == "hollow"


def test_materials_masonry_bolt_capacity() -> None:
    # Default pack BNBC 2020 Group B, d=16, t=100 (t/d=6.25), theta=0, double shear -> 7.6752 kN.
    res = features.run(
        "libraryMasonry.boltCapacity",
        None,
        {
            "boltDiaMm": 16.0,
            "mainThicknessMm": 100.0,
            "angleDeg": 0.0,
            "group": "B",
            "singleShear": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["perBoltKn"] == pytest.approx(7.6752, rel=0.01)
    assert res["summary"]["slendernessRatio"] == pytest.approx(6.25, rel=0.01)


def test_materials_masonry_clt_panels() -> None:
    # Plies [30, 20, 30] (h=80 mm), E0=12000 MPa (E90=400), G90=60, span=4.0 m:
    # Outer plies (z=+-25): 2 * 12000 * (1000*30^3/12 + 1000*30*25^2) / 1e9 = 504.0 kN*m^2/m.
    # Middle cross ply: 400 * (1000*20^3/12) / 1e9 = 0.2667 -> EI_eff = 504.267 kN*m^2/m.
    # GA_eff = 60*1000*80*0.25/1000 = 1200.0 kN/m; span/h = 4000/80 = 50.0.
    res = features.run(
        "libraryMasonry.cltPanels",
        None,
        {"plyThicknessMm": "30, 20, 30", "e0Mpa": 12000.0, "g90Mpa": 60.0, "spanM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalThicknessMm"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["eiEffMajorKnM2PerM"] == pytest.approx(504.267, rel=0.01)
    assert res["summary"]["gaEffKnPerM"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["spanToDepthRatio"] == pytest.approx(50.0, rel=0.01)


def test_materials_masonry_composites() -> None:
    # Ef=200000, ff=4000, Em=4000, Vf=0.50, t=0.40:
    # E1 = 0.5*200000 + 0.5*4000 = 102000.0 MPa.
    # E2 = 200000*4000 / (0.5*4000 + 0.5*200000) = 7843.14 MPa.
    # f_ult = 4000*0.5 = 2000.0 MPa; axial = 102000*0.4/1000 = 40.8 kN/mm.
    res = features.run(
        "libraryMasonry.composites",
        None,
        {
            "fiberModulusMpa": 200000.0,
            "fiberStrengthMpa": 4000.0,
            "matrixModulusMpa": 4000.0,
            "fiberVolumeFraction": 0.50,
            "plyThicknessMm": 0.40,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["longitudinalModulusE1Mpa"] == pytest.approx(102000.0, rel=0.01)
    assert res["summary"]["transverseModulusE2Mpa"] == pytest.approx(7843.14, rel=0.01)
    assert res["summary"]["tensileStrengthMpa"] == pytest.approx(2000.0, rel=0.01)
    assert res["summary"]["axialStiffnessKnPerMmWidth"] == pytest.approx(40.8, rel=0.01)


def test_materials_masonry_compressive_strength() -> None:
    # Default pack BNBC 2020: clay 15 MPa + M2 -> f'm = 7.1048 MPa; gammaM=2.0 -> fd = 3.5524 MPa.
    res = features.run(
        "libraryMasonry.compressiveStrength",
        None,
        {"unitStrengthMpa": 15.0, "unitKind": "clay", "mortarGrade": "M2", "gammaM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["masonryStrengthFmMpa"] == pytest.approx(7.1048, rel=0.01)
    assert res["summary"]["designCompressiveMpa"] == pytest.approx(3.5524, rel=0.01)


def test_materials_masonry_fire_char_rate() -> None:
    # b=200, h=400, t=40, beta=0.75 -> d_char=30 mm, d0=5 -> d_ef=35 mm.
    # 4 sides: b_res = 200-70 = 130 mm, h_res = 400-70 = 330 mm -> areaRatio = 42900/80000 = 0.53625.
    res = features.run(
        "libraryMasonry.fireCharRate",
        None,
        {
            "widthMm": 200.0,
            "depthMm": 400.0,
            "fireMinutes": 40.0,
            "charRateMmPerMin": 0.75,
            "zeroStrengthMm": 5.0,
            "sidesExposed": "4",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["charDepthMm"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["effectiveLossMm"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["residualWidthMm"] == pytest.approx(130.0, rel=0.01)
    assert res["summary"]["residualDepthMm"] == pytest.approx(330.0, rel=0.01)
    assert res["summary"]["residualAreaRatio"] == pytest.approx(0.53625, rel=0.01)


def test_materials_masonry_flexural_bond() -> None:
    # mortar=8.0 (>=7.5 -> 0.15), full grouting (*1.6 -> 0.24), parallel (*2.0 -> 0.48 MPa).
    res = features.run(
        "libraryMasonry.flexuralBond",
        None,
        {"direction": "parallel", "grouting": "full", "mortarStrengthMpa": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flexuralBondMpa"] == pytest.approx(0.48, rel=0.01)


def test_materials_masonry_glulam() -> None:
    # b=150, 10x40 -> h=400, kh=(600/400)^0.1 = 1.04138, EI = 12000 * 150*400^3/12 / 1e9 = 9600 kN*m^2.
    # M_char = 24 * 1.04138 * (150*400^2/6) / 1e6 = 99.972 kN*m.
    res = features.run(
        "libraryMasonry.glulam",
        None,
        {
            "widthMm": 150.0,
            "laminationCount": 10.0,
            "lamThicknessMm": 40.0,
            "fbMpa": 24.0,
            "e0MeanMpa": 12000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalDepthMm"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["sizeFactorKh"] == pytest.approx(1.04138, rel=0.01)
    assert res["summary"]["flexuralRigidityKnM2"] == pytest.approx(9600.0, rel=0.01)
    assert res["summary"]["characteristicMomentKnM"] == pytest.approx(99.972, rel=0.01)


def test_materials_masonry_glulam_design() -> None:
    # b=150, h=400, L=6.0, w=10.0, fmd=20.0, E0=12000.0:
    # M_ed = 10*36/8 = 45.0 kN*m; M_rd = 20 * (150*400^2/6) / 1e6 = 80.0 kN*m -> util = 0.5625.
    # Iy = 8e8 mm^4 -> defl = 5 * 10 * 6000^4 / (384 * 12000 * 8e8) = 17.5781 mm.
    res = features.run(
        "libraryMasonry.glulamDesign",
        None,
        {
            "widthMm": 150.0,
            "depthMm": 400.0,
            "spanM": 6.0,
            "udlKnPerM": 10.0,
            "fmdMpa": 20.0,
            "e0MeanMpa": 12000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["momentDemandKnM"] == pytest.approx(45.0, rel=0.01)
    assert res["summary"]["momentCapacityKnM"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["bendingUtilisation"] == pytest.approx(0.5625, rel=0.01)
    assert res["summary"]["midspanDeflectionMm"] == pytest.approx(17.5781, rel=0.01)


def test_materials_masonry_grout_mix() -> None:
    # Fine grout (ignores peaGravelParts): 1 cement : 3 sand -> total=4 -> cem = 1.4*(1/4)*1440 = 504.0 kg/m3.
    res = features.run(
        "libraryMasonry.groutMix",
        None,
        {
            "groutType": "fine",
            "cementParts": 1.0,
            "sandParts": 3.0,
            "peaGravelParts": 2.0,
            "slumpMm": 240.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedCementKgPerM3"] == pytest.approx(504.0, rel=0.01)
    assert res["summary"]["flowCompliant"] is True


def test_materials_masonry_lime_mortar() -> None:
    # NHL2 (2.0 MPa), 1:2 -> fc = 2.0 * (2.5/2.0) * 1 = 2.5 MPa < 0.75 * 6.0 = 4.5 -> compatible=True.
    res = features.run(
        "libraryMasonry.limeMortar",
        None,
        {"nhlClass": "NHL2", "limeParts": 1.0, "sandParts": 2.0, "unitStrengthMpa": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedMortarStrengthMpa"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["unitCompatible"] is True


def test_materials_masonry_masonry_prisms() -> None:
    # hp/tp = 300/150 = 2.0 -> k_ht = 1.0. [10, 12] -> mean=11.0, s=sqrt(2)=1.4142 -> fm = 11 - 1.5*1.4142 = 8.8787 MPa.
    res = features.run(
        "libraryMasonry.masonryPrisms",
        None,
        {"prismMpa": "10.0, 12.0", "heightMm": 300.0, "thicknessMm": 150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatio"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["correctionFactor"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["meanCorrectedMpa"] == pytest.approx(11.0, rel=0.01)
    assert res["summary"]["designFmMpa"] == pytest.approx(8.8787, rel=0.01)


def test_materials_masonry_modulus_of_masonry() -> None:
    # Default pack BNBC 2020 clay: Em = 750 * 12 = 9000.0 MPa, Gm = 0.4 * 9000 = 3600.0 MPa.
    res = features.run("libraryMasonry.modulusOfMasonry", None, {"fmMpa": 12.0, "unitKind": "clay"})
    assert res["problems"] == []
    assert res["summary"]["elasticModulusMpa"] == pytest.approx(9000.0, rel=0.01)
    assert res["summary"]["shearModulusMpa"] == pytest.approx(3600.0, rel=0.01)


def test_materials_masonry_mortar_classes() -> None:
    # Default pack BNBC 2020: 1:3 cement:sand maps to grade M1 (10.0 MPa).
    res = features.run("libraryMasonry.mortarClasses", None, {"sandParts": 3.0})
    assert res["problems"] == []
    assert res["summary"]["matchedGrade"] == "M1"
    assert res["summary"]["classCount"] == 6


def test_materials_masonry_nail_capacity() -> None:
    # d=4.0, t=40.0, rho=500.0, n=4, single shear:
    # fh = 0.082*500*4^-0.3 = 27.050 MPa; My = 0.3*600*4^2.6 = 6616.5 N*mm.
    # f_single = min(27.05*40*4, sqrt(2*6616.5*27.05*4) + 0.2*4328) = min(4328, 2062.2) = 2.0622 kN.
    # n_eff = 4^0.85 = 3.2490 -> group = 6.700 kN.
    res = features.run(
        "libraryMasonry.nailCapacity",
        None,
        {
            "nailDiaMm": 4.0,
            "memberThicknessMm": 40.0,
            "timberDensityKgPerM3": 500.0,
            "nailCount": 4.0,
            "doubleShear": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["perNailKn"] == pytest.approx(2.0622, rel=0.01)
    assert res["summary"]["effectiveFasteners"] == pytest.approx(3.2490, rel=0.01)
    assert res["summary"]["groupCapacityKn"] == pytest.approx(6.700, rel=0.01)


def test_materials_masonry_reinforcement_grout() -> None:
    # clearance = (80 - 20)/2 = 30 mm >= 20; req_grout = max(14, 15) = 15 MPa <= 18 -> both ok.
    res = features.run(
        "libraryMasonry.reinforcementGrout",
        None,
        {"cellWidthMm": 80.0, "barDiaMm": 20.0, "groutStrengthMpa": 18.0, "fmMpa": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["sideClearanceMm"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["requiredGroutMpa"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["strengthOk"] is True
    assert res["summary"]["clearanceOk"] is True


def test_materials_masonry_shear_strength() -> None:
    # fv_raw = 0.30 + 0.50*1.00 = 0.80 MPa <= min(0.065*15, 1.7) = 0.975 MPa.
    res = features.run(
        "libraryMasonry.shearStrength",
        None,
        {
            "fvk0Mpa": 0.30,
            "frictionCoeff": 0.50,
            "precompressionMpa": 1.00,
            "unitStrengthMpa": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["shearStrengthMpa"] == pytest.approx(0.80, rel=0.01)
    assert res["summary"]["shearCapMpa"] == pytest.approx(0.975, rel=0.01)


# ── Materials Mapping (materials_mapping.py: 4) ────────────────────────────────────────────────────


def test_materials_mapping_modulus_mapping() -> None:
    # 100 GPa = 100000 MPa; nu=0.25 -> G = 100000 / 2.5 = 40000 MPa; 100000 / 6.894757 = 14503.77 ksi.
    res = features.run(
        "materialsMapping.modulusMapping",
        None,
        {"elasticModulus": 100.0, "unit": "GPa", "poisson": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["eMpa"] == pytest.approx(100000.0, rel=0.01)
    assert res["summary"]["gMpa"] == pytest.approx(40000.0, rel=0.01)
    assert res["summary"]["eKsi"] == pytest.approx(14503.77, rel=0.01)


def test_materials_mapping_thermal_coefficient() -> None:
    # 1.0e-4 /F * 1.8 = 1.8e-4 /C = 180.0 microstrain/C.
    # Note: features.result() rounds floats to 4 decimals, so 1/C and 1/F are preserved in the table as scientific strings.
    res = features.run(
        "materialsMapping.thermalCoefficient",
        None,
        {"alpha": 1.0e-4, "fromUnit": "perF"},
    )
    assert res["problems"] == []
    assert res["summary"]["microstrainPerC"] == pytest.approx(180.0, rel=0.01)
    assert float(_row_by(res, "unit", "1/C")["value"]) == pytest.approx(1.8e-4, rel=0.01)
    assert float(_row_by(res, "unit", "1/F")["value"]) == pytest.approx(1.0e-4, rel=0.01)


def test_materials_mapping_translate_density() -> None:
    # 20 kN/m3 -> 20000 / 9.80665 = 2039.43 kg/m3, 2.03943 g/cm3, 2039.43 / 16.018463 = 127.318 pcf.
    res = features.run(
        "materialsMapping.translateDensity",
        None,
        {"density": 20.0, "fromUnit": "kN_m3", "materialId": ""},
    )
    assert res["problems"] == []
    assert res["summary"]["kgPerM3"] == pytest.approx(2039.43, rel=0.01)
    assert res["summary"]["knPerM3"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["gPerCm3"] == pytest.approx(2.03943, rel=0.01)
    assert res["summary"]["pcf"] == pytest.approx(127.318, rel=0.01)


def test_materials_mapping_yield_equivalent() -> None:
    # 50 ksi = 50 * 6.894757 = 344.738 MPa; Ry=1.2 -> expected = 413.685 MPa.
    res = features.run(
        "materialsMapping.yieldEquivalent",
        None,
        {"fyValue": 50.0, "fromUnit": "ksi", "overstrengthFactor": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["nominalFyMpa"] == pytest.approx(344.738, rel=0.01)
    assert res["summary"]["nominalFyKsi"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["expectedFyMpa"] == pytest.approx(413.685, rel=0.01)


# ── Materials Steel (materials_steel.py: 19) ───────────────────────────────────────────────────────


def test_materials_steel_bauschinger_effect() -> None:
    # fy=400, E0=200000 (eps_y=0.002), xiPlastic=0.01 -> xi = 0.01/0.002 = 5.0.
    # R_eff = 20 - (0.925 * 5.0) / (0.15 + 5.0) = 20 - 4.625 / 5.15 = 19.1019.
    res = features.run(
        "materialsSteel.bauschingerEffect",
        None,
        {"fyMpa": 400.0, "modulusMpa": 200000.0, "bRatio": 0.02, "r0": 20.0, "xiPlastic": 0.01},
    )
    assert res["problems"] == []
    assert res["summary"]["degradedR"] == pytest.approx(19.1019, rel=0.01)


def test_materials_steel_bearing_strength() -> None:
    # d=20 (hole=22), t=12, fu=450, e1=35 (lc_edge=24), p1=70 (lc_inner=48).
    # Default pack BNBC 2020: phi*1.2*lc*t*fu = 0.75*1.2*24*12*450/1e3 = 116.64 kN (end);
    # inner governed by 0.75*2.4*20*12*450/1e3 = 194.40 kN.
    res = features.run(
        "materialsSteel.bearingStrength",
        None,
        {
            "boltDiaMm": 20.0,
            "plateThicknessMm": 12.0,
            "plateFuMpa": 450.0,
            "edgeDistanceMm": 35.0,
            "spacingMm": 70.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["holeDiameterMm"] == pytest.approx(22.0, rel=0.01)
    assert res["summary"]["endBoltBearingKn"] == pytest.approx(116.64, rel=0.01)
    assert res["summary"]["innerBoltBearingKn"] == pytest.approx(194.40, rel=0.01)


def test_materials_steel_bolt_grades() -> None:
    # M24 (Ab = 452.389 mm^2), A325N (BNBC 2020: phi=0.75, Fnv=330 MPa, Fnt=620 MPa):
    # shear = 0.75 * 330 * 452.389 / 1e3 = 111.966 kN; tension = 0.75 * 620 * 452.389 / 1e3 = 210.361 kN.
    res = features.run("materialsSteel.boltGrades", None, {"boltDiaMm": 24.0})
    assert res["problems"] == []
    row = _row_by(res, "grade", "A325N")
    assert row["shearKn"] == pytest.approx(111.966, rel=0.01)
    assert row["tensionKn"] == pytest.approx(210.361, rel=0.01)


def test_materials_steel_charpy_value() -> None:
    # seismicDemand=True raises req from 20 J to 27 J; measured=30 J >= 27 J -> toughnessOk=True.
    res = features.run(
        "materialsSteel.charpyValue",
        None,
        {
            "measuredEnergyJ": 30.0,
            "requiredEnergyJ": 20.0,
            "testTempC": -10.0,
            "seismicDemand": True,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredEnergyJ"] == pytest.approx(27.0, rel=0.01)
    assert res["summary"]["toughnessOk"] is True


def test_materials_steel_cold_formed_modulus() -> None:
    # fyb=280, fub=420 (ratio=1.5), t=2, r=2 (r/t=1), 4 bends, Ag=500:
    # Bc = 3.69*1.5 - 0.819*2.25 - 1.79 = 1.90225 -> fyc = min(420, 1.90225*280) = 420.0 MPa.
    # Ac = 4*(pi/2)*2*(2+1) = 37.6991 mm^2 -> fya = 280 + (420-280)*(37.6991/500) = 290.556 MPa.
    res = features.run(
        "materialsSteel.coldFormedModulus",
        None,
        {
            "virginFyMpa": 280.0,
            "virginFuMpa": 420.0,
            "thicknessMm": 2.0,
            "bendRadiusMm": 2.0,
            "cornerCount": 4.0,
            "grossAreaMm2": 500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["cornerFyMpa"] == pytest.approx(420.0, rel=0.01)
    assert res["summary"]["averageFyMpa"] == pytest.approx(290.556, rel=0.01)


def test_materials_steel_endurance_limit() -> None:
    # Default pack category C threshold F_TH = 69.0 MPa -> appliedRange=100.0 fails infiniteLife on C.
    res = features.run("materialsSteel.enduranceLimit", None, {"appliedRangeMpa": 100.0})
    assert res["problems"] == []
    row_c = _row_by(res, "category", "C")
    assert row_c["thresholdMpa"] == pytest.approx(69.0, rel=0.01)
    assert row_c["infiniteLife"] is False


def test_materials_steel_fatigue_category() -> None:
    # 200 cycles/day * 365 * 50 yr = 3,650,000 cycles; applied=50 MPa < F_TH(C)=69 MPa -> ok=True.
    res = features.run(
        "materialsSteel.fatigueCategory",
        None,
        {
            "category": "C",
            "cyclesPerDay": 200.0,
            "designLifeYears": 50.0,
            "stressRangeMpa": 50.0,
            "maxServiceStressMpa": 150.0,
            "fyMpa": 345.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalCycles"] == 3_650_000
    assert res["summary"]["ok"] is True


def test_materials_steel_residual_stress_profile() -> None:
    # Rolled, h/b=1.1 (<=1.2 -> -0.50*fy), fy=300 -> peakComp=-150.0 MPa, peakTens=90.0 MPa.
    res = features.run(
        "materialsSteel.residualStressProfile",
        None,
        {"fabrication": "rolled", "depthWidthRatio": 1.1, "fyMpa": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakCompressiveMpa"] == pytest.approx(-150.0, rel=0.01)
    assert res["summary"]["peakTensileMpa"] == pytest.approx(90.0, rel=0.01)


def test_materials_steel_shear_plane() -> None:
    # A325N M20: BNBC singlePlane = 77.754 kN; 2 planes -> 155.509 kN/bolt; 5 bolts -> 777.54 kN.
    res = features.run(
        "materialsSteel.shearPlane",
        None,
        {"boltGrade": "A325N", "boltDiaMm": 20.0, "planes": "2", "boltCount": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["singlePlaneKn"] == pytest.approx(77.754, rel=0.01)
    assert res["summary"]["perBoltKn"] == pytest.approx(155.509, rel=0.01)
    assert res["summary"]["groupCapacityKn"] == pytest.approx(777.54, rel=0.01)


def test_materials_steel_strain_hardening() -> None:
    # E0=200000, fy=400 (eps_y=0.002), b=0.02 -> E_sh=4000 MPa.
    # eps=0.012 -> eps_p=0.010 -> sigma = 400 + 4000*0.01 = 440.0 MPa (overstrength=1.10).
    res = features.run(
        "materialsSteel.strainHardening",
        None,
        {"modulusMpa": 200000.0, "fyMpa": 400.0, "hardeningRatioB": 0.02, "targetStrain": 0.012},
    )
    assert res["problems"] == []
    assert res["summary"]["hardeningModulusMpa"] == pytest.approx(4000.0, rel=0.01)
    assert res["summary"]["plasticStrain"] == pytest.approx(0.010, rel=0.01)
    assert res["summary"]["stressAtTargetMpa"] == pytest.approx(440.0, rel=0.01)
    assert res["summary"]["overstrengthRatio"] == pytest.approx(1.10, rel=0.01)


def test_materials_steel_stress_strain_curve() -> None:
    # fy=400, fu=520, E=200000 -> eps_y=0.002; eps_sh=0.02, eps_u=0.12.
    # hardeningModulus = (520-400)/(0.12-0.02) = 1200.0 MPa; ductility = 0.12/0.002 = 60.0.
    res = features.run(
        "materialsSteel.stressStrainCurve",
        None,
        {
            "fyMpa": 400.0,
            "fuMpa": 520.0,
            "modulusMpa": 200000.0,
            "hardeningStrain": 0.02,
            "ultimateStrain": 0.12,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["yieldStrain"] == pytest.approx(0.002, rel=0.01)
    assert res["summary"]["hardeningModulusMpa"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["ductilityRatio"] == pytest.approx(60.0, rel=0.01)


def test_materials_steel_test_temperature() -> None:
    # T_serv=-5, t=32 (>12 -> -0.7*20=-14), stressRatio=0.70 (>0.5 -> -25*0.2=-5) -> T_req = -24.0 C.
    res = features.run(
        "materialsSteel.testTemperature",
        None,
        {"serviceTempC": -5.0, "thicknessMm": 32.0, "stressRatio": 0.70},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredTestTempC"] == pytest.approx(-24.0, rel=0.01)
    assert res["summary"]["recommendedSubgrade"].startswith("K2")


def test_materials_steel_thermal_softening() -> None:
    # Midpoint 550 C between 500 C (ky=0.78, ke=0.60) and 600 C (ky=0.47, ke=0.31):
    # ky = 0.625, ke = 0.455 -> fy(550) = 400*0.625 = 250.0 MPa, E(550) = 200000*0.455 = 91000.0 MPa.
    res = features.run(
        "materialsSteel.thermalSoftening",
        None,
        {"fyMpa": 400.0, "modulusMpa": 200000.0, "steelTempC": 550.0},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldRetentionKy"] == pytest.approx(0.625, rel=0.01)
    assert res["summary"]["modulusRetentionKe"] == pytest.approx(0.455, rel=0.01)
    assert res["summary"]["reducedFyMpa"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["reducedModulusMpa"] == pytest.approx(91000.0, rel=0.01)


def test_materials_steel_thickness_effect() -> None:
    # baseFy=355, t=50 mm (40 < t <= 63 -> drop=20) -> effectiveFy = 335.0 MPa, factor = 335/355 = 0.94366.
    res = features.run(
        "materialsSteel.thicknessEffect", None, {"baseFyMpa": 355.0, "thicknessMm": 50.0}
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveFyMpa"] == pytest.approx(335.0, rel=0.01)
    assert res["summary"]["reductionFactor"] == pytest.approx(335.0 / 355.0, rel=0.01)


def test_materials_steel_ultimate_strength() -> None:
    # fy=300, fu=450 -> fu/fy = 1.50 >= 1.25 (BNBC 2020), elong=20 >= 15 -> ductilityOk=True.
    res = features.run(
        "materialsSteel.ultimateStrength",
        None,
        {"fyMpa": 300.0, "fuMpa": 450.0, "elongationPct": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["fuFyRatio"] == pytest.approx(1.50, rel=0.01)
    assert res["summary"]["ductilityOk"] is True


def test_materials_steel_weld_strength() -> None:
    # leg=10 mm -> throat = 7.07 mm; BNBC 2020 fillet: phi*0.6*FEXX*0.707*w = 0.75*0.6*480*0.707*10 = 1527.12 N/mm.
    # L=250 mm -> 1.52712 * 250 = 381.78 kN.
    res = features.run(
        "materialsSteel.weldStrength",
        None,
        {"legMm": 10.0, "electrodeMpa": 480.0, "lengthMm": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["throatMm"] == pytest.approx(7.07, rel=0.01)
    assert res["summary"]["capacityKnPerMm"] == pytest.approx(1.52712, rel=0.01)
    assert res["summary"]["totalCapacityKn"] == pytest.approx(381.78, rel=0.01)


def test_materials_steel_weldability() -> None:
    # CEV = 0.20 + 1.20/6 + 0.20/5 + 0.30/15 = 0.20 + 0.20 + 0.04 + 0.02 = 0.46%.
    # Pcm = 0.20 + 0.30/30 + 1.20/20 + 0.30/60 + 0.20/15 = 0.28833%.
    # 0.45 < CEV <= 0.50 -> preheat = 125 C.
    res = features.run(
        "materialsSteel.weldability",
        None,
        {
            "carbonPct": 0.20,
            "manganesePct": 1.20,
            "crMoVPct": 0.20,
            "niCuPct": 0.30,
            "siliconPct": 0.30,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["cevPercent"] == pytest.approx(0.46, rel=0.01)
    assert res["summary"]["pcmPercent"] == pytest.approx(0.28833, rel=0.01)
    assert res["summary"]["suggestedPreheatC"] == pytest.approx(125.0, rel=0.01)


def test_materials_steel_yield_strength() -> None:
    # BNBC 2020 Ry(A992, rolled) = 1.0 -> expectedFy = 345.0; millFy=380.0 overrides actualOrExpected.
    res = features.run(
        "materialsSteel.yieldStrength",
        None,
        {"nominalFyMpa": 345.0, "grade": "A992", "millFyMpa": 380.0},
    )
    assert res["problems"] == []
    assert res["summary"]["expectedFactorRy"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["expectedFyMpa"] == pytest.approx(345.0, rel=0.01)
    assert res["summary"]["actualOrExpectedMpa"] == pytest.approx(380.0, rel=0.01)


def test_materials_steel_z_quality() -> None:
    # z_a = min(15, 0.25*20)=5, z_b = min(8, 0.25*32)=8, z_d(medium)=5 -> Z_Ed = 18.0 -> Z15, sulfur 0.008 <= 0.010 ok.
    res = features.run(
        "materialsSteel.zQuality",
        None,
        {
            "plateThicknessMm": 32.0,
            "weldThroatMm": 20.0,
            "restraint": "medium",
            "sulfurPct": 0.008,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["zDemandIndex"] == pytest.approx(18.0, rel=0.01)
    assert res["summary"]["requiredZClass"] == "Z15"
    assert res["summary"]["sulfurLimitOk"] is True


# ── Materials Test Data (materials_tests.py: 12) ───────────────────────────────────────────────────


def test_materials_tests_add_sample() -> None:
    # C24.1 default spec = 24.1 MPa; measured = 26.0 MPa -> passesSpec=True.
    res = features.run(
        "materialsTests.addSample",
        None,
        {"sampleId": "S-99", "materialId": "C24.1", "batchRef": "B-9", "measuredMpa": 26.0},
    )
    assert res["problems"] == []
    assert res["summary"]["specifiedMpa"] == pytest.approx(24.1, rel=0.01)
    assert res["summary"]["passesSpec"] is True


def test_materials_tests_batch_acceptance() -> None:
    # [30, 32, 34]: mean=32 >= 30, min=30 >= 27 -> accepted=True.
    res = features.run(
        "materialsTests.batchAcceptance",
        None,
        {"valuesMpa": "30, 32, 34", "specifiedMpa": 30.0, "minIndividualOffsetMpa": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["batchMeanMpa"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["batchMinMpa"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["accepted"] is True


def test_materials_tests_conformance_score() -> None:
    # [30, 30, 30, 30], spec=30, certs=True:
    # mean=30 -> margin_pts=25, cov=0 -> consistency_pts=40, doc_pts=20 -> score=85.0 ("Excellent").
    res = features.run(
        "materialsTests.conformanceScore",
        None,
        {"valuesMpa": "30, 30, 30, 30", "specifiedMpa": 30.0, "certificatesVerified": True},
    )
    assert res["problems"] == []
    assert res["summary"]["conformanceScore"] == pytest.approx(85.0, rel=0.01)
    assert res["summary"]["rating"] == "Excellent"


def test_materials_tests_deviation() -> None:
    # [27, 30, 33] vs 30 (-10%, 0%, +10%), tol=5% -> flaggedCount=1, maxNegativePct=-10.0.
    res = features.run(
        "materialsTests.deviation",
        None,
        {"measuredMpa": "27.0, 30.0, 33.0", "targetMpa": 30.0, "tolerancePct": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flaggedCount"] == 1
    assert res["summary"]["maxNegativePct"] == pytest.approx(-10.0, rel=0.01)


def test_materials_tests_machine_calibration() -> None:
    # 200*1.05 - 10 = 200 (0%); 400*1.05 - 10 = 410 (+2.5%) -> maxCorrectionPct = 2.5%.
    res = features.run(
        "materialsTests.machineCalibration",
        None,
        {"rawLoadsKn": "200, 400", "gainFactor": 1.05, "zeroOffsetKn": -10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxCorrectionPct"] == pytest.approx(2.5, rel=0.01)


def test_materials_tests_measured_value() -> None:
    # [400, 500, 600] kN / 20000 mm^2 -> [20, 25, 30] MPa -> mean=25, min=20, max=30.
    res = features.run(
        "materialsTests.measuredValue",
        None,
        {"loadsKn": "400, 500, 600", "areaMm2": 20000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["meanStressMpa"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["minStressMpa"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["maxStressMpa"] == pytest.approx(30.0, rel=0.01)


def test_materials_tests_outlier_filter() -> None:
    # [29, 30, 30, 31, 10]: median=30, MAD=1 -> Z(10) = 0.6745*(-20)/1 = -13.49 -> 1 outlier, filtered mean = 30.0.
    res = features.run(
        "materialsTests.outlierFilter",
        None,
        {"valuesMpa": "29, 30, 30, 31, 10", "zThreshold": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["outlierCount"] == 1
    assert res["summary"]["filteredMeanMpa"] == pytest.approx(30.0, rel=0.01)


def test_materials_tests_qa_summary() -> None:
    # [30, 32, 34, 36], spec=31 -> mean=33.0, s=2.58199, fk=33 - 1.645*2.58199 = 28.7526, passRate = 3/4 = 75%.
    res = features.run(
        "materialsTests.qaSummary",
        None,
        {"valuesMpa": "30, 32, 34, 36", "specifiedMpa": 31.0, "writeReport": False},
    )
    assert res["problems"] == []
    assert res["summary"]["meanMpa"] == pytest.approx(33.0, rel=0.01)
    assert res["summary"]["characteristicMpa"] == pytest.approx(28.7526, rel=0.01)
    assert res["summary"]["passRatePercent"] == pytest.approx(75.0, rel=0.01)


def test_materials_tests_sample_date() -> None:
    # 7 days: beta = exp(0.25*(1 - sqrt(28/7))) = exp(-0.25) = 0.778801.
    # 21.0 / 0.778801 = 26.9645 MPa < 28.0 -> meetsTarget28Day=False.
    res = features.run(
        "materialsTests.sampleDate",
        None,
        {
            "castDate": "2026-03-01",
            "testDate": "2026-03-08",
            "measuredMpa": 21.0,
            "target28Mpa": 28.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["ageDays"] == 7
    assert res["summary"]["maturityFactor"] == pytest.approx(math.exp(-0.25), rel=0.01)
    assert res["summary"]["projected28DayMpa"] == pytest.approx(26.9645, rel=0.01)
    assert res["summary"]["meetsTarget28Day"] is False


def test_materials_tests_supplier_record() -> None:
    # Pure record-keeping lookup/echo of supplier, ticket, material, and delivered quantity.
    res = features.run(
        "materialsTests.supplierRecord",
        None,
        {"supplier": "Plant A", "deliveryRef": "T-99", "materialId": "C31", "quantity": 55.5},
    )
    assert res["problems"] == []
    assert res["summary"]["supplier"] == "Plant A"
    assert res["summary"]["deliveryRef"] == "T-99"
    assert res["summary"]["materialId"] == "C31"
    assert res["summary"]["quantity"] == pytest.approx(55.5, rel=0.01)


def test_materials_tests_test_type() -> None:
    # 150 mm cube: area = 22500 mm^2, conv = 0.80 -> 900 kN = 40.0 MPa raw -> 32.0 MPa equiv cylinder.
    res = features.run(
        "materialsTests.testType",
        None,
        {"testKind": "cube_150", "failureLoadKn": 900.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(22500.0, rel=0.01)
    assert res["summary"]["rawStressMpa"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["convertedStrengthMpa"] == pytest.approx(32.0, rel=0.01)


def test_materials_tests_verify_certificate() -> None:
    # fy_spec=400, fy_act=480 (+80 <= 125 BNBC margin), fu_act=624 (ratio 1.30 >= 1.25 BNBC min) -> verified=True.
    res = features.run(
        "materialsTests.verifyCertificate",
        None,
        {"specifiedFyMpa": 400.0, "actualFyMpa": 480.0, "actualFuMpa": 624.0},
    )
    assert res["problems"] == []
    assert res["summary"]["overstrengthMpa"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["fuFyRatio"] == pytest.approx(1.30, rel=0.01)
    assert res["summary"]["verified"] is True
