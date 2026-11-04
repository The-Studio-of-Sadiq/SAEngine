# philippines-nscp: values to verify against the printed NSCP 2015

No copy of the NSCP 2015 (Volume 1) was available when this pack was written (alpha 9, track
C16, 2026-11-04). Every value was entered from knowledge of the code (Section 208 follows the UBC
1997 form, Section 207 ASCE 7-10, Chapter 4 ACI 318-14 numbered 4xx) and is to be checked by the
owner against the printed edition. The table and section numbers of NSCP 2015 given here are
believed right but uncertain: where they differ, fix the reference. **Sure**, **Check**,
**Uncertain** and **SAEngine practice** as in the other packs' lists. Everything the pack does not
set is the base pack's (`aci318-asce7-22`, its VERIFY.md).

## Section 208 (earthquake loads)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N1 | zoneCoefficients.zones; locations.*.zone | zone 2: Z 0.20 (Palawan except Busuanga, Sulu, Tawi-Tawi); zone 4: Z 0.40 (the rest) | Sec 208.4.4.1, Table 208-3 | Seismic zone and zone factor | Sure (values); Check (the table number) |
| N3 | seismic.designSpectrum.ubc97.ca | zone 2 / zone 4: SA 0.16 / 0.32 Na, SB 0.20 / 0.40 Na, SC 0.24 / 0.40 Na, SD 0.28 / 0.44 Na, SE 0.34 / 0.36 Na | Table 208-7 | Seismic coefficient Ca | Sure (values); Check (the table number) |
| N4 | seismic.designSpectrum.ubc97.cv | zone 2 / zone 4: SA 0.16 / 0.32 Nv, SB 0.20 / 0.40 Nv, SC 0.32 / 0.56 Nv, SD 0.40 / 0.64 Nv, SE 0.64 / 0.96 Nv | Table 208-8 | Seismic coefficient Cv | Sure (values); Check (the table number) |
| N5 | seismic.designSpectrum.ubc97.na / nv | Na: A 1.5, 1.2, 1.0 at ≤ 2, 5, ≥ 10 km; B 1.3, 1.0, 1.0; C 1.0. Nv: A 2.0, 1.6, 1.2, 1.0 at ≤ 2, 5, 10, ≥ 15 km; B 1.6, 1.2, 1.0, 1.0; C 1.0 (linear between) | Tables 208-4 to 208-6 | Seismic source types and near-source factors (zone 4) | Check (the cap Na ≤ 1.1 for regular structures on SA-SD is not applied, on the safe side) |
| N6 | seismic.designSpectrum.ubc97.nearSourceFactor, csLimits.sdsFactor | 0.8; 0.044 (× 2.5 Ca = 0.11 Ca) | Sec 208.5.2.1, Eqs 208-8 to 208-11 | V = Cv I W/(R T) ≤ 2.5 Ca I W/R, ≥ 0.11 Ca I W, ≥ 0.8 Z Nv I W/R in zone 4 | Sure (form); Check (the equation numbers) |
| N7 | seismic.designSpectrum t0Share, rampStart | 0.2, 0.4 | Sec 208.5.1, Figure 208-3 | Design response spectrum | Sure |
| N8 | seismic.designSpectrum.ubc97.periodUpper | 1.3 Ta in zone 4 (1.4 Ta in zone 2) | Sec 208.5.2.2 | Period from the structure's properties at most this | Check |
| N9 | seismic.periodCoefficients | Ct 0.0853, 0.0731, 0.0488; x 3/4 (hn in m) | Sec 208.5.2.2, Eq 208-12 | T = Ct hn^(3/4) | Sure |
| N10 | seismic.siteClasses | SA > 1500, SB 760-1500, SC 360-760, SD 180-360, SE < 180 m/s, SF | Table 208-2 | Soil profile types | Sure |
| N11 | seismic.systems | concrete SMRF 8.5, IMRF 5.5, OMRF 3.5; bearing walls 4.5; building frame walls 5.5; dual with SMRF 8.5, with IMRF 6.5; steel SMRF 8.5, OMRF 4.5, EBF 7.0, SCBF 6.4, OCBF 5.6; Ω0 2.8 (braced 2.2); heights as pakistan-bcp P15 | Tables 208-11A, 208-11B | R, Ω0, height limits | Uncertain (UBC 1997 values; NSCP 2015 is believed to have revised the steel rows after AISC 341: check every row) |
| N12 | seismic.systems.*.Cd | 0.7 R | Sec 208.6.5 (ΔM = 0.7 R ΔS) | Deflection amplification | SAEngine practice (as pakistan-bcp P14) |
| N13 | seismic.designCategories | zone 2: C, zone 4: D | - | The category whose detailing the zone asks | SAEngine practice |
| N14 | seismic.allowableDrift | 0.020 for all | Sec 208.6.5 | ΔM ≤ 0.020 h (T ≥ 0.7 s) | SAEngine practice (the 0.025 h of T < 0.7 s not used) |
| N15 | occupancyCategories | IV: 1.5 (NSCP I essential), III: 1.25 (NSCP II hazardous; III special occupancy takes 1.0 in the code), II: 1.0 (NSCP IV standard), I: 1.0 (NSCP V miscellaneous) | Table 103-1, Table 208-1 | Seismic importance (SAEngine's I-IV ids hold the NSCP categories) | Check |
| N16 | seismic (ρ, Ev, accidental torsion) | the base pack's | Sec 208.5.1.1 | Other seismic numbers | Uncertain (as pakistan-bcp P20) |

## Section 207 (wind) and the other loads

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N2 | locations.*.windSpeed | Metro Manila 250, Batanes 290, Cagayan 290, Isabela 290, Benguet 270, Pampanga 250, Batangas 250, Albay 290, Iloilo 200, Cebu 200, Leyte 290, Davao del Sur 150, Zamboanga del Sur 150, Palawan 200, Sulu 150, Tawi-Tawi 150 km/h (÷ 3.6 m/s) | Table 207A.5-1 | Basic wind speed V (3-second gust) of the province | Uncertain (from memory: check every province; the speed of the occupancy category in force) |
| N17 | wind.kzFactor, wind.exposures | 2.01; B 7.0 / 365.76 m, C 9.5 / 274.32 m, D 11.5 / 213.36 m | Sec 207A.10, Table 207A.3-1 | ASCE 7-10 velocity pressure constants | Check |
| N18 | combinations, areaLoads | the base pack's ASCE 7-22 values | Sec 203.3, Table 205-1 | Combinations and live loads | Check (NSCP 2015 Sec 203.3.1 combinations 1.2D + 1.0E + f1 L, 0.9D + 1.0E and 1.0W are believed to give the same cases; the live loads of Table 205-1 differ in places: check) |

## Chapter 4 (concrete) and Chapter 5 (steel)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| N19 | citations.clauses | the base pack's ACI 318 numbers with chapter NN as section 4NN (25.4.2 → 425.4.2, Chapter 18 → Section 418) | NSCP 2015 Chapter 4 | Concrete clause references | Check (mechanical: NSCP 2015 is ACI 318-14 numbered 4xx; the rules applied are ACI 318-19's) |
| N20 | concrete rules | the base pack's ACI 318-19 rules | NSCP 2015 Chapter 4 | Shear size effect, ψg, 2019 hooked bars and effective inertia are ACI 318-19's | Uncertain (not covered: the ACI 318-14 forms) |
| N21 | concrete.barDiameters | 10, 12, 16, 20, 25, 28, 32, 36 mm (by use: see the data file) | PNS 49 | Bar sizes designed | SAEngine practice |
| N22 | barSchedule.standards.aci315 | lengths rounded to 25 mm, stock 12 m, sizes Ø16 | - | ACI 315 with metric practice | SAEngine practice |
| N23 | steel | the base pack's AISC 360-22 | NSCP 2015 Chapter 5 | Steel design | Check (NSCP 2015 follows AISC 360-10) |
