# ACI 318-19 + ASCE 7-22 code pack (`aci318-asce7-22`)

The built-in US pack. This version (alpha 9, track C1) covers the **loads** of ASCE/SEI 7-22;
concrete (ACI 318-19), steel and the other materials are later tracks. The pack extends
`bnbc2020`: every table it does not give (concrete, detailing, steel, foundations, masonry,
timber, the building services, dead load unit weights ...) is BNBC 2020's, and the report and
the design notes cite those tables as BNBC 2020's.

Choose it in Project Settings (Design code) or in the New Building wizard. The site's values
come from the ASCE Hazard Tool, not from a table of towns: enter SDS, SD1 (or SMS, SM1, or the
multi-period MCER spectrum), S1 and TL under Site > Mapped spectral values, the basic wind
speed V of the risk category under Site, and a ground snow load under Site > Snow.

**Every value is listed with its clause in [`VERIFY.md`](VERIFY.md), to be checked against the
printed standard.** No text of the standards is reproduced here.

## Tables

| File | What it holds | Clauses |
| --- | --- | --- |
| `locations.json` | No towns: the site's values are entered | Sec 11.4.2, 26.5.1, 7.2 |
| `occupancyCategories.json` | Risk categories I-IV, Ie; no wind importance factor | Tables 1.5-1, 1.5-2 |
| `areaLoads.json` | Live loads by use with their concentrated loads, partitions, impact | Table 4.3-1, Sec 4.3.2, 4.4, 4.6 |
| `liveReduction.json` | Reduction by influence area, KLL, roof R1 R2 | Sec 4.7, Table 4.7-1, Sec 4.8.2 |
| `combinations.json` | Strength and ASD combinations with E, flood, cantilever uplift | Sec 2.3, 2.4, 12.4 |
| `seismic.json` | Mapped spectral hazard (method `mappedSpectral`), site classes, systems, SDC bands, Cs bounds, Cu, drift limits, irregularities, W, θ | Ch 11, 12, 20 |
| `wind.json` | ASCE 7-22 terrain constants and Kz, topography; the shared coefficients from bnbc2020 | Ch 26-30 |
| `snow.json` | Flat and sloped roof snow, minimum load, density, drift (method `windParameter`) | Ch 7 |
| `flood.json` | US design flood; the Bangladesh surge tables removed | Ch 5, Sec 8.2 |
| `transfer.json` | Diaphragm force bounds and collectors | Sec 12.10.1.1, 12.10.2.1 |

## Methods it chooses

- `seismic.designSpectrum.method = mappedSpectral` (`saengine.fem.spectral_hazard`; the methods `reducedElastic` and `behaviourFactor` of the other packs share the selector): the two-period and
  multi-period spectra from the site's mapped values, Cs with its bounds, the SDC from the
  bands of SDS and SD1, Cu by SD1.
- `snow.method = slopeFactor`, `snow.loadCase = S` and `snow.drift.method = windParameter` (`saengine.fem.snow_load`, shared with the Eurocodes pack's `shapeCoefficient`).
- `seismic.stability.method = elasticDrift` (θ of Eq 12.8-16).
