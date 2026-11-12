# Sri Lanka (`srilanka`)

A thin pack for Sri Lankan practice: it `extends` the built-in pack `eurocodes` (EN 1990, EN 1991,
EN 1992-1-1, EN 1993 and the rest with the recommended values) and sets the Sri Lankan wind
zones for 16 towns. Choose it in **02 Project Settings → Design code** or in the **New Building**
wizard. Any value can be overridden per project under **Code Values**.

Every value, with its source and how sure it is, is in [`VERIFY.md`](VERIFY.md).

## What it sets

| Table | Source | What |
| --- | --- | --- |
| `locations` | Design of Buildings for High Winds - Sri Lanka (1980) | Towns in zones 1-3; vb,0 = 32.0, 28.1, 21.6 m/s (49, 43, 33 m/s gusts / 1.53) |
| `zoneCoefficients`, `seismic` | - | No seismic design (zone 0) |

Post-disaster structures take the higher zone speeds (54, 47, 38 m/s gusts): enter vb,0 =
speed / 1.53 as the project's wind speed.

## Not covered

A Sri Lankan National Annex (none is reliably known to SAEngine: the recommended values apply),
seismic design (no seismic code reliably known: a project may enter agR as Z and the parent's EN
1998-1 spectrum applies, named EN 1998-1 in the report). The legacy practice with BS 8110 and CP 3
is the built-in pack `bs8110` with a custom location (its wind method is BS 6399-2).
