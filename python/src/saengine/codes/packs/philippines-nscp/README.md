# National Structural Code of the Philippines 2015 (`philippines-nscp`)

A pack that adopts the US codes with local values: it `extends` the US pack `aci318-asce7-22`
(ASCE 7-22, ACI 318-19, AISC 360-22) and sets only what NSCP 2015 (Volume 1) changes; every other
table and value is the base pack's (see its README). Choose it in **02 Project Settings → Design
code** or in the **New Project** wizard's design code list; the wizard then offers the provinces
below. Any single value can be overridden per project under **Code Values**, and switching the
pack applies on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
code was available when the pack was written, and the values marked uncertain there (the provinces'
wind speeds and the system table above all) must be checked before the pack is used for design.

## What it sets

| Table | NSCP 2015 | What |
| --- | --- | --- |
| `zoneCoefficients` | Table 208-3 | Zone 2: Z 0.20, zone 4: Z 0.40 |
| `locations` | Sec 208.4.4.1, Table 207A.5-1 | 16 provinces with their zone and basic wind speed |
| `seismic` | Section 208 (UBC 1997 form) | The `ubc97` spectrum method: Ca, Cv by soil profile SA-SF and Z, near-source factors Na, Nv in zone 4; R and Ω0; Ct hn^(3/4); the drift limit; zones read as categories C and D |
| `wind` | Section 207A (ASCE 7-10 form) | The ASCE 7-10 velocity pressure constants |
| `occupancyCategories` | Table 208-1 | I = 1.5 essential, 1.25 hazardous |
| `concrete` | PNS 49 | Bar sizes 10-36 mm |
| `barSchedule` | ACI 315 | Metric lengths (12 m stock), sizes printed Ø16 |
| `citations` | Chapter 4 | The concrete clause references in the NSCP numbering (Section 425.4.2 for ACI 25.4.2) |

How the seismic hazard is found: the province's zone gives Z; with the soil profile Z gives Ca and
Cv; in zone 4 the near-source factors come from the seismic source type (A, B, C) and the distance
to it entered in **Site → Mapped spectral values** (or Na and Nv entered directly; 1.0 until then,
and the settings check says so). The design spectrum is 2.5 Ca on the plateau and Cv/T beyond;
V = Cv I W/(R T), at most 2.5 Ca I W/R, at least 0.11 Ca I W and 0.8 Z Nv I W/R in zone 4.

SAEngine's occupancy ids I-IV hold NSCP's categories: IV essential (NSCP I), III hazardous and
special (NSCP II, III), II standard (NSCP IV), I miscellaneous (NSCP V).

Not set by this version: the ACI 318-14 forms of Chapter 4 (the base pack's ACI 318-19 rules
apply), the live loads of Table 205-1 and Chapter 5's own values.
