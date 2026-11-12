# Myanmar National Building Code 2020 (`myanmar-mnbc`)

A thin built-in pack (alpha 9 track C23). MNBC 2020 Part 3 (structural design) follows the
IBC / ASCE 7 form for loads and ACI 318 for concrete, so the pack `extends` the US pack
`aci318-asce7-22` and sets only what MNBC changes; every other table is the US pack's (see its
README), and the report names those ASCE 7-22, ACI 318-19 or AISC 360-22. Choose it in
**02 Project Settings → Design code** or in the **New Project** wizard; its towns are in
**Site → Location**. Any value can be overridden per project under **Code Values**; switching
the pack applies on the next run. New projects start in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md). No copy of
MNBC 2020 was available when the pack was written: the towns' SS, S1 and wind speeds are
SAEngine estimates by zone and region and must be replaced with the MNBC tables' values before
the pack is used for design.

## What it sets

| Table | What | Form |
| --- | --- | --- |
| `locations` | 19 towns: MNBC seismic zone (for information), mapped SS and S1 [g], basic wind speed V (3-second gust, 50-year) | MNBC 2020 Part 3 |
| `zoneCoefficients` | Upper PGA of zones 1-5, for information only (Z is not used) | MNBC zone map |
| `seismic` | Site coefficients Fa (by SS) and Fv (by S1) of site classes A-E; site classes A-F by vs30 | ASCE 7-05 Tables 11.4-1, 11.4-2, 20.3-1 form |
| `combinations` | 1.4D; 1.2D + 1.6L + 0.5Lr; 1.2D + 1.6Lr + (L or 0.8W); 1.2D + 1.6W + L + 0.5Lr; 1.2D + E + L + 0.2S; 0.9D + 1.6W; 0.9D + E; ASD with W at 1.0 | ASCE 7-05 Sec 2.3.2, 2.4.1 form |
| `occupancyCategories` | Wind importance 0.87 / 1.0 / 1.15 / 1.15 | ASCE 7-05 Table 6-1 form |
| `wind` | Exposure constants α, zg and Kz = 2.01 (z/zg)^(2/α) | ASCE 7-05 Table 6-2 form |
| `concrete` | Metric bars 10-32 mm (8 mm links), no US bar numbers | SAEngine practice |
| `barSchedule` | BS 8666 bar shapes | SAEngine practice |

## Seismic hazard

The design spectrum is the parent's `mappedSpectral` method with the generic option
`seismic.designSpectrum.siteCoefficients` (alpha 9 C23): where the project gives neither SDS,
SD1 nor SMS, SM1, SMS = Fa SS and SM1 = Fv S1 from the town's SS and S1 (or the project's own,
Site → Mapped spectral values), SDS = 2/3 SMS, SD1 = 2/3 SM1; the two-period spectrum, Cs with
its bounds, the Seismic Design Category bands and Cu are the parent's (the same in ASCE 7-05).
Site class F is read as class E until a site response analysis is made (the parent's rule). TL
is not set (the spectrum stays SD1/T at long periods, on the safe side).

## Not covered

MNBC's own live loads (the parent's ASCE 7-22 Table 4.3-1 apply), MNBC's own wind pressure
coefficients (the parent's), the long-period TL map, the towns not listed (custom location:
enter SS, S1 and V). The towns' map coordinates (for the site map's suggestion) are not given.
