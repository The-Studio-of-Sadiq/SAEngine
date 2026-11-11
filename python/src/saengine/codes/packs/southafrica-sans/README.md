# South Africa: SANS 10160, SANS 10100, SANS 10162 (`southafrica-sans`)

A pack that `extends` the built-in `eurocodes` pack: SANS 10160:2011 (basis of design and
actions) follows EN 1990, EN 1991 and EN 1998 with South African values, so the parent's methods
apply with this pack's numbers. Choose it in **02 Project Settings → Design code** or in the
**New Project** wizard; the wizard then offers the towns below. Any value can be overridden per
project under **Code Values**; switching the pack applies on the next run. A new project starts
in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standards was available when the pack was written.

## What it sets

| Table | Standard | What |
| --- | --- | --- |
| `zoneCoefficients` | SANS 10160-4 5.2 | ag = 0.05, 0.10, 0.15 g |
| `locations` | SANS 10160-3, -4 maps | 14 towns with vb,0 (36 / 40 m/s) and ag |
| `seismic` | SANS 10160-4 | One spectrum, ground types 1-4 (S, TB, TC, TD); the category by ag |
| `combinations` | SANS 10160-1 Table 3 | The STR set "sans" of the parent's strengthSets (chosen) |
| `concreteMethods` | SANS 10100-1 | αcc 0.85 with γc 1.5, γs 1.15 on the parent's EN 1992-1-1 methods |

**Which parent for the materials.** A pack has one parent and the loads decide it here
(SANS 10160 is an EN 1990 / 1991 / 1998 code). SANS 10100-1 is a BS 8110 type concrete code on
the cube strength, and SANS 10162-1 a CSA S16 type steel code: neither is the parent's. The pack
therefore keeps the parent's EN 1992-1-1 concrete methods with SANS 10100-1's partial factors
(αcc 0.85 stands for 0.67 fcu/γm on fck), and leaves the steel to the parent's EN 1993-1-1 (named
so in the report). A project that needs SANS 10100-1's own shear, deflection and detailing values
or SANS 10162-1's member resistances is not covered by this version.

Wind: the parent's EN 1991-1-4 method with the towns' vb,0; SANS 10160-3's own terrain
categories A-D (its power-law profile) are not set: the parent's EN terrain categories apply.
Seismic: the parent's EN 1998-1 behaviour factors, rules and drift limits; SANS 10160-4's own
behaviour factors and simplified rules for low-rise buildings are not set.
