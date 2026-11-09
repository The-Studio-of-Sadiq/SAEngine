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

Not covered by C9 (the parent pack's method and values, named after the parent in the notes): the
connection rules IS 800 has no counterpart for in SAEngine's checks (the column side under flange
forces, HSS truss and moment joints; the base plate bearing since C9b, 320), torsion, the
stability bracing forces, IS 800 eccentrically braced frames, fatigue and fire, IS 801
cold-formed steel, the composite columns and deck rules, reinforced masonry (IS 4326 masonry
strengthening since C9b, 330).

## Alpha 9 C9b: the remainder (concrete, steel, masonry, loads)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| 294 | concreteMethods.shear.axialFactor / axialMax | δ = 1 + 3 Pu/(Ag fck) <= 1.5 | IS 456 40.2.2 | Column shear: τc × δ under axial compression | Sure |
| 295 | (SAEngine) column shear under net tension | δ = 1 + 3 Pu/(Ag fck) with Pu < 0, not below 0 | IS 456 40.2.2 | IS gives no tension rule; the line continued (on the safe side) | SAEngine choice |
| 296 | (SAEngine) column shear steel ratio | pt of the bars in the far half of each axis (a circle: half its bars) | IS 456 40.2.2, Table 19 | | SAEngine choice |
| 297 | concreteMethods.shear.spacing (columns) | ties for shear at most min(0.75 d, 300 mm) where Vu > Vc | IS 456 26.5.1.5 | The beams' stirrup spacing applied to column ties carrying shear | SAEngine choice |
| 298 | concreteMethods.shear.enhancement (beams) | not applied to beams; the shear at d from the face | IS 456 40.5.1, 40.5.2 | 2 d τc / av near a support used for corbels only | Check (SAEngine reading, on the safe side) |
| 299 | concreteMethods.walls.axialFactor, eccentricityFactor, additionalDivisor, minEccentricityShare | Puw = 0.3 (t - 1.2 e - 2 ea) fck Lw, ea = Hwe²/(2500 t), e >= t/20 | IS 456 32.2.5 | Empirical wall strength (informative row: the P-M surface governs) | Check |
| 300 | concreteMethods.walls.slendernessMax | Hwe/t <= 30 | IS 456 32.2.3 | | Check |
| 301 | (SAEngine) wall effective height | 0.75 H braced and restrained, 1.0 H braced, 2.0 H unbraced | IS 456 32.2.4 | From SAEngine's bracing flags | Check (the IS cases) |
| 302 | concreteMethods.twoWaySlabs.torsionShare / torsionLength / torsionOneEdgeShare | 3/4 of the largest midspan steel, over lx/5, half of it with one edge continuous | IS 456 D-1.8, D-1.9, D-1.10 | Corner torsion steel; the panel's own top and bottom meshes counted | Check |
| 303 | concreteMethods.deepBeams.spanRatio | l/D < 2.0 simply supported, < 2.5 continuous | IS 456 29.1 | Deep beams (continuous: a beam of more than one span, SAEngine) | Check |
| 304 | concreteMethods.deepBeams.clearFactor | l = min(c/c, 1.15 clear span) | IS 456 29.1 | Effective span | Check |
| 305 | concreteMethods.deepBeams.leverArm | simple 0.2 (l + 2D), 0.6 l below l/D = 1; continuous 0.2 (l + 1.5 D), 0.5 l | IS 456 29.2 | Lever arm z | Check |
| 306 | concreteMethods.deepBeams.tensionZone | 0.25 D - 0.05 l | IS 456 29.3.1 | Zone of the positive steel at the tension face | Check |
| 307 | (SAEngine) deep beam side face steel | the walls' least steel (0.0012 / 0.0020 for fy >= 415, else 0.0015 / 0.0025), spacing min(3 t, 450) | IS 456 29.3.4, 32.5 | | Check (which wall ratio applies to which face) |
| 308 | (SAEngine) deep beam shear | the sectional shear rows (IS 456 has no deep beam shear method) | IS 456 29 | The strut-and-tie model of the parent is not run | SAEngine choice |
| 309 | concreteMethods.corbels.spanRatio / edgeDepth | av < d; the outer edge at least half the depth at the face | IS 456 28.1 | | Check |
| 310 | concreteMethods.corbels.tensionShare | horizontal force at least 0.5 Vu | IS 456 28.2.1 | | Check |
| 311 | concreteMethods.corbels.tiesShare / tiesDepth | links at least 0.5 As within 2/3 d | IS 456 28.2.4 | | Check |
| 312 | concreteMethods.corbels.bearing | 0.45 fck | IS 456 28.2.2, 34.4 | No increase for the area around | Check |
| 313 | (SAEngine) corbel tie | As = Af + An, Af for Vu av + Nuc (h - d) by the pack's stress block at fy/1.15 | IS 456 28.2.1 | The strain compatibility of 28.2.1.1 taken as the section's | SAEngine choice |
| 314 | (SAEngine) corbel shear | (2 d/av) τc b d + fyd Ah <= τc,max b d | IS 456 28.2.4, 40.5 | All the closed links counted across the failure plane | Uncertain (SAEngine reading) |
| 315 | stairMethods.builtIn | 110 mm, 150 mm strip, 75 mm breadth | IS 456 33.2 | Same as the parent | Check |
| 316 | stairMethods.openWellShare | 0.5 | IS 456 33.2 | Same as the parent | Check |
| 317 | designClauses.stairs.spans | 33.1 (a)-(c) | IS 456 33.1 | The effective spans (same rules as the parent's) | Check ((d) is the parent's: IS has three cases) |
| 318 | (SAEngine) stairs | k τc b d without shear bars, the slab steel rows (26.3.3, 26.5.2), span/d with kt, no 15 % stair increase | IS 456 33, 23.2.1, 40.2.1.1 | | Check (IS 456 has no 15 % increase for stairs) |
| 319 | (SAEngine) torsion links in Design Reinforcement | the whole Asv/sv of 41.4.3 on the closed links, τc of the least steel ratio before the bars are known | IS 456 41.4.3, 26.5.1.7 | On the safe side | SAEngine choice |
| 320 | steel.connections.concreteBearing* | 0.6 fck, no φ, no A2/A1 increase | IS 800 7.4.1 | Base plate bearing | Check (0.6 fck; the increase) |
| 321 | steelSections.rolled.ISLB | 75x50 3.7/5.0 ... 600x210 10.5/15.5 (17 sizes) | IS 808:1989 | D x B, tw / tf (mean) | Uncertain (every dimension from memory; consistent with the published masses to about 3 %) |
| 322 | steelSections.rolled.ISWB | 150x100 5.4/7.0 ... 600x250 11.2/21.3 (12 sizes) | IS 808:1989 | The lighter ISWB 600 only | Uncertain (as 321) |
| 323 | steelSections.rolled.ISHB | 150x150 5.4/9.0 ... 450x250 9.8/13.7 (8 sizes) | IS 808:1989 | The lightest section of each size only | Uncertain (as 321) |
| 324 | steelSections.rolled.ISLB/ISWB/ISHB r | derived from the published mass per metre, 6-15 mm | IS 808:1989 | Root radius (the printed r1 not recalled) | SAEngine choice |
| 325 | bolt grade 4.6 | fub 400, fyb 240 (steelLimitState); A307 in the default pack | IS 1367, IS 800 10.3 | Property class 4.6 in the object library's grade list | Check |
| 326 | seismic.dampingCorrection.points | 0 % 3.2, 2 % 1.4, 5 % 1.0, 7 % 0.9, 10 % 0.8, 15 % 0.7, 20 % 0.6, 25 % 0.55, 30 % 0.5 | IS 1893 (Part 1):2016 Table 4 | Multiplying factors for other damping (linear between) | Check (the values as in the 2002 edition's Table 3) |
| 327 | seismic.verticalFactor | 0.667 (Ev = 2/3 × Z/2 × D) | IS 1893 (Part 1):2016 6.4.6 | Two-thirds of the horizontal, the vertical response taken rigid (Sa/g = 1) | Uncertain (SAEngine reading: Sa/g of the vertical period not used) |
| 328 | wind.speedFactors.cyclonicImportance | 1.30 for the 100-year class, 1.0 otherwise | IS 875 (Part 3):2015 6.3.4 | k4 on a cyclone-prone site (wind.speedFactors.cyclonic) | Check (which occupancies are of post-cyclone importance) |
| 329 | wind.speedFactors.cyclonicDirectionality | Kd = 1.0 | IS 875 (Part 3):2015 7.2.1 | Cyclone-affected regions | Check |
| 330 | masonry.seismic.zones / strengthening / bands.rows | zones III-V, zone V as the parent's highest group | IS 4326:2013 | The parent's bars and arrangements by IS zone | Uncertain (IS 4326 building categories A-E and its tables not modelled) |

## Alpha 9 C12 (steel half): torsion, bracing, column side, IS 801 cold-formed, Section 16 fire

Rows numbered S1-S16 (their own series, so the parallel tracks do not collide).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| S1 | steelLimitState.torsion | (σ/fd)² + 3 (τ/fd)² <= 1, fd = fy/γm0 (1.10); Vd reduced by √(1 - τt/(1.25 fd/√3)) | IS 800 has no member torsion clause | Torsion by the elastic St. Venant and warping stresses (the EN 1993-1-1 6.2.7 form) | Uncertain (SAEngine practice) |
| S2 | steelLimitState.bracing.share | 0.025 of the compression flange force (beams), of the axial force (columns) | IS 800:2007 lateral restraint (clause to find) | Restraint force | Uncertain (the clause and the column share) |
| S3 | steelLimitState.columnSide (dispersion) | Fw = (b1 + n2) tw fyw/γm0, n2 = 2 × 2.5 (tf + r) | IS 800:2007 8.7.4 | Web bearing under a flange force | Check |
| S4 | steelLimitState.columnSide | (b1 + n1) tw fcd, n1 = D (45° to mid-depth both ways), λ = 2.5 d/t, curve c | IS 800:2007 8.7.3.1 | Web buckling | Check (n1 for a load through the column) |
| S5 | steelLimitState.columnSide | panel Av fy/(√3 γm0), Av = dc tw; flange: the parent's 6.25 tf² Fy | IS 800:2007 8.4.1 | Panel as web shear; no IS column flange rule (the default pack's named) | Uncertain (SAEngine practice) |
| S6 | coldFormed.effectiveWidth | (w/t)lim = 1435/√f; be/t = 2120/√f (1 - 465/((w/t)√f)), f in kgf/cm² | IS 801:1975 5.2.1.1 | Stiffened elements | Check |
| S7 | coldFormed.effectiveWidth.factors[3] | unstiffened lip fully effective up to 530 t/√f | IS 801:1975 6.2 | The lip counted to 530 t/√f (the stress reduction of 6.2 as a width: SAEngine practice) | Uncertain |
| S8 | coldFormed.distortional (lipAdequacy) | dmin = 2.8 t ⁶√((w/t)² - 281 200/fy) >= 4.8 t | IS 801:1975 5.2.2.1 | The lip's least depth (else the flange unstiffened) | Check |
| S9 | coldFormed.resistance | 0.60 fy tension and bending, Fa1 = 12/23 Q fy - 3 (Q fy)² (KL/r)²/(23 π² E), 12 π² E/(23 (KL/r)²) beyond Cc/√Q | IS 801:1975 6.1, 6.6.1.1 | Permissible stresses (KL/r of the elastic buckling stress incl. torsional-flexural: SAEngine practice) | Check |
| S10 | coldFormed.resistance | Fb = 0.6 fy; 2/3 fy - fy²/(5.4 π² E Cb) (L² Sxc/(d Iyc)) to 1.8 π² E Cb/fy; 0.6 π² E Cb d Iyc/(L² Sxc) beyond; Z: d Iyc/2 | IS 801:1975 6.3 | Lateral buckling of C and Z | Check |
| S11 | coldFormed.resistance | Fv = 1275 √fy/(h/t) <= 0.40 fy; 5 850 000/(h/t)² above h/t = 4590/√fy (kgf/cm²) | IS 801:1975 6.4.1 | Web shear | Check |
| S12 | coldFormed.resistance | fa/Fa1 + Cm fb/((1 - fa/F'e) Fb) <= 1, Cm 0.85, F'e = 12 π² E/(23 (KLb/rb)²); working forces = factored / 1.5 | IS 801:1975 6.7.2 | Combined; the load factor 1.5: SAEngine practice | Check / Uncertain (1.5) |
| S13 | coldFormed | E = 2 074 000 kgf/cm² (203 395 MPa); w/t web 150, flange 60, lip 60; t <= 25 mm | IS 801:1975 5.2.3, 5.2.4 | Limits | Uncertain (t) |
| S14 | steelFire.retention (formula) | fy(T)/fy = 1 to 215 °C, (905 - T)/690 to 905 °C; E(T)/E = 1 + T/(2000 ln(T/1100)) to 600 °C, 690 (1 - T/1000)/(T - 53.5) to 1000 °C | IS 800:2007 16.2 | Variation of fy and E with temperature | Check |
| S15 | steelFire.critical (linear) | Tl = 905 - 690 rf | IS 800:2007 16.3 | Limiting steel temperature, every member (compression too) | Check |
| S16 | steelFire | rf = 0.6 × the ambient utilisation; heating by the lumped heat capacity in the ISO 834 curve (IS 3809), αc 25, εm 0.7, ca 600, ρa 7850 | IS 800:2007 16.4-16.6 | The load ratio and the steel temperature (IS 800's own time-temperature formulas not used) | Uncertain (SAEngine practice) |

## Alpha 9 C12 (concrete, foundations and loads half)

Rows L1-L20 (their own series).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| L1 | concrete.prestress.tensionForm | absolute (tension limits in MPa) | IS 1343:1980 22.7, 22.8 | IS gives stresses, not k √f'c | Check |
| L2 | concrete.prestress.jackingFpu | 0.76 fpu | IS 1343:1980 18.5.1 | Largest initial prestress | Uncertain (0.76 or 0.80 by edition) |
| L3 | concrete.prestress.transferCompression, transferTension | 0.54 fci (post-tensioned, M30-M40 of Figure 8); 1 MPa | IS 1343:1980 22.8.1, 22.8.2 | Stresses at transfer | Uncertain (from memory; the figure varies with grade) |
| L4 | concrete.prestress.totalCompression, sustainedCompression, tensionClassU, tensionTwoWay | 0.41 fck in bending; 0.33 fck sustained; 3 MPa (Type 2); two-way slabs 3 MPa | IS 1343:1980 22.7.1, Figure 7 | Service stresses; Types 1-2 as Class U, Type 3 as Class C | Uncertain (0.33 and the slab use are SAEngine practice) |
| L5 | concreteTime (parent) | relaxation 0, 35, 70, 90 MPa at 0.5-0.8 fpu; creep 2.2, 1.6, 1.1 at 7, 28, 365 days; shrinkage 0.0003 and 0.0002 / log10(t + 2) | IS 1343:1980 Table 4, 5.2.5.1, 5.2.4.1 | The parent's values are the same; cited now by concrete.clauses | Check |
| L6 | plumbing.tanks.crackLimit, crackControl | 0.2 mm, crackWidth (limit state); steelStress selectable | IS 3370 (Part 2):2009 4.1-4.2 | Crack control | Check |
| L7 | plumbing.tanks.steelStress | 130 MPa direct tension and liquid face, 190 MPa away from the liquid (HYSD) | IS 3370 (Part 2):2009 Table 2 | Working stress method | Uncertain |
| L8 | plumbing.tanks.surfaceZone | 0.35 % of the surface zone, h/2 up to 250 mm | IS 3370 (Part 2):2009 8.1.1, Figure 1 | Least steel each face and direction | Uncertain (ratio and the zone depth) |
| L9 | plumbing.tanks.cover, maxWaterCement, spacingMax, combinations | 45 mm liquid and weather faces (M30 least), 30 mm moderate; w/c 0.45; 300 mm; 1.5(D + F (+ H, + Lr)), 0.9D + 1.5H, service at 1.0 | IS 3370 (Part 1):2009 8.2, Table 1; IS 456 Table 18, 26.3.3 | Tank cover, durability, spacing, combinations | Check |
| L10 | concreteMethods.deepBeams.hogging | 0.5 (l/D - 0.5) within 0.2 D of the tension face, the rest within 0.3 D of mid-depth; even over 0.8 D at l/D <= 1 | IS 456:2000 29.3.2 (b) | Support steel of continuous deep beams (the side face bars across the middle zone counted) | Check |
| L11 | foundations.shallow.settlementRigidity | 0.8 (the elastic settlement of clay under an isolated footing) | IS 8009 (Part 1):1976 9.2.3 | Rigid footing correction (not on Schmertmann or consolidation: SAEngine practice) | Uncertain (clause number) |
| L12 | foundations.shallow.settlementLimits, settlementGuide | the parent's table (the same values) | IS 1904:1986 Table 1 | Permissible settlements | Check |
| L13 | foundations.shallow.raftStiffness | rigid when the column spacing < 1.75/λ, spacings within 20 % | IS 2950 (Part 1):1981 5.3.2 | Rigid / flexible raft (a note; the plate on springs runs either way) | Uncertain (clause number) |
| L14 | seismic.periodCoefficients.concreteWall | Ta = 0.075 h^0.75 / √Aw >= 0.09 h/√d, Aw = Σ Awi (0.2 + (Lwi/h)²), Lwi/h <= 0.9; systems rcOrdinaryWallFrame, rcSpecialWallFrame, rcFlatSlabWalls | IS 1893 (Part 1):2016 7.6.2 (b) | Wall-building period (the first storey's structural walls within 25° of the shaking) | Check |
| L15 | seismic.designEccentricity | edi = 1.5 esi + 0.05 bi or esi - 0.05 bi (the static cases add 0.5 esi on its side) | IS 1893 (Part 1):2016 7.8.2 | esi from the centre of mass and a plan estimate of the centre of rigidity (b d³ of the vertical members) | Check / Uncertain (the CR estimate is SAEngine practice) |
| L16 | wind.speedFactors.topography | k3 = 1 + C s; C = 1.2 Z/L (3°-17°), 0.36 above 17°; s 1.0; L = 2 Lh | IS 875 (Part 3):2015 Annex C | k3 from the topography settings | Uncertain (s at its crest peak; L from Lh: SAEngine practice) |
| L17 | wind.speedFactors.gustFactor | h/b > 5 or f0 < 1 Hz; G = 1 + r √(gv² Bs (1 + φ)² + Hs gR² S E/β); gv 3; Lh 85 (h/10)^0.25 (70 terrain 4); Bs 0.26, 0.46; S 3.5, 4; E 70.8, 5/6; gR √(2 ln 3600 f0); β 0.02 | IS 875 (Part 3):2015 10.2 | Gust factor method | Check |
| L18 | wind.speedFactors.gustFactor.turbulence, roughness, terrainShares | Iz,1 = 0.3507 - 0.0535 log10(z/0.002); Iz,4 = 0.466 - 0.1358 log10(z/2.0); terrains 2, 3 at 1/7, 3/7 | IS 875 (Part 3):2015 6.5 | Turbulence intensity | Check |
| L19 | wind.speedFactors.gustFactor.meanFactors | k̄2 at 10-300 m: TC1 0.78-1.09, TC2 0.67-1.04, TC3 0.50-0.95, TC4 0.50-0.80 | IS 875 (Part 3):2015 Table 4 (hourly mean) | Hourly mean speed factors | Uncertain (from memory: check every row) |
| L20 | serviceability.sway | H/500 under D + 0.8L + 0.8W | IS 16700:2017 5.4.1 | Lateral sway of tall buildings (the parent's value too) | Uncertain (clause number) |

Still the parent's after C12 (named after it in the notes): the column construction joint (shear
friction; IS 456 13.4 only places the joints), the IS 1343 flexural strength (Table 11), unbonded
fps, punching, bonded reinforcement and anchorage zones of prestressed slabs (the parent's ACI
318 based rules), the strength design of tank sections (φ of the parent), reinforced masonry
(IS 1905:1987 covers unreinforced masonry only; the IS 4326 bands are in masonry.seismic since
C9b), HSS joints, eccentrically braced frames, the composite columns and deck rules (not in IS
800:2007 / IS 11384:1985); in the loads the cladding and roof pressure coefficients (IS 875-3
Tables 5-8: SAEngine's components and cladding check is built on the area-dependent (GCp) form,
not the local Cpe zones), the across-wind response and the IS 16700 slenderness and acceleration
limits (SAEngine has no such checks).

## IS 2502:1963 bar bending schedules (alpha 9 C14)

`barSchedule.standard` = `is2502`. IS 2502 schedules show each shape as a sketch; SAEngine keeps
the BS 8666 / ISO 3766 numbers as each shape's reference (the sheets draw the sketches,
`shapeKey`). The bend radii are the code's (this pack has no IS 456 bend rule of its own yet:
the parent's), with no IS 2502 minimum radius.

| # | Path | Value | Clause | What | Confidence |
|---|---|---|---|---|---|
| BS1 | barSchedule.standards.is2502.deductions | 45° 1 d, 90° 2 d, 135° 3 d, 180° 4 d | IS 2502:1963 (bend deductions), SP 34:1987 | Bend deductions | Uncertain (from memory; the values commonly used with IS 2502) |
| BS2 | barSchedule.standards.is2502.shapes.11 / 21 / 23 / 31 / 41 | outside dimensions less n × 2 d | IS 2502:1963 | Bent bars | Check |
| BS3 | barSchedule.standards.is2502.shapes.26 | A + B + C - 2 × 1 d | IS 2502 (45° deduction) | Cranked bar (the stair crank is not 45°) | Uncertain |
| BS4 | barSchedule.standards.is2502.shapes.13 | A + B + C - 4 d | IS 2502 | One 180° bend | Uncertain |
| BS5 | barSchedule.standards.is2502.shapes.51, linkHook | 2(A + B) + 2C - 3 × 2d - 2 × 3d, C = code's 135° extension + r + d | IS 2502 / SAEngine practice | Closed stirrup | Uncertain (the hook allowance IS 2502 tabulates is not used) |
| BS6 | barSchedule.standards.is2502.shapes.77 | C √((π(A - d))² + B²) | geometry | Helix | Sure (geometry) |
| BS7 | barSchedule.standards.is2502.shapes (codes) | 00, 11, 13, 21, 23, 26, 31, 41, 51, 77, 99 | SAEngine practice | Shape references | Practice (IS 2502's own designations not used) |
| BS8 | barSchedule.standards.is2502.roundTo | 10 mm, up | SAEngine practice | Rounding | Practice |

## Alpha 9 P2: creep, shrinkage and column shortening (concreteTime)

| # | Path | Value | Clause | What | Confidence |
|---|---|---|---|---|---|
| P2I1 | concreteTime.creep.coefficients | 2.2, 1.6, 1.1 at 7 days, 28 days, 1 year | IS 456:2000 Cl 6.2.5.1 | Ultimate creep coefficient | Sure |
| P2I2 | concreteTime.creep.development | 0.451, 0.721, 0.889, 1.0 after 30 days, 6 months, 30 months, 30 years | ACI 209R-92 time-ratio normalised (IS 456 gives none) | Development in time | SAEngine practice |
| P2I3 | concreteTime.shrinkage.points | 300 × 10⁻⁶ at 30 years (134 and 253 at 28 days and 6 months) | IS 456:2000 Cl 6.2.4.1 (0.0003); the intermediate points by the ACI 209R-92 time-ratio | Total shrinkage | Sure (0.0003); practice (development) |
| P2I4 | concreteTime.shrinkage.reinforcementCoefficient | 0 (no factor) | IS 456 gives none | The steel restrains it in the age-adjusted analysis | SAEngine practice |
| P2I5 | concreteTime.analysis, ageing.chi | ageAdjusted, χ = 0.8 | none in IS 456 | Analysis method | SAEngine practice |
| P2I6 | combinations.creepShrinkage | none | IS 875 (Part 5), IS 456 Table 18 | CS analysed but not designed for | Check (whether IS 875-5 takes creep and shrinkage with the temperature load) |

## CFD wind tunnel (`cfdWind`; alpha 9 L3)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L3-1 | directionStep | 30° | none in the code | SAEngine practice |
| L3-2 | roughness.1 / 2 / 3 / 4 | z0 = 0.002 / 0.02 / 0.2 / 2.0 m | IS 875 (Part 3):2015 Sec 6.3.2.1 (the same values as the gust factor's roughness) | Check (clause number) |
| L3-3 | lowerLimit | 0.8 | after ASCE 7-22 Sec 31.4.3; IS 875 (Part 3) gives none | SAEngine practice |
| L3-4 | validation / clauses | wind tunnel studies of tall or unusual buildings | IS 875 (Part 3):2015 Sec 10 | Check (clause number) |
