# Nepal (`nepal-nbc`)

A pack for Nepal's National Building Code: it `extends` the built-in pack `is-codes` (IS 875
loads and wind, IS 456 and IS 13920 concrete, IS 800 steel) and sets what NBC 105:2020 changes.
Choose it in **02 Project Settings → Design code** or in the **New Project** wizard; the wizard
then offers the municipalities below. Any value can be overridden per project under **Code
Values**; switching the pack applies on the next run.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of NBC
105:2020 was available when the pack was written. The municipalities' Z and the long-period
branch of Ch(T) are uncertain and must be checked before design.

## What it sets

| Table | Code | What |
| --- | --- | --- |
| `locations` | NBC 105:2020 Table 4-5, NBC 104 | 14 municipalities with Z (as zone 100 Z) and Vb 47 m/s |
| `zoneCoefficients` | NBC 105:2020 4.1.4 | Z = 0.25, 0.30, 0.35, 0.40 |
| `occupancyCategories` | NBC 105:2020 Table 4-3 | I = 1.0, 1.25, 1.5 |
| `seismic` | NBC 105:2020 Sections 3-6 | Soil types A-D with Ch(T), Cd(T) = Ch(T) Z I / (Rμ Ωu), Rμ and Ωu by system, T1 = 1.25 kt H^0.75, ULS drift 0.025 |
| `combinations` | NBC 105:2020 3.6 | 1.2 DL + 1.5 LL, DL + 0.3 LL + E; the parent's wind combinations |

How the seismic design runs: the municipality's Z (or a custom Z), the soil type's spectral shape
factor Ch(T) (Table 4-1: Ta, Tc, α, K; α below Ta for the equivalent static method), the
importance factor I and the system's Rμ and Ωu give the ULS design coefficient Cd(T) = Ch(T) Z I /
(Rμ Ωu) by the generic `shapeFactors` method; the base shear V = Cd(T1) W, distributed with k = 1
to 2; the ULS deflections are Rμ times the elastic ones, at most 0.025 h.

## Not covered

The SLS spectrum Cs(T) = 0.2 C(T) / Ωs and its 0.006 drift check (the ULS check governs for the
usual factors: VERIFY.md N12), the NBC 105 irregularity checks and its modal scaling rule (taken
as 1.0 × the static base shear, on the safe side), NBC 110 (Nepal designs concrete to IS 456,
the parent's), the Mandatory Rules of Thumb (NBC 205) for small buildings. NBC 102 / 103 / 104
values are the parent's IS 875 Parts 1-3.
