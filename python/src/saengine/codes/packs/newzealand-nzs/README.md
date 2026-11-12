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

## Alpha 9 C18b (version 0.2)

- `designClauses`: the NZS 3101 clauses of the checks whose method has the NZS form (torsion
  7.6, punching 12.7, deflection, column shear, fire, the NZS 1170.5 accidental eccentricity);
  the Australian pack's AS 3600 clauses are not inherited.
- Inherited from the Australian pack (AS/NZS 1170.2:2021, a joint standard): the hill-shape
  multiplier Mh and the dynamic response factor Cdyn. The AS 1170.4 design category by height is
  removed (NZS 1170.5 has none).

## Alpha 9 C18c (version 0.3)

- `concreteMethods.seismic` method `ductileDetailing` with `basis: "capacityFactor"` and
  `levels` (NZS 3101 Chapters 9, 10, 11, 15, Appendix D): ductile (special) and limited ductile
  (intermediate) frames; plastic hinge regions on D and by N*/(φ f'c Ag), the confinement by
  the axial load (10.4.7), the Appendix D capacity design (Mo = λo Mn, the strong column ratio
  ω λo/φ, the columns' capacity shear), joints by vjh <= min(0.2 f'c, 10 MPa) with the
  horizontal joint hoops (15.4), the ductile walls' design shear φo,w ωv V*E and confined ends
  (11.4), diagonally reinforced coupling beams.
- Walls: `concrete.walls` 0.7/fy each way, min(3 t, 450 mm) (11.3.11; the Australian values are
  not inherited).
- `steelLimitState.seismic` method `prescriptiveFrames` (NZS 3404 Section 12): categories 1 and
  3 (compact yielding members, the connections for φoms Mp, category 1 columns ΣMpc >= φoms
  ΣMpb); the connections of the Australian pack (Chapter 9, the AS 4100 rules).
- `designClauses`: the walls' rows, the slenderness and the detailing chapter are NZS 3101's.

## Not covered (from the parent packs, named so)

Slender columns, torsion, punching and column shear run the parent's methods, of the same form
as NZS 3101 10.4, 7.6, 12.7 and 10.3.10 (their constants to verify); the AS 3600 anchorage and
strut-and-tie are not inherited (concreteMethods replaced: the parent's ACI-type development
lengths and strut-and-tie apply); footings, NZS 4230 masonry and NZS 3603 timber (none fits
SAEngine's masonry or timber engines in this version). Every value is listed with its clause in
[VERIFY.md](VERIFY.md).
