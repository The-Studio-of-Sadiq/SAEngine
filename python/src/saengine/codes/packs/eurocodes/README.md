# Eurocodes code pack (`eurocodes`)

The Eurocodes with their **recommended values**, loads and seismic actions only (version 0.1,
alpha 9 track C4). Choose it in **02 Project Settings → Design code** or in the **New Building**
wizard's design code list.

Every value, with its clause and a one-line description, is in [`VERIFY.md`](VERIFY.md) for
checking against the printed codes: no code text was available when the pack was written, and
the values marked there as unsure must be checked before the pack is used for design.

## What it covers

| Table | Code | What |
| --- | --- | --- |
| `combinations` | EN 1990 Sec 6.4.3, 6.5.3, Annex A1 | ULS sets **6.10** and **6.10a/b** (`strengthSet` chooses), seismic 6.12b, SLS characteristic, frequent and quasi-permanent; ψ of Table A1.1, partial factors of Table A1.2(B) |
| `areaLoads` | EN 1991-1-1 Sec 6.3, 6.4, Annex B | Imposed loads of categories A-I (with `category`), movable partitions, barriers and vehicle barriers |
| `liveReduction` | EN 1991-1-1 Sec 6.3.1.2(10)-(11) | αA and αn (`method: "areaAndStoreys"`) |
| `snow` | EN 1991-1-3 Sec 5.2, 5.3.2 | s = μ1·Ce·Ct·sk on the roof (the project gives sk under Site → Snow) |
| `wind` | EN 1991-1-4 Sec 4, 6.2, 7.2.2 | Peak velocity pressure qp(z) by terrain category (`method: "peakVelocityPressure"`), cpe of walls, lack of correlation, cscd |
| `flood` | EN 1991-1-7 Annex D | Internal gas explosions only (`explosion`); the rest of the table is the parent's |
| `seismic` | EN 1998-1 Sec 3, 4; Tables 5.1, 6.2, 9.1 | Ground types A-E (ids SA-SE), Type 1 and Type 2 spectra (`spectrumType`), the design spectrum with q and β, behaviour factors of the systems SAEngine models (DCL, DCM, DCH), λ and the linear lateral force distribution, accidental torsion, 90 % modal mass, 0.3 orthogonal share, ψE, drift with ν, θ |
| `occupancyCategories` | EN 1998-1 Sec 4.2.5 | Importance classes I-IV, γI |
| `locations`, `zoneCoefficients` | EN 1998-1 Sec 3.2.1, EN 1991-1-4 Sec 4.2 | No towns (National Annex maps): Location Custom with agR as Z and vb,0 as V; bands of agR for the category of the seismic action |

The pack chooses these generic methods of SAEngine by id (other packs may choose them too):
`seismic.designSpectrum.method: "behaviourFactor"` (`saengine.fem.spectra`),
`seismic.lateralForce`, `seismic.driftAmplification: "displacementFactor"`,
`seismic.stability.method: "designDrift"`, `wind.method: "peakVelocityPressure"`
(`saengine.fem.peak_velocity_pressure`), `liveReduction.method: "areaAndStoreys"` and the
`snow` table (`saengine.fem.snow_load`).

## What falls back (not Eurocode yet)

The pack `extends` BNBC 2020, so a project designs and runs. Until the EN 1992 to EN 1999 packs
(tracks C5, C6) exist, these tables come from **BNBC 2020** and the report's design basis says
so: `materials`, `factors`, `concrete`, `detailing`, `steel`, `steelSections`, `steelSeismic`,
`steelStability`, `foundations`, `transfer`, `slabCoefficients`, `slabMethods`, `wallMethods`,
`stairMethods`, `masonry`, `timber`, `composite`, `compositeConcrete`, `anchors`,
`concreteTime`, `designLimits`, `designClauses`, `serviceability`, `siteInvestigation`,
`fireResistance` and the services (`plumbing`, `hvac`, `electrical`, `fire`, `planning`,
`accessibility`, `mepOpenings`). The load tables without a Eurocode counterpart here are the
parent's too: `deadLoads` (unit weights), `cranes`, `nonstructural`, `isolation`, `pushover`,
`nonlinearHistory`, `fatigue` and the flood, rain, helipad and shelter parts of `flood`. The
member design therefore applies BNBC's strength reduction factors φ to the EN 1990 design
actions.

Not covered by this version (stated in the results where they would apply): EN 1991-1-4
torsion (e = b/10), orography (co ≠ 1), the detailed cscd and the cladding pressures;
EN 1991-1-3 drift and local effects; EN 1998-1 regularity criteria (4.2.3), the torsional
effects factor δ (4.3.3.2.4), the vertical component, the SRSS/CQC choice (CQC is always used),
response history rules and capacity design.

## National Annexes

A National Annex is a pack that `extends: "eurocodes"` and gives only its Nationally Determined
Parameters. For example (see `python/tests/test_codes_eurocodes.py`):

```json
{ "schema": "saengine.codePack/1", "id": "ec-xx", "name": "Eurocodes with the XX National Annex",
  "extends": "eurocodes", "covers": ["combinations", "seismic"] }
```

`data/combinations.json`: `{ "strengthSet": "6.10ab" }`;
`data/seismic.json`: `{ "spectrumType": "2", "designSpectrum": { "lowerBound": 0.1 } }`.
Objects merge key by key, so the annex changes one value and keeps the rest. It may also list
its towns with their zones and wind speeds in `locations`, and give its own `zoneCoefficients`.
A project may override any single value under **Code Values** instead.
