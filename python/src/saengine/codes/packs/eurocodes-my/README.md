# Eurocodes with the Malaysian National Annexes (`eurocodes-my`)

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
| `locations` | MS EN 1991-1-4 NA; MS EN 1998-1 NA | Towns with vb,0 of the wind zone and the agR band |
| `zoneCoefficients` | MS EN 1998-1 NA Figure NA.1 | Bands of agR (SAEngine practice) |
| `concreteMethods` | MS EN 1992-1-1 NA | αcc 0.85 flexure and axial, 1.0 shear |

The town values are uncertain (VERIFY.md M1, M2): check them on the NA maps. Combinations,
imposed loads, steel and geotechnics are the base pack's recommended values in this version.
