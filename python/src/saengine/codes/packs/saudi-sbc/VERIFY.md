# saudi-sbc: values to verify against the printed SBC

No copy of SBC 301, SBC 304 or SBC 306 was available when this pack was written (alpha 9, track
C16, 2026-11-04). Every value was entered from knowledge of the codes (SBC 301-2018 follows the
ASCE 7-16 form and numbering, SBC 304-2018 ACI 318-14, SBC 306 AISC 360) and is to be checked by
the owner against the printed edition. **Sure**: well-known value, low risk. **Check**: believed
right, confirm the number or the clause. **Uncertain**: the value may be wrong; replace it from the
code before design. **SAEngine practice**: a choice of SAEngine where the code gives no number.
Everything the pack does not set is the base pack's (`aci318-asce7-22`, its VERIFY.md).

## SBC 301-2018 (loads)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| S1 | locations.*.ss / s1 | Riyadh 0.06 / 0.02, Jeddah 0.24 / 0.07, Makkah 0.20 / 0.06, Madinah 0.18 / 0.06, Taif 0.18 / 0.06, Dammam 0.12 / 0.04, Yanbu 0.20 / 0.07, Tabuk 0.34 / 0.11, Haql 1.00 / 0.33, Jazan 0.38 / 0.12, Abha 0.18 / 0.06, Najran 0.15 / 0.05, Hail 0.10 / 0.04, Buraydah 0.07 / 0.03 g | Sec 11.4.2 (the cities' table of SS, S1) | Mapped MCER SS and S1 of each city | Uncertain (from memory of the older SBC 301 city table: replace every pair with SBC 301-2018's) |
| S2 | locations.*.windSpeed | Riyadh 46, Jeddah 47, Makkah 46, Madinah 46, Taif 45, Dammam 49, Yanbu 47, Tabuk 44, Haql 45, Jazan 47, Abha 44, Najran 44, Hail 45, Buraydah 46 m/s | Sec 26.5.1, Figure 26.5-1B | Basic wind speed V (3-second gust, risk category II) | Uncertain (SAEngine estimates: read V of risk category II from the SBC map; III-IV and I have their own maps, enter V for those) |
| S3 | locations.*.tl | not given | Sec 11.4.6 (TL map) | Long-period transition period | Uncertain (no TL entered: the spectrum stays SD1/T beyond TL, on the safe side; enter TL in Site > Mapped spectral values) |
| S4 | seismic.designSpectrum.siteCoefficients.fa | A 0.8; B 0.9; C 1.3, 1.3, 1.2, 1.2, 1.2, 1.2; D 1.6, 1.4, 1.2, 1.1, 1.0, 1.0; E 2.4, 1.7, 1.3, 1.1, 0.9, 0.8 at SS ≤ 0.25, 0.5, 0.75, 1.0, 1.25, ≥ 1.5 | Table 11.4-1 | Short-period site coefficient Fa (linear between columns) | Check (ASCE 7-16 values; ASCE 7-16 gives "see 11.4.8" for E at SS ≥ 1.0: the E row's last three values are SAEngine's from the SNI table, check) |
| S5 | seismic.designSpectrum.siteCoefficients.fv | A 0.8; B 0.8; C 1.5, 1.5, 1.5, 1.5, 1.5, 1.4; D 2.4, 2.2, 2.0, 1.9, 1.8, 1.7; E 4.2, 3.3, 2.8, 2.4, 2.2, 2.0 at S1 ≤ 0.1, 0.2, 0.3, 0.4, 0.5, ≥ 0.6 | Table 11.4-2 | Long-period site coefficient Fv | Check (the 11.4.8 site-specific requirements for D with S1 ≥ 0.2 and E with S1 ≥ 0.2 are not checked; the exceptions are assumed to hold) |
| S6 | seismic.siteClasses | A > 1500, B 760-1500, C 360-760, D 180-360, E < 180 m/s, F | Table 20.3-1 | Site classes by vs30 | Check (the SI numbers of the SBC table) |
| S7 | seismic.defaultSiteClass | SD | Sec 11.4.3 | Site class D where the soil properties are not known | Check |
| S8 | seismic.designSpectrum.multiPeriod | none | - | ASCE 7-16 has no multi-period spectrum | Sure |
| S9 | seismic (everything else) | the base pack's ASCE 7-22 values (SDS = 2/3 SMS, the two-period spectrum, SDC bands 0.167, 0.33, 0.50 and 0.067, 0.133, 0.20, Cs bounds 0.044 SDS Ie ≥ 0.01 and 0.5 S1/(R/Ie), Cu table, R, Ω0, Cd of Table 12.2-1, Ct and x, drift limits, irregularities) | Sec 11.4.4-11.6, 12.2-12.12 | The same numbers in ASCE 7-16 and 7-22 | Check (they are cited as ASCE 7-22 in the report) |
| S10 | wind.kzFactor, wind.exposures.*.alpha / zg | 2.01; B 7.0 / 365.76 m, C 9.5 / 274.32 m, D 11.5 / 213.36 m | Table 26.10-1 note, Table 26.11-1 | Velocity pressure exposure constants (ASCE 7-16 values) | Check |
| S11 | combinations, areaLoads, liveReduction, snow | the base pack's ASCE 7-22 values | Ch 2, 4, 7 | Load combinations, live loads | Uncertain (believed the same as SBC 301-2018 for the cases SAEngine builds; check the live loads of Table 4.3-1) |

## SBC 304-2018 (concrete) and SBC 306 (steel)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| S12 | concrete.barDiameters | 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 32 mm (by use: see the data file) | SBC 304 Sec 20.2 | Bar sizes designed | SAEngine practice (the sizes rolled in the Kingdom) |
| S13 | concrete.barNames | none (sizes print as Ø16) | - | Bar names | SAEngine practice |
| S14 | barSchedule.standard | bs8666 | - | Bar schedule standard | SAEngine practice (the Gulf's common practice; ACI 315 is selectable per project) |
| S15 | citations.clauses | the base pack's ACI 318 numbers, named SBC 304-2018 | SBC 304-2018 (ACI 318-14 numbering) | Concrete clause references of the report, worksheets and drawings | Check (SBC 304-2018 is believed to keep the ACI 318-14 numbering; the rules applied are ACI 318-19's) |
| S16 | concrete rules | the base pack's ACI 318-19 rules | SBC 304-2018 | One-way shear with the size effect, development lengths with ψg, the 2019 hooked bars and effective inertia are ACI 318-19's, not ACI 318-14's | Uncertain (SBC 304-2018 follows ACI 318-14 with Saudi modifications, mainly durability: exposure classes, cover and the concrete limits for sulfate and chloride exposure; none is set here) |
| S17 | steel | the base pack's AISC 360-22 | SBC 306 | Steel design | Check (SBC 306 follows AISC 360-10/16; the AISC 360-22 changes apply) |
