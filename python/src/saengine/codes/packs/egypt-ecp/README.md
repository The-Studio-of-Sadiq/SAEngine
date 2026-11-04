# Egyptian Codes: ECP 201 and ECP 203 (`egypt-ecp`)

A pack that `extends` the legacy British Standards pack `bs8110` and sets the Egyptian Code of
Practice for loads and seismic actions (ECP 201-2012) and for concrete (ECP 203-2018). Choose it
in **02 Project Settings → Design code** or in the **New Building** wizard; the wizard then offers
the towns below. Any value can be overridden per project under **Code Values**; switching the
pack applies on the next run. A new project starts in SI units.

**Why bs8110 as the parent.** ECP 203 designs concrete on the cube strength fcu with the block
0.67 fcu/γc, γc = 1.5, BS 8110's way; the concrete methods (flexure, shear by a design stress,
the columns, slabs, detailing) therefore come from the parent with ECP 203's numbers. The seismic
part of ECP 201 has the EN 1998-1 form; it is a data choice (the generic `behaviourFactor`
spectrum method a pack picks by id), not a parent, so it is set here in full and needs nothing
of the `eurocodes` pack.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
codes was available when the pack was written.

## What it sets

| Table | Code | What |
| --- | --- | --- |
| `zoneCoefficients` | ECP 201 Table 8.1 | ag = 0.10, 0.125, 0.15, 0.20, 0.25, 0.30 g (zones 1, 2, 3, 4, 5A, 5B) |
| `locations` | ECP 201 Figure 8.1 | 14 towns with their zone; placeholder wind speeds |
| `occupancyCategories` | ECP 201 Table 8.9 | γI = 0.8, 1.0, 1.2, 1.4 |
| `seismic` | ECP 201 Ch 8 | The EN 1998-1 design spectrum with ag γI, two spectrum types, soil classes A-D, β = 0.2, R, λ = 0.85, drift |
| `combinations` | ECP 203 3.2.1 | 1.4D + 1.6L, 0.8(1.4D + 1.6L + 1.6W), 0.9D + 1.3W, 1.12D + αL + E, 0.9D + E |
| `concrete` | ES 262 | Bars Ø8-Ø32 |
| `concreteMethods` | ECP 203 Ch 4 | γs 1.15, the block over 0.8 c, c ≤ 2/3 cb, Ec 4400 √fcu, emin, short columns, shear qcu / qmax |

Spectrum type: the Type 2 values (the longer corner periods) are taken; override
`seismic.spectrumType` to "1" where ECP 201 gives the Type 1 spectrum for the site.

Not set by this version: ECP 201's wind (the parent's BS 6399-2 method with placeholder hourly
mean speeds) and live loads (the parent's BS 6399-1), the vertical component, the irregularity
rules, ECP 203's punching, deflection, crack, cover and detailing values (the parent's BS 8110
ones), ECP 205 steel (the parent's BS 5950-1).
