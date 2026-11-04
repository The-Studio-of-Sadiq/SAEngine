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


# Concrete and foundations (alpha 9 track C8, 2026-11-04)

Same rules as above: entered from knowledge of the codes, no copy of the text at hand; the
paths are of `concreteMethods` unless another table is named.

## IS 456:2000, materials and the limit state

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 91 | ultimate.gammaC / gammaS | 1.5 / 1.15 | 36.4.2 | Partial safety factors of the materials (ultimate) | Sure |
| 92 | ultimate.alphaCC | 0.67 | 38.1(c) | Design stress 0.67 fck / γm = 0.446 fck | Sure |
| 93 | ultimate.relations.epsCu2 / epsC2 / n | 3.5 ‰, 2.0 ‰, 2 | 38.1(b), (c), Fig. 21 | εcu, strain at the peak, parabola | Sure |
| 94 | ultimate.relations eta / lambda | 0.9595 / 0.84 | 38.1, Annex G-1.1 | Rectangular block of the same force and centroid (0.36 fck xu at 0.42 xu) | SAEngine form (values derived) |
| 95 | ultimate.relations.ecmCoefficient | Ec = 5000 √fck | 6.2.3.1 | Short-term modulus (also concrete.modulus.normal) | Sure |
| 96 | ultimate.relations.fctmCoefficient | fcr = 0.7 √fck | 6.2.2 | Flexural strength (cracking moment of Annex C) | Sure |
| 97 | ultimate.strengthClasses | M15 to M80, named "M" + fck | Table 2 | Grades; the project's concrete fc is read as fck | Check (M65-M80 rows) |
| 98 | ultimate.axialShares | 0.4 fck Ac + 0.67 fy Asc | 39.3 | The axial cap of the interaction surface | Sure (value); SAEngine practice (used with emin also) |
| 99 | ultimate.eccentricity* | l/500 + D/30 ≥ 20 mm | 25.4 | Minimum eccentricity about each axis (both at once, on the safe side) | Sure |
| 100 | memberLimits.neutralAxisStrain | 0.002 | 38.1(f) | xu,max: steel strain fyd/Es + 0.002 (0.48 d for Fe 415) | Sure |
| 101 | (steel) | elastic-perfectly plastic at fy/1.15 | 38.1(e), Fig. 23 | The HYSD bars' curved diagram of Fig. 23A not modelled | SAEngine practice |

