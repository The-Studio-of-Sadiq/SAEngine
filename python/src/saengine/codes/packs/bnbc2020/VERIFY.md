# BNBC 2020 pack: values to verify

The BNBC 2020 values of this pack were transcribed from the code text with their pages. This
file lists the values that are **not** BNBC's own: the methods of other codes and references the
pack uses where BNBC 2020 requires a check but gives no method (alpha 9 track P7), and the ASCE/SEI
7-05 Chapter 15 values BNBC Sec 2.5.18 adopts. They were entered from knowledge of the sources,
without a copy at hand: check each against the printed document. "Check" marks the ones the
author is less sure of.

## Floor vibration (`floorVibration`; BNBC Part 6 Sec 1.4.2(e) p. 495, 10.12.5 p. 1375)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| FV1 | frequencyConstant | 0.18 (fn = 0.18 √(g/Δ)) | AISC DG11 2nd ed. Eq 3-3 | Sure |
| FV2 | walkingAcceleration.force | 0.29 kN (65 lb) | AISC DG11 Eq 4-1 | Sure |
| FV3 | walkingAcceleration.decay | 0.35 | AISC DG11 Eq 4-1 | Sure |
| FV4 | walkingAcceleration.minimumFrequency / maximumFrequency | 3 Hz / 9 Hz | AISC DG11 Ch 4 (validity) | Check |
| FV5 | walkingAcceleration.damping | 0.01 bare, 0.02 ceilings, 0.025 furnished, 0.05 partitions | AISC DG11 2nd ed. Table 4-2 | Check |
| FV6 | walkingAcceleration.panelBays | 1.0 bay | SAEngine practice (DG11 B ≤ 2/3 floor width gives more) | Practice |
| FV7 | occupancies.*.accelerationLimit | 0.5 % offices, residences, hospitals; 0.25 % critical; 1.5 % shopping, indoor walkways | AISC DG11 Table 4-1 (critical: SAEngine practice) | Check |
| FV8 | occupancies.*.serviceLive | 0.5 kPa offices, 0.3 kPa residences, 0 shopping | AISC DG11 Sec 4.1 (11 psf, 6 psf) | Check |
| FV9 | responseFactor.walkerWeight | 746 N | SCI P354 (76 kg) | Check |
| FV10 | responseFactor.pace | 1.8 - 2.2 Hz | SCI P354 Table 3.1, harmonic 1 | Check |
| FV11 | responseFactor.harmonics | r1 = 0.436(fp - 0.95), r2 = 0.006(2fp + 12.3), r3 = 0.007(3fp + 5.2), r4 = 0.007(4fp + 2.0) | SCI P354 Table 3.1 (Arup / Young 2001) | Check |
| FV12 | responseFactor.highFrequency | 10 Hz | SCI P354 / CCIP-016 | Check |
| FV13 | responseFactor.baseAcceleration | 0.005 m/s² rms | ISO 10137 base curve (4-8 Hz) | Sure |
| FV14 | responseFactor.impulse, impulsePace, impulseFrequency, impulseWeight | 54 fp^1.43 / fn^1.30 × Q/700 N·s | CCIP-016 effective impulse | Check |
| FV15 | responseFactor.stepLength, modalShare | 0.75 m, 0.25 of one bay | SAEngine practice (simply supported panel) | Practice |
| FV16 | responseFactor.damping | 0.015 bare, 0.02 ceilings, 0.03 furnished, 0.045 partitions | CCIP-016 | Check |
| FV17 | occupancies.*.responseLimit | 4 office, residential, shopping; 2 hospital ward; 1 critical; 8 walkway | ISO 10137:2007 Annex C, SCI P354 Table 5.1 | Check |

