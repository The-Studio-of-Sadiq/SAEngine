# canada-nbcc: values to verify against the printed NBCC 2020, CSA A23.3-19 and CSA S16-19

No copy of the codes was available when this pack was written (alpha 9, track C17,
2026-11-04). Every value was entered from knowledge of the codes and is to be checked by the
owner against the printed editions. **Sure**: well-known value, low risk. **Check**: believed
right, confirm the number or the row. **Uncertain**: the value or its reading may be wrong, or
it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack does not set
is the US pack's (`aci318-asce7-22`, its VERIFY.md).

## Towns (Appendix C)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K1 | locations.*.groundSnow | Vancouver 1.8, Calgary 1.1, Edmonton 1.7, Winnipeg 1.9, Toronto 0.9, Ottawa 2.4, Montréal 2.6, Québec 3.6, Halifax 1.9 kPa | Table C-2, Ss | 1-in-50 ground snow | Uncertain (from memory of the 2015 table; Halifax and Edmonton least sure) |
| K2 | locations.*.rainLoad | Vancouver 0.2, Calgary 0.1, Edmonton 0.1, Winnipeg 0.2, Toronto 0.4, Ottawa 0.4, Montréal 0.4, Québec 0.6, Halifax 0.6 kPa | Table C-2, Sr | Associated rain load | Uncertain |
| K3 | locations.*.windSpeed | from q1/50: Vancouver 0.45, Calgary 0.48, Edmonton 0.45, Winnipeg 0.45, Toronto 0.44, Ottawa 0.41, Montréal 0.42, Québec 0.41, Halifax 0.52 kPa; V = √(q / 0.000613) | Table C-2, q1/50 | Reference velocity pressure | Uncertain (q values from memory) |
| K4 | locations.vancouver.spectrum | Sa(0.2, 0.5, 1, 2, 5, 10) = 0.848, 0.751, 0.425, 0.257, 0.080, 0.029 g | Appendix C, site class C | Uniform hazard spectrum | Uncertain (the 2015 edition's values as remembered; the 2020 values differ: replace) |
| K5 | locations.toronto.spectrum | 0.249, 0.126, 0.063, 0.029, 0.0071, 0.0026 g | Appendix C, class C | | Uncertain (2015, remembered; replace) |
| K6 | locations.ottawa.spectrum | 0.439, 0.237, 0.118, 0.056, 0.015, 0.0055 g | Appendix C, class C | | Uncertain (2015, remembered; replace) |
| K7 | locations.montreal.spectrum | 0.595, 0.311, 0.148, 0.068, 0.018, 0.0062 g | Appendix C, class C | | Uncertain (2015, remembered; replace) |
| K8 | locations (others) | no spectrum: the project enters the site's Sa(T) | - | | SAEngine practice |
| K9 | locations.towns | coordinates of the city centres | - | Site map suggestion | Sure |

## Importance and loads

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K10 | occupancyCategories.*.seismicImportance | 0.8, 1.0, 1.3, 1.5 | Table 4.1.8.5 | IE | Sure |
| K11 | occupancyCategories.*.windImportance | 0.8, 1.0, 1.15, 1.25 (ULS) | Table 4.1.7.3 | IW | Sure |
| K12 | snow.importance | 0.8, 1.0, 1.15, 1.25 (ULS) | Table 4.1.6.2-A | IS | Sure |
| K13 | areaLoads.uses | residential 1.9; office 2.4; office first storey, corridors, assembly (other), retail, exits, balconies 4.8; classrooms, assembly fixed seats 2.4; storage 4.8 (at least); garages 2.4; roof 1.0 kPa | Table 4.1.5.3 | Live loads | Check (every row) |
| K14 | areaLoads.partitions.minimum | 1.0 kPa | 4.1.4.1(3) | Partition allowance | Check |
| K15 | areaLoads (others) | the parent's ASCE 7-22 values | - | | Uncertain (not NBCC) |
| K16 | liveReduction | the parent's ASCE 7-22 Sec 4.7 | 4.1.5.8 | | Not covered |

## Combinations (Table 4.1.3.2-A)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K17 | combinations.strength | 1.4D; 1.25D + 1.5L + 1.0S; 1.25D + 1.5L + 0.4W; 1.25D + 1.5S + 1.0L; 1.25D + 1.5S + 0.4W; 1.25D + 1.4W + 0.5L; 1.25D + 1.4W + 0.5S; 0.9D + 1.4W; 1.0D + 1.0E + 0.5L + 0.25S; 1.0D + 1.0E | Table 4.1.3.2-A, 4.1.3.2(5) | ULS | Sure (the cases); Check the 0.9D rows formed |
| K18 | combinations.strength H | 1.5 (1.0 with E) | 4.1.3.2 | Earth pressure | Check |
| K19 | companion L 1.0 for storage | not formed (0.5 everywhere) | Table 4.1.3.2-A note | | Not covered (raise under Code Values) |
| K20 | combinations.service | D + L; D + 0.5L; D + 0.5L + 0.75W | 4.1.3.4-4.1.3.6 | SLS | SAEngine practice (0.5L sustained, 0.75W = IW SLS) |
| K21 | combinations.temperature | 1.25D ± 1.25T + 1.5L | 4.1.3.2(4) | T | Uncertain (T factor 1.25 believed; its companions SAEngine's) |
| K22 | combinations.pDeltaPreload | 1.0D + 0.5L | case 5 | P-delta preload | Check |
| K23 | seismicDeadUpper/Lower | 1.0 / 1.0 | case 5 | | Sure |
| K24 | snow.loadCase | the larger of snow and roof live load in Lr | 4.1.5.3, 4.1.6 | | SAEngine practice |

## Snow (4.1.6.2)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K25 | snow.factor | Cb 0.8 | 4.1.6.2(2) | Basic roof factor | Sure (large roofs take more: not covered) |
| K26 | snow.exposures | Cw 1.0 sheltered, 0.75 exposed, 0.5 exposed north of the tree line | 4.1.6.2(3) | | Check |
| K27 | snow.shape | Cs 1.0 to 30°, 0 at 70° | 4.1.6.2(5) | Non-slippery roofs | Sure (slippery 15°-60° not covered) |
| K28 | snow.rainShare | + Sr × Is | 4.1.6.2(1) | | Sure |
| K29 | snow.seismicShare | 0.25 | 4.1.8.2 (W) | Snow in W | Sure |

## Wind (4.1.7.3, static procedure)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K30 | wind.exposures.open | Ce = (h/10)^0.2 >= 0.9 | 4.1.7.3(5)(a) | Open terrain | Sure |
| K31 | wind.exposures.rough | Ce = 0.7 (h/12)^0.3 >= 0.7 | 4.1.7.3(5)(b) | Rough terrain | Sure |
| K32 | wind.gust | Cg 2.0 | 4.1.7.3(8) | Whole building | Sure |
| K33 | wind.cpByHeight | windward 0.6-0.8, leeward -0.3 to -0.5 by H/D 0.25-1.0 (band tops) | 4.1.7.3, commentary | Wall Cp | Check (and D = the lesser plan dimension: SAEngine reading); leeward Ce at h (NBCC h/2: on the safe side) |
| K34 | wind.directionality, topographic | 1.0, 1.0 (topography not covered) | 4.1.7.4 | | SAEngine practice |
| K35 | wind cladding, internal, roof Cp | the parent's | 4.1.7.6-4.1.7.7 | | Not covered (not NBCC) |

## Seismic (4.1.8)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K36 | seismic.designSpectrum.ordinates.shortPeriods | S(T <= 0.2) = max(Sa(0.2), Sa(0.5)) | 4.1.8.4(7) | Plateau | Check (2020 wording for each site designation) |
| K37 | ordinates (between, beyond) | linear between the periods; held at S(10) beyond 10 s | 4.1.8.4(7) | | Check (held: on the safe side) |
| K38 | ordinates.minimumPeriod | 2.0 s frames, braced, other; 4.0 s walls, coupled walls | 4.1.8.11(2)(a) | V lower bound | Check (2015 form, believed kept in 2020) |
| K39 | ordinates.capShares, capFromRd | max(2/3 S(0.2), S(0.5)) for Rd >= 1.5 | 4.1.8.11(2)(c) | V upper bound | Check |
| K40 | ordinates.higherMode | empty (Mv = 1); J = 1 | 4.1.8.11(5)-(6), Table 4.1.8.11 | Higher mode and overturning | Not entered: enter Table 4.1.8.11 (Mv = 1 is unconservative for walls at long periods) |
| K41 | designSpectrum.sdsBands | 0.2, 0.35, 0.75 (of S(0.2)) | Table 4.1.8.9 | Height-limit ranges | Check |
| K42 | designCategories | B (< 0.35), C (0.35-0.75), D (> 0.75); High and Post-disaster one range up | Table 4.1.8.9 (IE S(0.2)) | SAEngine's letters | SAEngine practice (the IE shift on the safe side) |
| K43 | systems Rd, Ro | steel D MRF 5.0/1.5, MD MRF 3.5/1.5, LD MRF 2.0/1.3, MD CBF 3.0/1.3, LD CBF 2.0/1.3, ductile EBF 4.0/1.5, ductile BRBF 4.0/1.2, ductile plate walls 5.0/1.6, conventional 1.5/1.3; concrete ductile MRF 4.0/1.7, MD MRF 2.5/1.4, ductile coupled walls 4.0/1.7, ductile walls 3.5/1.6, MD walls 2.0/1.4, conventional 1.5/1.3; masonry LD walls 1.5/1.5, unreinforced 1.0/1.0 | Table 4.1.8.9 | | Check (the common rows Sure) |
| K44 | systems heightLimits | LD steel MRF -, 60, 30; MD CBF -, 40, 40; LD CBF -, 60, 40; BRBF -, 40, 40; conventional steel 15; MD concrete MRF and walls -, 60, 40; conventional concrete MRF -, 15, NP; walls -, 30, NP; masonry LD -, 40, 30; unreinforced 15, NP, NP (m, for B / C / D) | Table 4.1.8.9 | | Uncertain (from memory; every row) |
| K45 | systems Cd, Omega0 | Cd = Rd Ro; Ω0 = Ro | 4.1.8.13(2) | | SAEngine practice (Ω0) |
| K46 | rcDualSpecial | the ductile walls' row | - | NBCC has no dual row | SAEngine practice |
| K47 | periodCoefficients | 0.085 hn^0.75 steel MRF, 0.075 hn^0.75 concrete MRF, 0.025 hn braced, 0.05 hn^0.75 walls and other | 4.1.8.11(3) | Ta | Sure |
| K48 | periodUpperFactor | 1.5 | 4.1.8.11(3)(d) | T from analysis <= 1.5 Ta (MRF; 2.0 braced and walls) | Check (1.5 for all: on the safe side) |
| K49 | lateralForce.topForce | Ft = 0.07 Ta V <= 0.25 V, 0 for Ta <= 0.7 s | 4.1.8.11(7) | | Sure |
| K50 | accidentalEccentricity | 0.10 Dn | 4.1.8.11(11) | | Sure |
| K51 | torsionIrregular / Extreme | B > 1.7 | 4.1.8.11(10), Type 7 | Torsional sensitivity | Check (SAEngine's ratio δmax/δave stands for B) |
| K52 | torsionAmplificationMax | 1.0 (none) | - | | Sure (NBCC has no Ax) |
| K53 | allowableDrift | 0.025 Low and Normal, 0.02 High, 0.01 Post-disaster | 4.1.8.13(3) | | Sure |
| K54 | driftAmplification | Rd Ro / IE × elastic | 4.1.8.13(2) | | Sure |
| K55 | minimumScale | 0.8 | 4.1.8.12(8) | Vd >= 0.8 V (1.0 irregular) | Check (0.8 for all: raise for irregular) |
| K56 | irregularities | soft 0.7 / 0.8 (Type 1), mass 1.5 (Type 2), geometry 1.3 (Type 3), weak 0.8 (Type 6) | Table 4.1.8.6 | | Check |
| K57 | liveShare, heavyLiveShare | 0; 0.6 above 4.8 kPa | 4.1.8.2 (W) | Storage at 60 % | SAEngine practice (storage taken as live > 4.8 kPa) |
| K58 | verticalFactor | 0 | - | No Ev | Sure |
| K59 | stability | θ = P dr / (V h), dr = Rd Ro de; ignore below 0.10 | 4.1.8.3(8) | | Uncertain (SAEngine form) |
| K60 | separation | sum of the deflections | 4.1.8.14(2) | | Check |
| K61 | siteClasses | A > 1500, B 760-1500, C 360-760, D 180-360, E < 180 m/s, F | Table 4.1.8.4-A | | Sure |
| K62 | pgaFactor | 0.4 S(0.2) as PGA | - | | SAEngine practice |

## Concrete (CSA A23.3-19)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K63 | concreteMethods.ultimate.gammaC, gammaS | 1/0.65, 1/0.85 | 8.4.2, 8.4.3 | φc, φs | Sure |
| K64 | relations.eta (α1) | 0.85 - 0.0015 f'c at each 5 MPa band top (0.82 at 20 to 0.73 at 80) | 10.1.7 | | Sure (the formula) |
| K65 | relations.lambda (β1) | 0.97 - 0.0025 f'c (0.92 at 20 to 0.77 at 80) | 10.1.7 | | Sure |
| K66 | relations.epsCu3, materials.concreteStrain | 0.0035 | 10.1.3 | | Sure |
| K67 | relations.ecm | 4500 √f'c | 8.6.2.3 | Ec (normal density) | Sure |
| K68 | relations.fctm | 0.6 √f'c | 8.6.4 | fr | Sure |
| K69 | ultimate.axialShares | 0.3952 f'c Ac + 0.68 fy As | 10.10.4 | Pr,max = 0.80 Pro with α1 of 60 MPa | Check (α1 fixed at 0.76: on the safe side to 60 MPa; spirals as ties) |
| K70 | ultimate.eccentricity | none (e0 = 0) | - | | SAEngine practice |
| K71 | ultimate.neutralAxisLimit | c/d <= 0.636 (700/(700 + 400)) | 10.5.2 | | Check (grade 400 taken) |
| K72 | shear.phiC, phiS | 0.65, 0.85 | 8.4 | | Sure |
| K73 | shear.depthShares | dv = max(0.9 d, 0.72 h) | 2.3 (dv) | | Sure |
| K74 | shear.rootMax | √f'c <= 8 MPa | 11.3.4 | | Sure |
| K75 | shear.betaWithStirrups, thetaDeg | 0.18, 35° | 11.3.6.3 | Simplified method | Sure |
| K76 | shear.betaNoStirrups | 230 / (1000 + dv) | 11.3.6.3(b) | | Check |
| K77 | shear.vrMaxShare | 0.25 φc f'c bw dv | 11.3.3 | | Sure |
| K78 | shear.minCoefficient | Av,min = 0.06 √f'c bw s / fy | 11.2.8.2 | | Sure |
| K79 | shear.general | β = 0.40/(1 + 1500 εx) × 1300/(1000 + sze), θ = 29 + 7000 εx, sze = 35 dv/(15 + ag) >= 0.85 dv, 300 mm with Av,min; -0.0002 <= εx <= 0.003 | 11.3.6.4 | General method | Check |
| K80 | shear.spacing, closeSpacing, closeShare | 0.7 dv <= 600; 0.35 dv <= 300 where Vf > 0.125 λ φc f'c bw dv | 11.3.8.1, 11.3.8.3 | | Check |
| K81 | shear.fyMax, simplifiedFyMax | 500, 400 MPa | 11.3.6.3, 11.3.5 | | Uncertain (fyMax 500) |
| K82 | concrete.barDiameters | 11.3, 16.0, 19.5, 25.2, 29.9, 35.7, 43.7, 56.4 mm (10M-55M) | CSA G30.18 | | Sure |
| K83 | concrete.shrinkage | 0.002 | 7.8.1 | | Sure |
| K84 | column and wall shear, torsion, punching, slenderness, detailing (Clause 21) | the parent's ACI 318-19 | - | | Not covered |

## Steel (CSA S16-19)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| K85 | steel.memberMethods.columnCurve, curveExponent | Cr = φ A Fy (1 + λ^2n)^(-1/n), n = 1.34 | 13.3.1 | | Sure (class H hollow sections n = 2.24: override) |
| K86 | steel.memberMethods.lateralTorsional, ltbCurve | Mu = ω2 π/L √(E Iy G J + (π E/L)² Iy Cw); 1.15 φ Mp (1 - 0.28 Mp/Mu) <= φ Mp where Mu > 0.67 Mp, else φ Mu | 13.6(a) | | Sure (formula); the program's Cb for ω2, at most 2.5: SAEngine practice |
| K87 | steel.phi | the parent's (0.90 / 0.75 the same as S16) | 13.1 | | Check (bolts and welds stay AISC's with AISC's equations) |
| K88 | steel.omegaFromPhi | none (no ASD) | - | | Sure |
| K89 | steelSeismic, connections, timber (O86) | the parent's | Clause 27; O86 | | Not covered |

## Column splice hoops (pack follow-up 2026-11-09)

| # | Path | Value | Source | Sure? |
|---|---|---|---|---|
| S1 | detailing.special.columnSplice* (inherited) | the ACI 318-19 pack's: ties over the lap splices of special moment frame columns at the end zones' spacing (least dimension / 4, 6 db, so) | CSA A23.3-19 Clause 21 (ductile columns, lap splices) | Check (the CSA rule not entered) |
