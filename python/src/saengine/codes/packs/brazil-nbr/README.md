# Brazil: ABNT NBR standards (`brazil-nbr`)

A pack that `extends` the US pack `aci318-asce7-22` and sets the Brazilian standards: NBR 15421
(seismic), NBR 6123 (wind), NBR 8681 (combinations) and NBR 6118 (concrete). Choose it in
**02 Project Settings → Design code** or in the **New Building** wizard; the wizard then offers
the towns below. Any value can be overridden per project under **Code Values**; switching the
pack applies on the next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standards was available when the pack was written. The towns' ag and V0 must be checked before
design.

## What it sets

| Table | Standard | What |
| --- | --- | --- |
| `locations` | NBR 15421 Fig 1, NBR 6123 Fig 1 | 14 towns with ag (as SS = 2.5 ag, S1 = ag) and V0 |
| `seismic` | NBR 15421 | Classes A-F, Ca and Cv, SDS = 2.5 Ca ag, SD1 = Cv ag, Cs ≥ 0.01, Cup, categories |
| `occupancyCategories` | NBR 15421 Table 3, NBR 6123 Table 3 | I = 1.0, 1.25, 1.5; S3 = 0.95, 1.00, 1.10 |
| `wind` | NBR 6123 | Vk = V0 S1 S2 S3, S2 = b Fr (z/10)^p (terrain I-V, class B), q = 0.613 Vk² (generic `speedFactors` method) |
| `combinations` | NBR 8681 | 1.4G + 1.4Q, wind with ψ0, the exceptional seismic combination |
| `concrete` | NBR 7480, NBR 6118 8.2.8 | Bars Ø5-Ø40 (Ø6,3 and Ø12,5 included), Ecs |
| `concreteMethods` | NBR 6118 | γc 1.4, γs 1.15, 0.85 fcd over 0.8 x, x/d ≤ 0.45; shear model I |

How the seismic hazard is found: the town's ag is entered as SS = 2.5 ag and S1 = ag with the
site coefficients Fa = Ca and Fv = Cv and no 2/3, so the base pack's two-period spectrum is NBR
15421's (2.5 ags0 to 0.4 Cv/Ca, ags1/T beyond; T0 = 0.2 TS is NBR's 0.08 Cv/Ca). R, Ω0, Cd and
the drift limits are the base pack's ASCE 7 numbers, which NBR 15421 shares. Zones 0 and 1
(category A) are analysed as category B (NBR 15421 asks only for 0.01 W at each level there:
SAEngine's analysis is on the safe side).

Concrete: the generic `partialFactors` ultimate method and `tabulatedStress` shear (model I,
θ = 45°); the other concrete areas take the base pack's ACI 318-19 methods. Model II, NBR 6118's
torsion, punching, second order, cover, anchorage, deflection and cracking are not set.

Not set by this version: NBR 6120 live loads (the base pack's ASCE 7-22 values), NBR 6123's
classes A and C, its force coefficients Ca, the dynamic response (Ch 9), cladding; NBR 8800
steel (the base pack's AISC 360-22: γa1 1.10 against 1/φ = 1.11).
