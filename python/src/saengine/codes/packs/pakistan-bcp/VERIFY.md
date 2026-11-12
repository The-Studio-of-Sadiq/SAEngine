# pakistan-bcp: values to verify against the printed BCP

No copy of the Building Code of Pakistan, Seismic Provisions 2007 (or of its 2021 revision) was
available when this pack was written (alpha 9, track C16, 2026-11-04). Every value was entered from
knowledge of the code, which follows the UBC 1997 Chapter 16 form, and is to be checked by the
owner against the printed edition. The table, section and equation numbers of BCP SP-2007 given
here are believed right but uncertain: where they differ, fix the reference (the values follow
UBC 1997, whose table is named beside). **Sure**, **Check**, **Uncertain** and **SAEngine
practice** as in the other packs' lists. Everything the pack does not set is the base pack's
(`aci318-asce7-22`, its VERIFY.md).

The pack follows SP-2007. If the 2021 revision changed the form (mapped spectral values in the
ASCE 7 form), a new pack should extend this one and set `seismic.designSpectrum.method`
`mappedSpectral` with its maps; nothing in the engine needs to change.

## BCP SP-2007 (seismic)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| P1 | locations.*.zone | Islamabad 2B, Rawalpindi 2B, Lahore 2A, Karachi 2B, Hyderabad 2A, Faisalabad 2A, Multan 2A, Peshawar 2B, Quetta 3, Muzaffarabad 3, Gilgit 3, Gwadar 3 | Seismic zoning map and list of towns | Seismic zone of each town | Uncertain (from memory: check every town on the map; Quetta and Muzaffarabad may be zone 4) |
| P2 | locations.*.windSpeed | 45 m/s (Karachi and Gwadar 50, Hyderabad 47) | - | Basic wind speed V (3-second gust, ASCE 7 form) | SAEngine practice (BCP SP-2007 covers the seismic provisions only; replace with the project's value) |
| P3 | zoneCoefficients.zones | 1: 0.075, 2A: 0.15, 2B: 0.20, 3: 0.30, 4: 0.40 (ids 1-5) | Table 5.10 (UBC Table 16-I) | Zone factor Z | Sure (the values); Check (the table number) |
| P4 | seismic.designSpectrum.ubc97.ca | SA 0.06, 0.12, 0.16, 0.24, 0.32 Na; SB 0.08, 0.15, 0.20, 0.30, 0.40 Na; SC 0.09, 0.18, 0.24, 0.33, 0.40 Na; SD 0.12, 0.22, 0.28, 0.36, 0.44 Na; SE 0.19, 0.30, 0.34, 0.36, 0.36 Na at Z 0.075, 0.15, 0.2, 0.3, 0.4 | Table 5.16 (UBC Table 16-Q) | Seismic coefficient Ca (linear between columns for an entered Z) | Sure (UBC values); Check (the BCP table) |
| P5 | seismic.designSpectrum.ubc97.cv | SA 0.06, 0.12, 0.16, 0.24, 0.32 Nv; SB 0.08, 0.15, 0.20, 0.30, 0.40 Nv; SC 0.13, 0.25, 0.32, 0.45, 0.56 Nv; SD 0.18, 0.32, 0.40, 0.54, 0.64 Nv; SE 0.26, 0.50, 0.64, 0.84, 0.96 Nv | Table 5.17 (UBC Table 16-R) | Seismic coefficient Cv | Sure (UBC values); Check (the BCP table) |
| P6 | seismic.designSpectrum.ubc97.na / nv | Na: A 1.5, 1.2, 1.0 at ≤ 2, 5, ≥ 10 km; B 1.3, 1.0, 1.0; C 1.0. Nv: A 2.0, 1.6, 1.2, 1.0 at ≤ 2, 5, 10, ≥ 15 km; B 1.6, 1.2, 1.0, 1.0; C 1.0 (linear between) | UBC Tables 16-S, 16-T | Near-source factors in zone 4 | Check (that BCP SP-2007 keeps them; the cap Na ≤ 1.1 for regular structures on SA-SD is not applied, on the safe side) |
| P7 | seismic.designSpectrum.ubc97.nearSourceFactor, csLimits.sdsFactor | 0.8; 0.044 (× 2.5 Ca = 0.11 Ca) | Sec 5.30.2 (UBC Eqs 30-6, 30-7) | V ≥ 0.11 Ca I W; V ≥ 0.8 Z Nv I W / R in zone 4 | Sure (UBC); Check (the BCP equations) |
| P8 | seismic.designSpectrum t0Share, rampStart | 0.2, 0.4 | UBC Figure 16-3 | T0 = 0.2 Ts, Sa(0) = Ca = 0.4 × 2.5 Ca | Sure |
| P9 | seismic.designSpectrum.ubc97.periodUpper | 1.4 Ta, 1.3 Ta in zone 4 | UBC Sec 1630.2.2 | Period from the structure's properties at most this | Check |
| P10 | seismic.periodCoefficients | Ct 0.0853 steel moment frames, 0.0731 concrete moment frames and EBF, 0.0488 others; x 3/4 (hn in m) | UBC Sec 1630.2.2 Eq 30-8 | Approximate period T = Ct hn^(3/4) | Sure |
| P11 | seismic.siteClasses | SA > 1500, SB 760-1500, SC 360-760, SD 180-360, SE < 180 m/s, SF | UBC Table 16-J | Soil profile types | Sure (UBC); Check (BCP) |
| P12 | seismic.defaultSiteClass | SD | UBC Sec 1629.3.1 | SD where the soil is not known | Sure |
| P13 | seismic.systems (rcSmf, rcImf, rcOmf, walls, duals, steel frames) | R 8.5, 5.5, 3.5; bearing walls 4.5; building frame walls 5.5; dual with SMRF 8.5, with IMRF 6.5; steel SMRF 8.5, OMRF 4.5, EBF 7.0, SCBF 6.4, OCBF 5.6; Ω0 2.8 (braced frames 2.2) | Table 5.18 (UBC Table 16-N) | Response modification factor and overstrength | Check |
| P14 | seismic.systems.*.Cd | 0.7 R | UBC Sec 1630.9.2 (ΔM = 0.7 R ΔS) | Deflection amplification | SAEngine practice (the storey drift Cd δe / I of the base pack: with I > 1 the drift is divided by I, which UBC does not do) |
| P15 | seismic.systems.*.heightLimits.D | bearing walls 48.8 m (160 ft), building frame walls, EBF and SCBF 73.2 m (240 ft), steel OMRF and OCBF 48.8 m; concrete IMRF and OMRF not permitted | UBC Table 16-N (zones 3 and 4) | Height limits | Check |
| P16 | seismic.designCategories | zone 1: B, 2A and 2B: C, 3 and 4: D (both occupancy groups) | - | The category whose detailing the zone asks | SAEngine practice (UBC-form codes have no SDC: ordinary detailing in zone 1, intermediate in zone 2, special in 3 and 4) |
| P17 | seismic.allowableDrift | 0.020 for all | UBC Sec 1630.10.2 | ΔM ≤ 0.020 h (T ≥ 0.7 s) | SAEngine practice (the 0.025 h of T < 0.7 s is not used, on the safe side) |
| P18 | seismic.driftLimits, driftRedundancyCategories | none | - | The ASCE rows do not apply | SAEngine practice |
| P19 | occupancyCategories IV, III | I = 1.25 (essential), 1.25 (hazardous; special occupancies take 1.0 in the code) | Table 5.11 (UBC Table 16-K) | Seismic importance | Check (category III takes 1.25: SAEngine practice for a school or assembly, override 1.0 per project) |
| P20 | seismic (redundancy ρ, vertical Ev = 0.5 Ca I D, accidental torsion 5 %) | the base pack's (ρ of ASCE 7-22, Ev = 0.5 × 0.4 × 2.5 Ca D = 0.5 Ca D, 5 %) | UBC Sec 1630.1.1, 1630.6 | Other seismic numbers | Uncertain (the UBC ρ = 2 - 20/(rmax √A) is not built in; Ev omits I) |

## Loads, concrete and steel

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| P21 | combinations, areaLoads, wind | the base pack's ASCE 7-22 values | - | BCP SP-2007 gives no loads but seismic | Check (the strength combinations 1.2D + 1.0E + f1 L, 0.9D ± 1.0E of UBC Sec 1612.2.1 match the base pack's for the cases SAEngine builds) |
| P22 | concrete | the base pack's ACI 318-19, US bar sizes (#3-#11) | ACI 318 | Concrete design | Check (Pakistani practice designs to ACI 318; the bars rolled to ASTM A615) |
| P23 | barSchedule.standards.aci315 | lengths rounded to 25 mm, stock 12 m | - | ACI 315 with metric practice | SAEngine practice |
