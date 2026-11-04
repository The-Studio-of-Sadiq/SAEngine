# Peru: E.030 and E.060 (`peru-e030`)

A pack that `extends` the US pack `aci318-asce7-22` and sets the Peruvian seismic standard E.030
(2018) and the E.060 concrete factors and combinations. Choose it in **02 Project Settings →
Design code** or in the **New Building** wizard; the wizard then offers the towns below. Any
value can be overridden per project under **Code Values**; switching the pack applies on the
next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standards was available when the pack was written.

## What it sets

| Table | Standard | What |
| --- | --- | --- |
| `zoneCoefficients` | E.030 Table 1 | Z = 0.10, 0.25, 0.35, 0.45 (zones 1-4) |
| `locations` | E.030 Anexo I | 14 towns with their zone; wind speed E.020's least 75 km/h |
| `occupancyCategories` | E.030 Table 5 | U = 1.0 (C), 1.3 (B), 1.5 (A) |
| `seismic` | E.030 Ch 2-5 | Sa = Z U C S / R with S by zone and soil, TP, TL, C/R ≥ 0.11, R0, T = hn/CT, drift 0.007 / 0.010 / 0.005 |
| `combinations` | E.060 9.2 | 1.4D + 1.7L, 1.25(D + L ± W), 0.9D ± 1.25W, 1.25(D + L) ± E, 0.9D ± E |
| `factors` | E.060 9.3 | φ = 0.70 tied columns, 0.85 shear, 0.70 bearing |
| `concrete` | NTP 341.031 | Bar names in inches (3/8" ... 1 3/8") |

How the spectrum is built: the generic `shapeFactors` method with the soil profile's C(T) as
its shape (2.5 to TP, 2.5 TP/T to TL, 2.5 TP TL/T² beyond; the modal analysis rises from 1 at
T = 0 to 2.5 at 0.2 TP, the static method takes the plateau), Z and U as the hazard, R0 as the
system's R, and the soil factor S of the soil profile and the zone (Table 3) on top. C/R is at
least 0.11. Buildings are taken as regular (Ia = Ip = 1): enter R = R0 Ia Ip as a Code Value for
an irregular one. The drift is 0.75 R (Cd) times the elastic displacements.

Not set by this version: the irregularity factors Ia, Ip, the limits on systems by zone and
category (E.030 Table 10), the E.020 live loads and wind (the base pack's ASCE 7-22 live loads
and method; the towns' speeds are E.020's least), E.060's own detailing (the base pack's ACI
318-19 rules, which E.060 follows), E.090 steel (the base pack's AISC 360-22), the soil profile
S4 (site-specific).
