# Indonesian Standards (`indonesia-sni`)

A pack that adopts the US codes with local values: it `extends` the US pack `aci318-asce7-22`
(ASCE 7-22, ACI 318-19, AISC 360-22) and sets only what the Indonesian standards change; every
other table and value is the base pack's (see its README). Choose it in **02 Project Settings →
Design code** or in the **New Building** wizard's design code list; the wizard then offers the
cities below. Any single value can be overridden per project under **Code Values**, and switching
the pack applies on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standards was available when the pack was written, and the values marked uncertain there (the
cities' SS, S1, TL and the wind speed above all) must be checked before the pack is used for design.

## What it sets

| Table | Standard | What |
| --- | --- | --- |
| `locations` | SNI 1726:2019 Pasal 6.1 maps | 15 cities with SS, S1 and TL; the wind speed a placeholder (no national map) |
| `seismic` | SNI 1726:2019 Pasal 5.3, 6.2 | Site classes SA-SF (Tabel 5), Fa and Fv (Tabel 6, 7): SMS = Fa SS, SM1 = Fv S1, SDS, SD1 = 2/3 of them |
| `wind` | SNI 1727:2020 Pasal 26 | The ASCE 7-16 velocity pressure constants |
| `concrete` | SNI 2052:2017 | Bar names D10-D36 |
| `barSchedule` | ACI 315 | Metric lengths (12 m stock), sizes printed D16 |
| `citations` | SNI 2847:2019 | The concrete clause references named after SNI 2847 (same numbers) |

How the seismic hazard is found: a city's SS, S1 and TL (or the values entered in **Site → Mapped
spectral values**) with the site class give SDS and SD1; the Seismic Design Category (KDS), the
spectrum and Cs then follow the base pack's ASCE 7 rules, which SNI 1726:2019 shares.

Not set by this version: the ACI 318-14 forms of SNI 2847:2019 (the base pack's ACI 318-19 rules
apply), SNI 1729's own values (AISC 360-22 applies): the report names the base pack's clauses.
