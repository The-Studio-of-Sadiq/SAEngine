# Turkey (`turkey-tbdy`)

A pack for the Turkish codes: it `extends` the US pack `aci318-asce7-22` (ASCE 7-22, ACI 318-19,
AISC 360-22, AISC 341-22) and sets what TBDY 2018, TS 500 and TS 498 change. Choose it in
**02 Project Settings → Design code** or in the **New Building** wizard. Any value can be
overridden per project under **Code Values**; switching the pack applies on the next run. A new
project starts in SI units.

Every value, with its clause and how sure it is, is in [`VERIFY.md`](VERIFY.md): no copy of the
codes was available when the pack was written. The cities' SS and S1 are example readings only:
TBDY's hazard is site-specific (the AFAD map by coordinates), so enter the site's values under
**Site → Mapped spectral values**.

## What it sets

| Table | Code | What |
| --- | --- | --- |
| `locations` | TBDY 2018 2.2 | 10 cities with DD-2 SS, S1 (examples), TL = 6 s; a placeholder wind speed |
| `occupancyCategories` | TBDY Tablo 3.1 | BKS 1 (I 1.5), BKS 2 (1.2), BKS 3 (1.0) in the slots IV, III, I-II |
| `seismic` | TBDY Bolum 2-4, 13 | ZA-ZF, FS / F1, the spectrum, DTS, R and D, Ra(T), ELF, drift, BYS, performance-based design |
| `combinations` | TS 500 6.2.6, TBDY 4.4.4 | 1.4G + 1.6Q, G + 1.3Q + 1.3W, 0.9G + 1.3W, G + Q + 0.2S + E, 0.9G + E |
| `concreteMethods` | TS 500, TBDY Bolum 7 | γmc 1.5, γms 1.15, k1, Vcr / Vc, punching, minimum steel, ductile detailing |
| `concrete` | TS 708, TS 500 3.3 | Bars Ø8-Ø32, Ec for the analysis |
| `pushover` | TBDY 3.4 | Hazard levels DD-2 (controlled damage) and DD-1 (collapse prevention) |

## How the seismic design runs

1. SDS = SS FS and SD1 = S1 F1 of the site class (Tablo 2.1, 2.2), from the town or the values
   the project enters. TA = 0.2 SD1/SDS, TB = SD1/SDS, TL = 6 s.
2. The design earthquake category DTS by SDS (Tablo 3.2): DTS 1 and 2 are SAEngine's category D
   (high ductility required), DTS 3 is C and DTS 4 is B (limited ductility permitted).
3. SaR(T) = Sae(T) / Ra(T) with Ra = D + (R/I − D) T/TB below TB and R/I above (Denk. 4.1), D
   the system's overstrength (held in Omega0), for the response spectrum and the equivalent
   lateral load (Vt ≥ 0.04 I SDS W; ΔFN = 0.0075 N Vt at the top).
4. Drift: δ = (R/I) Δ, λ δ/h ≤ 0.008 κ (infill fixed to the frame) or 0.016 κ (separated,
   Project Settings → drift-tolerant finishes), κ = 1 concrete, 0.5 steel. λ = 1.0 until the
   project enters the site's DD-3/DD-2 ratio (`seismic.driftServiceRatio.value`).
5. The building height class BYS by HN and DTS (Tablo 3.3). A BYS 1 (tall) building needs a
   performance-based design (TBDY 3.4, Bolum 13): the analysis notes say so and name the
   procedures, DD-4 continuous use by an elastic analysis, DD-2 controlled damage by the
   strength design, DD-1 collapse prevention by the **Nonlinear time history** analysis (11
   record pairs; target × 1.5 until the site's DD-1 values are entered). The **Pushover**
   analysis checks DD-2 and DD-1 with the base pack's ASCE 41 hinges.

## Not covered

TS 498 live loads and wind (the base pack's ASCE 7-22 live loads and wind method apply; the
towns' wind speed is a placeholder to replace), the BKS 1 performance evaluation of TBDY Tablo
3.4a outside BYS 1 (the DTS 1a/2a categories share SAEngine's slot D), TBDY Bolum 5 strain limits,
the second order limit θ ≤ 0.12 D/R (the generic default applies), the TBDY limited-ductility
detailing (Bolum 7 rules apply to high ductility frames; limited ductility frames take the base
pack's ACI intermediate rules), TS 500 torsion, deflection, cracking, cover, anchorage, slabs and
footings (ACI 318-19 of the base pack), and the Turkish steel regulation's own values (AISC
360-22 applies). The report names the base pack's codes for these.
