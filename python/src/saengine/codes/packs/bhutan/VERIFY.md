# bhutan: values to verify

No copy of the Bhutan Building Rules or of Bhutan's seismic zoning was available when this pack
was written (alpha 9, track C23, 2026-11-04). Every value was entered from knowledge and is to be
checked by the owner. **Sure**: well-known value, low risk. **Check**: believed right, confirm the
number or the row. **Uncertain**: the value or its reading may be wrong, or it is an SAEngine
form of the rule; SAEngine's choice is stated. Everything the pack does not set is the parent's
(`is-codes`, its VERIFY.md).

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| B1 | locations.*.zone | Thimphu, Paro, Haa, Punakha, Wangdue Phodrang, Phuentsholing, Samtse: 4 (zone IV); Tsirang, Gelephu, Trongsa, Bumthang, Mongar, Trashigang, Samdrup Jongkhar: 5 (zone V) | IS 1893 (Part 1):2016 zoning as applied in Bhutan | Seismic zone | Uncertain (SAEngine reading: Bhutan is commonly placed in zones IV and V, the west in IV next to Sikkim and the Duars, the rest in V next to Assam and Arunachal Pradesh; some practice takes zone V for the whole country. Check the zoning the Department of Engineering Services applies) |
| B2 | locations.*.windSpeed | 47 m/s (west, centre); 50 m/s (Gelephu, Mongar, Trashigang, Samdrup Jongkhar) | IS 875 (Part 3):2015 Figure 1 at the adjoining Indian regions | Basic wind speed Vb | Uncertain (Bhutan is outside the IS map: read at the adjoining regions, 47 m/s on the West Bengal and Sikkim side, 50 m/s on the Assam side) |
| B3 | locations.default | thimphu | - | New projects start in Thimphu | SAEngine practice |
| B4 | zoneCoefficients (inherited) | IV 0.24, V 0.36 | IS 1893 (Part 1):2016 Table 3 | Z | Sure (the IS values) |
