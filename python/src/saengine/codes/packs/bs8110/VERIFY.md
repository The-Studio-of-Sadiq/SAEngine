# bs8110: values to verify against the printed codes

No copy of BS 8110, BS 6399 or BS 5950 was available when this pack was written (alpha 9, track
C10, 2026-11-04). Every value below was entered from knowledge of the codes and is to be checked
by the owner against the printed editions. **Sure**: well-known value, low risk. **Check**:
believed right, confirm the number or the row. **Uncertain**: the value or its reading may be
wrong, or it is an SAEngine form of the rule; SAEngine's choice is stated.

## BS 6399-2:1997 wind (standard method) and the sites

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| L1 | locations.*.windSpeed | London 21.5, Birmingham 22.0, Manchester 23.5, Liverpool 24.0, Leeds 23.0, Sheffield 22.5, Newcastle 24.0, Bristol 22.5, Cardiff 23.5, Swansea 24.5, Plymouth 24.0, Southampton 22.0, Norwich 22.5, Cambridge 21.5, Nottingham 22.0, Edinburgh 25.0, Glasgow 25.5, Aberdeen 26.0, Inverness 27.0, Belfast 25.0, Londonderry 27.0, Lerwick 31.0 m/s | Figure 6 | Basic hourly mean wind speed Vb read near each town | Uncertain (read off the isopleths from memory: check every town on the map) |
| L2 | locations.default | london | - | New projects start in London | SAEngine practice |
| L3 | speedFactors.airFactor | 0.613 | 2.1.2.1 | qs = 0.613 Ve² [Pa] | Sure |
| L4 | speedFactors.heightFactors | see the table below | Table 4 | Sb by effective height and distance from the sea, country and town | Uncertain (every cell from memory) |
| L5 | speedFactors.heightFactors (He) | He = the height (no displacement height) | 2.2.3.2 | Effective height | SAEngine practice (on the safe side in towns) |
| L6 | speedFactors.riskCoefficients | Sp = 1.0 | 2.2.2.5 | Probability factor of the standard design (Q = 0.02) | Sure |
| L7 | speedFactors.importance | Ss = 1.0 | 2.2.2.4 | Seasonal factor of permanent buildings | Sure |
| L8 | directionality | Sd = 1.0 | 2.2.2.3, Table 3 | Direction factor, the largest of Table 3 for every direction | Check (Table 3 peaks at 1.00 for the WSW sector) |
| L9 | topographic | Sa = 1.0 | 2.2.2.2 | Altitude factor 1 + 0.001 Δs: enter it as the topographic factor | Sure (the formula); the site's value is the project's |
| L10 | speedFactors.areaAveraging | Ca = 1.0 | 2.1.3.4, Figure 4 | Size effect factor, conservative (Figure 4 gives about 0.8-0.95 for buildings) | SAEngine practice |
| L11 | speedFactors.combination | 0.85 | 2.1.3.6 | The overall horizontal load as 0.85 (front + rear) | Check (the condition of 2.1.3.6 on the building) |
| L12 | cpWindward | +0.85 | Table 5 | Front face, D/H <= 1 | Check |
| L13 | cpLeeward | -0.5 | Table 5 | Rear face, D/H <= 1 (kept for deeper buildings, on the safe side) | Check |
| L14 | gust | 1.0 | 2.1.3.1 | The gusts are in Sb; the dynamic augmentation Cr is not applied | Check (buildings with Cr > 0.25 are outside the method) |
| L15 | defaultExposure | country10 | - | Country site 10 km from the sea | SAEngine practice |

Table 4 as entered (Sb; He in m):

| He | Country 0 km | 2 km | 10 km | >= 100 km | Town 2 km | 10 km | >= 100 km |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <= 2 | 1.48 | 1.40 | 1.35 | 1.26 | 1.40 | 1.35 | 1.26 |
| 5 | 1.65 | 1.62 | 1.57 | 1.45 | 1.45 | 1.42 | 1.36 |
| 10 | 1.78 | 1.78 | 1.73 | 1.62 | 1.56 | 1.54 | 1.47 |
| 15 | 1.85 | 1.85 | 1.82 | 1.71 | 1.73 | 1.70 | 1.63 |
| 20 | 1.90 | 1.90 | 1.89 | 1.77 | 1.83 | 1.81 | 1.74 |
| 30 | 1.96 | 1.96 | 1.96 | 1.85 | 1.96 | 1.95 | 1.87 |
| 50 | 2.04 | 2.04 | 2.04 | 1.95 | 2.04 | 2.04 | 1.99 |
| 100 | 2.12 | 2.12 | 2.12 | 2.07 | 2.12 | 2.12 | 2.10 |

