# Eurocodes with the German National Annexes (`eurocodes-de`)

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
| `combinations` | DIN EN 1990/NA | Eq 6.10 with the recommended γ and ψ |
| `areaLoads` | DIN EN 1991-1-1/NA Table 6.1DE | Imposed loads by the German categories (offices B1 2.0 kN/m², ...) |
| `locations` | DIN EN 1991-1-4/NA Annex NA.A; DIN EN 1998-1/NA | Towns with wind zone (vb,0 22.5-30 m/s) and seismic zone |
| `wind` | DIN EN 1991-1-4/NA Annex NA.B | qp(z) profiles inland, coast and North Sea islands (`peakVelocityPressure.profiles`); the simplified pressures up to 25 m by `useSimplified` |
| `snow` | DIN EN 1991-1-3/NA | sk of zones 1, 1a, 2, 2a, 3 by the site altitude |
| `concreteMethods` | DIN EN 1992-1-1/NA | αcc 0.85, CRd,c 0.15/γc, ν1 = 0.75 ν2 (`nuMax`) |
| `steelLimitState` | DIN EN 1993-1-1/NA | γM0 1.0, γM1 1.1, γM2 1.25 |
| `geotechnicalMethods` | DIN EN 1997-1/NA, DIN 1054 | Design approach 2* |
| `zoneCoefficients`, `seismic` | DIN EN 1998-1/NA | Zones 0-3 (agR 0, 0.4, 0.6, 0.8 m/s²), the combined subsoil classes A-R ... C-S |

Not covered: the cot θ limit of Eq 6.7aDE (the base pack's 2.5 taken), DA2*'s separate
eccentricity from characteristic actions, the DIN turbulence profiles (the detailed cscd uses
EN's with the profiles' z0).
