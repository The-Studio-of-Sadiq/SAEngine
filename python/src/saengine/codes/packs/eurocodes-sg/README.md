# Eurocodes with the Singapore National Annexes (`eurocodes-sg`)

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
| `locations` | SS EN 1991-1-4 NA | Singapore, vb,0 = 20 m/s |
| `wind` | Singapore NA | The least horizontal load, 1.5 % of each floor's characteristic dead weight (`wind.minimumLateral`) |
| `zoneCoefficients` | - | No seismic design (EN 1998 not adopted) |
| `concreteMethods` | SS EN 1992-1-1 NA | αcc 0.85 flexure and axial, 1.0 shear |
| `steelLimitState` | SS EN 1993-1-1 NA | γM2 1.10 |

Combinations and imposed loads are the base pack's recommended values in this version.
