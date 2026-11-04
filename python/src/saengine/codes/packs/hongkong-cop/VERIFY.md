# hongkong-cop: values to verify against the printed Hong Kong codes

No copy of the Hong Kong Codes of Practice was available when this pack was written (alpha 9,
track C23, 2026-11-04). Every value was entered from knowledge of the codes and is to be checked
by the owner against the printed editions. **Sure**: well-known value, low risk. **Check**:
believed right, confirm the number or the row. **Uncertain**: the value or its reading may be
wrong, or it is an SAEngine form of the rule; SAEngine's choice is stated. Everything the pack
does not set is the parent's (`bs8110`, its VERIFY.md).

## Code of Practice on Wind Effects in Hong Kong 2019

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| H1 | wind.speedFactors.referencePressures.hongKong | ≤2.5 m 1.82, 5 m 2.01, 10 m 2.23, 20 m 2.46, 30 m 2.60, 50 m 2.79, 75 m 2.94, 100 m 3.06, 150 m 3.25, 200 m 3.39, 250 m 3.50, 300 m 3.60, 400 m 3.75, 500 m 3.88 kPa | Section 3, table of reference design wind pressures | q(z), linear between, constant beyond | Uncertain (the 2004 edition's Table 1 design pressures as remembered; the 2019 edition's reference pressures may differ: replace them) |
| H2 | wind.topographic | 1.0 (the project enters Sq) | Section 3 / Appendix (topography factor Sq) | Sq on the pressure | Check (that Sq multiplies the pressure) |
| H3 | wind.directionality | 1.0 | 2019 directional factor Sθ | Sθ, every direction | SAEngine practice (the largest) |
| H4 | wind.speedFactors.areaAveraging | 1.0 | Size and dynamic factor | Rigid buildings | SAEngine practice (the dynamic response is not covered) |
| H5 | wind.speedFactors.combination | 1.0 | - | No lack-of-correlation reduction | Uncertain (SAEngine reading) |
| H6 | wind.cpWindward / cpLeeward (inherited) | +0.85 / -0.5 | Force coefficients of buildings | Net 1.35 on the face | Uncertain (the parent's BS 6399 wall coefficients stand in for the HK force coefficient Cf of the building: check Cf by h/b and d/b) |
| H7 | locations.*.windSpeed | 60.3 m/s | - | √(q(10 m)/0.613), shown only; the pressures do not use it | SAEngine practice |

## Code of Practice for Structural Use of Concrete 2013

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| H8 | concreteMethods.ultimate.gammaS | 1.15 | Table 2.2 | γm of reinforcement | Sure |
| H9 | concreteMethods.ultimate.relations.lambda.steps | 0.9 (≤ C45), 0.8 (≤ C70), 0.72 (≤ C100) | 6.1.2.4, Figure 6.1 | Depth of the rectangular block / x | Check |
| H10 | concreteMethods.ultimate.neutralAxisSteps | 0.5 (≤ C45), 0.4 (≤ C70), 0.33 (≤ C100) | 6.1.2.4(c) | x/d limit without redistribution (K' 0.156 / 0.120 / 0.094) | Check |
| H11 | concreteMethods.ultimate.relations.epsCu2 / epsCu3.steps | 3.5 ‰ to C60; 3.31, 3.23, 3.17, 3.12 ‰ at C70, C80, C90, C100 | 3.1.7, Figure 3.8 (εcu = 0.0035 - 0.00006 √(fcu - 60)) | εcu, as steps at each band's top | Check (the formula); the steps are SAEngine form, on the safe side |
| H12 | concreteMethods.ultimate.relations.ecm* | Ec = 3.46 √fcu + 3.21 kN/mm² | Table 3.2 (3.1.5) | Short-term modulus | Check |
| H13 | concrete.modulus.normal | 4050 √fcu | Table 3.2 | Ec of the analysis model | SAEngine form (within 3 % C25-C45) |
| H14 | concreteMethods.shear.grades, tauC | fcu up to 80 by (fcu/25)^1/3; columns 50-80 computed | Table 6.3 | vc | Check (the fcu limit of 80) |
| H15 | concreteMethods.shear.maxStress | 0.8 √fcu, at most 7.0 N/mm² | 6.1.2.5(a) | vmax | Check |
| H16 | concreteMethods.ultimate.strengthClasses | C25-C80 | 3.1.3 | Grades listed | SAEngine practice |
| H17 | concreteMethods (inherited) | shear γm 1.25 in vc, depth factor (400/d)^1/4 >= 1, links fyv <= 460, cover, laps, deflection | BS 8110 values | Not set | Uncertain (check the HK values: fyv of grade 500 bars, the HK cover table) |

## Code of Practice for Dead and Imposed Loads 2011

| # | Path | Value | Clause | What | Confidence |
| --- | --- | --- | --- | --- | --- |
| H18 | areaLoads.uses.residential | 2.0 kPa | Table 3.2 | Domestic uses | Check |
| H19 | areaLoads.uses.office | 3.0 kPa | Table 3.2 | Offices for general use | Check |
| H20 | areaLoads.uses.roof | 0.75 kPa | Table 3.2 | Roofs not accessible to the public | Check |
| H21 | areaLoads (the other rows) | BS 6399-1 | - | Not set | Uncertain (check every row used) |

## Not covered

| # | Path | Value | What | Confidence |
| --- | --- | --- | --- | --- |
| H22 | zoneCoefficients (inherited) | zone 0, Z = 0 | No earthquake cases | Not covered |
| H23 | steelLimitState (inherited) | BS 5950-1:2000 | HK CoP Steel 2011 values not set | Uncertain (check py, the buckling curves and the steel grades of the HK code) |
