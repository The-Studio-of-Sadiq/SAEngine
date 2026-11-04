# Chile: NCh 433 and NCh 430 (`chile-nch`)

A pack that `extends` the US pack `aci318-asce7-22` and sets the Chilean seismic standard
NCh 433 Of.1996 Mod.2009 with the decree DS 61 (2011), the concrete standard NCh 430:2008 with
the decree DS 60 (2011) and the combinations of NCh 3171. Choose it in **02 Project Settings →
Design code** or in the **New Building** wizard; the wizard then offers the towns below. Any
value can be overridden per project under **Code Values**; switching the pack applies on the
next run. A new project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
standards was available when the pack was written.

## What it sets

| Table | Standard | What |
| --- | --- | --- |
| `zoneCoefficients` | NCh 433 Table 6.2 | A0 = 0.20, 0.30, 0.40 g (zones 1-3) |
| `locations` | NCh 433 Table 4.1 | 14 towns with their zone; wind speed placeholders (35 m/s) |
| `occupancyCategories` | NCh 433 Table 6.1 | I = 0.6, 1.0, 1.2, 1.2 |
| `seismic` | NCh 433, DS 61 | Sa = S A0 α / (R*/I), soil types A-E, R* = 1 + T/(0.10 T0 + T/R0), Cmin = A0 S/6g, Cmax by R, drift 0.002 |
| `combinations` | NCh 3171 | 1.4D, 1.2D + 1.6L, 1.2D + 1.6W + L, 1.2D + 1.4E + L, 0.9D ± 1.6W, 0.9D ± 1.4E |
| `concrete` | NCh 204 | Bars Ø8-Ø36 |
| `detailing` | DS 60 21.9.6.2 | Walls' boundary elements: c ≥ lw / (600 δu/hw), δu/hw ≥ 0.007 |

How the spectrum is built: the generic `shapeFactors` method. The soil type's α(T) is one shape
branch with a divisor ((1 + 4.5 (T/T0)^p) / (1 + (T/T0)^3)), S its soil factor, A0/g and I the
hazard, R0 the system's R and the reduction R* by the `periodRatio` form. R* is taken at the
period of each ordinate (NCh 433 takes it at T* of the main mode: at the fundamental period the
two agree, the higher modes get a smaller R*, on the safe side). Every ordinate is held between
Cmin = A0 S / 6g × I and Cmax S A0 / g × I. The equivalent static method takes the same spectrum
at the building's period: NCh 433's own static coefficient 2.75 S A0 (T'/T*)^n / (g R) is not
built (the two are close for the usual periods: VERIFY.md C14). The drift is checked at 0.002 h
under the design forces (no amplification).

Concrete: NCh 430 is ACI 318-08 with Chilean changes; the pack keeps the base pack's ACI 318-19
rules and sets the DS 60 boundary element trigger of walls. DS 60's compressive strain limit
(0.008), its least wall thickness and confinement rules are not set.

Not set by this version: the static coefficient of NCh 433 6.2.3 and its Ak distribution, the
wall-building form of R* (Eq 6-11b), the drift at any point (CM drift + 0.001 h), NCh 1537 live
loads (the base pack's ASCE 7-22 values), NCh 432 wind (the towns' speeds are placeholders), NCh
427 steel (the base pack's AISC 360-22), soil type F.
