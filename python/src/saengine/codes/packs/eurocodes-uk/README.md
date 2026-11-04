# Eurocodes with the UK National Annexes (`eurocodes-uk`)

It is a National Annex pack: it `extends` the base pack `eurocodes` (recommended values) and
sets only the Nationally Determined Parameters listed below; every other table and value is the
base pack's (see its README). Choose it in **02 Project Settings → Design code** or in the **New
Building** wizard's design code list. Any single value can be overridden per project under
**Code Values**, and switching the pack applies on the next run.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
annex was available when the pack was written, and the values marked there as uncertain must be
checked before the pack is used for design.

## What it sets

| Table | Annex | What |
| --- | --- | --- |
| `combinations` | UK NA to BS EN 1990 | Eqs 6.10a/6.10b (default), ξ = 0.925, ψ0 of the wind 0.5; Eq 6.10 by `combinations.strengthSet` |
| `areaLoads` | UK NA to BS EN 1991-1-1 | Imposed loads of Tables NA.2-NA.4 (dwellings 1.5, offices 2.5 kN/m², ...), roofs 0.6 kN/m² |
| `locations` | UK NA to BS EN 1991-1-4 Figure NA.1 | vb,map by town (22 towns); calt = 1 + 0.001 A on it (`wind.altitude`, Site > Site altitude) |
| `snow` | UK NA to BS EN 1991-1-3 | sk by the zone of Figure NA.1 and the site altitude (`snow.groundLoad`, Site > Snow > Snow zone) |
| `concreteMethods` | UK NA to BS EN 1992-1-1 | αcc 0.85 in flexure and axial, 1.0 in shear, torsion and punching (`alphaCCShear`); Δcdev 10 mm |
| `steelLimitState` | UK NA to BS EN 1993-1-1 / -1-8 | γM0 1.0, γM1 1.0, γM2 1.10 (members), 1.25 (joints) |
| `geotechnicalMethods` | UK NA to BS EN 1997-1 | Design Approach 1 |
| `zoneCoefficients` | UK NA to BS EN 1998-1, PD 6698 | Very low seismicity: no earthquake cases unless agR is entered |
| `barSchedule` | BS 8666:2020 | Bar schedules by BS 8666 |

Not covered: the UK exposure factors of Figures NA.7/NA.8 (qp by EN Eq 4.8), cdir by direction
(1.0 taken), the BS 8500 covers, the UK pile factors.
