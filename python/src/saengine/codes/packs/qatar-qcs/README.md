# Qatar, QCS 2014 (`qatar-qcs`)

A thin built-in pack (alpha 9 track C23). The Qatar Construction Specifications 2014 refer the
structural design to the British Standards (BS 8110 concrete, BS 6399 loads, BS 5950 steel), so
the pack `extends` the legacy pack `bs8110` and sets Qatar's towns, a coastal default terrain and
the 'severe' exposure of new concrete members. Everything else is the parent's (see its README).
Projects that follow the Eurocodes in Qatar choose `eurocodes` instead and enter vb,0. Choose the
pack in **02 Project Settings → Design code** or in the **New Building** wizard; the towns are in
**Site → Location**. Any value can be overridden per project under **Code Values**.

Every value, with how sure it is, is in [`VERIFY.md`](VERIFY.md): the basic wind speed (Q1) is
one SAEngine practice value for the whole peninsula, to be replaced with the value the project's
authority gives.

Why `bs8110` and not `eurocodes`: QCS 2014's structural references are the British Standards,
and its wind loading follows BS 6399-2 (the parent's standard method with the distance from the
sea), which the parent already covers.

## What it sets

| Table | What | Code |
| --- | --- | --- |
| `locations` | 8 towns with Vb = 25 m/s (hourly mean, BS 6399-2), zone 0 | QCS 2014 / BS 6399-2 |
| `wind` | New projects start as a town site 2 km from the sea | SAEngine practice |
| `concreteMethods` | New members start in the 'severe' exposure (BS 8110-1 Table 3.3) | SAEngine practice |

## Temperature

The Gulf's temperature range is large (shade air from about 5 °C in winter to about 50 °C in
summer). It is not a pack value: switch on **Project Settings → Temperature** and enter the
uniform change from the construction temperature (SAEngine suggestion: about 25 °C, the larger of
the rise and the fall) and the roof gradient.

## Not covered

Earthquake (QCS 2014 and the British Standards give no seismic loading: zone 0, no earthquake
cases; where the authority asks for one, enter Z, which uses BNBC 2020's spectrum and is named
so), QCS's own durability rules (covers, cement types, the classes below ground), the UAE and the
other Gulf states (Dubai practice follows the US codes with its own authority's values; no
separate pack in this version).