## Earthquake (not covered)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| E1 | zoneCoefficients.zones | {0: 0.0}; every location zone 0 | - | The British Standards give no seismic loading: Z = 0, no EX / EY cases | Sure (coverage) |
| E2 | occupancyCategories.*.seismicImportance | 1.0 | - | Unused while Z = 0 | SAEngine practice |
| E3 | combinations.seismicDeadUpper / Lower | 1.0 / 1.0 | - | Unused (no earthquake combinations) | SAEngine practice |

A Z entered per project takes BNBC 2020's spectrum, systems and detailing (the parent pack); the
report names them BNBC 2020.

## BS 6399-1:1996 and BS 6399-3:1988 imposed loads

| # | Path | Value (kN/m², kN) | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| I1 | uses.residential | 1.5, 1.4 | Table 1 A1 | Self-contained dwelling units | Sure |
| I2 | uses.residentialPublic | 2.0, 1.8 | Table 1 A | Communal areas, hotel bedrooms | Check |
| I3 | uses.balcony | 1.5, 1.4 | Table 1 A | Balconies of dwellings (plus 1.5 kN/m at the edge, not applied) | Check |
| I4 | uses.office | 2.5, 2.7 | Table 1 B | Offices for general use | Sure |
| I5 | uses.officeComputer | 3.5, 4.5 | Table 1 B | Offices with data processing equipment | Check |
| I6 | uses.officeCorridor | 4.0, 4.5 | Table 1 C3 | Corridors, hallways | Check |
| I7 | uses.classroom | 3.0, 2.7 | Table 1 C1 | Classrooms | Sure |
| I8 | uses.schoolCorridor | 4.0, 4.5 | Table 1 C3 | Corridors, stairs of schools | Check |
| I9 | uses.hospitalWard | 2.0, 1.8 | Table 1 | Wards, bedrooms | Check |
| I10 | uses.operatingRoom | 2.0, 4.5 | Table 1 | Operating theatres, X-ray rooms | Check |
| I11 | uses.hospitalCorridor | 4.0, 4.5 | Table 1 C3 | Corridors | Check |
| I12 | uses.assemblyFixed | 4.0, 3.6 | Table 1 C2 | Areas with fixed seats | Sure |
| I13 | uses.assemblyMovable | 5.0, 3.6 | Table 1 C3/C5 | Areas without fixed seats | Sure |
| I14 | uses.dining | 2.0, 2.7 | Table 1 C1 | Dining rooms | Check |
| I15 | uses.gymnasium | 5.0, 3.6 | Table 1 C4 | Gymnasia, dance halls | Sure |
| I16 | uses.stageFloor | 7.5, 4.5 | Table 1 C5 | Stages | Check |
| I17 | uses.retailUpper | 4.0, 3.6 | Table 1 D1 | Shop floors | Sure |
| I18 | uses.manufacturingLight | 5.0, 4.5 | Table 1 E | Workrooms, light industrial | Check |
| I19 | uses.storageLight | 7.2, 7.0 | Table 1 E | 2.4 per m of storage height, here 3 m | Check (the height is SAEngine's) |
| I20 | uses.libraryStacks | 6.5, 7.0 | Table 1 | Stack rooms, 2.4 per m, at least 6.5 | Check |
| I21 | uses.parking | 2.5, 9.0 | Table 1 F | Car parks, vehicles up to 2500 kg | Sure |
| I22 | uses.stairs / stairsDwelling | 4.0, 4.5 / 1.5, 1.4 | Table 1 | Stairs and landings | Check |
| I23 | uses.roof | 0.6, 0.9 | BS 6399-3 4.3.1 | No access except maintenance | Sure |
| I24 | uses.roofAccess | 1.5, 1.8 | BS 6399-3 4.2 | With access (as the floors) | Check |
| I25 | concentratedPatch | 50 mm | 6.2 | Concentrated loads on a 50 mm square | Check |
| I26 | partitions | 1/3 of the weight per m, at least 1.0 | 6.3 | Partitions not located | Check (the 1.0 minimum is for offices) |
| I27 | liveReduction.floorCount.rows | 0, 10, 20, 30, 40 (5-10), 50 % (over 10) | 5.2, Table 2 | Reduction by the floors carried | Check |
| I28 | liveReduction.floorCount.beam* | 5 % per 50 m² over 50 m², at most 25 % | 5.1, Table 3 | Beams by the area supported | Check |

## Load combinations (BS 8110-1:1997 Table 2.1, BS 5950-1:2000 Table 2)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| C1 | strength "1" | 1.4G + 1.6Q (earth 1.4) | Table 2.1 | Dead and imposed | Sure |
| C2 | strength "2" | 1.0G + 1.6Q | Table 2.1 | Dead beneficial (applied to the whole structure: SAEngine) | Sure (factors) |
| C3 | strength "3W" / "4W" | 1.4G + 1.4W / 1.0G + 1.4W | Table 2.1 | Dead and wind | Sure |
| C4 | strength "5W" | 1.2(G + Q + W) | Table 2.1 | Dead, imposed and wind | Sure |
| C5 | service | G + Q, G + W, G + 0.8Q + 0.8W | BS 8110-2 3.3.3 | Serviceability | Check |
| C6 | - | not covered | 3.1.4.2 | The notional horizontal loads 1.5 % of the dead load | Not covered |

## BS 8110-1:1997 concrete

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K1 | ultimate.gammaC / gammaS | 1.5 / 1.05 | Table 2.2 | Partial factors (steel 1.05 with the amendment; 1.15 before) | Check (amendment in force) |
| K2 | ultimate.alphaCC, eta, lambda | 0.67, 1.007463, 0.9 | 3.4.4.1, Figure 3.3 | The simplified block 0.45 fcu over 0.9 x | Sure |
| K3 | ultimate.neutralAxisLimit | x/d <= 0.5 | 3.4.4.4 | K' = 0.156 (the limit with up to 10 % redistribution, taken everywhere) | Sure (value); SAEngine practice (no redistribution used) |
| K4 | ultimate.relations.ecm* | 20000 + 200 fcu MPa | BS 8110-2 7.2 | Ec,28 = 20 + 0.2 fcu kN/mm² | Sure |
| K5 | ultimate.relations.fctm* | 0.55 √fcu | BS 8110-2 3.6 | Flexural tensile strength | Uncertain |
| K6 | ultimate.eccentricity* | 0.05 h, at most 20 mm | 3.8.2.4 | Nominal eccentricity | Sure |
| K7 | ultimate.axialShares | 0.4 fcu Ac + 0.80 fy Asc | 3.8.4.3 eq. 38 | Short braced columns (0.75 with γs 1.15) | Check |
| K8 | ultimate.strengthClasses | C25-C50 (cube) | 3.1.7.4 | The project's fc read as fcu | Check |
| K9 | shear.tauC | 0.79 (100As/bd)^1/3 / 1.25 × (fcu/25)^1/3, rows 0.15-3 %, columns 25-40 | Table 3.8 | vc (the tabulated values come from this formula) | Sure (formula) |
| K10 | shear.depthFactor | (400/d)^1/4 >= 1 | Table 3.8 | Depth factor, every member | Check (whether 0.67 applies to members without links in the 1997 text) |
| K11 | shear.maxStress | 4.00, 4.38, 4.73, 5.00 | 3.4.5.2 | 0.8 √fcu at most 5 N/mm² | Sure |
| K12 | shear.minStirrupStress / fyMax | 0.4 / 460 | Table 3.7, 3.4.5.1 | Least links, fyv at most 460 | Sure |
| K13 | shear.spacing | 0.75 d | 3.4.5.5 | Link spacing along the span | Sure |
| K14 | shear.enhancement | 2 d / av | 3.4.5.8 | Near supports (corbels only) | Sure |
| K15 | punching | v on 1.5 d, vc as 0.10 √fcu, links up to 2 vc | 3.7.7 | Punching (vc without the slab's steel ratio) | Uncertain (SAEngine form) |
| K16 | deflection.basic | 7, 20, 26 | Table 3.9 | Basic span / effective depth | Sure |
| K17 | deflection.flange | 0.8 at bw/b <= 0.3 | Table 3.9 | Flanged beams | Sure |
| K18 | deflection.longSpan | 10 m | 3.4.6.4 | × 10 / span | Sure |
| K19 | deflection.tensionMoment | 0.55 + (477 - fs)/(120 (0.9 + M/bd²)) <= 2 | Table 3.10 | Tension steel factor | Sure (formula) |
| K20 | deflection.stressShare | 2/3 | Table 3.10 | fs = 2/3 fy As,req/As,prov (5/8 fy may apply with γs 1.05) | Check |
| K21 | deflection.leverArm | 0.9 | - | M/bd² from pt (As,req = As,prov) | SAEngine practice |
| K22 | deflection.compression | 1 + pc/(3 + pc) <= 1.5 | Table 3.11 | Compression steel factor | Sure |
| K23 | deflection.flatSlabFactor | 0.9 | 3.7.8 | Flat slabs without drops | Sure |
| K24 | deflection.flangeT / flangeL | bw + l/5, bw + l/10 | 3.4.1.5 | Effective flange (lz = the span) | Check |
| K25 | deflection.limitTotal / After / AfterMax | 250 / 350 / 20 mm | BS 8110-2 3.2.1.1 | Calculated deflection limits | Sure |
| K26 | deflection.shrinkageK3 | 0.5, 0.125, 0.086, 0.063 | BS 8110-2 3.7.2 | Shrinkage curvature coefficient by support | Check |
| K27 | deflection.creep, shrinkageStrain, shrinkageK4, ruptureCoefficient | 2.8 / 2.5 / 1.5 (7, 28, 365 days), 0.0003, IS-form k4, 0.55 | BS 8110-2 7.3-7.4, 3.6 | Creep, shrinkage | Uncertain (SAEngine practice in place of Figures 7.1, 7.2) |
| K28 | deflection.tension | unused | - | The IS-type fit (tensionMoment replaces it) | - |
| K29 | cracking.width | 0.3 mm; tanks 0.2 mm | BS 8110-2 3.2.4.1; BS 8007 | Crack width limits | Sure |
| K30 | cracking.stiffeningDivisor | 3 | BS 8110-2 3.8.3 eq. 13 | Tension stiffening | Sure |
| K31 | cover.conditions | mild 25/C30/275/0.65; moderate 35/C35/300/0.60; severe 40/C40/325/0.55; very severe 50/C40/325/0.55; most severe 50/C50/400/0.45 | Table 3.3 | Nominal cover, least grade, cement, w/c | Check (each cell) |
| K32 | cover.gradeReduction | 5 mm less at C40 and above, moderate | Table 3.3 | Moderate: 30 mm at C40 | Check |
| K33 | cover.footingCover / columnCover | 75 / 25 | 3.3.1.4 | Cast against earth; columns as the exposure | Sure / SAEngine practice |
| K34 | anchorage.bond | 0.28 √fcu | 3.12.8.4, Table 3.26 | Plain bars in tension | Sure |
| K35 | anchorage.deformedFactor / compressionFactor | 0.5/0.28; 1.008 | Table 3.26, 3.12.8.13 | Type 2 bars 0.5 √fcu; compression 0.63 √fcu with the compression lap 1.25 × (the compression anchorage 25 % long: on the safe side) | Check |
| K36 | anchorage.lapTension / lapCompression | 15 φ | 3.12.8.13 | Laps at least 15 φ (and 300 mm, not checked) | Check |
| K37 | anchorage | top and corner lap factors 1.4 / 2.0 | 3.12.8.13 | Not applied | Not covered |
| K38 | memberLimits.beamMin | 0.66 (As/bd >= 0.66/fy) | Table 3.25 | 0.13 % of b h at fy 460, on b d with d = 0.9 h | Uncertain (SAEngine form) |
| K39 | memberLimits.beamMax | 4 % | 3.12.6.1 | Largest steel | Sure |
| K40 | memberLimits.sideFace* | h > 750 mm, 250 mm apart, 0.1 % | 3.12.5.4 | Side bars (the size rule as 0.1 %: SAEngine) | Check / SAEngine practice |
| K41 | memberLimits.slabMin | 0.13 % / 0.24 % of b h | Table 3.25 | High yield / mild steel | Sure |
| K42 | memberLimits.slabSpacing | 3 d, 750 mm | 3.12.11.2.7 | Slab bar spacing | Sure |
| K43 | memberLimits.columnRho / columnBars / columnBarDia | 0.4-6 %, 4 and 6 bars, 12 mm | 3.12.5.3, 3.12.6.2, 3.12.5.4 | Column steel | Sure |
| K44 | memberLimits.tie* | φ/4, 6 mm, 12 φ | 3.12.7.1 | Links of columns | Sure |
| K45 | memberLimits.neutralAxisStrain | 0.0013 | - | The balanced strain of Nbal (x = 0.5 d at fy 460) | SAEngine practice |
| K46 | columns.slenderness | 15 braced, 10 unbraced, /2000, 60 | 3.8.1.3, 3.8.3.1, 3.8.1.7 | Slender columns and the additional moment | Sure |
| K47 | columns.biaxial.puzShares | 0.45 fcu Ac + 0.95 fy Asc | 3.8.3.1 | Nuz of K | Check (0.87 fy before the amendment) |
| K48 | columns.biaxial.method | surface | 3.8.4.5 | Biaxial bending by the interaction surface (not the enhanced moment) | SAEngine practice |
| K49 | twoWaySlabs.cases | nine cases, ly/lx 1.0-2.0 | Table 3.14 | Restrained slab coefficients | Check (every cell) |
| K50 | twoWaySlabs.simple* | 0.062-0.118 / 0.062-0.029 | Table 3.13 | Simply supported slabs | Check |
| K51 | twoWaySlabs.torsion* | 3/4 over lx/5; half | 3.5.3.5 | Corner torsion steel | Sure |
| K52 | concrete.modulus.normal | 4750 √fcu | BS 8110-2 7.2 | Ec of the shared checks (within 5 % of 20 + 0.2 fcu for C25-C35) | SAEngine form |

Table 3.14 as entered (short span negative at a continuous edge / positive at midspan, ly/lx 1.0,
1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0; then the long span negative / positive):

| Case | Short negative | Short positive | Long negative | Long positive |
| --- | --- | --- | --- | --- |
| 1 interior | .031 .037 .042 .046 .050 .053 .059 .063 | .024 .028 .032 .035 .037 .040 .044 .048 | .032 | .024 |
| 2 one short edge disc. | .039 .044 .048 .052 .055 .058 .063 .067 | .029 .033 .036 .039 .041 .043 .047 .050 | .037 | .028 |
| 3 one long edge disc. | .039 .049 .056 .062 .068 .073 .082 .089 | .030 .036 .042 .047 .051 .055 .062 .067 | .037 | .028 |
| 4 two adjacent edges disc. | .047 .056 .063 .069 .074 .078 .087 .093 | .036 .042 .047 .051 .055 .059 .065 .070 | .045 | .034 |
| 5 two short edges disc. | .046 .050 .054 .057 .060 .062 .067 .070 | .034 .038 .040 .043 .045 .047 .050 .053 | - | .034 |
| 6 two long edges disc. | - | .034 .046 .056 .065 .072 .078 .091 .100 | .045 | .034 |
| 7 three edges disc. (one long cont.) | .057 .065 .071 .076 .081 .084 .092 .098 | .043 .048 .053 .057 .060 .063 .069 .074 | - | .044 |
| 8 three edges disc. (one short cont.) | - | .042 .054 .063 .071 .078 .084 .096 .105 | .058 | .044 |
| 9 four edges disc. | - | .055 .065 .074 .081 .087 .092 .103 .111 | - | .056 |

## BS 5950-1:2000 steel

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| S1 | partialFactors.gammaM0 | 1.0 | 2.4.4 | γm (in py) | Sure |
| S2 | partialFactors.gammaM1 | 1.1 | 3.4.3, 4.6.1 | 0.9 An fu / 1.1 standing for Ke An py (Ke 1.2 S275, 1.1 S355) | SAEngine form (within 2 %) |
| S3 | designStrength | S275: 275, 265, 255, 245, 235; S355: 355, 345, 335, 325, 315 at t <= 16, 40, 63, 80, 100 mm | Table 9 | py by thickness (applies when the material's fy is 275 or 355) | Check |
| S4 | classification | outstands 9, 10, 15 ε (welded 8, 9, 13); webs 80, 100, 120 ε; RHS flanges 28, 32, 40 ε; CHS 40, 50, 140 ε²; ε = √(275/py) | Tables 11-12 | Section classes | Check |
| S5 | compression.alpha (robertson) | a 2.0, 3.5, 5.5, 8.0; λ0 = 0.2 π √(E/py) | Annex C | Perry-Robertson strut curves a-d | Sure |
| S6 | compression curves | rolled I x-x a / y-y b (tf <= 40), b / c above; welded b / c, c / d; hot-finished hollow a; channels, angles, tees c; solid bars b | Table 23 | Strut curve allocation | Check |
| S7 | compression.angleConstants | λ = 0.85 Lv/rv (two bolts), 1.0 (one bolt) | 4.7.10.2 | Single angles (the lower bounds not modelled) | Uncertain (SAEngine form) |
| S8 | flexure.elasticCap | 1.2 py Zx; 1.5 cantilevers | 4.2.5.1 | Moment capacity | Sure |
| S9 | flexure.alphaLT (robertson), ltbPlateau, ltbBase | 7.0; 0.4 | Annex B.2.2 | pb by ηLT = 0.007 (λLT - λL0) | Check |
| S10 | flexure | the moment factor in Mcr | 4.3.6 | In place of mLT on the moment | SAEngine form |
| S11 | flexure.highShare | 0.6 Pv | 4.2.5.3 | High shear | Sure |
| S12 | shear.yieldShare | 0.6 | 4.2.3 | Pv = 0.6 py Av | Sure |
| S13 | shear.bucklingLimit | 70 ε | 4.4.5 | Shear buckling of webs (post-critical method in place of Annex H) | Check / SAEngine form |
| S14 | interaction | linear section check; member K = 1, m >= 0.4 | 4.8.3.2, 4.8.3.3.1 | Combined forces with the plastic moment capacities | Uncertain (less conservative than py Z for class 1-2) |
| S15 | tension.angleAlpha | 0.55 | 4.6.3.1 | Angles connected by one leg | Uncertain (SAEngine form) |
| S16 | slenderness | 180 compression, 350 tension | 4.7.3.2 | Slenderness limits (BS 5950 has no tension limit) | Check / SAEngine practice |
| S17 | shearModulus | 79 000 MPa | 3.1.3 | G of E 205 kN/mm², ν 0.3 | Sure |
| S18 | bracing.share | 2.5 % | 4.3.2.2 | Restraint force | Sure |

## Not covered (from BNBC 2020, named so)

Concrete torsion (BS 8110-2 2.4), flat slab moment coefficients (Table 3.12 / 3.7), walls (3.9),
bases (3.11), the notional horizontal loads, the fire covers of Table 3.4; BS 5950 connections
(bolts Table 30, welds), the composite and the steel seismic rules; BS 5628 masonry and BS 5268
timber (SAEngine's masonry and timber engines keep the parent's methods).

## BS 8666:2020 bar schedules (alpha 9 C14; the parent's barSchedule, inherited)

The default pack's schedule standard, which this pack keeps. Moved from code constants into the
default pack's `barSchedule` table unchanged (written from memory before code packs).

| # | Path | Value | Clause | What | Confidence |
|---|---|---|---|---|---|
| BB1 | barSchedule.standards.bs8666.radius.bySize | 6:12, 8:16, 10:20, 12:24, 16:32, 20:70, 25:87, 32:112, 40:140, 50:175 mm | BS 8666:2020 Table 2 | Minimum scheduling radius r (B500) | Uncertain (from memory) |
| BB2 | barSchedule.standards.bs8666.radius.steps | 2 d up to 16 mm, 3.5 d (rounded up) above | BS 8666:2020 Table 2 | r of other sizes | Uncertain |
| BB3 | barSchedule.standards.bs8666.endProjection | 6:110, 8:115, 10:130, 12:160, 16:210, 20:290, 25:365, 32:465, 40:585, 50:725 mm; else r + 11 d to 5 mm | BS 8666:2020 Table 2 | Minimum end projection P | Uncertain (from memory) |
| BB4 | barSchedule.standards.bs8666.shapes.11 / 21 / 23 | A + B - 0.5r - d; A + B + C - r - 2d | BS 8666:2020 Table 3 | Shapes 11, 21, 23 | Check |
| BB5 | barSchedule.standards.bs8666.shapes.12 / 13 / 15 / 26 | A + B - 0.43R - 1.2d; A + 0.57B + C - 1.6d; A + C; A + B + C | BS 8666:2020 Table 3 | Shapes 12, 13, 15, 26 | Uncertain |
| BB6 | barSchedule.standards.bs8666.shapes.22 / 31 / 33 / 41 | A+B+C+D - 1.5r - 3d; 2A + 1.7B + 2(C - 4d); A+B+C+D+E - 2r - 4d | BS 8666:2020 Table 3 | Shapes 22, 31, 33, 41 | Uncertain |
| BB7 | barSchedule.standards.bs8666.shapes.51 / 63 / 77 | 2(A+B+C) - 2.5r - 5d; 2A + 3B + 2C - 3r - 6d; C π (A - d) | BS 8666:2020 Table 3 | Links and helix | Check |
| BB8 | barSchedule.standards.bs8666.roundTo, linkHook | 25 mm up; hook end = code's 135° extension + r + d, to 5 mm, >= P | BS 8666:2020 (rounding), SAEngine practice (hook) | Rounding and link hooks | Check |
