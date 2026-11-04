# Iran: Standard 2800 and the National Building Regulations (`iran-2800`)

A pack that `extends` the US pack `aci318-asce7-22` and sets the Iranian seismic standard
(Standard 2800, 4th edition) and the concrete design of INBC Part 9. Choose it in **02 Project
Settings → Design code** or in the **New Building** wizard; the wizard then offers the towns
below. Any value can be overridden per project under **Code Values**; switching the pack applies
on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standard or the regulations was available when the pack was written. The towns' zones, the soil
parameters, the system factors and the wind speeds (placeholders) must be checked before design.

## What it sets

| Table | Code | What |
| --- | --- | --- |
| `zoneCoefficients` | Standard 2800 Table 2-1 | A = 0.35, 0.30, 0.25, 0.20 (zones 1-4) |
| `locations` | Standard 2800 Appendix 1 | 14 towns with their zone; wind speed placeholders (40 m/s) |
| `occupancyCategories` | Standard 2800 Table 3-1 | I = 0.8, 1.0, 1.2, 1.4 |
| `seismic` | Standard 2800 Ch 2-3 | C = A B I / Ru ≥ 0.12 A I, B = B1 N of the soil type (generic `shapeFactors` method), Ru / Ω0 / Cd, the period, the drift |
| `concrete` | INBC Part 9 | Bars Φ8-Φ32 |
| `concreteMethods` | INBC Part 9 | φc = 0.65, φs = 0.85 on the materials; the block α1 φc fc over β1 c |

Soil types: B = B1 N depends on the zone's group (N reaches 1.7 in the very high and high
zones, 1.4 in the moderate and low ones; soil type IV also has its own S0 and S). Each soil type
therefore has two site classes: **I, II, III, IV** for zones 1-2 and **IL, IIL, IIIL, IVL** for
zones 3-4. Choose the one of the site's zone (the settings do not check it).

The drift limit is 0.020 for every building (0.025 below T = 0.7 s: enter it as a Code Value),
with Cd times the displacements of the design forces. The equivalent static method takes the
plateau of B below T0 (SAEngine practice, on the safe side).

Not set by this version: the INBC Part 6 loads (the base pack's ASCE 7-22 combinations and live
loads apply), the wind (the towns' speeds are placeholders for the base pack's ASCE 7 method),
the 0.8 period factor of frames with infill walls, the irregularity rules of Standard 2800, the
INBC Part 9 shear and detailing (the base pack's ACI 318-19 rules with φ = 0.75 for shear, which
gives φVc = 0.1275 √fc bw d against Part 9's 0.13 √fc bw d) and the steel of INBC Part 10 (the
base pack's AISC 360-22).
