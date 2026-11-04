# is-codes: values to verify against the printed codes

No copy of the IS codes was available when this pack was written (alpha 9, track C7,
2026-11-04). Every value below was entered from reliable knowledge of the codes and is to be
checked by the owner against the printed edition. **Sure**: well-known value, low risk.
**Check**: believed right, confirm the number or the row. **Uncertain**: the value or its reading
may be wrong; SAEngine's choice is stated.

## IS 1893 (Part 1):2016

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | zoneCoefficients.zones | II 0.10, III 0.16, IV 0.24, V 0.36 | Table 3 | Zone factor Z | Sure |
| 2 | occupancyCategories.*.seismicImportance | 1.5 / 1.2 / 1.0 | Table 8 | Critical and lifeline; business continuity (and > 200 persons, its note); others | Check (row wording, the 200-person note) |
| 3 | seismic.designSpectrum.factor | 0.5 | 6.4.2 | Ah = (Z/2)(I/R)(Sa/g) | Sure |
| 4 | seismic.siteClasses.*.TC | 0.40, 0.544, 0.668 s | 6.4.2, Fig. 2 | End of the plateau so that 2.5 TC/T = 1.00/T, 1.36/T, 1.67/T; the code prints the plateau to 0.40 / 0.55 / 0.67 s | Check (the printed ends differ by < 1.2 %) |
| 5 | seismic.siteClasses.*.TD | 4.0 s | 6.4.2 | Sa/g constant beyond 4 s (0.25, 0.34, 0.42) | Check |
| 6 | seismic.siteClasses.*.TB | 0.10 s | 6.4.2 | Rising branch 1 + 15T of the response spectrum method | Sure |
| 7 | seismic.designSpectrum.staticPlateau | true | 6.4.2, Fig. 2(a) | Equivalent static method: Sa/g = 2.5 from T = 0 | Check |
| 8 | seismic.siteClasses descriptions | Types I, II, III | Table 4 | Rock or hard soil (N > 30), medium (10-30), soft (< 10) | Check (N limits) |
| 9 | seismic.systems.rcOmf.R | 3.0 | Table 9 (i)(a) | RC OMRF | Sure |
| 10 | seismic.systems.rcSmf.R | 5.0 | Table 9 (i)(b) | RC SMRF | Sure |
| 11 | seismic.systems.steelOmf.R / steelSmf.R | 3.0 / 5.0 | Table 9 (i)(c)(d) | Steel OMRF / SMRF | Sure |
| 12 | seismic.systems.steelScbf.R / steelEbf.R | 4.0 / 5.0 | Table 9 (ii) | Steel concentric / eccentric braced frames | Check |
| 13 | seismic.systems.masonry*.R | 1.5 / 2.0 / 2.5 | Table 9 (iii)(a) | URM without bands / with bands / bands and vertical bars | Check |
| 14 | seismic.systems.rcOrdinaryWallFrame.R / rcSpecialWallFrame.R | 3.0 / 4.0 | Table 9 (iii)(b)(c) | Ordinary / ductile RC structural walls | Sure |
| 15 | seismic.systems.rcDual*.R | 3.0 / 4.0 / 4.5 / 5.0 | Table 9 (iv)(a)-(d) | Ordinary walls + OMRF / + SMRF; ductile walls + OMRF / + SMRF | Check |
| 16 | seismic.systems.rcFlatSlabWalls.R | 3.0 | Table 9 (v) | Flat slab with ductile RC structural walls | Uncertain (row wording) |
| 17 | seismic.systems.*.heightLimits | 0 in categories C, D for the ordinary systems | Table 9 notes | OMRF and ordinary RC walls not permitted in zones III-V | Uncertain (SAEngine reading of the note) |
| 18 | seismic.systems.*.Cd | = R | 7.11.3 | The displacement estimate is R times the elastic one (used for the separation only) | Check (SAEngine reading) |
| 19 | seismic.systems.*.Omega0 | 2.5 | none | IS gives no system overstrength; 2.5 where the design names Ω0 | Uncertain (SAEngine practice) |
| 20 | seismic.periodCoefficients.concreteMomentFrame | 0.075 h^0.75 | 7.6.2(a) | Bare RC moment frame | Sure |
| 21 | seismic.periodCoefficients.steelMomentFrame | 0.085 h^0.75 | 7.6.2(a) | Bare steel moment frame | Sure |
| 22 | seismic.periodCoefficients.other | 0.09 h / √d | 7.6.2(c) | All other buildings, d the base dimension along the shaking; the wall form 7.6.2(b) 0.075 h^0.75/√Aw is not modelled | Check |
| 23 | seismic.periodUpperFactor | 1.0 | 7.6.2, 7.7.3 | The base shear uses Ta; a modal period is not taken above it | Uncertain (reading) |
| 24 | seismic.lateralForce.minimumShare | 0.007 / 0.011 / 0.016 / 0.024 | 7.2.2, Table 7 | Least VB / W in zones II-V | Check |
| 25 | seismic.lateralForce.distribution | heightSquared | 7.6.3 | Qi = VB Wi hi² / Σ Wj hj² | Sure |
| 26 | seismic.minimumScale | 1.0 | 7.7.3 | Dynamic base shear scaled up to VB of Ta | Sure |
| 27 | seismic.massParticipation | 0.90 | 7.7.5.2 | Modes to 90 % of the mass | Sure |
| 28 | seismic.orthogonalShare | 0.30 | 6.3.4.1 | 100 % + 30 % | Sure |
| 29 | seismic.irregularities.nonparallelOrthogonal | ["C"] | 6.3.2.2 | 100 % + 30 % for non-orthogonal systems (zones III-V as category C); orthogonal systems one direction at a time | Check (reading) |
| 30 | seismic.accidentalEccentricity | 0.05 | 7.8.2 | ± 0.05 bi; the 1.5 esi amplification is not modelled | Check |
| 31 | seismic.allowableDrift | 0.004 | 7.11.1.1 | Storey drift under the design force, load factor 1.0 | Sure |
| 32 | seismic.driftAmplification | designForces | 7.11.1 | Drift checked as computed from the design forces | Sure |
| 33 | seismic.separation | sum, × 0.5 for equal floor levels | 7.11.3 | R × (Δ1 + Δ2); R/2 where the floors align | Check |
| 34 | seismic.liveShare / heavyLiveLimit / heavyLiveShare | 0.25 / 3.0 / 0.5 | 7.3.1, Table 10 | Imposed load in the seismic weight | Sure |
| 35 | seismic.torsionIrregular / torsionExtreme | 1.0909 / 1.1667 | Table 5 (i) | Δmax > 1.2 / 1.4 Δmin, as Δmax/Δavg of the two ends | Check (conversion) |
| 36 | seismic.torsionAmplificationMax | 1.0 | Table 5 (i) | No Ax: a torsionally irregular building needs the 3D dynamic analysis | Check |
| 37 | seismic.irregularities.reentrantProjection | 0.15 | Table 5 (ii) | Re-entrant corner projection > 15 % | Sure |
| 38 | seismic.irregularities.openingShare | 0.50 | Table 5 (iii) | Slab openings > 50 % | Sure |
| 39 | seismic.irregularities.soft / weak | storey above × 1.0 | Table 6 (i), (v) | Stiffness / strength less than the storey above (2016 wording) | Check |
| 40 | seismic.irregularities.mass | 2.0 | Table 6 (ii) | Seismic weight > 2 × an adjacent storey | Check |
| 41 | seismic.irregularities.geometry | 1.25 | Table 6 (iii) | Plan dimension > 125 % of the storey below | Check |
| 42 | seismic.dynamicAnalysis | zone II regular 15 m; else 0 | 7.7.1 | Dynamic analysis for all buildings but regular ones below 15 m in zone II | Uncertain (7.7.1 wording) |
| 43 | seismic.pgaFactor | 0.5 | 6.4.2 | PGA of the design basis earthquake Z/2 (liquefaction, retaining walls) | Check |
| 44 | seismic.verticalFactor | 0 | 6.3.3.1 | Vertical motion not applied (only for the structures the clause lists) | Check |
| 45 | seismic.designCategories | zone II → B, III-V → C | none | SAEngine practice: no SDC in IS | SAEngine practice |
| 46 | seismic.requiredDetailing | B ordinary, C/D special | IS 13920:2016 Clause 1 | Ductile detailing in zones III-V | Check |
| 47 | seismic.dampingCorrection | none | 6.4.2, Table 4 | Damping factors other than 5 % not modelled | Not covered |
| 48 | locations.*.zone | 67 cities | Annex E | City zones (Delhi IV, Mumbai III, Kolkata III, Chennai III, Guwahati V, Bhuj V, Srinagar V, Bengaluru II ...) | Check every row |

