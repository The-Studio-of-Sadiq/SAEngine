# indonesia-sni: values to verify against the printed SNI

No copy of SNI 1726:2019, SNI 1727:2020, SNI 2847:2019 or SNI 1729:2020 was available when this
pack was written (alpha 9, track C16, 2026-11-04). Every value was entered from knowledge of the
standards (SNI 1726:2019 follows ASCE 7-16, SNI 1727:2020 ASCE 7-16, SNI 2847:2019 ACI 318M-14
in the same numbering, SNI 1729:2020 AISC 360-16) and is to be checked by the owner against the
printed edition and the national hazard maps. **Sure**, **Check**, **Uncertain** and **SAEngine
practice** as in the other packs' lists. Everything the pack does not set is the base pack's
(`aci318-asce7-22`, its VERIFY.md).

## SNI 1726:2019 (seismic) and SNI 1727:2020 (loads)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| I1 | locations.*.ss / s1 | Jakarta 0.77 / 0.34, Bandung 1.45 / 0.55, Surabaya 0.73 / 0.30, Semarang 0.87 / 0.34, Yogyakarta 1.12 / 0.47, Denpasar 0.98 / 0.38, Medan 0.65 / 0.37, Padang 1.55 / 0.65, Banda Aceh 1.40 / 0.62, Makassar 0.47 / 0.18, Palu 2.00 / 0.80, Manado 1.30 / 0.55, Jayapura 1.60 / 0.60, Balikpapan 0.13 / 0.10, Pontianak 0.04 / 0.04 g | Pasal 6.1, Gambar 15 and 16 (SS and S1 maps) | Mapped MCER SS and S1 of each city | Uncertain (from memory of the national maps: read each city's values from the maps or the national hazard tool; values vary within a city) |
| I2 | locations.*.tl | 20 s | Pasal 6.4, Gambar 20 (TL map) | Long-period transition period | Uncertain (20 s for every city, the largest of the map, on the safe side; replace with the map's value) |
| I3 | locations.*.windSpeed | 30 m/s | SNI 1727:2020 Pasal 26.5 | Basic wind speed V | SAEngine practice (SNI 1727:2020 gives no national map: replace with the site's value from the meteorological data) |
| I4 | seismic.designSpectrum.siteCoefficients.fa | SA 0.8; SB 0.9; SC 1.3, 1.3, 1.2, 1.2, 1.2, 1.2; SD 1.6, 1.4, 1.2, 1.1, 1.0, 1.0; SE 2.4, 1.7, 1.3, 1.1, 0.9, 0.8 at SS ≤ 0.25 ... ≥ 1.5 | Pasal 6.2, Tabel 6 | Fa (linear between columns) | Check |
| I5 | seismic.designSpectrum.siteCoefficients.fv | SA 0.8; SB 0.8; SC 1.5, 1.5, 1.5, 1.5, 1.5, 1.4; SD 2.4, 2.2, 2.0, 1.9, 1.8, 1.7; SE 4.2, 3.3, 2.8, 2.4, 2.2, 2.0 at S1 ≤ 0.1 ... ≥ 0.6 | Pasal 6.2, Tabel 7 | Fv | Check (the site-specific requirements of the footnotes for SD and SE are not checked) |
| I6 | seismic.siteClasses | SA > 1500, SB 750-1500, SC 350-750, SD 175-350, SE < 175 m/s, SF | Pasal 5.3, Tabel 5 | Site classes by vs30 | Check |
| I7 | seismic.defaultSiteClass | SD | Pasal 6.1.2 | Where the soil is not known | Check |
| I8 | seismic (everything else) | the base pack's ASCE 7-22 values: SDS = 2/3 Fa SS, the two-period spectrum, the SDC table, Cs bounds, Cu, R, Ω0, Cd, Ct, drift limits | Pasal 6.3-6.5, 7.2-7.12 | The same numbers as ASCE 7-16 | Check (cited as ASCE 7-22 in the report; the SNI 1726:2019 Tabel 12 rows are believed to match) |
| I9 | wind.kzFactor, wind.exposures.*.alpha / zg | 2.01; B 7.0 / 365.76 m, C 9.5 / 274.32 m, D 11.5 / 213.36 m | SNI 1727:2020 Tabel 26.10-1, 26.11-1 | ASCE 7-16 constants | Check |
| I10 | combinations, areaLoads, liveReduction | the base pack's ASCE 7-22 values | SNI 1727:2020 Pasal 2, 4 | Combinations and live loads | Check (the ASCE 7-16 values; SNI 1727:2020 Tabel 4.3-1 is believed to match) |

## SNI 2847:2019 (concrete) and SNI 1729:2020 (steel)

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| I11 | concrete.barNames | D10, D13, D16, D19, D22, D25, D29, D32, D36 | SNI 2052:2017 | Deformed bar names (the base pack's diameters) | Check |
| I12 | barSchedule.standards.aci315 | lengths rounded to 25 mm, stock 12 m, sizes "D{d}" | - | ACI 315 bar types with metric practice | SAEngine practice |
| I13 | citations.clauses | the base pack's ACI 318 numbers, named SNI 2847:2019 | SNI 2847:2019 | The concrete clause references | Check (SNI 2847:2019 keeps ACI 318-14's numbering) |
| I14 | concrete rules | the base pack's ACI 318-19 rules | SNI 2847:2019 | One-way shear with the size effect, ψg in development, the 2019 hooked bars and effective inertia are ACI 318-19's, not 318-14's | Uncertain (not covered: the ACI 318-14 forms are not built in) |
| I15 | steel | the base pack's AISC 360-22 | SNI 1729:2020 | Steel design | Check (SNI 1729:2020 follows AISC 360-16) |
