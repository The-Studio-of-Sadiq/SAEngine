# Building Code of Pakistan, Seismic Provisions (`pakistan-bcp`)

A pack that adopts the US codes with local values: it `extends` the US pack `aci318-asce7-22`
(ASCE 7-22, ACI 318-19, AISC 360-22) and sets the seismic provisions of BCP SP-2007; every other
table and value is the base pack's (see its README). Choose it in **02 Project Settings → Design
code** or in the **New Building** wizard's design code list; the wizard then offers the towns
below. Any single value can be overridden per project under **Code Values**, and switching the
pack applies on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
code was available when the pack was written, and the values marked uncertain there (the towns'
zones and the wind speeds above all) must be checked before the pack is used for design.

## What it sets

| Table | Code | What |
| --- | --- | --- |
| `zoneCoefficients` | BCP SP-2007 | Zones 1, 2A, 2B, 3, 4 (ids 1-5) with Z 0.075, 0.15, 0.20, 0.30, 0.40 |
| `locations` | BCP SP-2007 zoning map | 12 towns with their zone; the wind speed a placeholder |
| `seismic` | BCP SP-2007 Ch 5 (UBC 1997 form) | The `ubc97` spectrum method: Ca, Cv by soil profile SA-SF and Z, near-source factors Na, Nv in zone 4; R and Ω0; Ct hn^(3/4); the drift limit; zones read as categories B, C, D |
| `occupancyCategories` | BCP SP-2007 | I = 1.25 for essential and hazardous facilities |
| `barSchedule` | ACI 315 | Metric lengths (12 m stock) |

How the seismic hazard is found: the town's zone gives Z (or enter Z for a custom location); with
the soil profile Z gives Ca and Cv; in zone 4 the near-source factors come from the seismic source
type and the distance to it entered in **Site → Mapped spectral values** (or Na and Nv entered
directly; 1.0 until then, and the settings check says so). The design spectrum is 2.5 Ca on the
plateau and Cv/T beyond; V = Cv I W/(R T), at most 2.5 Ca I W/R, at least 0.11 Ca I W (and 0.8 Z
Nv I W/R in zone 4).

Not covered by BCP SP-2007 and so the base pack's: wind (ASCE 7-22), live loads, combinations,
concrete (ACI 318-19) and steel (AISC 360-22).
