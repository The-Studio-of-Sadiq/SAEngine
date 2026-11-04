# Saudi Building Code (`saudi-sbc`)

A pack that adopts the US codes with local values: it `extends` the US pack `aci318-asce7-22`
(ASCE 7-22, ACI 318-19, AISC 360-22) and sets only what the Saudi Building Code changes; every
other table and value is the base pack's (see its README). Choose it in **02 Project Settings →
Design code** or in the **New Building** wizard's design code list; the wizard then offers the
cities below. Any single value can be overridden per project under **Code Values**, and switching
the pack applies on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
code was available when the pack was written, and the values marked uncertain there (the cities'
SS, S1 and wind speeds above all) must be checked before the pack is used for design.

## What it sets

| Table | Code | What |
| --- | --- | --- |
| `locations` | SBC 301-2018 Sec 11.4.2, 26.5.1 | 14 cities with the mapped SS, S1 and the basic wind speed V |
| `seismic` | SBC 301-2018 Ch 11, 20 | Site classes A-F, Fa and Fv (Tables 11.4-1, 11.4-2): SMS = Fa SS, SM1 = Fv S1, SDS, SD1 = 2/3 of them; no multi-period spectrum |
| `wind` | SBC 301-2018 Table 26.10-1, 26.11-1 | The ASCE 7-16 velocity pressure constants (Kz = 2.01 (z/zg)^(2/α)) |
| `concrete` | SBC 304-2018 | The Kingdom's bar sizes 8-32 mm (SAEngine practice) |
| `barSchedule` | BS 8666 | Bar schedules after BS 8666 (Gulf practice) |
| `citations` | SBC 304-2018 | The concrete clause references named after SBC 304 |

How the seismic hazard is found: a city's SS and S1 (or the values entered in **Site → Mapped
spectral values**: SDS and SD1, SMS and SM1, or SS and S1) with the site class give SDS and SD1;
the Seismic Design Category, the spectrum and Cs then follow the base pack's ASCE 7 rules. For a
site elsewhere choose **Custom** and enter SS and S1 (and V).

Not set by this version: the Saudi modifications of SBC 304 (durability, covers), SBC 306's own
values and the SBC live load table: the base pack's values apply and the report names them.
