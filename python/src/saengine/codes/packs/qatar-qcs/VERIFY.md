# qatar-qcs: values to verify

No copy of QCS 2014 was available when this pack was written (alpha 9, track C23, 2026-11-04).
Every value was entered from knowledge and is to be checked by the owner. **Sure**: well-known
value, low risk. **Check**: believed right, confirm the number or the row. **Uncertain**: the
value or its reading may be wrong, or it is an SAEngine form of the rule; SAEngine's choice is
stated. Everything the pack does not set is the parent's (`bs8110`, its VERIFY.md).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| Q1 | locations.*.windSpeed | 25.0 m/s for Doha, Lusail, Al Wakrah, Al Rayyan, Al Khor, Mesaieed, Ras Laffan, Dukhan | QCS 2014 (wind to BS 6399-2) | Basic hourly mean wind speed Vb at 10 m, open country | Uncertain (SAEngine practice: about the hourly mean of a 45 m/s 3-second gust over open country, ÷ Sb ≈ 1.8; replace with the value the authority or the QCS section in force gives) |
| Q2 | locations.*.zone | 0 | QCS 2014 | No seismic loading | Uncertain (not covered: check whether the project's authority asks for a seismic design) |
| Q3 | wind.defaultExposure | town2 | BS 6399-2 Table 4 | Town site 2 km from the sea | SAEngine practice |
| Q4 | concreteMethods.defaultExposure | severe | BS 8110-1 Table 3.3 | New members' exposure (cover 40 mm, C40) | SAEngine practice (check QCS's own exposure classes and covers) |
| Q5 | pack.json sources | QCS 2014, Qatar General Organization for Standards and Metrology | - | Publisher and edition | Check |
| Q6 | Project Settings > Temperature (README) | about 25 °C uniform change | - | Suggestion only, not a pack value | SAEngine practice |