## Wind comfort (`windComfort`; BNBC Part 6 Sec 10.12.6 p. 1376)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| WC1 | response | along-wind σ = 0.85 φ ρ B h Cfx V̄z̄² Iz̄ K R / m1, K = 1.65^ᾱ/(ᾱ + ξ + 1) | ASCE 7-05 Commentary C6.5.8 | Check (ᾱ or α̂ in K) |
| WC2 | mriTerms | V_T/V_50 = 0.36 + 0.10 ln(12 T) | ASCE 7-05 Commentary C6.5.5 | Sure |
| WC3 | referencePeriod | 50 years | BNBC 2020 Part 6 Sec 2.4.2 (p. 516) | Sure |
| WC4 | returnPeriod | 10 years | SAEngine practice (tall-building criteria) | Practice |
| WC5 | airDensity | 1.25 kg/m³ | SAEngine practice | Practice |
| WC6 | duration, peakConstant | 3600 s, 0.5772 | ASCE 7-05 Eq 6-9 (gR) | Sure |
| WC7 | damping | 0.015 concrete, 0.01 steel | SAEngine practice (serviceability damping) | Practice |
| WC8 | limits | 15 / 18 / 25 milli-g residential / hotel / office (10-year peak) | Isyumov 1993; CTBUH practice | Check |

## Non-building structures (`nonBuilding`; BNBC Part 6 Sec 2.5.18 p. 669 → ASCE/SEI 7-05 Ch 15)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| NB1 | supportedShare | 25 % | BNBC Sec 2.5.15 (p. 653); ASCE 7-05 15.3.1 | Sure |
| NB2 | rigidPeriod, rigidFactor | 0.06 s, 0.30 SDS W I | ASCE 7-05 15.4.2 | Sure |
| NB3 | minimumCoefficient | 0.044 SDS I ≥ 0.03 | ASCE 7-05 15.4.1(2) | Check (7-05 wording) |
| NB4 | elevatedTankBraced | R 3, Ω0 2, Cd 2.5 | ASCE 7-05 Table 15.4-2 | Check |
| NB5 | elevatedTankUnbraced | R 2, Ω0 2, Cd 2.5 | Table 15.4-2 | Check |
| NB6 | horizontalVessel | R 3, Ω0 2, Cd 2.5 | Table 15.4-2 | Check |
| NB7 | trussedTower | R 3, Ω0 2, Cd 2.5 | Table 15.4-2 | Check |
| NB8 | cantileverColumn | R 2, Ω0 2, Cd 2 | Table 15.4-2 | Check |
| NB9 | signBillboard | R 3.5, Ω0 1.75, Cd 3 (US pack: 3.0) | Table 15.4-2 | Check |
| NB10 | telecomTrussSteel / telecomPoleSteel | 3 / 1.5 / 3; 1.5 / 1.5 / 1.5 | Table 15.4-2 | Check |
| NB11 | coolingTower | R 3.5, Ω0 1.75, Cd 3 | Table 15.4-2 | Check |
| NB12 | steelStorageRack | R 4, Ω0 2, Cd 3.5 | Table 15.4-1 | Check |
| NB13 | otherSelfSupporting | R 1.25, Ω0 2, Cd 2.5 | Table 15.4-2 | Check |

## Laterally loaded piles (`foundations.piles.lateral.soilFailure`, `.pyAnalysis`; BNBC Sec 3.10.1.21 p. 752)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| LP1 | soilFailure.passiveCohesive, cohesiveGap | 9 cu D below 1.5 D | Broms 1964a | Sure |
| LP2 | soilFailure.passiveGranular | 3 Kp γ' D z | Broms 1964b | Sure |
| LP3 | soilFailure.factorOfSafety | 2.5 | SAEngine practice | Practice |
| LP4 | soilFailure.averagingDepth | 10 D | SAEngine practice | Practice |
| LP5 | pyAnalysis.clayJ | 0.5 | Matlock 1970 | Sure |
| LP6 | pyAnalysis.stiffClayCu | 96 kPa | SAEngine practice (stiff clay band) | Practice |
| LP7 | pyAnalysis.strain50 | ε50 0.02 / 0.01 / 0.007 / 0.005 / 0.004 up to cu 24 / 48 / 96 / 192 / 383 kPa | Reese & Van Impe | Check |
| LP8 | pyAnalysis.sandModulus | k above / below water: φ 28: 6.8 / 5.4, 32: 24.4 / 16.3, 36: 61 / 34, 40: 81 / 45 MN/m³ | API RP 2GEO figure (digitised from memory) | Check |
| LP9 | pyAnalysis.sandCoefficient | A = 3 - 0.8 z/D ≥ 0.9 | API RP 2GEO (static) | Sure |
| LP10 | pyAnalysis.inertiaFactor | 1.0 (gross EI) | SAEngine practice | Practice |