## IS 456:2000, shear, torsion and punching

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 102 | shear.tauC | 13 × 6 values, M15-M40, pt 0.15-3.0 % | Table 19 | Design shear strength τc | Check every cell |
| 103 | shear.maxStress | 2.5, 2.8, 3.1, 3.5, 3.7, 4.0 | Table 20 | τc,max M15-M40 | Sure |
| 104 | shear.minStirrupStress | 0.4 | 26.5.1.6 | Asv/(b sv) ≥ 0.4/(0.87 fy) | Sure |
| 105 | shear (threshold) | τv > τc/2 | 26.5.1.6 | Minor members may omit the least stirrups below half τc: SAEngine applies the exemption to every beam | Check (reading) |
| 106 | shear.fyMax | 415 MPa | 40.4(a) | fy of stirrups taken at most 415 | Sure |
| 107 | shear.spacing | 0.75 d, 300 mm | 26.5.1.5 | Vertical stirrups | Sure |
| 108 | shear.slabDepths | k 1.30 (≤150) to 1.00 (≥300) | 40.2.1.1 | Solid slabs (overall depth taken as d + 25 mm) | Check (the d + 25 mm is SAEngine's) |
| 109 | shear.enhancement | 2 d / av | 40.5 | Near supports: stored, not applied (the checks take τc) | Check |
| 110 | torsion.shearFactor / momentDivisor | 1.6 / 1.7 | 41.3.1, 41.4.2 | Ve = Vu + 1.6 T/b; Mt = T (1 + D/b)/1.7 | Sure |
| 111 | torsion.depthDivisor | 2.5 | 41.4.3 | Asv = T sv/(b1 d1 0.87fy) + V sv/(2.5 d1 0.87 fy) | Sure |
| 112 | torsion.spacing* | x1, (x1 + y1)/4, 300 mm | 26.5.1.7 | Closed links | Sure |
| 113 | punching.perimeterDistance | d/2 | 31.6.1 | Critical section | Sure |
| 114 | punching.coefficient / ratioBase | 0.25 √fck; ks = 0.5 + βc ≤ 1 | 31.6.3.1 | Punching shear stress | Sure |
| 115 | punching.reinforcedMax / concreteShare | 1.5 τc; 0.5 Vc | 31.6.3.2 | With shear reinforcement (not laid out by SAEngine) | Sure |
| 116 | (punching) | unbalanced moment as the parent's γv M c / J | 31.6.2.2 | The fraction transferred by shear | Check (reading) |

## IS 456:2000, columns, deflection, cracking

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 117 | columns.slenderness.limit | lex/D > 12 slender | 25.1.2 | | Sure |
| 118 | columns.slenderness.maxRatio | 60 | 25.3.1 | Unsupported length at most 60 × least dimension (read on lex/D) | Check (reading) |
| 119 | columns.slenderness.divisor | Ma = Pu D/2000 (lex/D)² | 39.7.1 | Additional moments, added at every station | Sure (value); SAEngine practice (no 0.4M1 + 0.6M2) |
| 120 | (columns) | k = (Puz − Pu)/(Puz − Pb) ≤ 1 | 39.7.1.1 | Pb at the balanced strain state | Sure |
| 121 | (columns) | lex = k lu with the parent's k | 25.2, Annex E | k from the alignment charts SAEngine has | Check |
| 122 | columns.biaxial.alphaN | 1.0 at ≤ 0.2 Puz, 2.0 at ≥ 0.8 | 39.6 | Load contour exponent | Sure |
| 123 | columns.biaxial.puzShares | 0.45 fck Ac + 0.75 fy Asc | 39.6 | Puz | Sure |
| 124 | deflection.basic | 7 / 20 / 26 | 23.2.1(a) | Cantilever / simply supported / continuous; one end continuous taken as continuous | Sure (values); Check (one end) |
| 125 | deflection.longSpan | 10 m, × 10/span | 23.2.1(b) | | Sure |
| 126 | deflection.tension | 1/(0.225 + 0.00322 fs − 0.625 log10(1/pt)) ≤ 2.0, fs = 0.58 fy | Fig. 4, 23.2.1(c) | Curve fit of Fig. 4 (As,req/As,prov taken 1) | Uncertain (the fit) |
| 127 | deflection.compression | 1 + pc/(3 + pc) ≤ 1.5 | Fig. 5 | Curve fit | Uncertain (the fit) |
| 128 | deflection.flange | 0.8 at bw/bf ≤ 0.3, 1.0 at 1.0 | Fig. 6 | Flanged beams (bf of 23.1.2) | Check |
| 129 | deflection.flangeT / flangeL | l0/6 + bw + 6 Df; l0/12 + bw + 3 Df | 23.1.2 | Effective flange width | Check |
| 130 | deflection.limitTotal / limitAfter* | span/250; span/350 or 20 mm | 23.2(a), (b) | | Sure |
| 131 | deflection.shrinkage* | εcs 0.0003; k3 0.5/0.125/0.086/0.063; k4 0.72, 0.65 | 6.2.4.1, C-3 | Shrinkage curvature | Check |
| 132 | deflection.creep / loadingAge | θ 2.2 / 1.6 / 1.1 at 7 / 28 / 365 days; 28 days | 6.2.5.1, C-4 | Creep coefficient | Check |
| 133 | (deflection) | Ieff = Ir/(1.2 − (Mr/M)(z/d)(1 − x/d)(bw/b)) | C-2.1 | Effective inertia | Check |
| 134 | cracking.width | 0.3 mm; 0.2 / 0.1 aggressive | 35.3.2 | IS gives 0.004 × cover for aggressive: SAEngine stores 0.2/0.1 by exposure | Uncertain (reading) |
| 135 | cracking (formula) | Wcr = 3 acr εm/(1 + 2(acr − cmin)/(h − x)) | Annex F | The corner bar of the soffit | Check |
| 136 | cracking.stiffeningDivisor | 3 | Annex F | εm = ε1 − b(h − x)(a' − x)/(3 Es As (d − x)) | Check |
| 137 | cracking.tankWidth | 0.2 mm | IS 3370 (Part 2):2009 | Stored, not wired (no tank check reads it yet) | Check |

## IS 456:2000, cover, durability, anchorage, member limits

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 138 | cover.conditions.*.cover | 20 / 30 / 45 / 50 / 75 mm | Table 16 | Mild to extreme | Sure |
| 139 | cover.smallBarReduction / gradeReduction | 5 mm (≤ 12 mm bars, mild); 5 mm at M35+ (severe, very severe) | Table 16 notes | | Check |
| 140 | cover.columnCover / footingCover | 40 / 50 mm | 26.4.2.1, 26.4.2.2 | | Sure |
| 141 | cover.conditions.* cement / waterCement / grade | 300/300/320/340/360; 0.55/0.50/0.45/0.45/0.40; M20/M25/M30/M35/M40 | Table 5 | Reinforced concrete | Sure |
| 142 | defaultExposure | moderate | Table 3 | SAEngine default, overridable per project (Code values) | SAEngine practice |
| 143 | anchorage.bond | 1.0 / 1.2 / 1.4 / 1.5 / 1.7 / 1.9 | 26.2.1.1 | τbd M15-M40, plain bars in tension | Sure |
| 144 | anchorage.deformedFactor / compressionFactor | +60 % / +25 % | 26.2.1.1 | | Sure |
| 145 | anchorage.lap* | max(Ld, 30φ); 2 Ld; max(Ld,c, 24φ); none above 36 mm | 26.2.5.1 | | Sure |
| 146 | memberLimits.beamMin / beamMax | 0.85/fy; 0.04 b D | 26.5.1.1 | | Sure |
| 147 | memberLimits.sideFace* | D > 750 mm, 0.1 % of the web, 300 mm | 26.5.1.3 | | Sure |
| 148 | memberLimits.slabMin / plainFy / slabBarShare | 0.12 % / 0.15 % (mild, fy ≤ 250); D/8 | 26.5.2.1, 26.5.2.2 | | Sure |
| 149 | memberLimits.slab*Spacing | 3 d or 300 mm; 5 d or 450 mm | 26.3.3(b) | | Sure |
| 150 | memberLimits.column* | 0.8-6 %; 4 / 6 bars; 12 mm | 26.5.3.1 | | Sure |
| 151 | memberLimits.tie* | φ/4 and 6 mm; min(least dimension, 16 φ, 300 mm) | 26.5.3.2(c) | | Sure |

## IS 456:2000, slabs, walls, footings

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 152 | twoWaySlabs.cases | nine cases, αx at ly/lx 1.0-2.0, αy | Annex D Table 26 | Restrained panels | Check every cell |
| 153 | twoWaySlabs.simple* | αx, αy at 1.0-3.0 | Table 27 | Simply supported (stored; the coefficient design takes the four-edge discontinuous case of Table 26) | Check |
| 154 | twoWaySlabs.middleStrip / torsion* | 3/4; 3/4 over lx/5; half with one edge continuous | D-1.1, D-1.8 | Stored; the corner steel rows stay the parent's | Check |
| 155 | flatSlabs.interiorNegative / positive / exteriorNegative | 0.75 − 0.10/(1 + 1/αc); 0.63 − 0.28/(1 + 1/αc); 0.65/(1 + 1/αc) | 31.4.3.3 | End spans by αc | Check |
| 156 | flatSlabs.columnStrip / minThickness | 75 % / 100 % / 60 %; 125 mm | 31.5.5, 31.2.1 | (the parent's αf = 0 rows hold the same shares) | Check |
| 157 | walls.shear* | τcw = (3 − αw) 0.2 √fck; αw > 1: also 0.045 fck (αw+1)/(αw−1); τv ≤ 0.17 fck; d = 0.8 Lw | 32.4 | In-plane shear | Check (K1, K2) |
| 158 | walls.axialFactor / eccentricity / ea | 0.3 (t − 1.2e − 2ea) fck Lw; ea = Hwe²/2500t; Hwe/t ≤ 30 | 32.2.5, 32.2.3 | Stored; the axial check stays the parent's | Check |
| 159 | walls.minEccentricityShare | 0.05 t | 32.2.2 | Uncertain (t/20 reading) | Uncertain |
| 160 | walls.vertical / horizontal | 0.0012 / 0.0015; 0.0020 / 0.0025 | 32.5 | Same as the parent's values | Sure |
| 161 | footings.edgeThickness / pileEdgeThickness | 150 / 300 mm | 34.1.2 | (the parent's foundations.shallow.minThickness agrees) | Sure |
| 162 | foundations.shallow.columnBase | 0.45 fck √(A1/A2), √ ≤ 2, no φ; dowels 0.5 % | 34.4, 34.4.3 | | Sure |

## IS 13920:2016

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 163 | seismic.frames | special | Clause 1 | Ductile detailing where the detailing level is special (zones III-V) | Check (reading) |
| 164 | seismic.beams.minWidth / minRatio / depthShare | 200 mm; 0.3; D ≤ clear span/4 | 6.1 | | Check |
| 165 | seismic.beams.minBars / minBarDia | 2 bars of 12 mm top and bottom | 6.2.1 | | Sure |
| 166 | seismic.beams.rhoMinRoot / rhoMax | 0.24 √fck/fy; 2.5 % | 6.2.1, 6.2.2 | | Sure |
| 167 | seismic.beams.positiveShare / anyShare | 1/2; 1/4 | 6.2.3, 6.2.4 | | Sure |
| 168 | seismic.beams.hoopSpacing / hoopZoneDepths / firstHoop / elsewhereShare | min(d/4, 8 db, 100 mm) over 2d, first 50 mm; d/2 | 6.3.5 | | Check (2016 values) |
| 169 | seismic.beams.hoopMinDia | 8 mm (6 mm for spans < 5 m not used) | 6.3.2 | | Check |
| 170 | seismic.beams.overstrength | 1.4 (MuAs + MuBh)/LAB | 6.3.3 | Capacity design shear from the design moment capacities | Sure |
| 171 | seismic.columns.axialShare | 0.08 fck Ag | 7 (scope) | Members with more axial stress are columns | Check |
| 172 | seismic.columns.minDimension / minRatio | 300 mm; 0.4 | 7.1.1, 7.1.2 | The 200 mm exception (short columns, short beams) not used | Check |
| 173 | seismic.columns.rho | 0.8 % to 4 % | 7.3.1 | | Check |
| 174 | seismic.columns.strongColumn | ΣMc ≥ 1.4 ΣMb | 7.2.1 | Joints with no column above exempt (SAEngine reading) | Sure (1.4); Check (exemption) |
| 175 | seismic.columns.confinedLength | max(D, clear/6, 450 mm) | 8.1 | lo | Sure |
| 176 | seismic.columns.confinedSpacing | min(B/4, 6 db, 100 mm) | 8.1 | In lo | Check (2016 values) |
| 177 | seismic.columns.ash | max(0.18 (Ag/Ak − 1), 0.05) s h fck/fy | 8.1(b) | Rectangular hoops, h the leg spacing | Check |
| 178 | seismic.columns.spiral | max(0.09 (Ag/Ak − 1), 0.024) s Dk fck/fy | 8.1(a) | Circular hoops | Uncertain |
| 179 | seismic.columns.hxMax / outsideShare / lapHoopSpacing | 300 mm; B/2; 150 mm | 8.1, 7.4 | | Check |
| 180 | seismic.joints.gamma | 1.5 / 1.2 / 1.0 √fck Aej | 9.1.1 | Four faces / three or two opposite / others confined | Check |
| 181 | seismic.joints.widthShare | bj = min(bb + hc/2, bc) | 9.1.2 | Effective joint width | Uncertain |
| 182 | seismic.joints.overstrength | 1.4 fyd (As,top + As,bottom) − Vcol | 9.1 | Joint design shear (SAEngine form) | Uncertain |
| 183 | seismic.walls.minThickness / rhoMin | 150 mm; 0.25 % each way | 10.1, 10.2 | Special shear walls | Check |
| 184 | seismic.walls.twoCurtain* / barDiaShare / spacing | t > 200 mm or τv > 0.25 √fck; t/10; min(lw/5, 3t, 450 mm) | 10.1-10.2 | | Check |
| 185 | seismic.walls.boundaryStress / boundaryStop | 0.2 fck; 0.15 fck | 10.4 | Boundary elements | Sure |
| 186 | seismic.walls.couplingRoot / couplingSpanRatio | diagonals where τv > 0.1 (ls/D) √fck with ls/D < 2 | 10.5 | Coupling beams; Vu = 2 Asd 0.87 fy sin α | Uncertain |
| 187 | detailing.joints.probableStress | 1.4 | 6.3.3 | The parent's Mpr form read as 1.4 × the design strengths (Design Reinforcement, capacity shear) | SAEngine practice |

## Foundations

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 188 | foundations.shallow.bearingFactors | qnu = c Nc sc dc + q (Nq − 1) sq dq + ½ B γ Nγ sγ dγ | IS 6403 5.1 | Net ultimate bearing capacity | Sure |
| 189 | bearingFactors.gammaFactor | Nγ = 2 (Nq + 1) tan φ | IS 6403 Table 1 (Vesic) | | Check |
| 190 | bearingFactors.shape / square / circle | 1 + 0.2 B/L, 1 + 0.2 B/L, 1 − 0.4 B/L; 1.3, 1.2, 0.8; 1.3, 1.2, 0.6 | IS 6403 Table 2 | | Sure |
| 191 | bearingFactors.depth / depthPhiMin | dc = 1 + 0.2 Df/B √Nφ; dq = dγ = 1 + 0.1 Df/B √Nφ from φ 10° | IS 6403 5.1.2.2 | | Check |
| 192 | bearingFactors (inclination) | (1 − α/90)², (1 − α/φ)² | IS 6403 5.1.2.3 | Vertical loads only here: 1 | Not covered |
| 193 | foundations.piles.earthPressure.nc | 9 | IS 2911-1-2 B-1 | Cohesive base | Sure |
| 194 | earthPressure.k | 1.5 | IS 2911-1-2 B-2 | K of bored piles (the code gives 1 to 2) | Check (SAEngine choice in the range) |
| 195 | earthPressure.deltaShare | δ = φ | IS 2911-1-2 B-2 | | Check |
| 196 | earthPressure.criticalDepth | 15 D | IS 2911-1-2 B-2 note | σ'v constant below it | Uncertain (15 or 20 D) |
| 197 | earthPressure (Nq) | the parent's Nq figure (Berezantsev) | IS 2911-1-2 Fig. 1 | | Check |
| 198 | foundations.noLoadTestSafety | 2.5 | IS 2911-1-2 B-1, B-2 | Static formula | Sure |
| 199 | (α of clay) | 1.0 at cu ≤ 25 kPa to 0.5 at ≥ 70 kPa | IS 2911-1-2 Fig. 5 | The parent's static.alpha* hold these | Check |

Not covered yet (the parent pack's method and values, stated in their rows): the walls' axial
capacity (32.2.5, stored), the near-support shear enhancement (40.5, stored), IS 8009
settlement (the parent's methods), IS 2950 rafts (the parent's raft design; no IS rigidity
criterion yet), IS 3370 tanks (the 0.2 mm width stored, the tank design is the parent's),
precast, prestress, corbels, deep beams, stairs.


## Alpha 9 C9: IS 800:2007 steel (steelLimitState, steel, steelSections, serviceability)

Entered from knowledge of IS 800:2007 (no copy of the code on the PC, 2026-11-04). IS 800 names
the major axis z-z and the minor y-y; SAEngine's x is the major axis.

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 200 | steelLimitState.partialFactors.gammaM0 / gammaM1 | 1.10 / 1.25 | 5.4.1, Table 5 | Yielding and buckling / ultimate stress | Sure |
| 201 | partialFactors.gammaMb | 1.25 | Table 5 | Bolts, bearing type | Sure |
| 202 | partialFactors.gammaMf / gammaMfService | 1.25 / 1.10 | Table 5 | Friction grip slip at ultimate / service load | Sure |
| 203 | partialFactors.gammaMw / gammaMwField | 1.25 / 1.50 | Table 5 | Welds, shop / field | Sure |
| 204 | classification.referenceFy | 250 | 3.7.2, Table 2 | ε = √(250/fy) | Sure |
| 205 | classification.outstandRolled | 9.4, 10.5, 15.7 ε | Table 2 | Outstand of a compression flange, rolled (b = bf/2) | Sure |
| 206 | classification.outstandWelded | 8.4, 9.4, 13.6 ε | Table 2 | The same, welded | Sure |
| 207 | classification.internalFlange / internalAxial | 29.3, 33.5, 42 ε / 42 ε | Table 2 | Internal element of a flange in bending / axial (RHS walls) | Sure |
| 208 | classification.web | 84, 105, 126 ε | Table 2 | Web, neutral axis at mid-depth (d = clear web depth) | Sure |
| 209 | classification.webAxialFactors, webAxial | ÷ (1 + r1), (1 + 1.5 r1), (1 + 2 r2), ≥ 42 ε | Table 2 | Web with axial compression; SAEngine takes r1 = r2 = P / (A fy / γm0) | Check (r1 is of the web alone in the code) |
| 210 | classification.channelWeb | 42 ε (all classes) | Table 2 | Web of a channel | Check |
| 211 | classification.angleBending, angleAxial | 9.4, 10.5, 15.7 ε; 15.7 ε and (b + d)/t 25 ε | Table 2 | Single angles | Sure |
| 212 | classification.teeStem | 8.4, 9.4, 18.9 ε | Table 2 | Stem of a tee (the table prints D/tf; SAEngine uses D/tw) | Uncertain (D/tf as printed?) |
| 213 | classification.circularBending / circularAxial | 42, 52, 146 ε² / 88 ε² | Table 2 | Circular hollow sections | Sure |
| 214 | compression.alpha | a 0.21, b 0.34, c 0.49, d 0.76 | 7.1.2.1, Table 7 | Imperfection factor | Sure |
| 215 | compression.plateau | 0.2 | 7.1.2.1 | φ = 0.5 [1 + α (λ − 0.2) + λ²] | Sure |
| 216 | compression.rolledI | h/b > 1.2: tf ≤ 40 a/b, ≤ 100 b/c; h/b ≤ 1.2: tf ≤ 100 b/c, above d/d | 7.1.2.2, Table 10 | Buckling class of rolled I-sections (z-z / y-y) | Sure |
| 217 | compression.weldedI | tf ≤ 40 b/c, above c/d | Table 10 | Welded I-sections | Sure |
| 218 | compression.families | channels, angles, tees, solid c; hollow b | Table 10 | Hollow sections: hot rolled a, cold formed b; SAEngine's tubes are cold formed (b) | Check |
| 219 | compression.angleConstants | ≥ 2 bolts fixed 0.20, 0.35, 20; hinged 0.70, 0.60, 5; 1 bolt fixed 0.75, 0.35, 20; hinged 1.25, 0.50, 60 | 7.5.1.2, Table 12 | k1, k2, k3 of λe | Check |
| 220 | compression.angleCondition | twoBoltsHinged | 7.5.1.2 | SAEngine practice (the end is not known to the member) | SAEngine choice |
| 221 | (slender sections) | each slender element counted up to its semi-compact width | 7.3.2 | SAEngine's reading of the effective area | Check |
| 222 | tension.ruptureShare | 0.9 | 6.3.1 | Tdn = 0.9 An fu / γm1; An = Ag (welded ends) unless the member's net ratio is set | Sure |
| 223 | tension.angleAlpha, angleBolts | α 0.6 / 0.7 / 0.8 for 2 / 3 / ≥ 4 bolts; 2 bolts taken | 6.3.3 | Single angles (the alternative to the β formula) | Check |
| 224 | flexure.elasticCap / elasticCapCantilever | 1.2 / 1.5 | 8.2.1.2 | Md ≤ 1.2 Ze fy / γm0 (1.5 cantilever) | Sure |
| 225 | flexure.alphaLT | 0.21 rolled / 0.49 welded | 8.2.2 | Imperfection factor of LTB | Sure |
| 226 | flexure.ltbPlateau | 0.4 | 8.2.2 | No LTB check while λLT ≤ 0.4 | Sure |
| 227 | flexure.highShare | 0.6 | 8.2.1.3 | High shear V > 0.6 Vd: Mdv = Md − β (Md − Mfd), β = (2V/Vd − 1)² | Sure |
| 228 | (Mcr) | c1 √[(π² E Iy / L²)(G It + π² E Iw / L²)], c1 = SAEngine's Cb of the moment diagram | 8.2.2.1, Annex E | Load at the shear centre, K = Kw = 1; tees and angles with Iw of SAEngine (0) | Check (c1 of Table 42 vs the Cb SAEngine computes) |
| 229 | shear.bucklingLimit | 67 ε | 8.4.2.1 | Unstiffened webs | Sure |
| 230 | shear.kvUnstiffened / kvStiffened | 5.35; 4 + 5.35/(c/d)², 5.35 + 4/(c/d)² | 8.4.2.2(a) | kv | Sure |
| 231 | shear.lambdaLimits / lambdaSlope | 0.8, 1.2 / 0.8 | 8.4.2.2(a) | τb by λw (simple post-critical method) | Sure |
| 232 | (shear areas) | h tw (rolled), d tw (welded), 2 bf tf, A h/(b + h), 2A/π | 8.4.1.1 | Av by shape; angles and tees: the leg / stem (SAEngine practice) | Check |
| 233 | interaction.alphaMinor / alphaMajor | 5 n ≥ 1 / 2 | 9.3.1.1 | Plastic and compact I-sections | Sure |
| 234 | interaction.flangeShare / majorReduction | a ≤ 0.5 / Mndz = Mdz (1 − n)/(1 − 0.5 a) | 9.3.1.1 | | Sure |
| 235 | interaction (linear) | N/Nd + Mz/Mdz + My/Mdy ≤ 1 | 9.3.1.3 | Other sections (and the cap of the plastic form) | Sure |
| 236 | interaction.kCap / minorShare | Ky, Kz ≤ 1 + 0.8 n; 0.6 | 9.3.2.2 | The two member equations | Sure |
| 237 | interaction.ltbFactor / ltbOffset | KLT = 1 − 0.1 λLT ny/(CmLT − 0.25) ≥ 1 − 0.1 ny/(CmLT − 0.25) | 9.3.2.2 | | Sure |
| 238 | interaction.cmMin | 0.4 | Table 18 | Cm = 0.6 + 0.4 ψ ≥ 0.4; transverse loads: SAEngine takes 1.0 (conservative) | Check |
| 239 | interaction.tensionPsi | 0.8 | 9.3.2.1 | Meff = M − ψ T Zec / A (T and M independent) | Sure |
| 240 | slenderness.compression / tension | 180 / 400 | 3.8, Table 3 | Members in compression / always in tension | Sure |
| 241 | shearModulus | 76 900 MPa | 2.2.4.1 | G | Sure |
| 242 | nominalHollowWall | true | (IS 4923) | Hollow sections on the nominal wall (no ERW 0.93 t) | SAEngine choice |
| 243 | connections.bolts.grades | 4.6: 400/240, 8.8: 800/640, 10.9: 1000/900 | IS 1367 | fub / fyb; 8.8 and 10.9 friction grip | Sure |
| 244 | connections.bolts.aliases | A307 → 4.6, A325 → 8.8, A490 → 10.9 | | The object library's grade names (SAEngine practice) | SAEngine choice |
| 245 | connections.bolts.netShare | 0.78 | 10.3.3 | Anb at the threads; threads taken in every shear plane | Check |
| 246 | connections.bolts.tensionShare | 0.9 | 10.3.5 | Tnb = 0.9 fub An ≤ fyb Asb γmb/γm0 | Sure |
| 247 | connections.bolts.bearing* | 2.5 kb d t fu / γmb, kb = min(e/3d0, p/3d0 − 0.25, fub/fu, 1) | 10.3.4 | fub/fu not known in the shared check (taken ≥ 1) | Check |
| 248 | connections.bolts.proofShare | 0.7 | 10.4.3 | F0 = 0.7 fub Anb | Sure |
| 249 | connections.bolts.slipMu | A 0.20, B 0.50 | Table 20 | Surfaces not treated / blasted (the object library's classes A and B) | Check (mapping) |
| 250 | connections.bolts.holeKh | 1.0 / 0.85 / 0.85 / 0.70 | 10.4.3 | Clearance, oversized, short slot, long slot | Sure |
| 251 | connections.bolts.longJoint | βlj = 1.075 − 0.005 lj/d, 0.75-1.0, lj > 15 d | 10.3.3.1 | βlg and βpk taken 1 (grip and packing not known) | Sure |
| 252 | connections.welds.throatShare | 0.7 | 10.5.3.2 | Throat of 60-90° fillets | Sure |
| 253 | (fillet strength) | fu / (√3 γmw); fu of the electrode | 10.5.7.1.1 | The smaller of weld and parent fu in the code; the parent is not known in the shared check | Check |
| 254 | connections.blockShear | 0.9, 0.9 | 6.4.1 | Tdb; Atg taken as Atn (on the safe side) | Sure |
| 255 | steel.connections.holes | d + 1 (12-14), d + 2 (16-24), d + 3 (above) | 10.2.1, Table 19 | Standard clearance holes | Check |
| 256 | steel.connections.edgeRolled / edgeSheared | 1.5 d0 / 1.7 d0 | 10.2.4.2 | Least edge and end distance | Sure |
| 257 | steel.connections.minSpacing | 2.5 d | 10.2.2 | | Sure |
| 258 | steel.connections.maxEdge* | 12 t (ε = 1) | 10.2.4.3 | 12 t ε in the code: less strict for fy > 250 | Check |
| 259 | steel.connections.filletMin | 3 / 5 / 6 / 8 mm up to 10 / 20 / 32 / above | 10.5.2.3, Table 21 | By the thicker part in the code; SAEngine's check gives the thinner | Check |
| 260 | steel.connections.filletMax* | t − 1.5 mm | 10.5.8.1 | Along a square edge | Check |
| 261 | steel.phi (connection elements) | 0.9091, 0.72, 0.8748, 0.6928 | 6.2, 6.3.1, 8.4.1, 6.4.1 | 1/γm0, 0.9/γm1, 1/(0.6 √3 γm0), 0.9/(0.6 √3 γm1) as factors of the shared 0.6 fy / 0.6 fu forms | Sure (arithmetic) |
| 262 | serviceability.deflection.uses | floors 300 / 360; purlins 150 / 180; industrial 240 / 300; rafters 180 / 240; gantry 500 / 750 / 1000 | 5.6.1, Table 6 | Live (and wind) load deflection; cantilevers by cantileverSpan 2 (150 / 180) | Check (the rows) |
| 263 | steelSections | ISMB, ISMC, equal angles, SHS / RHS / CHS | IS 808, IS 4923 | The parent table's IS 808 rows; ISLB, ISWB, ISHB not entered | Check (the angle list is the shared EN 10056 / IS 808 one) |

## IS 800:2007 Section 12 (steelLimitState.seismic)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 264 | seismic.systems | steelSmf → SMF, steelOmf → OMF, steelScbf → SCBF | IS 1893 Table 9 | IS 1893's "concentric braced frame" taken as SCBF (stricter); EBF not covered | SAEngine choice |
| 265 | frames.ocbf.braceSlenderness / braceCompressionShare | 120 / 0.8 Pd | 12.7.2 | OCBF braces | Check |
| 266 | frames.ocbf/scbf.tensionShare | 30-70 % | 12.7.2, 12.8.2 | Tension braces' share along a line (a flag; SAEngine groups braces by plan direction) | Check |
| 267 | frames.*.kBracing | false | 12.7, 12.8 | K bracing not permitted (a note: not detected) | Check |
| 268 | frames.scbf.braceSlenderness / plasticMembers | 160 / braces plastic | 12.8.2 | SCBF braces | Check |
| 269 | frames.omf/smf.connectionMoment | 1.2 Mp | 12.10, 12.11 | Beam-to-column connections (a flag) | Check |
| 270 | frames.smf.driftAngle | 0.04 rad | 12.11 | Connection rotation capacity (a flag) | Uncertain |
| 271 | frames.smf.strongColumn | ΣMpc ≥ 1.2 ΣMpb | 12.11 | Mpc = Zp (fy − P/A) | Check |
| 272 | frames.smf.plasticMembers | beams and columns plastic | 12.11 | | Check |
| 273 | seismic.columnAmplified | the Ω0 (2.5) combinations | 12.2.2, 12.5 | Columns' axial strength under 1.2 DL + 0.5 LL ± 2.5 EL; SAEngine uses its Ω0 combinations of the pack (Ω0 2.5) | Check (the combination itself) |
| 274 | seismic.rAbove | 0 | 12.1 | Applied whenever a steel frame system is in use (the code ties Section 12 to the zones) | SAEngine choice |

## IS 1905:1987 masonry (masonry.basicStress)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 275 | masonry.method | basicStress | 5.4 | Unreinforced masonry by permissible stresses | Sure |
| 276 | basicStress.mortars, unitStrengths | fb rows H1, H2, M1, M2, M3 (1:3 to 1:7) by unit strength 3.5-40 MPa | Table 8 | Basic compressive stress | Uncertain (every number from memory; L1, L2 not entered) |
| 277 | basicStress.reduction | ks by SR 6-27 and e/t 0-1/3 | Table 9 | Stress reduction factor | Uncertain (every number from memory) |
| 278 | basicStress.areaBelow / areaBase / areaSlope | 0.2 m², 0.7 + 1.5 A | 5.4.1.2 | Area reduction factor | Sure |
| 279 | basicStress.shapeFactor | 1.0 | 5.4.1.3, Table 10 | kp of bricks (h/w ≤ 0.75); other units: override | SAEngine choice |
| 280 | basicStress.effectiveHeight | 0.75 H | 4.3.1, Table 4 | Walls with RC slabs or floors at both ends; 2 H free top | Check (SAEngine applies it to every braced wall) |
| 281 | basicStress.slendernessMax | 27 | 4.6.1 | Cement mortar walls | Check |
| 282 | basicStress.eccentricityIncrease | e/t > 1/24: face stress ≤ 1.25 fc | 5.4.1.4 | | Check |
| 283 | basicStress.tension / tensionMix | 0.07 / 0.14 MPa, mortar M1 (1:5) or richer | 5.4.2 | Normal to / parallel to the bed joints | Check |
| 284 | basicStress.shear | 0.1 + fd/6 ≤ 0.5 MPa | 5.4.3 | | Check |
| 285 | basicStress.lateralIncrease | 1.25 | 5.4.1 | With wind or earthquake | Uncertain (25 % or 33 %) |
| 286 | combinations.allowable | D, D + L, D + W, D + E, D + L + W, D + L + E | IS 875 (Part 5) 8.1 | Working stress combinations at full factors (masonry, timber) | Check |

## IS 883:1994 timber (timber) and IS 11384:1985 composite beams (composite)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 287 | timber.groups, grades, duration, column, depthFactor | the parent's values (BNBC 2020 Chapter 11 follows IS 883) | IS 883 5-7 | Groups A, B, C; 1.16 / 0.84; K2; K3; K8 | Check (equal to IS 883 as SAEngine reads it) |
| 288 | timber.clauses | clause groups of IS 883 | IS 883 5-10 | The clause numbers are given at the section level | Uncertain (numbers) |
| 289 | timber.species | the parent's species list | IS 883 Table 1 | Indian species not listed: design by strength group | SAEngine choice |
| 290 | composite.beam.limitState.concreteShare | 0.4286 (0.36 fck over 0.84 xu) | IS 11384 App. B | The concrete of the plastic moment | Uncertain |
| 291 | composite.beam.limitState.steelGamma | 1.15 (0.87 fy) | IS 11384 App. B | | Uncertain |
| 292 | composite.beam.limitState.studs | 12×62: 26-31; 16×75: 44-55; 20×75: 60-75; 20×100: 63-79; 22×100: 77-101; 25×100: 86-113 kN for M20-M40 | IS 11384 Table 1 | Design strength of headed studs | Uncertain (every number from memory) |
| 293 | composite.materials.concreteMin | 20 MPa | IS 11384 | Slab concrete at least M20 | Check |

Not covered yet (the parent pack's method and values, named after the parent in the notes): the
connection rules IS 800 has no counterpart for in SAEngine's checks (the column side under flange
forces, HSS truss and moment joints, the base plate bearing on concrete), torsion, the stability
bracing forces, IS 800 eccentrically braced frames, fatigue and fire, IS 801 cold-formed steel,
the composite columns and deck rules, IS 4326 masonry earthquake detailing, reinforced masonry.
