# New Zealand Standards (NZS 1170.5, NZS 3101, NZS 3404)

Code pack `newzealand-nzs`, built in (alpha 9 track C18). It `extends` the Australian pack
`australia-as` where the joint standards are equal; that pack extends BNBC 2020, so a table
neither covers comes from the default pack and the report names it so.

| Table | What it holds | Code |
| --- | --- | --- |
| `locations` | 22 towns with Z and the V500 of their wind region NZ1-NZ4; default Wellington | NZS 1170.5 Table 3.3, AS/NZS 1170.2:2021 |
| `zoneCoefficients` | Z 0.10-0.42 in SAEngine's zone slots | NZS 1170.5 Table 3.3 |
| `occupancyCategories` | IL1-IL4: R 0.5 / 1.0 / 1.3 / 1.8, the wind row marker | AS/NZS 1170.0 Table 3.3, NZS 1170.5 Table 3.5 |
| `seismic` | Classes A-E with Ch(T), N(T,D), Sp and kμ, the least Cd, Ft = 0.08 V, μ of the systems, 2.5 % drift | NZS 1170.5:2004 |
| `materials` | α1 and β1 of NZS 3101, the 300E / 500E grades | NZS 3101:2006 7.4.2.7 |
| `factors` | φ 0.85 flexure (any axial force), 0.75 shear; N*max = 0.85 φ N0 | NZS 3101:2006 2.3.2.2, 10.3.4.2 |
| `concrete` | Bars HD10-HD40, vc = (0.07 + 10 ρw) √f'c, Ec 4700 √f'c, shrinkage steel | NZS 3101:2006 |
| `concreteMethods` | Empty: the AS 3600 shear method is not inherited | NZS 3101:2006 9.3.9 |
| `steelLimitState` | The AS 4100 member rules of the Australian pack, named NZS 3404 | NZS 3404 Part 1 |

Inherited from `australia-as` (AS/NZS joint standards): the combinations (AS/NZS 1170.0), the
imposed actions and ψa (AS/NZS 1170.1), the wind (AS/NZS 1170.2:2021, the regions in the towns)
and the period T1.

## Methods by id

Earthquake `designSpectrum.method: "shapeFactors"` (`fem/spectra.py`): C(T) = Ch(T) Z R N(T,D),
Z R at most 0.7, Cd(T) = C(T) Sp/kμ with the system's R holding μ, Sp = 1.3 - 0.3 μ (0.7 from
μ 2), kμ by 5.2.1.1 (class E its own), Cd at least (Z/20 + 0.02) R and 0.03 R; N(T,D) with the
site's distance to a major fault (Code Values `seismic.designSpectrum.shapeFactors.faultDistance`,
empty: N = 1). The equivalent static distribution `lateralForce` linear with the top force
0.08 V. Concrete on the strength design path with the pack's stress block, the axial cap and
`concrete.shearStress`.

## Not covered (from the parent packs, named so)

NZS 3101 capacity design beyond the program's probable-moment rules (Appendix D dynamic
magnification, the ductile wall provisions of 11.4, the ductile detailing lengths), NZS 3404
Section 12 seismic categories, punching, torsion, walls, footings, connections, NZS 4230 masonry,
NZS 3603 timber. Every value is listed with its clause in [VERIFY.md](VERIFY.md).
