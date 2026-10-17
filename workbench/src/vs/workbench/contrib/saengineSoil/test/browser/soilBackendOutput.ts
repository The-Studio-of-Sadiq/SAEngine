/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Real output of the backend's `saengine.soil.report.soil_report()` for the first two boreholes
 * of a Dhaka-like test report (soft silty clay over loose to medium dense silty fine sand, water
 * table 1.5 m) with the sample project's settings (zone 0.28, site class SD), trimmed to keep the
 * file small: per borehole the first 8 SPT records and liquefaction points, four bearing cells,
 * and no `layers`, `settlement` or `bearing.rows`. It pins the field names the editor reads.
 */

export const SOIL_BACKEND_OUTPUT: unknown = JSON.parse(`{
	"boreholes": [
		{
			"id": "BH-1",
			"x": 0.0,
			"y": 0.0,
			"groundLevel": 0.0,
			"waterTable": 1500.0,
			"depth": 30000,
			"siteClass": {
				"class": "SD",
				"N": 6.5,
				"su": 22.0,
				"byN": "SD",
				"bySu": "SD",
				"depth": 30000,
				"extrapolated": false,
				"note": "N̄ = 6.5 → SD; s̄u = 22 kPa over 4.5 m of cohesive soil → SD (BNBC 2020 Table 6.2.13, harmonic means over the top 30 m).",
				"notes": []
			},
			"profile": [
				{
					"depth": 1500,
					"N": 2,
					"energyRatio": 55.0,
					"CR": 0.75,
					"N60": 1.4,
					"sigma_v": 25.5,
					"u": 0.0,
					"sigma_v_eff": 25.5,
					"CN": 1.7,
					"N160": 2.3,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 3000,
					"N": 2,
					"energyRatio": 55.0,
					"CR": 0.8,
					"N60": 1.5,
					"sigma_v": 52.2,
					"u": 14.7,
					"sigma_v_eff": 37.5,
					"CN": 1.644,
					"N160": 2.4,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 4500,
					"N": 4,
					"energyRatio": 55.0,
					"CR": 0.85,
					"N60": 3.1,
					"sigma_v": 78.9,
					"u": 29.4,
					"sigma_v_eff": 49.5,
					"CN": 1.431,
					"N160": 4.5,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 6000,
					"N": 2,
					"energyRatio": 55.0,
					"CR": 0.95,
					"N60": 1.7,
					"sigma_v": 105.6,
					"u": 44.1,
					"sigma_v_eff": 61.5,
					"CN": 1.284,
					"N160": 2.2,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 7500,
					"N": 6,
					"energyRatio": 55.0,
					"CR": 0.95,
					"N60": 5.2,
					"sigma_v": 133.4,
					"u": 58.9,
					"sigma_v_eff": 74.5,
					"CN": 1.166,
					"N160": 6.1,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 9000,
					"N": 7,
					"energyRatio": 55.0,
					"CR": 0.95,
					"N60": 6.1,
					"sigma_v": 161.1,
					"u": 73.6,
					"sigma_v_eff": 87.5,
					"CN": 1.076,
					"N160": 6.6,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 10500,
					"N": 7,
					"energyRatio": 55.0,
					"CR": 1.0,
					"N60": 6.4,
					"sigma_v": 188.9,
					"u": 88.3,
					"sigma_v_eff": 100.6,
					"CN": 1.004,
					"N160": 6.4,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 12000,
					"N": 12,
					"energyRatio": 55.0,
					"CR": 1.0,
					"N60": 11.0,
					"sigma_v": 216.9,
					"u": 103.0,
					"sigma_v_eff": 113.8,
					"CN": 0.943,
					"N160": 10.4,
					"soilType": "sand",
					"layer": 3
				}
			],
			"liquefaction": {
				"amax": 0.37800000000000006,
				"magnitude": 7.5,
				"points": [
					{
						"depth": 1500,
						"N60": 1.4,
						"screened": false,
						"reason": "clay: not susceptible (clay-like)",
						"liquefiable": false
					},
					{
						"depth": 3000,
						"N60": 1.5,
						"screened": false,
						"reason": "clay: not susceptible (clay-like)",
						"liquefiable": false
					},
					{
						"depth": 4500,
						"N60": 3.1,
						"screened": false,
						"reason": "clay: not susceptible (clay-like)",
						"liquefiable": false
					},
					{
						"depth": 6000,
						"N60": 1.7,
						"screened": true,
						"sigma_v": 105.6,
						"sigma_v_eff": 61.5,
						"finesContent": 46.0,
						"rd": 0.949,
						"csr": 0.401,
						"N160cs": 7.9,
						"MSF": 1.0,
						"Ksigma": 1.043,
						"crr": 0.109,
						"fs": 0.27,
						"liquefiable": true
					},
					{
						"depth": 7500,
						"N60": 5.2,
						"screened": true,
						"sigma_v": 133.4,
						"sigma_v_eff": 74.5,
						"finesContent": 46.0,
						"rd": 0.93,
						"csr": 0.409,
						"N160cs": 11.7,
						"MSF": 1.0,
						"Ksigma": 1.03,
						"crr": 0.134,
						"fs": 0.33,
						"liquefiable": true
					},
					{
						"depth": 9000,
						"N60": 6.1,
						"screened": true,
						"sigma_v": 161.1,
						"sigma_v_eff": 87.5,
						"finesContent": 46.0,
						"rd": 0.91,
						"csr": 0.412,
						"N160cs": 12.2,
						"MSF": 1.0,
						"Ksigma": 1.015,
						"crr": 0.136,
						"fs": 0.33,
						"liquefiable": true
					},
					{
						"depth": 10500,
						"N60": 6.4,
						"screened": true,
						"sigma_v": 188.9,
						"sigma_v_eff": 100.6,
						"finesContent": 46.0,
						"rd": 0.889,
						"csr": 0.41,
						"N160cs": 12.1,
						"MSF": 1.0,
						"Ksigma": 1.001,
						"crr": 0.133,
						"fs": 0.32,
						"liquefiable": true
					},
					{
						"depth": 12000,
						"N60": 11.0,
						"screened": true,
						"sigma_v": 216.9,
						"sigma_v_eff": 113.8,
						"finesContent": 17.0,
						"rd": 0.867,
						"csr": 0.406,
						"N160cs": 14.2,
						"MSF": 1.0,
						"Ksigma": 0.987,
						"crr": 0.148,
						"fs": 0.36,
						"liquefiable": true
					}
				],
				"layers": [
					{
						"layer": 2,
						"top": 6000,
						"bottom": 11500,
						"soilType": "silt"
					},
					{
						"layer": 3,
						"top": 11500,
						"bottom": 21000,
						"soilType": "sand"
					}
				],
				"lpi": 31.59,
				"category": "very high",
				"note": "2 liquefiable layer(s); LPI = 31.6 (very high risk, Iwasaki 1982). amax = Z·S = 0.28 × 1.35 = 0.378 g (BNBC 2020 Tables 6.2.14 and 6.2.16, site class SD; the maximum considered earthquake, as ASCE 7-16 11.8.3).",
				"notes": [
					"amax = Z·S = 0.28 × 1.35 = 0.378 g (BNBC 2020 Tables 6.2.14 and 6.2.16, site class SD; the maximum considered earthquake, as ASCE 7-16 11.8.3)"
				]
			},
			"bearing": {
				"table": [
					{
						"B": 1000,
						"Df": 1000,
						"qa_shear": null,
						"qa_settlement": 35.0,
						"qa": null,
						"governs": null
					},
					{
						"B": 2000,
						"Df": 1000,
						"qa_shear": null,
						"qa_settlement": 25.5,
						"qa": null,
						"governs": null
					},
					{
						"B": 1000,
						"Df": 1500,
						"qa_shear": 62.7,
						"qa_settlement": 39.8,
						"qa": 39.8,
						"governs": "settlement"
					},
					{
						"B": 2000,
						"Df": 1500,
						"qa_shear": 58.5,
						"qa_settlement": 26.2,
						"qa": 26.2,
						"governs": "settlement"
					}
				],
				"method": "qa = min(shear, settlement). Shear: general bearing capacity",
				"factorOfSafety": 3.0,
				"allowableSettlement": 25.0,
				"notes": [
					"layer 1 (fill): no strength (cu or φ', or SPT to estimate them): it lies within B below the base, so there is no qa"
				]
			},
			"ks": 1049,
			"ksDetail": {
				"value": 1049,
				"B": 2000,
				"Df": 1500,
				"q": 26.2,
				"settlement": 25.0,
				"bowles": 3144,
				"method": "ks = qa/s(qa), the secant value for the subgrade footing",
				"note": "Square footing 2 m wide at 1.5 m: ks falls with the loaded width (about B_ref/B in clay); a raft is better designed from the settlement of the whole raft. Bowles' 40·FS·qa is shown for comparison."
			},
			"pile": [
				{
					"layer": 0,
					"top": 0,
					"bottom": 1500,
					"soilType": "fill",
					"sigma_v_eff": 12.8,
					"fs": null,
					"qb": null,
					"method": null,
					"note": "no SPT in the layer; fill: normally ignored for capacity; check downdrag"
				},
				{
					"layer": 1,
					"top": 1500,
					"bottom": 6000,
					"soilType": "clay",
					"sigma_v_eff": 43.5,
					"fs": 12.1,
					"qb": 143.0,
					"alpha": 0.55,
					"method": "α method, O'Neill & Reese 1999",
					"note": null
				},
				{
					"layer": 2,
					"top": 6000,
					"bottom": 11500,
					"soilType": "silt",
					"sigma_v_eff": 85.4,
					"fs": 21.5,
					"qb": 280.0,
					"beta": 0.252,
					"method": "β method, O'Neill & Reese 1999",
					"note": null
				},
				{
					"layer": 3,
					"top": 11500,
					"bottom": 21000,
					"soilType": "sand",
					"sigma_v_eff": 152.9,
					"fs": 72.6,
					"qb": 799.4,
					"beta": 0.475,
					"method": "β method, O'Neill & Reese 1999",
					"note": null
				},
				{
					"layer": 4,
					"top": 21000,
					"bottom": 30000,
					"soilType": "sand",
					"sigma_v_eff": 240.2,
					"fs": 63.1,
					"qb": 1807.1,
					"beta": 0.263,
					"method": "β method, O'Neill & Reese 1999",
					"note": null
				}
			],
			"pileType": "bored",
			"notes": []
		},
		{
			"id": "BH-2",
			"x": 18000.0,
			"y": 4000.0,
			"groundLevel": -150.0,
			"waterTable": 1800.0,
			"depth": 30000,
			"siteClass": {
				"class": "SD",
				"N": 6.7,
				"su": 22.0,
				"byN": "SD",
				"bySu": "SD",
				"depth": 30000,
				"extrapolated": false,
				"note": "N̄ = 6.7 → SD; s̄u = 22 kPa over 5.3 m of cohesive soil → SD (BNBC 2020 Table 6.2.13, harmonic means over the top 30 m).",
				"notes": []
			},
			"profile": [
				{
					"depth": 1500,
					"N": 4,
					"energyRatio": 55.0,
					"CR": 0.75,
					"N60": 2.8,
					"sigma_v": 25.6,
					"u": 0.0,
					"sigma_v_eff": 25.6,
					"CN": 1.7,
					"N160": 4.7,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 3000,
					"N": 1,
					"energyRatio": 55.0,
					"CR": 0.8,
					"N60": 0.7,
					"sigma_v": 52.3,
					"u": 11.8,
					"sigma_v_eff": 40.5,
					"CN": 1.582,
					"N160": 1.2,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 4500,
					"N": 5,
					"energyRatio": 55.0,
					"CR": 0.85,
					"N60": 3.9,
					"sigma_v": 79.0,
					"u": 26.5,
					"sigma_v_eff": 52.5,
					"CN": 1.39,
					"N160": 5.4,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 6000,
					"N": 3,
					"energyRatio": 55.0,
					"CR": 0.95,
					"N60": 2.6,
					"sigma_v": 105.7,
					"u": 41.2,
					"sigma_v_eff": 64.5,
					"CN": 1.254,
					"N160": 3.3,
					"soilType": "clay",
					"layer": 1
				},
				{
					"depth": 7500,
					"N": 5,
					"energyRatio": 55.0,
					"CR": 0.95,
					"N60": 4.4,
					"sigma_v": 133.1,
					"u": 55.9,
					"sigma_v_eff": 77.1,
					"CN": 1.146,
					"N160": 5.0,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 9000,
					"N": 6,
					"energyRatio": 55.0,
					"CR": 0.95,
					"N60": 5.2,
					"sigma_v": 160.8,
					"u": 70.6,
					"sigma_v_eff": 90.2,
					"CN": 1.06,
					"N160": 5.5,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 10500,
					"N": 8,
					"energyRatio": 55.0,
					"CR": 1.0,
					"N60": 7.3,
					"sigma_v": 188.6,
					"u": 85.3,
					"sigma_v_eff": 103.2,
					"CN": 0.991,
					"N160": 7.3,
					"soilType": "silt",
					"layer": 2
				},
				{
					"depth": 12000,
					"N": 13,
					"energyRatio": 55.0,
					"CR": 1.0,
					"N60": 11.9,
					"sigma_v": 216.3,
					"u": 100.1,
					"sigma_v_eff": 116.2,
					"CN": 0.934,
					"N160": 11.1,
					"soilType": "sand",
					"layer": 3
				}
			],
			"liquefaction": {
				"amax": 0.37800000000000006,
				"magnitude": 7.5,
				"points": [
					{
						"depth": 1500,
						"N60": 2.8,
						"screened": false,
						"reason": "above the water table",
						"liquefiable": false
					},
					{
						"depth": 3000,
						"N60": 0.7,
						"screened": false,
						"reason": "clay: not susceptible (clay-like)",
						"liquefiable": false
					},
					{
						"depth": 4500,
						"N60": 3.9,
						"screened": false,
						"reason": "clay: not susceptible (clay-like)",
						"liquefiable": false
					},
					{
						"depth": 6000,
						"N60": 2.6,
						"screened": false,
						"reason": "clay: not susceptible (clay-like)",
						"liquefiable": false
					},
					{
						"depth": 7500,
						"N60": 4.4,
						"screened": true,
						"sigma_v": 133.1,
						"sigma_v_eff": 77.1,
						"finesContent": 46.0,
						"rd": 0.93,
						"csr": 0.394,
						"N160cs": 10.6,
						"MSF": 1.0,
						"Ksigma": 1.026,
						"crr": 0.126,
						"fs": 0.32,
						"liquefiable": true
					},
					{
						"depth": 9000,
						"N60": 5.2,
						"screened": true,
						"sigma_v": 160.8,
						"sigma_v_eff": 90.2,
						"finesContent": 46.0,
						"rd": 0.91,
						"csr": 0.399,
						"N160cs": 11.2,
						"MSF": 1.0,
						"Ksigma": 1.011,
						"crr": 0.128,
						"fs": 0.32,
						"liquefiable": true
					},
					{
						"depth": 10500,
						"N60": 7.3,
						"screened": true,
						"sigma_v": 188.6,
						"sigma_v_eff": 103.2,
						"finesContent": 46.0,
						"rd": 0.889,
						"csr": 0.399,
						"N160cs": 12.9,
						"MSF": 1.0,
						"Ksigma": 0.998,
						"crr": 0.139,
						"fs": 0.35,
						"liquefiable": true
					},
					{
						"depth": 12000,
						"N60": 11.9,
						"screened": true,
						"sigma_v": 216.3,
						"sigma_v_eff": 116.2,
						"finesContent": 17.0,
						"rd": 0.867,
						"csr": 0.396,
						"N160cs": 15.0,
						"MSF": 1.0,
						"Ksigma": 0.985,
						"crr": 0.154,
						"fs": 0.39,
						"liquefiable": true
					}
				],
				"layers": [
					{
						"layer": 2,
						"top": 6500,
						"bottom": 12000,
						"soilType": "silt"
					},
					{
						"layer": 3,
						"top": 12000,
						"bottom": 20500,
						"soilType": "sand"
					}
				],
				"lpi": 26.2,
				"category": "very high",
				"note": "2 liquefiable layer(s); LPI = 26.2 (very high risk, Iwasaki 1982). amax = Z·S = 0.28 × 1.35 = 0.378 g (BNBC 2020 Tables 6.2.14 and 6.2.16, site class SD; the maximum considered earthquake, as ASCE 7-16 11.8.3).",
				"notes": [
					"amax = Z·S = 0.28 × 1.35 = 0.378 g (BNBC 2020 Tables 6.2.14 and 6.2.16, site class SD; the maximum considered earthquake, as ASCE 7-16 11.8.3)"
				]
			},
			"bearing": {
				"table": [
					{
						"B": 1000,
						"Df": 1000,
						"qa_shear": null,
						"qa_settlement": 48.2,
						"qa": null,
						"governs": null
					},
					{
						"B": 2000,
						"Df": 1000,
						"qa_shear": null,
						"qa_settlement": 28.9,
						"qa": null,
						"governs": null
					},
					{
						"B": 1000,
						"Df": 1500,
						"qa_shear": 62.7,
						"qa_settlement": 42.9,
						"qa": 42.9,
						"governs": "settlement"
					},
					{
						"B": 2000,
						"Df": 1500,
						"qa_shear": 58.5,
						"qa_settlement": 28.2,
						"qa": 28.2,
						"governs": "settlement"
					}
				],
				"method": "qa = min(shear, settlement). Shear: general bearing capacity",
				"factorOfSafety": 3.0,
				"allowableSettlement": 25.0,
				"notes": [
					"layer 1 (fill): no strength (cu or φ', or SPT to estimate them): it lies within B below the base, so there is no qa"
				]
			},
			"ks": 1129,
			"ksDetail": {
				"value": 1129,
				"B": 2000,
				"Df": 1500,
				"q": 28.2,
				"settlement": 25.0,
				"bowles": 3384,
				"method": "ks = qa/s(qa), the secant value for the subgrade footing",
				"note": "Square footing 2 m wide at 1.5 m: ks falls with the loaded width (about B_ref/B in clay); a raft is better designed from the settlement of the whole raft. Bowles' 40·FS·qa is shown for comparison."
			},
			"pile": [
				{
					"layer": 0,
					"top": 0,
					"bottom": 1200,
					"soilType": "fill",
					"sigma_v_eff": 10.2,
					"fs": null,
					"qb": null,
					"method": null,
					"note": "no SPT in the layer; fill: normally ignored for capacity; check downdrag"
				},
				{
					"layer": 1,
					"top": 1200,
					"bottom": 6500,
					"soilType": "clay",
					"sigma_v_eff": 47.3,
					"fs": 12.1,
					"qb": 143.0,
					"alpha": 0.55,
					"method": "α method, O'Neill & Reese 1999",
					"note": null
				},
				{
					"layer": 2,
					"top": 6500,
					"bottom": 12000,
					"soilType": "silt",
					"sigma_v_eff": 92.4,
					"fs": 26.2,
					"qb": 324.2,
					"beta": 0.284,
					"method": "β method, O'Neill & Reese 1999",
					"note": null
				},
				{
					"layer": 3,
					"top": 12000,
					"bottom": 20500,
					"soilType": "sand",
					"sigma_v_eff": 155.3,
					"fs": 79.4,
					"qb": 860.9,
					"beta": 0.511,
					"method": "β method, O'Neill & Reese 1999",
					"note": null
				},
				{
					"layer": 4,
					"top": 20500,
					"bottom": 30000,
					"soilType": "sand",
					"sigma_v_eff": 240.4,
					"fs": 64.6,
					"qb": 1762.0,
					"beta": 0.269,
					"method": "β method, O'Neill & Reese 1999",
					"note": null
				}
			],
			"pileType": "bored",
			"notes": []
		}
	],
	"siteClass": {
		"class": "SD",
		"governing": "BH-1",
		"boreholes": [
			"BH-1",
			"BH-2"
		],
		"note": "SD, the softest of the boreholes (BH-1 SD, BH-2 SD), in the order SA to SE of Table 6.2.13."
	},
	"amax": 0.37800000000000006,
	"methods": {
		"bearing": "qa = min(shear, settlement). Shear: general bearing capacity",
		"liquefaction": "Idriss & Boulanger (2014) SPT procedure: CSR = 0.65 (σv/σ'v)",
		"siteClass": "BNBC 2020 Table 6.2.13: harmonic mean N (field) and su over "
	},
	"notes": [
		"Liquefiable layers: the site may be class S2 of BNBC 2020 Table 6.2.13, which needs a site-specific study; shallow foundations on them need ground improvement or piles through them."
	]
}`);
