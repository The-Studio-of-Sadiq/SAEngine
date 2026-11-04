# turkey-tbdy: values to verify against the printed codes

No copy of TBDY 2018, TS 500:2000, TS 498 or TS 708 was available when this pack was written
(alpha 9, track C21, 2026-11-05). Every value was entered from knowledge of the codes and is to
be checked by the owner against the printed editions. **Sure**: well-known value, low risk.
**Check**: believed right, confirm the number or the clause. **Uncertain**: the value or its
reading may be wrong, or it is an SAEngine form of the rule. **SAEngine practice**: no code
value; SAEngine's choice. Everything the pack does not set is the base pack's
(`aci318-asce7-22`, its VERIFY.md).

## TBDY 2018 hazard and spectrum

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| T1 | locations.*.ss / s1 | Istanbul (Fatih) 0.90 / 0.25, Ankara (Cankaya) 0.38 / 0.11, Izmir (Konak) 1.15 / 0.31, Bursa 1.05 / 0.30, Antalya 0.55 / 0.15, Adana 0.60 / 0.17, Konya 0.25 / 0.09, Erzincan 1.90 / 0.55, Duzce 1.60 / 0.45, Antakya 1.35 / 0.37 g | 2.2, AFAD TDTH map (DD-2) | Example SS, S1 near the city centres | Uncertain (SAEngine readings from memory; the map gives values by coordinates and they vary within a city: always enter the site's values) |
| T2 | locations.*.windSpeed | 40 m/s | TS 498 | The base pack's ASCE 7 wind speed | SAEngine practice (placeholder: TS 498 gives q by height, 0.5 / 0.8 / 1.1 / 1.3 kN/m² for 0-8 / 9-20 / 21-100 / > 100 m; not covered) |
| T3 | locations.*.tl | 6 s | 2.3.4 | TL | Sure |
| T4 | seismic.designSpectrum.siteCoefficients.fa | ZA 0.8; ZB 0.9; ZC 1.3, 1.3, 1.2, 1.2, 1.2, 1.2; ZD 1.6, 1.4, 1.2, 1.1, 1.0, 1.0; ZE 2.4, 1.7, 1.3, 1.1, 0.9, 0.8 at SS 0.25 ... 1.50 | Tablo 2.1 | FS (linear between) | Sure (also in the bundled OpenSees Studio `tbdy_site`) |
| T5 | seismic.designSpectrum.siteCoefficients.fv | ZA 0.8; ZB 0.8; ZC 1.5 ... 1.4; ZD 2.4, 2.2, 2.0, 1.9, 1.8, 1.7; ZE 4.2, 3.3, 2.8, 2.4, 2.2, 2.0 at S1 0.1 ... 0.6 | Tablo 2.2 | F1 | Sure |
| T6 | seismic.designSpectrum.designShare | 1.0 | 2.3.3, Denk. 2.1 | SDS = SS FS, SD1 = S1 F1 (no 2/3) | Sure |
| T7 | seismic.designSpectrum.t0Share / rampStart | 0.2 / 0.4 | 2.3.4, Denk. 2.2 | TA = 0.2 TB; Sae = (0.4 + 0.6 T/TA) SDS below TA | Sure |
| T8 | seismic.siteClasses.*.vs30 | ZA > 1500, ZB 760-1500, ZC 360-760, ZD 180-360, ZE < 180 m/s, ZF site study | 16.4, Tablo 16.1 | Local site classes | Check |
| T9 | seismic.siteSpecificStudy | ZF, assumed ZE meanwhile | 16.4 | ZF needs a site response analysis | Check (ZE meanwhile is SAEngine practice) |
| T10 | seismic.defaultSiteClass | ZC | - | New projects | SAEngine practice |
| T11 | seismic.dampingCorrection | η = √(10/(5 + ξ)) ≥ 0.55 | 2.3.5 | Damping other than 5 % | Uncertain |
| T12 | seismic.pgaFactor / verticalFactor | 0.4 / 1.6667 | 2.3.4; 4.4.3 | PGA = 0.4 SDS; vertical effect (2/3) SDS G | Check |

## TBDY 2018 categories, systems and analysis

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| T13 | occupancyCategories | BKS 3 I 1.0 (slots I, II), BKS 2 I 1.2 (III), BKS 1 I 1.5 (IV) | 3.1, Tablo 3.1 | Importance | Sure (the slot mapping is SAEngine practice) |
| T14 | seismic.designSpectrum.sdsBands, designCategories | SDS 0.33, 0.50, 0.75: DTS 4, 3, 2, 1 as B, C, D, D | 3.2, Tablo 3.2 | DTS by SDS (1a-4a for BKS 1) | Check (the B/C/D slots are SAEngine practice; 1a-4a are not told apart) |
| T15 | seismic.requiredDetailing | B, C intermediate; D special | 4.3.2-4.3.3 | Limited ductility permitted in DTS 3, 4 | Check |
| T16 | seismic.systems (R / D) | RC frames HD 8 / 3, RC coupled walls HD 8 / 2.5, RC uncoupled walls HD 6 / 2.5, RC frame + walls HD 7 / 2.5, RC frames LD 4 / 2.5, RC walls LD 4 / 2.5, steel frames HD 8 / 3, steel frames LD 4 / 2, steel CBF HD 5 / 2, steel CBF LD 3 / 2, steel EBF HD 6 / 2.5, unreinforced masonry 2.5 / 1.5 | Tablo 4.1 | R and the overstrength D (Omega0 holds D, Cd = R) | Uncertain (row ids and several values from memory: check each row, the EBF and masonry rows above all) |
| T17 | seismic.systems.*.heightLimits | LD systems: not in DTS 1, 2 (D 0); HN ≤ 28 m in DTS 3, 4 | Tablo 4.1 | Permitted BYS ≥ 6 read as heights | Uncertain (SAEngine reading of the permitted BYS columns) |
| T18 | seismic.designSpectrum.shortPeriodReduction | Ra = D + (R/I - D) T/TB below TB, R/I above | 4.3.4.1, Denk. 4.1 | Reduction | Sure (the clause number Check) |
| T19 | seismic.designSpectrum.csLimits.sdsFactor | 0.04 (Vt ≥ 0.04 m I SDS g) | 4.7.1.1 | Least base shear | Sure |
| T20 | seismic.lateralForce | Fi ∝ mi Hi; ΔFN = 0.0075 N Vt at the top | 4.7.2.1-4.7.2.2 | ELF distribution | Check |
| T21 | seismic.periodCoefficients | Ct 0.1 RC frames, 0.08 steel frames, 0.07 EBF, 0.05 others; m = 0.75 | 4.7.3.3, Denk. 4.31 | TpA = Ct HN^(3/4) | Check (the walls' Ct = 0.075/√At form is not built) |
| T22 | seismic.periodUpperFactor | 1.4 | 4.7.3.2 | Tp ≤ 1.4 TpA | Check |
| T23 | seismic.minimumScale | 0.80 | 4.8.4 | γE of the modal base shear | Check (0.90 for some irregular cases not built) |
| T24 | seismic.accidentalEccentricity / orthogonalShare / massParticipation | 0.05 / 0.30 / 0.95 | 4.5.3, 4.4.2, 4.8.3 | | Check |
| T25 | seismic.torsionIrregular / torsionExtreme / torsionAmplificationMax | 1.2 / 2.0 / 2.0 | Tablo 3.6 A1; 4.7.2.4 | ηbi > 1.2; ηbi ≤ 2.0; Dbi = (ηbi/1.2)² ≤ 2 | Check |
| T26 | seismic.liveShare | 0.3 | 4.5.9, Tablo 4.3 | n of residences and offices | Check (0.6 / 0.8 for other uses: Code Value) |
| T27 | seismic.allowableDrift, driftLimits | 0.008 κ (fixed infill), 0.016 κ (separated); κ 1 concrete, 0.5 steel | 4.9.1.3, Denk. 4.34 | λ δ/h limit | Check |
| T28 | seismic.driftServiceRatio.value | λ = 1.0 | 4.9.1.3 | λ = Sae(DD-3)/Sae(DD-2) | SAEngine practice (on the safe side; enter the site's ratio, usually about 0.4-0.5) |
| T29 | seismic.irregularities | A3 0.20, A2 1/3, B1 0.8, B2 as stiffness < 0.5 × the storey above | Tablo 3.6 | Irregularity thresholds | Uncertain (B2 is an SAEngine form of ηki > 2.0) |
| T30 | seismic.performanceBased.heightClasses | BYS 1 above 70 / 91 / 105 m (DTS 1-2 / 3 / 4); BYS 2 56 / 70 / 91; 3 42 / 56 / 56; 4 28 / 42 / 42; 5 17.5 / 28 / 28; 6 10.5 / 17.5 / 17.5; 7 7 / 10.5 / 10.5; 8 the rest | 3.3, Tablo 3.3 | Building height classes | Check (BYS 1 limits believed right; the lower rows of the DTS 4 column Uncertain) |
| T31 | seismic.performanceBased.rules | BYS 1: DD-4 continuous use (elastic), DD-2 controlled damage (strength design), DD-1 collapse prevention (nonlinear time history) | 3.4, Tablo 3.4b, Bolum 13 | Tall building objectives | Check (the BKS 1 evaluation of Tablo 3.4a in DTS 1a, 2a is not built) |
| T32 | seismic.timeHistory | 11 records; 0.2-1.5 T; single 1.0, SRSS pairs 1.3; nonlinear target × 1.5 | 2.5.1-2.5.2; Bolum 13 | Record suites | Check (the × 1.5 DD-1 factor is SAEngine practice) |
| T33 | pushover.targetDisplacement.hazards | DD-2 LS (× 1.0), DD-1 CP (× 1.5) | 3.4 | Performance levels on the ASCE 41 hinges | SAEngine practice (TBDY Bolum 5 strain limits not built) |
| T34 | pushover...siteFactors | ZA, ZB 130; ZC 90; ZD, ZE, ZF 60 | ASCE 41-17 Table 7-3 | a of C1 | SAEngine practice |

## Loads

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| T35 | combinations.strength | 1.4G + 1.6Q; 1.0G + 1.3Q + 1.3W; 0.9G + 1.3W; G + Q + 0.2S + E; 0.9G + E | TS 500 6.2.6; TBDY 4.4.4 | Strength combinations | Check |
| T36 | combinations.temperature | 1.0G + 1.2Q ± 1.2T | TS 500 6.2.6 | With temperature | Uncertain |
| T37 | combinations.service, allowable | G + Q, G + 0.3Q, G + Q + W; the ASCE 7-22 Sec 2.4 allowable rows | - | Service and allowable stress | SAEngine practice |

## TS 500:2000 concrete and TBDY Bolum 7

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| T38 | concreteMethods.ultimate.gammaC / gammaS | 1.5 / 1.15 | 6.2.5 | γmc, γms | Sure |
| T39 | concreteMethods.ultimate.alphaCC, eta | 0.85, 1.0 | 7.1 | 0.85 fcd block | Sure |
| T40 | concreteMethods.ultimate.relations.lambda.steps | k1 0.85 (≤ C25), 0.82, 0.79, 0.76, 0.73, 0.70 (C50) | 7.1 | Block depth factor | Sure |
| T41 | concreteMethods.ultimate.relations.epsCu3 | 3.0 ‰ | 7.1 | εcu | Sure |
| T42 | concreteMethods.ultimate.relations (fctm, Ec) | fctk = 0.35 √fck; Ec = 3250 √fck + 14000 | 3.3 | Tensile strength, modulus | Check |
| T43 | concreteMethods.ultimate.eccentricity | max(h/20, 25 mm) | 6.3.10 (15 mm + 0.03 h) | Least eccentricity | SAEngine practice (form of the TS 500 rule) |
| T44 | concreteMethods.ultimate.neutralAxisLimit | x/d ≤ 0.528 | 7.3 (ρ - ρ' ≤ 0.85 ρb) | Ductility limit | SAEngine practice (form, S420) |
| T45 | concreteMethods.shear.tauC | 0.52 × 0.35 √fck / 1.5 by grade C16-C50 | 8.1.3-8.1.4 | Vc = 0.8 Vcr | Check |
| T46 | concreteMethods.shear.maxStress | 0.22 fck / 1.5 | 8.1.5 | Vr ≤ 0.22 fcd bw d | Check |
| T47 | concreteMethods.shear.minStirrupStress | 0.44 MPa (0.3 fctd at C40) | 8.1.5 | ρw ≥ 0.3 fctd/fywd | Check (taken at C40) |
| T48 | concreteMethods.shear.axialFactor | 1.75 (0.07 × 25) | 8.1.3 | 1 + γ Nd/Ac, γ 0.07 | Uncertain (form) |
| T49 | concreteMethods.shear.spacing | d/2 | 8.1.5 | Stirrup spacing | Check |
| T50 | concreteMethods.punching | at d/2, 0.2333 √fck (fctd), γ = 1, × 1.5 with reinforcement | 8.3.1 | Punching | Uncertain (γ of the eccentricity not applied; the reinforced cap) |
| T51 | concreteMethods.memberLimits | beams ρmin 0.2147 √fck / fyk (at C40), ρ ≤ 0.02; slabs 0.002 / 0.003, ≤ 1.5 h, 200 mm; columns 0.01-0.04, 4Ø14 / 6 bars, ties ≥ Ø8 and 1/3 Ø, ≤ 12 Ø, 200 mm | 7.3, 7.4, 11.2; TBDY 7.3.4, 7.4.2 | Minimum and maximum steel | Check (the side bar and distribution rules Uncertain) |
| T52 | concreteMethods.seismic.beams | bw ≥ 250, h ≤ 3.5 bw, h ≤ ln/4, 2Ø12, ρ ≤ 0.02, bottom ≥ 0.5 top, 1/4 throughout; 2h zone, s ≤ min(h/4, 8 Ø, 150), first 50 mm, d/2 elsewhere; Ve from 1.4 Mr | TBDY 7.4 | Beams | Check |
| T53 | concreteMethods.seismic.columns | b ≥ 300, Nd > 0.1 Ac fck, ρ 0.01-0.04, strong column 1.2, confined length max(1.5 × larger side, ln/6, 500), s ≤ min(b/3, 6 Ø, 150), Ash 0.30 / 0.075, spirals 0.45 / 0.12, b/2 outside | TBDY 7.3 | Columns | Check (crossties 250 mm, laps 100 mm and the aspect ratio 1/6 Uncertain) |
| T54 | concreteMethods.seismic.joints | Ve ≤ 1.7 √fck bj h (confined), 1.0 (others); 1.25 fyk | TBDY 7.5 | Joints | Check (bj form Uncertain) |
| T55 | concreteMethods.seismic.walls | bw ≥ 200, ρ ≥ 0.0025, ≤ t/10, 250 mm; boundary and coupling thresholds | TBDY 7.6 | Walls | Uncertain (the boundary and coupling forms are the IS type's) |
| T56 | concrete.barDiameters / barNames | Ø8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 32 | TS 708:2016 | Bars | Check |
| T57 | concrete.modulus.normal | 5800 √fck for the analysis | TS 500 3.3 | Ec | SAEngine practice (form) |

The steel design is the base pack's AISC 360-22 / AISC 341-22 (the Turkish steel regulation of
2016 follows AISC 360-10): Check that the φ factors and the seismic provisions match.
