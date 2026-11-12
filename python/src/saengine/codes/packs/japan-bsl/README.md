# japan-bsl: Building Standard Law + AIJ standards (Japan)

The Japanese code pack (alpha 9 track C19). It extends `aci318-asce7-22`: what it does not set
is the US pack's (and through it the default pack's), and the report names the code each value
comes from. SI units. Every value is listed in [VERIFY.md](VERIFY.md) with its article,
notification or AIJ clause and how sure it is; no code text was available when it was written.

## What it covers

- **Site** (`locations`, `zoneCoefficients`): the 47 prefectures' capitals with the seismic zone
  factor Z of MOC Notification 1793 Art. 1 (1.0, 0.9, 0.8, 0.7; SAEngine zones 4 to 1, labelled
  "Z = ...") and the standard wind speed V0 of Notification 1454 (30-46 m/s), with their
  coordinates for the site map. The vertical snow depth is the prefecture's rule: enter the
  ground snow load (20 N/m² per cm of depth in ordinary areas, the authority's unit load in
  heavy-snow areas) in Project Settings > Site > Snow.
- **Loads** (Enforcement Order Art. 82-88): the long-term and short-term combinations of
  Art. 82 (`combinations.allowable`, ordinary and heavy-snow rows, the uplift rows with P = 0),
  the floor live loads of Art. 85 for slabs (`live`), frames (`frameLive`, applied to beams and
  columns by the live load method `frameValue` where Analysis > Live load reduction is on) and
  the seismic force (`seismicLive`, the seismic weight by use: `seismic.liveWeight` "byUse"),
  the snow of Art. 86 (μb = √cos(1.5β), 0.35S in W of heavy-snow roofs), the wind of Art. 87 and
  Notification 1454 (q = 0.6 Er² Gf V0², terrain categories I-IV with Zb, ZG, α, Gf by height,
  Cpe 0.8 kz windward and -0.4 leeward).
- **Seismic force** (Art. 88, Notification 1793): the design spectrum method
  `standardShearCoefficient` (C = Z Rt C0, Rt by the soil type 1-3 with Tc 0.4, 0.6, 0.8 s) and
  the lateral force distribution `shearCoefficientAi` (Qi = V Ai αi); T = 0.02 h (concrete),
  0.03 h (steel); C0 = 0.2 for the primary design, 1.0 for the required horizontal capacity;
  R = Cd = 1, no importance factor.
- **Primary design** (allowable stress calculation, `allowableStress`, method `elasticSection`):
  the long-term and short-term allowable stresses of concrete (Fc/3, 2Fc/3, fs), bars SR235,
  SD295-SD490 and steel (F/1.5, F); RC beams and columns by the cracked elastic section (n = 15)
  and the allowable shear b j (α fs + 0.5 wft (pw - 0.002)); steel members by the AIJ fc, fb,
  ft, fs; storey drift 1/200 (`seismic.allowableDrift`); Rs >= 0.6 and Re <= 0.15 (report
  section "Stiffness and eccentricity ratios").
- **Ultimate horizontal capacity** (Art. 82-3, Notification 1792, `horizontalCapacity`):
  Qun = Ds Fes Qud per storey and direction, Ds by material, member rank FA-FD and βu, Fes =
  Fs Fe; Qu of each storey from a pushover (Project Settings > Analysis > Pushover, pattern
  "seismic") at a storey drift of 1/100 (or the largest base shear before it); the report's
  pushover section lists Qu >= Qun per storey. The member ranks (design rows "Member rank ...")
  by h0/D, σ0/Fc, pt, τu/Fc for RC (with the mean shear strength Qsu against the shear at the
  flexural mechanism) and by the width-thickness ratios for steel; the worst rank of the design
  run gives Ds.
- **Bars** D10-D41 (JIS G 3112) by their nominal diameters (names printed in US display units;
  SI prints Ø and the diameter).

## What it does not cover (the parent's or not covered)

The ultimate strength design of members for the bar sizing (the parent's ACI 318-19 with the
pack's SAEngine sizing combinations: long-term × 1.5, short-term × 1.0), AIJ detailing rules, the
column live load reduction by the number of floors (Art. 85(2)), Rt from a special investigation,
topographic Er, cladding and roof wind coefficients (parent's), the snow removal reduction,
foundations (allowable bearing by Notification 1113), timber, the time-history route of tall
buildings, the route 2 checks beyond Rs and Re (column and wall area ratios, the 1.5 × force
rule), the per-storey Ds (one Ds for the building, from its worst member rank) and the D values
with the beams' stiffness (SAEngine takes 12 E I / h³ of each column and the in-plane stiffness
of each wall, the beams rigid).
