# srilanka: values to verify

No copy of the Sri Lankan wind guidance or of a Sri Lankan National Annex was available when this
pack was written (alpha 9, track C21, 2026-11-05). **Sure**, **Check**, **Uncertain** and
**SAEngine practice** as in the other packs' lists. Everything the pack does not set is the
parent's (`eurocodes`, its VERIFY.md).

| # | Path | Value | Source | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| S1 | (zone speeds) | Zone 1 49 m/s, zone 2 43 m/s, zone 3 33 m/s (normal structures); 54, 47, 38 m/s (post-disaster) | Design of Buildings for High Winds - Sri Lanka (1980) | Basic wind speeds, 3-second gusts at 10 m | Check |
| S2 | locations.*.windSpeed | 32.0 (zone 1), 28.1 (zone 2), 21.6 (zone 3) m/s | - | vb,0 = gust / 1.53 | SAEngine practice (the EN 1991-1-4 peak to mean ratio at 10 m in terrain II, √(1 + 7 × 0.19); check against the practice of Sri Lankan designers) |
| S3 | locations (zones of the towns) | Zone 1: Jaffna, Trincomalee, Batticaloa, Mullaitivu; zone 2: Anuradhapura, Polonnaruwa, Vavuniya, Ampara; zone 3: Colombo, Kandy, Galle, Matara, Negombo, Ratnapura, Nuwara Eliya, Kurunegala | 1980 zone map | Wind zone of each town | Uncertain (SAEngine readings from memory) |
| S4 | locations.default | colombo | - | New projects | SAEngine practice |
| S5 | zoneCoefficients, seismic.designCategories | zone 0, agR 0; the first category column | - | No seismic design | SAEngine practice (seismic not covered) |
| S6 | (National Annex) | none: the EN recommended values | - | Nationally determined parameters | Uncertain (check whether a Sri Lankan NA applies) |
