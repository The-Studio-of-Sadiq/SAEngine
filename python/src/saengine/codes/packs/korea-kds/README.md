# Korean Design Standards (`korea-kds`)

A pack that `extends` the US pack `aci318-asce7-22` (ASCE 7-22, ACI 318-19, AISC 360-22) and sets
what the Korean Design Standards change: KDS 41 17 00:2019 (seismic design of buildings, the
successor of KBC 2016), KDS 41 12 00 (wind) and KDS 14 20 (concrete). Choose it in **02 Project
Settings → Design code** or in the **New Project** wizard; the wizard then offers the towns
below. Any value can be overridden per project under **Code Values**; switching the pack applies
on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standards was available when the pack was written. The towns' zones and wind speeds and the
S1-S6 site coefficients are uncertain and must be checked before design.

## What it sets

| Table | Standard | What |
| --- | --- | --- |
| `locations` | KDS 41 17 00 4.2.1, KDS 41 12 00 5.5 | 13 towns: zone I or II as SS = 2.5 S, S1 = S (S = 0.22, 0.14 g), the wind speed |
| `seismic` | KDS 41 17 00 4.2 | Site classes S1-S6, Fa and Fv by S; SDS = 2.5 S Fa × 2/3, SD1 = S Fv × 2/3 |
| `occupancyCategories` | KDS 41 17 00 3.2 | Importance factors 1.5 (special), 1.2 (I), 1.0 (II) |
| `concrete` | KS D 3504 | Bars D10-D32 |
| `factors` | KDS 14 20 10 4.2.3 | φ = 0.85 tension-controlled, 0.70 spirals, 0.55 plain concrete |

How the seismic hazard is found: the town's S (zone factor × 2.0 for the 2400-year earthquake) is
entered as the mapped values SS = 2.5 S and S1 = S, so the base pack's SMS = Fa SS and
SDS = 2/3 SMS give KDS's SDS = 2.5 S Fa × 2/3 (and SD1 = S Fv × 2/3). The Seismic Design
Category, the design spectrum, Cs, R, Ω0, Cd and the drift limits then follow the base pack's
ASCE 7 rules, whose numbers KDS 41 17 00 shares (VERIFY.md K7-K9). For a site elsewhere choose
**Custom** and enter SS = 2.5 S and S1 = S.

Wind: the base pack's ASCE 7-22 method. KDS 41 12 00's basic wind speed V0 is a 10-minute mean;
the towns' speeds are V0 × 1.43 (the 3-second gust the ASCE 7 method takes, SAEngine practice).
KDS 41 12 00's own profile (Kzr), gust factor and importance factor are not set.

Concrete: the base pack's ACI 318-19 rules (KDS 14 20 follows ACI 318) with the KDS φ. The KDS
2021 stress block (εcu 0.0033 and its own block factors) is not set: the ACI block applies.

Not set by this version: the KDS live loads and combinations (the base pack's ASCE 7-22 values),
the height limits of Table 6.2-1, KDS 41 12 00's wind method, KDS 14 31's own steel values.
