# BNBC 1993 / 2006 (previous Bangladesh code)

Code pack `bnbc2006`, built in (alpha 9 track C10): the Bangladesh National Building Code of 1993,
reissued as BNBC 2006, for checking buildings designed to it. It `extends` BNBC 2020 and replaces
only what the older code gives differently:

| Table | What it overrides | Code |
| --- | --- | --- |
| `zoneCoefficients` | Three zones, Z = 0.075, 0.15, 0.25 | Table 6.2.22 |
| `locations` | The districts' zones and fastest-mile basic wind speeds (the default pack's site-map towns removed) | Table 6.2.8, Figure 6.2.24 |
| `occupancyCategories` | Structure importance I and CI (essential and hazardous 1.25; low-risk CI 0.80) | Tables 6.2.9, 6.2.23 |
| `seismic` | V = Z I C W / R, C = 1.25 S / T^(2/3) <= 2.75, C/R >= 0.075; S1-S4; T = Ct hn^(3/4); R of the systems; Ft = 0.07 T V <= 0.25 V | Sec 2.5 |
| `wind` | qz = Cc CI Cz Vb², pz = CG Cp qz by exposure A, B, C; the overall Cp of walls | Sec 2.4 |
| `combinations` | 1.4D + 1.7L, 0.75 (1.4D + 1.7L + 1.7W), 0.9D + 1.3W, 0.75 (1.4D + 1.7L + 1.87E), 0.9D + 1.43E | Sec 6.2.2, 2.7 |
| `factors` | φ 0.90 flexure, 0.70 tied, 0.75 spiral, 0.85 shear, 0.70 bearing, 0.65 plain | Sec 6.2.3 |

The generic methods it uses (open to any pack): the `reducedElastic` spectrum with this track's
`shapePlateau`, `descendingExponent` and `leastCoefficient` (`fem/loads.py`), the lateral force
rule's `topForce`, and the wind `speedFactors` method with k2 = √(Cz CG) and k1 = √CI.

Not covered: the working stress design of concrete, the 1993 drift limits (BNBC 2020's apply),
cladding and roof wind pressures. Everything else (live loads, concrete and steel design,
foundations, the services) is BNBC 2020's and the report names it so.

Every value is listed in [VERIFY.md](VERIFY.md) for checking against the printed code (no copy of
the 1993 / 2006 text was available).
