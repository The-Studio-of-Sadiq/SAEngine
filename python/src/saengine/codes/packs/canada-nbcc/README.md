# NBCC 2020 + CSA A23.3-19 + CSA S16-19 (`canada-nbcc`)

A built-in pack for Canada (alpha 9 track C17). It `extends` the US pack `aci318-asce7-22` and
sets what the National Building Code of Canada 2020 (Part 4), CSA A23.3-19 (concrete) and CSA
S16-19 (steel) change; every other table is the US pack's (see its README) and the report names
those ACI 318-19, AISC 360-22, NDS 2018 or ASCE 7-22. Choose it in **02 Project Settings →
Design code** or in the **New Building** wizard; its towns are in **Site → Location** and on the
site map. Any value can be overridden per project under **Code Values**; switching the pack
applies on the next run. New projects start in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md). No copy of the
codes was available when the pack was written: the values are to be checked against the printed
editions before the pack is used for design.

## What it sets

| Table | What | Clause |
| --- | --- | --- |
| `locations` | 9 towns: Ss, Sr, q1/50 (as the speed of the same velocity pressure); Sa(T) of site class C for Vancouver, Toronto, Ottawa and Montréal; coordinates for the site map | Appendix C |
| `occupancyCategories` | Low, Normal, High, Post-disaster (ids I-IV) with IE 0.8 / 1.0 / 1.3 / 1.5 and IW 0.8 / 1.0 / 1.15 / 1.25 | Tables 4.1.2.1, 4.1.8.5, 4.1.7.3 |
| `areaLoads` | The live loads of the common uses (offices 2.4, residential 1.9, corridors and assembly 4.8 kPa ...), partitions at least 1.0 kPa | Table 4.1.5.3, 4.1.4.1 |
| `combinations` | 1.4D; 1.25D + 1.5L + (1.0S or 0.4W); 1.25D + 1.5S + (1.0L or 0.4W); 1.25D + 1.4W + (0.5L or 0.5S); 0.9D + 1.4W; 1.0D + 1.0E + 0.5L + 0.25S; SLS | Table 4.1.3.2-A |
| `seismic` | The uniform hazard spectrum S(T) (S(0.2) = max(Sa(0.2), Sa(0.5))); V = S(Ta) Mv IE W / (Rd Ro) with the S(2.0) / S(4.0) lower bound and the max(2/3 S(0.2), S(0.5)) upper bound for Rd >= 1.5; Ft = 0.07 Ta V; Ta; Rd, Ro and height limits of the systems; ± 0.10 Dn; drift limits; irregularity types | 4.1.8.4, 4.1.8.9, 4.1.8.11, 4.1.8.13, Table 4.1.8.6 |
| `wind` | p = Iw q Ce Cg Cp: Ce of open and rough terrain, Cg 2.0, Cp by H/D | 4.1.7.3 |
| `snow` | S = Is [Ss (Cb Cw Cs Ca) + Sr]: Cb 0.8, Cw, Cs by slope, the town's Sr, Is | 4.1.6.2 |
| `concreteMethods` | φc 0.65, φs 0.85; α1, β1, εcu 0.0035, Ec, Pr,max, c/d; beam shear by the simplified method (β, θ) with the general method's β and θ | CSA A23.3-19 8.4, 10.1, 10.5, 10.10, 11.2-11.3 |
| `concrete`, `materials` | Bars 10M-55M; shrinkage steel 0.002; εcu | CSA G30.18; CSA A23.3-19 7.8, 10.1.3 |
| `steel`, `designClauses` | The column curve with n = 1.34; lateral-torsional buckling by Mu and ω2; LSD only | CSA S16-19 13.3.1, 13.6 |

## The seismic hazard

NBCC 2020 gives the hazard as the site's 5 % damped spectrum Sa(T) for its site designation (the
NRCan 2020 seismic hazard calculator). The pack reads it with the generic `mappedSpectral` option
`seismic.designSpectrum.ordinates` (alpha 9 C17): enter the site's Sa(0.2), Sa(0.5), Sa(1.0),
Sa(2.0), Sa(5.0), Sa(10.0) under **Site → Mapped spectral values → design spectrum**; a town
with values (site class C only) fills them where the project gives none, and a site of another
class is told to enter its own. The base shear's terms (S(Ta), Mv, the bounds) are in the
derivation notes and the summary.

## Not covered (the parent's method or none, named in the report)

- The higher mode factor Mv and the overturning factor J (Table 4.1.8.11): no values entered, Mv
  = 1 and J = 1 (J on the safe side; Mv = 1 is not, for walls with long periods: enter the table
  under Code Values `seismic.designSpectrum.ordinates.higherMode`).
- The Sa(T) of the other towns and site classes (enter them from the hazard calculator).
- CSA A23.3 shear of columns and walls, torsion, punching, slenderness and Clause 21 detailing
  values: the parent's ACI 318-19 methods and values (ductile ↔ special, moderately ductile ↔
  intermediate).
- CSA S16 connections, bolts and welds and Clause 27 seismic design: the parent's AISC 360-22 /
  AISC 341-22.
- CSA O86 timber: the timber engine's methods do not fit O86's form in this version; the parent's
  NDS 2018 applies.
- The live load reduction of 4.1.5.8 (the parent's ASCE 7-22 Sec 4.7), snow drifts and sliding
  (Ca), the wind's dynamic procedure and topography, the NBCC sway (P-delta) amplification (an
  SAEngine form of θ is used).
- The bar names 10M-55M are shown in US customary display units only (SI shows Ø and the
  diameter); the bar schedule is the parent's ACI 315 form.