## IS 875 (Part 3):2015 (wind)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 49 | locations.*.windSpeed | 33-55 m/s | Annex A, Fig. 1 | Basic wind speed of the 67 cities (Delhi 47, Mumbai 44, Kolkata 50, Chennai 50, Darbhanga 55, Bengaluru 33 ...) | Check every row |
| 50 | wind.speedFactors.riskCoefficients | 25-year 0.94-0.89; 50-year 1.0; 100-year 1.05-1.08 by Vb 33-55 | 6.3.1, Table 1 | k1 | Check |
| 51 | wind.speedFactors.heightFactors | Table 2 rows, categories 1-4, 10-500 m | 6.3.2, Table 2 | k2 | Uncertain (category 4 below 30 m and the 2015 values above 50 m) |
| 52 | wind.topographic | 1.0 | 6.3.3 | k3 for upwind slope < 3° (Annex C not modelled) | Sure |
| 53 | wind.speedFactors.importance | 1.0 (rows 1.30 / 1.15 / 1.0) | 6.3.4 | k4 cyclonic importance | Check |
| 54 | wind.speedFactors.airFactor | 0.6 | 6.4 | pz = 0.6 Vz² | Sure |
| 55 | wind.directionality | 0.90 | 7.2.1 | Kd for buildings (1.0 in cyclonic regions: override) | Check |
| 56 | wind.speedFactors.areaAveraging | 1.0 (rows 1.0 / 0.9 / 0.8 at 10 / 25 / 100 m²) | 7.2.2, Table 4 | Ka; SAEngine takes 1.0 for the storey forces | Check |
| 57 | wind.speedFactors.combination | 0.9 | 7.3.3.13 | Kc for framed buildings | Uncertain (clause number and scope) |
| 58 | wind.speedFactors.minimumShare | 0.7 | 7.2 | pd ≥ 0.7 pz | Check |
| 59 | wind.cpByHeight | h/w ≤ 1/2: +0.7, -0.2 / -0.25; ≤ 3/2: +0.7, -0.25 / -0.3; < 6: +0.8, -0.25 / -0.4 | 7.3.3.1, Table 5 | Wall Cpe, windward A and leeward B, by l/w ≤ 3/2 and up to 4 | Uncertain (the h/w > 3/2 row) |
| 60 | wind.gust | 1.0 | 7 | Static method; the gust factor method (Clause 10) is not covered | Check |
| 61 | wind.exposures | terrain categories 1-4 | 6.3.2.1 | Descriptions | Check |

