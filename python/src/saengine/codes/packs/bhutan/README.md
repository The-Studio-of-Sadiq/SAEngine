# Bhutan (`bhutan`)

A thin built-in pack (alpha 9 track C23). Bhutan designs to the Indian Standards, so the pack
`extends` the built-in pack `is-codes` (IS 875 loads, IS 1893 (Part 1):2016 seismic, IS 456 and
IS 13920 concrete, IS 800 steel, IS 1905 masonry and the rest; see its README) and sets only
Bhutan's towns. Choose it in **02 Project Settings → Design code** or in the **New Building**
wizard; the towns are in **Site → Location**. Any value can be overridden per project under
**Code Values**.

Every value, with how sure it is, is in [`VERIFY.md`](VERIFY.md): the zone and the basic wind
speed of every town are SAEngine readings and must be checked against the zoning Bhutan's
Department of Engineering Services applies before design.

## What it sets

| Table | What | Code |
| --- | --- | --- |
| `locations` | 14 towns: IS seismic zone IV (west) or V (centre, east, south-east), Z 0.24 / 0.36 of IS 1893 Table 3; Vb 47 or 50 m/s | IS 1893 (Part 1):2016 zoning as applied in Bhutan; IS 875 (Part 3):2015 Figure 1 |

Mountain sites: enter the topography in **Project Settings → Wind → Topography** for k3 (IS 875
(Part 3) Annex C, the parent's rule) and choose the terrain category of the site.

## Not covered

Bhutan's own building rules beyond the structural codes (the traditional architecture
requirements, the timber and rammed earth construction of the Bhutanese guidelines), a seismic
microzonation of Thimphu, and towns not listed (custom location: enter Z and Vb).