## Embedded walls (`embeddedWalls`; BNBC Part 6 Sec 3.12 p. 797)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| EW1 | passiveFactor | 2.0 | CIRIA Report 104 (Padfield & Mair 1984) | Check |
| EW2 | embedmentIncrease | 1.2 | Blum's simplification (fixed earth) | Sure (practice) |
| EW3 | freeEarthIncrease | 1.0 | with the factor on Kp | Practice |
| EW4 | minimumSurcharge | 10 kPa | CIRIA C580 / EN 1997-1 practice | Check |
| EW5 | overdigShare, overdigMax | 10 % of H, 0.5 m | EN 1997-1 9.3.2.2 | Sure |

## Excavation support (`excavationSupport`; BNBC Part 6 Sec 3.12 p. 797, Sec 3.16 p. 805; alpha 9 P1)

BNBC 2020 asks for retained excavation sides and names sheet piles with tie-back anchors without
a method: every value below except ES2 and ES16 is SAEngine practice.

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| ES1 | analysis | subgradeReaction: elastic-plastic springs, each stage on the total deflection, supports from their placing | SAEngine practice | Practice |
| ES2 | analyses[0] | characteristic soil, effects × hFactor 1.6 | BNBC Part 6 Sec 2.7.3.1 (p. 685): 1.6H | Check (1.6H on the effects of a characteristic soil-structure analysis) |
| ES3 | earthPressure.activeMethod / passiveMethod | coulomb / coulomb, horizontal components | SAEngine practice | Practice |
| ES4 | earthPressure.activeFriction | δa = 2/3 φ' | CIRIA C580, BS 8002 practice (from memory) | Check |
| ES5 | earthPressure.passiveFriction | δp = 1/3 φ' (Coulomb overestimates Kp above about φ'/3) | SAEngine practice | Check |
| ES6 | earthPressure.minimumFluid | 5 kN/m³ × z behind the wall | CIRIA C580 4.1.3 (from memory) | Check |
| ES7 | earthPressure.stripFactor | 1.0 (a flexible wall; 2.0 for an unyielding one) | Boussinesq, SAEngine practice | Check |
| ES8 | subgrade.method, schmittCoefficient | schmitt, 2.1 | Schmitt (1995), kh = 2.1 Eoed^(4/3) / EI^(1/3) | Check |
| ES9 | subgrade.poisson | 0.3 | SAEngine practice | Practice |
| ES10 | subgrade.granularModulus | φ' 28/32/36/40° → E 10/25/50/80 MPa | SAEngine practice (typical ranges) | Unsure |
| ES11 | subgrade.cohesiveModulus | E = 300 cu | SAEngine practice | Unsure |
| ES12 | subgrade.tabulatedGranular, tabulatedCohesive | φ' 28/32/36/40° → 10/25/50/80 MN/m³; 80 cu | SAEngine practice (Terzaghi 1955 order of magnitude) | Unsure |
| ES13 | subgrade.concreteStiffness | 0.7 × uncracked EI | SAEngine practice | Check |
| ES14 | subgrade.soldierPassiveWidth | 3 × flange width (≤ spacing) | FHWA / Broms arching practice | Check |
| ES15 | struts.temperatureRange, temperatureRestraint, expansion, temperatureFactor | 15 °C, 0.5, 1.2e-5 /°C, 1.0 | CIRIA C517 practice (ΔT for Bangladesh SAEngine's) | Unsure |
| ES16 | struts.selfWeightFactor | 1.2 | BNBC Part 6 Sec 2.7.3.1: 1.2D | Sure |
| ES17 | struts.effectiveLength, symmetricShare | K 1.0; half the strut's length shortens | SAEngine practice | Practice |
| ES18 | struts.walerMoment, walerShear | w s²/10, 0.6 w s | continuous-beam coefficients | Practice |
| ES19 | anchors.tendonFactor, groundFactor (permanent) | 1.4, 2.0 (2.0, 3.0) | BS 8081:2015 minimum factors of safety (from memory) | Check |
| ES20 | anchors.proofFactor (permanent), lockOffShare, testTendonLimit | 1.25 (1.5), 1.1, 0.8 fpk A | BS 8081 practice (from memory) | Check |
| ES21 | anchors.freeLengthMin, fixedLengthMin, fixedLengthMax | 5 m, 3 m, 10 m | BS 8081 practice | Check |
| ES22 | anchors.wedgeClearance, wedgeClearanceMin | 0.2 H, 1.5 m | FHWA GEC No. 4 | Check |
| ES23 | anchors.groutDiameter | 150 mm | SAEngine practice | Practice |
| ES24 | anchors.bondGranular | φ' 28/32/36/40° → τ 100/200/300/400 kPa | PTI DC35.1 ranges (mid values, from memory) | Unsure |
| ES25 | anchors.bondCohesive, bondCohesiveMax | 0.35 cu, 250 kPa | BS 8081 α for stiff clay (from memory) | Check |
| ES26 | anchors.stiffnessLength | free + 0.5 × fixed length | PTI apparent free length | Practice |
| ES27 | heave.basalFactor, basalNcMax | 1.5, Nc ≤ 9 | Bjerrum & Eide (1956), Skempton's Nc | Check |
| ES28 | heave.pipingFactor | 2.0 on Harr's exit gradient | Harr (1962) | Check |
| ES29 | deflectionShare | 0.5 % of the excavation depth (reported) | SAEngine practice | Practice |
| ES30 | sheet pile U sections (saengine.library.sheet_piles) | 400×100×10.5: W 874 cm³/m, I 8 740 cm⁴/m, 120 kg/m²; 400×125×13: 1 340, 16 800, 150; 400×170×15.5: 2 270, 38 600, 190; 600×130×10.3: 1 000, 13 000, 102; 600×180×13.4: 1 800, 32 400, 136; 600×210×18: 2 700, 56 700, 176 | JIS A 5523 / A 5528 types II-IV, IIw-IVw (from memory) | Check |
| ES31 | sheet pile Z sections | generic nominal W 1 100-3 000 cm³/m, I ≈ W h / 2 | SAEngine nominal | Unsure (use the supplier's) |

## Alpha 9 P2: the creep and shrinkage forces case

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| P2B1 | combinations.creepShrinkage | 1.2D + 1.2CS + 1.6L + 0.5Lr | Part 6 Sec 2.7.3.1 combination 2, 1.2(D + F + T), T including creep and shrinkage (Sec 2.1 notation, part 1 p. 525) | Sure |
| P2B2 | concreteTime (no ageing, no analysis) | χ = 0.8 generic for the forces' relaxation; superposition for the shortening (B25 unchanged) | SAEngine practice | Practice |

## Alpha 9 P4: assessment and retrofit of existing buildings (existing)

BNBC 2020 asks for the structural analysis of an existing building (Part 10 Sec 1.3.2, gazette p.
5003) and names seismic strengthening and retrofitting (Part 7 Sec 5.10.3-5.10.4, gazette pp.
4506-4507) without a method or values. Every value of `existing.json` is SAEngine practice on the
ASCE 41-17 basis: the same values as the aci318-asce7-22 pack's P4U1-P4U30 (see its VERIFY.md).

| # | Key | Value | Clause | Confidence |
|---|---|---|---|---|
| P4B1 | existing.sources.requirement | the existing building investigated and analysed by professionals; it supports the Part 6 loads | BNBC 2020 Part 10 Sec 1.3.1-1.3.2 (gazette p. 5003) | Sure |
| P4B2 | existing.sources.liveLoads | detail engineering assessment of factory buildings: 3 kN/m² manufacturing, 6 kN/m² storage; retrofit design with Part 6 loads | BNBC 2020 Part 10 Sec 1.3.2.3 | Sure (cited, not applied: the area loads are the project's) |
| P4B3 | existing.linear.hazards | DBE (scale 1.0) at LS, MCE (1.5 × DBE) at CP | BNBC 2020 Part 6 Sec 2.5.2.1 (gazette p. 3186: the design basis earthquake is 2/3 of the MCE) | Sure for the 1.5; SAEngine practice for the levels |
| P4B4 | all other values | as the US pack's P4U1-P4U30 | ASCE 41-17, ACI 440.2R-17, EN 1998-3 A.4.2.2 | SAEngine practice |

## Precast pieces (`precast`; alpha 9 L1; BNBC Part 6 Sec 6.10 pp. 987-992)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L1B1 | bearing.spanDivisor | ln / 180 | BNBC 2020 Part 6 Sec 6.10.6.2.2(a) (p. 991) | Sure |
| L1B2 | bearing.minimum | 50 mm solid or hollow-core slabs, 75 mm beams and stemmed members | Sec 6.10.6.2.2(a) | Sure |
| L1B3 | bearing.padSetback | 13 mm from an unarmoured edge | Sec 6.10.6.2.2(b) | Sure |
| L1B4 | bearing.stressFactor | 0.85 f'c A1, φ of factors.phi.bearing (0.65) | Sec 6.10.6.2.1, 6.3.14 | Sure |
| L1B5 | dowel.method | shearFriction (Sec 6.4.5) | Sec 6.10.6.1.1 (p. 990) | Sure |
| L1B6 | connections.tensionShare | 0.2 Vu where none is entered | the corbel's least Nuc, Sec 6.4.7.3.4, applied to every bearing | SAEngine practice |
| L1B7 | integrity.diaphragm | 4.4 kN/m | Sec 6.10.5.1.2 (p. 988) | Sure |
| L1B8 | integrity.columnTension | 1.4 Ag [N] | Sec 6.10.5.1.3(a) (p. 989) | Sure |
| L1B9 | integrity.panelTies / panelTieForce | 2 ties of 44 kN per panel | Sec 6.10.5.1.3(b) | Sure |
| L1B10 | integrity.bearingWallStoreys, floorTies, floorTieSpacing, perimeterTie, perimeterEdge, verticalTies | 3 storeys; 22 kN/m; 3 m; 71 kN; 1.2 m; 44 kN/m | Sec 6.10.5.2.1-6.10.5.2.5 (pp. 989-990) | Sure (printed as requirements, not checked member by member) |
| L1B11 | handling.stripping | 1.3 flat removable forms, 1.4 false joints, 1.6 fluted, 1.7 sculptured (smooth form column) | PCI Design Handbook 8th ed., equivalent static load multipliers | Check (table number and the smooth-form column) |
| L1B12 | handling.yard / transport / erection | 1.2 / 1.5 / 1.2 | PCI Design Handbook 8th ed. | Check |
| L1B13 | handling.stripShare | f'ci = 0.7 f'c when not entered | none | SAEngine practice |
| L1B14 | handling.tension | 0.62 √f'ci / 1.5 (fr = 7.5 √f'ci psi) | PCI Design Handbook (cracking during handling, SF 1.5) | Check |
| L1B15 | handling.inserts | 2 / 4 / 2 inserts carry the load (two-point / four-point equalised / four-point rigid) | none (rigid four-point rigging: two inserts assumed) | SAEngine practice |
| L1B16 | handling.insertSafety | 4 on the insert's ultimate load | PCI Design Handbook (lifting devices) | Check |
| L1B17 | erection.windPressure | 0.5 kPa while erected | none (Sec 6.10.9.2 asks for bracing) | SAEngine practice |
| L1B18 | erection.overturningSafety | 1.5 | none | SAEngine practice |
| L1B19 | erection.hanging | FS 1.5, sweep L/960, insert tolerance 6 mm | Mast, PCI Journal 1989 and 1993; PCI sweep tolerance 1/8 in per 10 ft | Check |

## Floor response spectra (`floorSpectra`; alpha 9 L5)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| L5-1 | methods | timeHistory, spectrumToSpectrum (time history first when the run has one) | none in the code | SAEngine practice |
| L5-2 | broadening | ±15 % of the period | ASCE 4-16 Sec 6.2 / US NRC RG 1.122 practice | Check |
| L5-3 | damping | 2, 3, 5, 7 % computed; 5 % for the components | none | SAEngine practice |
| L5-4 | periods | 0.02-4 s, 120 on a log scale | none | SAEngine practice |
| L5-5 | direct.duration / iterations | 20 s strong motion (Davenport peak factor), 8 iterations of the density | none | SAEngine practice |
| L5-6 | components | F = Sa(Tc) Wc Ic / Rc within the nonstructural table's least and largest force; rigid (αc ≤ 1) at 0.06 s, flexible at the peak | the form of ASCE 7-16 Eq 13.3-4 / EN 1998-1 Eq 4.24 with the floor spectrum | SAEngine practice (off unless the project turns it on) |