## IS 875 (Part 2):1987 (imposed loads)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 62 | areaLoads.uses.residential | 2.0, 1.8 kN | Table 1 (i) | Dwelling rooms, kitchens, toilets | Sure |
| 63 | areaLoads.uses.residentialPublic / balcony | 3.0 | Table 1 (i) | Corridors, staircases; balconies | Check |
| 64 | areaLoads.uses.office / officeComputer / officeCorridor | 2.5 / 3.5 / 4.0 | Table 1 (iv) | Offices | Check (computer rooms 3.5 or 4.0) |
| 65 | areaLoads.uses.classroom / schoolCorridor | 3.0 / 4.0 | Table 1 (ii) | Educational | Sure |
| 66 | areaLoads.uses.hospitalWard / operatingRoom / hospitalCorridor | 2.0 / 3.0 / 4.0 | Table 1 (iii) | Institutional | Check |
| 67 | areaLoads.uses.assemblyFixed / assemblyMovable / dining / gymnasium / stageFloor | 4.0 / 5.0 / 4.0 / 5.0 / 5.0 | Table 1 (iv) assembly | Assembly | Check |
| 68 | areaLoads.uses.retailUpper / wholesale | 4.0 / 5.0 | Table 1 (vi) | Mercantile | Check |
| 69 | areaLoads.uses.manufacturing* | 5.0 / 7.0 / 10.0 | Table 1 (vii) | Industrial, light / medium / heavy | Check |
| 70 | areaLoads.uses.storageLight | 7.5 (2.4 per m height) | Table 1 (viii) | Storage | Uncertain (the minimum) |
| 71 | areaLoads.uses.libraryStacks | 6.0 | Table 1 | Stack rooms, 2.2 m | Uncertain |
| 72 | areaLoads.uses.parking | 2.5, 9.0 kN | Table 1 | Garages for vehicles up to 2.5 t | Check |
| 73 | areaLoads.uses.stairs / stairsDwelling | 4.0 / 3.0 | Table 1 | Stairs | Check |
| 74 | areaLoads.uses.roof / roofAccess | 0.75, 0.9 kN / 1.5, 1.8 kN | Table 2 (i) | Flat roof up to 10°, without / with access | Check (concentrated values) |
| 75 | areaLoads.uses.*.concentrated | 1.8-9.0 kN | Table 1 | Concentrated loads of the rows | Uncertain (several rows) |
| 76 | areaLoads.concentratedPatch | 300 mm | 3.1.1 | Area of a concentrated load | Check |
| 77 | areaLoads.partitions | 1/3 of the weight per m, ≥ 1.0 kN/m², up to 4.0 kN/m | 3.1.2 | Partition allowance | Uncertain (the 4.0 kN/m limit) |
| 78 | liveReduction.floorCount.rows | 1 0 %, 2 10 %, 3 20 %, 4 30 %, 5-10 40 %, > 10 50 % | 3.2.1, Table 3 | Floors carried, including the roof | Check (whether SAEngine's floor count includes the roof) |
| 79 | liveReduction.floorCount.beam* | 5 % per 50 m², ≤ 25 % | 3.2.2 | Beams | Check |
| 80 | liveReduction.notReduced / heavyLive | storage, industrial, wholesale, parking; > 5.0 kN/m² | 3.2.1 | Not reduced | Uncertain (SAEngine reading) |

## IS 875 (Part 1):1987 (dead loads)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 81 | deadLoads.masonry.burntClayBrick | 18.85 kN/m³ | Table 1 | Common burnt clay brick masonry (1920 kg/m³) | Check |
| 82 | deadLoads.plaster.cement | 20.4 kN/m³ | Table 1 | Cement mortar (2080 kg/m³) as plaster | Check |
| 83 | deadLoads.wallTypes | 230 and 115 mm, 12 mm plaster | none | SAEngine choice of Indian practice | SAEngine practice |

## IS 875 (Part 5):1987, IS 456:2000 Table 18 (combinations)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 84 | combinations.strength 1 | 1.5(D + L) | IS 456 Table 18; IS 875-5 8.4 | Gravity | Sure |
| 85 | combinations.strength 2W / 2E | 1.2(D + L ± W/E) | IS 456 Table 18; IS 1893 6.3.4.1 | With wind / earthquake | Sure |
| 86 | combinations.strength 3W / 3E | 1.5(D ± W/E) | as above | | Sure |
| 87 | combinations.strength 4W / 4E | 0.9D ± 1.5(W/E) | as above | Dead load favourable | Sure |
| 88 | combinations.service | D + L; D + W; D + 0.8L + 0.8W | IS 456 Table 18 (serviceability) | Service | Check |
| 89 | combinations: Lr with L | 1.5 / 1.2 on Lr | IS 875-2 | IS takes the roof imposed load as imposed load | Check |
| 90 | combinations.overstrength | none | IS 1893 | No Ω0 in the combinations | Check |

Not entered, to add when the texts are at hand: IS 1893 Table 4 damping factors, Annex C
topography (k3), IS 875-3 Clause 10 gust factor, Table 6 roof Cpe and the cladding coefficients,
IS 16700:2017 tall-building limits (drift, accelerations).
