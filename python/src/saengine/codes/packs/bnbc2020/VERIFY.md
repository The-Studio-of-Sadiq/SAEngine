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
