# Clause audit: code references against BNBC 2020

Audit of every clause, table, equation and page citation in SAEngine against the text of
BNBC 2020 (Bangladesh Gazette, 11 February 2021), done on 2026-10-25 on
`origin/feat/ui-ux-redesign` at 6c5968b1. Where the code uses a number attributed to a clause
(φ factors, limits, coefficients, table values) the number itself was checked, on a rendered
image of the page for tables and formulas.

**Page convention.** "part1 p684" means page 684 of the PDF of Volume 1 of the gazette
(Parts I to VI Ch 10); "part2 p1107" means page 1107 of the PDF of Volume 2 (Part VI Ch 10
onwards, Parts VII and VIII). Gazette page numbers are PDF page + 2581 (Volume 1) or
PDF page + 3781 (Volume 2). Some steel citations use gazette pages; both are right where they
are consistent.

**Scope.** `python/src/saengine/**` (code, docstrings, notes, report strings and the code pack
`codes/packs/bnbc2020/**`), `docs/**`, `README.md` and the workbench UI strings
(`workbench/src/vs/workbench/contrib/saengine*/browser/**`,
`workbench/src/vs/workbench/services/saengineProject/**`). Generic mentions ("BNBC 2020",
"ACI 318-19" without a clause) are not counted.

**Verdicts.** correct · wrong number (the reference is wrong, the rule is right) · wrong value
(the number in the code differs from BNBC) · wrong clause · not in BNBC (the rule comes from
ACI/AISC/BS/NFPA or office practice) · could not find · external (ACI 318, AISC 360, ASCE 7,
BS 8666, NFPA, EN, IEC, ISO ...: **external standard, check against the owner's copy**; the
standards were not available).

## Counts

| Area | Checked | Correct | Wrong (number / value / clause) | Not in BNBC | Could not find | External | "From memory" markers |
|---|---|---|---|---|---|---|---|
| Concrete design (`design/**` RC, concrete/detailing/materials pack data) | 86 | 79 | 3 (2 / 1 / 0) | 1 | 0 | 3 rows (31 clause groups) | 3 |
| Seismic and loads (`fem/**`, seismic `design/**`, `library/bnbc.py`, settings, pack loads/seismic/wind) | 91 | 82 | 7 (4 / 3 / 0) + 1 missing rule | 1 | 0 | 1 row (8 clauses) | 3 |
| Steel (`design/steel/**`, `steel_*.py`, steel pack data, section designer) | 73 | 54 | 3 (1 / 2 / 0) | 6 | 0 | 10 | 6 |
| Soil, substructure, drawings, BOQ, GIS | 114 | 55 | 5 (2 / 3 / 0) | 2 | 0 | 52 | 11 |
| MEP (`plumbing/**`, `hvac/**`, `electrical/**`, `mep/**`, `library/mep.py`) | 175 | 171 | 2 (1 / 1 / 0) | 2 | 0 | 30 | 33 |
| Docs, UI strings, report, verification cases, importers/exporters | 157 | 119 | 6 (5 / 0 / 1) + 1 value the cited clause hides | 0 | 0 | 29 | 3 |
| **Total** | **696** | **560** | **26** | **12** | **0** | **125 rows** | **59** |

Rows are distinct citations (identical citations making the same claim are merged). External
rows count clause groups, so the columns do not add up to "checked". All 59 "from memory /
to be checked" markers were resolved: either confirmed in BNBC (cited now where the file
was in scope), or the value is not a BNBC value (IEC, ISO, ASHRAE, manufacturer or office
practice).

## Wrong numbers and their engineering impact (priority order)

| # | Where | Old → new | Impact | Status |
|---|---|---|---|---|
| 1 | `fem/loads.py:48` `design_acceleration` | No lower bound → Sa ≥ 0.67 β Z I S, β = 0.11 (Part 6 Eq 6.2.34, part1 p612) | **Unconservative** at long periods: static base shear and the RS spectrum. At R = 8, site SD, T = 4 s, Sa is 3.5× too low; the floor governs from about T ≈ 2.7 s (tall or flexible buildings). | core round |
| 2 | `codes/packs/bnbc2020/data/seismic.json:309` `liveShare` (used by `fem/derive.py:829`, `library/generator.py:1226`, ETABS exporter/importer) | 0.25 on every floor → 0.25 for L ≤ 3 kN/m², **0.50 for L > 3 kN/m²** (Sec 2.5.7.3 (a)-(b), part1 p628) | **Unconservative** seismic weight: about 13 % low on 4.8 kN/m² floors, about 23 % low on 12 kN/m² storage floors; base shear and storey forces drop by the same share. | core round |
| 3 | `plumbing/tanks.py:980-990` (and 1690) | Septic tank roof live 1.0 kPa → **at least 7.0 kPa** (Part 8 Sec 6.9.12.14, part2 p1107) | **Unconservative** septic roof slab: factored roof moments and shears about 2.3× what was designed (150 mm roof, 1 kPa finish). `tables.SEPTIC_COVER_LIVE = 7.0` existed and the septic report quoted it, but the structural design did not use it. | **fixed in this PR** |
| 4 | `substructure/piles.py` `FactorsOfSafety.for_method` | Uplift FS kept at Table 6.3.10a's 2.5 without a load test → **at least 3.0** by analysis, 2.0 with a load test (Sec 3.11.3, part1 p796) | **Unconservative** allowable uplift: 20 % too high for piles whose uplift capacity comes from analysis (the SPT method already used 3.5). The UI help texts that say "2.5" (substructureEditor.ts:82, :2158, substructureDocument.ts:142) still state the default factor, which is correct as an input. | **fixed in this PR** |
| 5 | `codes/packs/bnbc2020/data/concrete.json:68`, `design/bars.py:55` | Column ρmax 0.08 (ACI 10.6.1.1) → **0.06** (Part 6 Sec 6.3.9.1, part1 p910; 0.04 preferred) | Design mode can propose and accept 6-8 % column steel (12-16 % at laps), which BNBC forbids. Strength is computed correctly, so capacity is not overstated, but such designs do not comply. SMF columns already use 0.06. | core round |
| 6 | `codes/packs/bnbc2020/data/areaLoads.json:30, :34, :66` | Classroom, hospital patient room, parking 1.9 kN/m² (ASCE 7) → **2.0** (Table 6.2.3, part1 p534, p536) | Live loads 5 % low (unconservative); the generator's "below Table 6.2.3 minimum" check (`library/generator.py:974`) inherits the error. | core round |
| 7 | `design/steel_proposal.py:199` | Fallback KL/r flag 200 → **150** (Sec 10.5.2) | Flag only, on the fallback path; strength unchanged. | core round |
| 8 | `library/section_designer.py:20-21, :470-474` | φ transition ends at εty + 0.003 (ACI 318-19) where BNBC ends it at 0.005 (Sec 6.2.3.2.2 / 6.3.3.4) | Conservative (φ up to 0.03 low for Grade 500); the cited "Table 6.6.2.1" does not exist: fix the text. | core round |
| 9 | `substructure/loads.py:13`, `shallow.py:66` | "D + L + Lr" named as a BNBC 2.7.2 combination | BNBC has D + L, D + Lr and D + 0.75L + Lr; D + L + Lr envelopes them (conservative by up to Lr). | text **fixed in this PR** |
| 10 | `soil/liquefaction.py:27, :519`, `soil/site_class.py:60` | "FL < 1" → "FL ≤ 1" (part1 p734) | Text only; the code already uses `fs <= 1.0`. | core round (soil/** not in this side track) |
| 11 | `library/soil.py:778` | Help text "empty PGA: Z × S" → "(2/3) Z S" (Sec 2.5.13.2) | Text only; the code already uses (2/3) Z S. | core round |
| 12 | `wind.json:19`, `library/bnbc.py:109-110` | Exposure C described as "coastal" → coastal / cyclone-prone open terrain is exposure **B**; C only outside cyclone-prone regions (Sec 2.4.6.2-2.4.6.3, part1 p551) | Text; choosing C for a coastal site is conservative. | core round |
| 13 | `design/steel/members.py:148` (possible, not counted) | Table 6.10.2 case 7 "d" taken as the tee's own depth; AISC means the parent W's depth | U = 0.90 instead of 0.85 for some tees: tee rupture up to 5.9 % unconservative. BNBC does not define d; check against the owner's AISC copy. | core round to decide |

Not counted as wrong but worth a ticket (code does not apply a BNBC rule; no citation is
wrong): **pile minimum reinforcement** is not checked against BNBC (driven 1/1.5/2 % main,
0.4/0.2 % lateral, part1 p757; bored 0.5/0.375/0.25 % Ag, ≥ 6 bars, ≥ Ø16 for D ≥ 600, part1
p765); **brick-aggregate concrete** ×1.5 minimum steel (Sec 8.1.11.2(b)) is applied in
`stairs.py` but not in `slab.py:395-400`, `footing.py:141-142` or the footing/cap/raft minimum
steel; **default covers** in `concrete.json` are below Sec 8.1.7.2 (lintel 25 mm vs 40 mm for
beams, pile cap 50 mm vs 75 mm cast against earth); **fire reserve** in plumbing is 1 h (Part 8
Sec 5.9.1.2(c)) while Part 4 Table 4.4.1 asks up to 112 min for ordinary hazards above 51 m
(owner to decide which governs); wind importance for category I is 0.77 in cyclone-prone
regions with V > 44 m/s (Table 6.2.9), the pack uses 0.87 everywhere (conservative).

BNBC misprints found (keep the code as it is): Table 6.10.1 case 15 prints λp = 0.07√(E/Fy),
the code's 0.07 E/Fy is the intended (AISC) value; Sec 3.10.5 refers to "Table 6.3.7" for
settlement limits, meaning Table 6.3.8; Appendix S prints "V = PQ + PSY" with t defined but
left out (the code's PQt is the intended form).

## Fixed in this PR

Only files outside the areas another session is editing (drawings/**, substructure/**,
plumbing/**, docs/**, verification/**):

- `plumbing/tanks.py`: new `roof_live()`; a septic tank's roof live load is
  max(`roofLive`, 7 kPa) in the Lr pattern, its load note and the bearing weight (BNBC Part 8
  Sec 6.9.12.14). Test: `test_septic_tank_roof_takes_at_least_7_kpa`.
- `plumbing/tables.py:530`: "Table 8.S.1 (iv) kindergarten" → "(iv) community centre,
  kindergarten" (value 0.08 unchanged).
- `substructure/piles.py`: the uplift factor of safety is raised to at least 3.0 without a
  load test (2.0 with one), BNBC Sec 3.11.3, with a note; docstrings updated.
  `tests/test_substructure_piles.py` and the verification case
  `verification/cases/substructure_deep.py` (bored pile DP1: Ta = (0.7 Qs + W)/3.0) follow.
- `substructure/loads.py:13`, `substructure/shallow.py:66`: D + L + Lr explained as the
  envelope of BNBC 2.7.2.1 (2)-(4).
- `substructure/pilecap.py:40`: "ACI 318-19 as BNBC 2020 adopts it" corrected (BNBC Ch 6 is an
  earlier ACI 318 without λs; ACI 318-19 is the more conservative).
- `drawings/detailing.py:70, :603, :1225`: the 0.30 ln beam top-bar extent is marked as
  office practice, not a BNBC rule (was "from memory, to be checked"); clause 8.2.7.4 is on
  p1080, 8.2.9.2 on p1081.
- `docs/manual/02-project-settings.md`: exposure clause 6.2.9.3 → Part 6 Sec 2.4.6.3; ACI
  318-19 vs BNBC Ch 6 statement corrected. `docs/manual/08-fem.md`: same statement.
  `docs/manual/09-substructure.md`: uplift factor raised to 3.0 without a load test.
- `verification/cases/design.py:6`, `design_mode.py:3`: "BNBC Ch 6 adopts ACI 318-19, so the
  clauses are the same" corrected.

The manual PDF (`docs/manual/SAEngine-User-Manual.pdf`) is not rebuilt here.

## Handed to the next core round (do not edit in side tracks)

Exact corrections, `path:line` relative to `python/src/saengine/` unless the path says
otherwise. Line numbers are those of 6c5968b1.

### codes/packs/bnbc2020/**

- `data/concrete.json:68` `0.08` → `0.06` (column ρmax, Sec 6.3.9.1).
- `data/concrete.json:139` `"columnRho": "ACI 318 10.6.1.1 (as the code's Chapter 6; page not checked)",` → `"columnRho": "BNBC 2020 Part 6 Sec 6.3.9.1 (p. 910): 0.01-0.06 Ag, 0.04 preferred",`
- `data/concrete.json:141` `"slabStrainMin": "ACI 318 7.3.3.1, 8.3.3.1 (page not checked)",` → `"slabStrainMin": "BNBC 2020 Part 6 Sec 6.3.3.5 (p. 906); ACI 318 7.3.3.1, 8.3.3.1",`
- `data/materials.json:26` `"concreteStrain": "ACI 318 22.2.2.1 (as the code's Chapter 6; page not checked)",` → `"concreteStrain": "BNBC 2020 Part 6 Sec 6.3.2.3 (p. 904); ACI 318 22.2.2.1",`
- `data/seismic.json:309` `"liveShare": 0.25,` → keep 0.25 for L ≤ 3 kN/m² and add the 50 % rule (e.g. `"liveShareHeavy": 0.5, "liveShareThreshold": 3.0`), used per floor area load in `fem/derive.py:829-832`, `library/generator.py:1226` and the ETABS exporter/importer (schema + code change).
- `data/seismic.json:326` `"liveShare": "BNBC 2020 Part 6 Sec 2.5.7, seismic weight W (p. 628)",` → `"liveShare": "BNBC 2020 Part 6 Sec 2.5.7.3(a)-(b) (p. 628): 25 % for L <= 3 kN/m², 50 % above",`
- `data/seismic.json:336` `"5 % damping: η = 1 (page not checked)"` → `"BNBC 2020 Part 6 Eq. 6.2.36 (p. 613): η = 1 at 5 % damping"`
- `data/seismic.json:4,6`, `pack.json:39`, `README.md:20` `Sec 2.5 (pp. 609-648)` → `(pp. 604-648)`.
- `data/areaLoads.json:30, :34, :66` `"live": 1.9` → `"live": 2.0` (classroom, hospitalWard, parking; Table 6.2.3).
- `data/areaLoads.json:4,6`, `pack.json:37` `Table 6.2.3 (pp. 533-539` → `(pp. 533-538`.
- `data/wind.json:6` `(pp. 549-603)` → `(pp. 544-603)`.
- `data/wind.json:14` (exposure B) → `"Open terrain with scattered obstructions; flat open country and water surfaces in cyclone-prone (coastal) regions"`; `:19` (exposure C) `"Flat open country, coastal"` → `"Flat unobstructed areas and water surfaces outside cyclone-prone regions"`.
- `data/wind.json:43` `"exposures": "BNBC 2020 Part 6 Table 6.2.11 (p. 602) and its α, zg",` → `"exposures": "BNBC 2020 Part 6 Table 6.2.10 (p. 602) α, zg; Sec 2.4.6.2-2.4.6.3 (p. 551) categories",`
- `data/wind.json:46-47` `Figure 6.2.6 (page not checked)` → `Figure 6.2.6 (p. 571)`.
- `data/steel.json:25` `plate flexure 0.9 from memory` → `plate flexure 0.9: not in BNBC Sec 10.10.4 (AISC 360-16 J4.5), φb of Sec 10.6.1`.
- `pack.json:44` `Sec 8.3 (pp. 1088-1122)` → `(pp. 1088-1124)`.

### fem/**

- `fem/loads.py:48-52` add the Eq 6.2.34 floor: `Sa = max((2/3)·(Z·I/R)·Cs, 0.67·β·Z·I·S)`, β = 0.11 (part1 p612); docstring `"""Design spectral acceleration Sa = (2/3)·(Z·I/R)·Cs >= 0.67·β·Z·I·S, β = 0.11 (BNBC 2020 Part 6 Eq. 6.2.34, p. 612), as a fraction of g."""`. Needs S of the site class; the RS spectrum built from it follows.
- `fem/derive.py:829-832`: seismic live share per floor by Sec 2.5.7.3 (see seismic.json above).

### design/**

- `design/bars.py:54` `#: Column steel ratio limits (ACI 10.6.1.1).` → `#: Column steel ratio limits (BNBC 2020 Part 6 Sec 6.3.9.1, p. 910; ACI 10.6.1.1 allows 0.08).`
- `design/bars.py:55` `RHO_MIN, RHO_MAX = 0.01, 0.08` → `RHO_MIN, RHO_MAX = 0.01, 0.06`
- `design/bars.py:415` `(ACI 10.6.1.1, 10.7.3.1: at least 4` → `(BNBC 6.3.9.1, 6.3.9.2: at least 4`
- `design/proposal.py:355` `(ACI 10.6.1.1) carries the demand` → `(BNBC 6.3.9.1) carries the demand`
- `design/required.py:665` `carries the demand (ACI 10.6.1.1)` → `carries the demand (BNBC 6.3.9.1)`; `:671` `governs (ACI 10.6.1.1)` → `governs (BNBC 6.3.9.1)`
- `design/punching.py:155` `γv = 1 - 1 / (1 + (2/3) √(b1 / b2)) (Eq. 6.6.77)."""` → `γv = 1 - γf (Eq. 6.6.77), γf = 1 / (1 + (2/3) √(b1 / b2)) (Eq. 6.6.81, Sec 6.5.5.3.2, p. 950)."""`
- `design/slab.py:565` `#: ACI Table 8.3.1.1 (without drop panels)` → `#: BNBC 2020 Part 6 Table 6.6.3 (p. 902; ACI 318-19 Table 8.3.1.1 has a 550 MPa row instead of 520) (without drop panels)`; `:571` `"""The ln divisor of ACI Table 8.3.1.1, interpolated in fy (footnote)."""` → `"""The ln divisor of BNBC Table 6.6.3 (ACI Table 8.3.1.1), interpolated in fy (footnote †)."""`
- `design/seismic_rules.py:2` `(pp. 1088-1123 of the code PDF)` → `(pp. 1088-1124 of the code PDF)`; the same page range in `design/ductile_members.py:3`, `design/ductile_joints.py:6`, `design/seismic_detailing.py:1-2`.
- `design/steel_proposal.py:199` `checks.append(_check("slenderness KL/r", kl_r, 200.0, "-", None, note, flag=True))` → `... kl_r, 150.0, ...` (BNBC Sec 10.5.2).
- `design/steel_proposal.py:156` `and the H1-1 interaction (from memory of AISC 360).` → `and the H1 interaction (BNBC 2020 Part 6 Sec 10.8.1.1, Eqs 6.10.147a/b).`
- `design/steel_connections.py:35-36` `From memory, to be checked against the code: the fillet throat 0.707 w; the net-hole allowance dh + 2 mm; the Whitmore width` → `Checked in BNBC: the fillet throat 0.707 w (Sec 10.10.2.2.1) and the net-hole allowance dh + 2 mm (Sec 10.2.3.13.2, 10.4.3.2). Not in BNBC (AISC Manual practice): the Whitmore width`
- `design/steel_connections.py:124` `dh + 2 mm (from memory, to be checked).` → `dh + 2 mm (BNBC 2020 Part 6 Sec 10.4.3.2).`
- `design/steel_connections.py:177` `(from memory, to be checked)` → `(AISC Manual Part 9 practice; not in BNBC)`
- `design/steel_connections.py:341` `"φ 0.9 Fy Z (from memory)"` → `"φ 0.9 Fy Z (not in BNBC Sec 10.10.4; φb of Sec 10.6.1, AISC 360-16 J4.5)"`
- `design/steel_connections.py:171` `(Sec 10.10.2.2, p. 116)` → `(Sec 10.10.2.2.2, p. 116)`; `:211` `"Sec 10.10.2.2 maximum size along edges"` → `"Sec 10.10.2.2.2 maximum size along edges"` (precision).
- `design/steel/lengths.py:20-21` `A segment with a free end gets K = 2.0 for compression and Cb = 1.0 (BNBC 2020 Part 6 Sec 10.6.1,` → `A segment with a free end gets K = 2.0 for compression (theoretical cantilever value, not in BNBC) and Cb = 1.0 (BNBC 2020 Part 6 Sec 10.6.1,`; `:345` `": K = 2.0 for compression, Cb = 1.0 for LTB (Sec 10.6.1)"` → `": K = 2.0 for compression (cantilever), Cb = 1.0 for LTB (Sec 10.6.1)"`
- `design/steel/members.py:148`: decide whether Table 6.10.2 case 7's d is the parent W depth (AISC) — up to 5.9 % unconservative for some tees as written.

### library/**

- `library/bnbc.py:143` `#: Share of the floor live load in the seismic weight W: 25 % for ordinary floors.` → `#: Share of the floor live load in the seismic weight W (Sec 2.5.7.3): 25 % for L <= 3 kN/m², 50 % above.`
- `library/bnbc.py:146` `(Table 6.2.11).` → `(α, zg: Table 6.2.10).`
- `library/bnbc.py:109-110` `C - flat unobstructed areas and water surfaces, including coastal belts.` → `B - open terrain, including flat open country and water surfaces in cyclone-prone (coastal) regions; C - flat unobstructed areas and water surfaces outside cyclone-prone regions.`
- `library/defaults.py:31` `# reinforced normal-weight concrete, ~23.6 kN/m³ (BNBC 2020 Part 6)` → `# reinforced stone-aggregate concrete, ~23.6 kN/m³ (BNBC 2020 Part 6 Table 6.2.1, p. 530: 22.8 + 0.63 per 1 % steel; brick-aggregate 20.4)`
- `library/settings.py:169` `description="Exposure category (6.2.9.3).",` → `description="Exposure category (Sec 2.4.6.3).",`
- `library/objects.py:165` `(BNBC 2020 Part 6 Sec 8.3.4.2(b), Figure 6.8.8)` → `(BNBC 2020 Part 6 Sec 8.3.4.2(b), Figure 6.8.3 for beams; Sec 8.3.5.3(b), 8.3.5.4, Figure 6.8.8 for columns)`
- `library/section_designer.py:16` `(ACI 318-19 / BNBC 2020 Part 6 Sec 6.2.2: 0.85 f'c over β1 c,` → `(ACI 318-19 / BNBC 2020 Part 6 Sec 6.3.2.3, 6.3.2.7: 0.85 f'c over β1 c,`
- `library/section_designer.py:20-21` `linear between (Table 6.6.2.1 / ACI 21.2.2)` → `linear between (ACI 318-19 21.2.2; BNBC 2020 Part 6 Sec 6.2.3.2.2 / 6.3.3.4, Figure 6.6.1, ends the band at 0.005: conservative here for fy > 420 MPa)`
- `library/soil.py:778` `"At the ground surface [g]; empty: Z × S from the project settings: the "` → `"At the ground surface [g]; empty: (2/3) Z S from the project settings (the design PGA of BNBC 2020 Sec 2.5.13.2): the "`
- `library/substructure.py:262` `"or from the SPT N values by BNBC 2020 Eqs 6.3.29 and 6.3.31-32."` → `"or from the SPT N values by BNBC 2020 Eqs 6.3.21-6.3.22 and 6.3.25-6.3.28 (driven) or 6.3.29-6.3.34 (bored)."`
- `library/substructure.py:227` (pile uplift FS help): add "raised to at least 3.0 without a load test (Sec 3.11.3)" to match the new behaviour of `substructure/piles.py`.
- Then regenerate `workbench/src/vs/workbench/services/saengineProject/common/projectLibraries.generated.ts`.

### soil/** (not in this side track's edit list)

- `soil/liquefaction.py:27` `when FL < 1.` → `when FL ≤ 1.`; `:519` `liquefaction when FL < 1;` → `liquefaction when FL ≤ 1;`
- `soil/liquefaction.py:31-34` replace the "a visual check of the printed page would settle it" note with `(Checked on the printed page, part1 p734: Eq 6.3.8 is CSR = (amax/g) rd σv/σ'v, with no 0.65.)`
- `soil/site_class.py:60` `(FS < 1): Table 6.2.13 classes the site S2` → `(FS ≤ 1): ...`
- `soil/lab.py:47-50, :87, :399-400`: the sulphate thresholds ("from memory") are identical to BNBC Part 6 Table 6.5.2 (part1 p846); cite `BNBC 2020 Part 6 Table 6.5.2 (= ACI 318-19 Table 19.3.1.1 S1-S3)` and drop the from-memory notes (test comment `tests/test_soil_lab.py:281` likewise).

### report/**

- `report/templates/report.typ:453` `settings (BNBC 2020 6.2).` → `settings (BNBC 2020 Part 6 Chapter 2).`
- `report/build.py:880-881` (optional) `allowable story drift of BNBC 2020 Part 6 Chapter 2` → `... Part 6 Table 6.2.21 ...`

### Workbench UI strings (not in this side track's edit list)

- `workbench/src/vs/workbench/contrib/saengineLibrary/browser/settingsEditor.ts:116` `localize('code.exposureSource', "6.2.9.3")` → `"Sec 2.4.6.3"`, and the Bangla string `workbench/build/saengine/i18n/bn/strings.bn.json:6613-6614`.
- `workbench/src/vs/workbench/contrib/saengineFem/browser/femChartData.ts:198` `(the design drift is Cd·δ/I, Part 6 Sec 2.5.7.1)` → `(..., Part 6 Sec 2.5.7.7, Eq 6.2.45)`
- `workbench/src/vs/workbench/contrib/saengineLibrary/browser/codePacksModel.ts:44` `("BNBC 2020 Part 6 Table 6.2.14, p. 3160")` → `("BNBC 2020 Part 6 Table 6.2.14, p. 615")`

### Optional MEP text clarifications (plumbing/hvac/mep, may go with any later MEP work)

- `hvac/air.py:22` `(continuous; 25 intermittent, note f, p. 866)` → `(continuous; 25 intermittent, p. 866, note f p. 869)`; `:94` likewise.
- `hvac/energyplus.py:342` 1 air change an hour ("from memory"): consider BNBC Part 8 Table 8.2.6 (part2 p904-905).
- `mep/openings.py:929` `more than 250 mm thick, so it has two layers (BNBC 6.6.3.4)` → `more than 250 mm thick (other than a basement wall), so it has two layers (BNBC 6.6.3.4)`.
- `plumbing/septic.py:3` note that BNBC prints "V = PQ + PSY" (t defined, left out).

Files held by the open fire-protection work (`mep/loads.py`, `library/mep.py`,
`verification/cases/__init__.py`, `docs/verification/README.md`) need no corrections.

## External standards (check against the owner's copy)

Not verifiable here. The full deduplicated lists per area, with file:line examples, are in the
appendices below. Summary:

- **ACI 318-19**: Chapters 2, 6 (6.6.3.1.1 cracked factors), 7, 8 (8.4 moment transfer), 9,
  10.6/10.7, 13 (footings), 14 (plain concrete), 18 (18.7, 18.8, 18.13 seismic), 19 (Table
  19.3.1.1), 21.2 (φ), 22.2, 22.4, 22.5 (Table 22.5.5.1, λs), 22.6 (punching), 25. BNBC Part 6
  Ch 6/8 follow an earlier ACI 318: where they differ, the ACI 318-19 rule SAEngine uses is the
  same or more conservative (no size factor in BNBC Vc; tension-controlled limit 0.005).
- **ACI 336.2R** (combined footing strips), **ACI SP-66** (beam bar extents, practice).
- **AISC 360** (-10/-16/-22: J4.5 plate flexure, H1-1 = BNBC Eq 6.10.147), **AISC Steel
  Construction Manual** (Whitmore section, gusset K, bolt-group and weld-line methods).
- **ASCE 7-05 / 7-16** (2.4.1 combinations, Table 19.2-1, 20.4), **ASCE 41-06** 4.4.2.1.2,
  **FEMA 356**, **WSDOT** practice (SSI).
- **BS 8666** shape codes and end projections in `drawings/bbs.py`: check the P values before
  schedules go to fabrication.
- **EN 1992-1-1** Eq 7.1 (tank crack control), **ISO 6946**, **ISO 8528**, **ISO 4065**,
  **BS EN 10255**, **IEC 60076**, **IEC 62305-3**, **NFPA 780** (lightning; BNBC Sec
  1.3.33.8(j) refers to it), **ASHRAE** data in `hvac/**`, FHWA-IF-99-025 (O'Neill & Reese).
- **NFPA 13 / 14 / 20**: not cited in the audited tree at 6c5968b1 (fire protection is in a
  separate open branch).

# Appendices: citation tables by area

The tables are the checked rows as recorded during the audit (paths relative to
`python/src/saengine/` unless given in full; line numbers of 6c5968b1).


## Appendix A: Concrete design

Scope: python/src/saengine/design/** (except steel/, steel_*, seismic_rules, seismic_detailing, ductile_*, overstrength) and codes/packs/bnbc2020/data/{concrete,detailing,materials}.json. Paths below are relative to python/src/saengine/.
All BNBC pages are pdf pages of bnbc-2020-part1.pdf (text read and tables rendered: p310, 311, 536, 900, 902).

**Counts:** checked=86 correct=79 wrong(number+value+clause)=3 (number 2, value 1, clause 0) not-in-BNBC=1 could-not-find=0 external=3 table rows (plus 31 external clause groups, ~70 file:line uses, in section 4) markers(from memory etc.)=3 ("page not checked": concrete.json:139, :141, materials.json:26; all three verified: 1 wrong value, 2 same as BNBC)

### 1. Citation table

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| ACI 318 10.6.1.1 (page not checked) / "ACI 10.6.1.1" | codes/packs/bnbc2020/data/concrete.json:66-69,139; design/bars.py:54-55,415; design/proposal.py:355; design/required.py:665,671 | column rho 0.01 to **0.08** | p910 (Sec 6.3.9.1) | wrong value | 0.08 -> 0.06 (BNBC 6.3.9.1: 0.01Ag to 0.06Ag, preferably at most 0.04Ag). Cite "BNBC 2020 Part 6 Sec 6.3.9.1 (p. 910)" |
| Eq. 6.6.77 for gamma_v = 1 - 1/(1 + (2/3)sqrt(b1/b2)) | design/punching.py:155 | gamma_v formula | p943, p950 | wrong number | Eq. 6.6.77 is only gamma_v = 1 - gamma_f; gamma_f = 1/(1+(2/3)sqrt(b1/b2)) is Eq. 6.6.81 (Sec 6.5.5.3.2, p. 950): cite both |
| "ACI Table 8.3.1.1" with rows 280/420/**520** (33/36/36, 30/33/33, 28/31/31) | design/slab.py:565-567,571 | two-way thickness divisors | p902 (Table 6.6.3) | wrong number | Values are BNBC Table 6.6.3 (fy 280/420/520), not ACI 318-19 (whose third row is 550: 27/30/30). Cite "BNBC 2020 Part 6 Table 6.6.3 (p. 902)" |
| ACI 318 7.3.3.1, 8.3.3.1 (page not checked) | concrete.json:141; slab.py:73,131,167,363,1473; bars.py:170; proposal.py:186; check.py:1325 (ACI 9.3.3.1) | eps_t >= 0.004 (slabs, beams) | p906 | external | BNBC equivalent: Part 6 Sec 6.3.3.5 (p. 906), same 0.004 |
| ACI 318 22.2.2.1 (page not checked) | materials.json:26; rc.py:47 | eps_cu = 0.003 | p904 | external | BNBC equivalent: Part 6 Sec 6.3.2.3 (p. 904), same 0.003 |
| BNBC 2020 Part 6 Sec 8.3 (pp. 1088-1122) | detailing.json:4,6 | source of detailing pack | p1088-1124 | correct | - |
| Sec 8.3.4, 8.3.5 (pp. 1090-1100), 8.1.9.4(c) | detailing.json:51 | axialShare 0.1, beam rho_max 0.025, column rho 0.01-0.06, b >= 250, b/h >= 0.3, column >= 300, ratio >= 0.4, fyt <= 700, hx <= 350, 150 mm clear, first hoop 50 mm | p1090,1091,1093,1095,1096,1098,1074 | correct | - |
| Sec 8.3.5.2(b), 8.3.7 (pp. 1096, 1108-1110), 8.3.8.2(a) (p. 1112) | detailing.json:52 | 1.25 fy, sum Mnc >= 1.2 sum Mnb, gamma 1.7/1.2/1.2/1.0, 0.05 Ag f'c | p1096,1108,1110,1112 | correct | - |
| Sec 8.3.6.2, 8.3.6.6 (pp. 1100-1105) | detailing.json:53 | 0.083, 0.17, drift >= 0.007, 0.2/0.15 f'c, 700, 350 | p1100,1103,1090,1098 | correct | - |
| BNBC Part 6 Sec 6.4.3.2 (p. 924) | concrete.json:142 | fyt <= 420 MPa in shear | p924 | correct | - |
| Table 6.6.3 (p. 902), no drop panels | concrete.json:74-90,143 | 280: 33/36/36; 420: 30/33/33; 520: 28/31/31 | p902 (rendered) | correct | - |
| Table 6.6.1 (p. 900) | concrete.json:91-100,144,145 | slabs l/20,24,28; beams l/16,18.5,21 | p900 (rendered) | correct | - |
| Sec 6.3.10.4.1 | concrete.json:106-111,147; slender.py:115-119,154,605 | column 0.70, beam 0.35, flat plate 0.25, cracked wall 0.35 Ig | p912 | correct | - |
| Sec 6.3.10 (Eqs. 6.6.13, 6.6.14, 6.6.17) | concrete.json:73,112-118,148; slender.py:92-102 | Q <= 0.05, klu/r <= 22, 34-12M1/M2 <= 40, delta_s 1.5, 1.4 | p910,912,913,915 | correct | - |
| Sec 6.6.3.2-6.6.3.4, 6.4.8.9, 8.3.6.2(a) | concrete.json:120-134,149; walls.py:145-153 | 0.0012/0.0020, 0.0015/0.0025, 16 mm, 420, 0.0025, 250 mm, 450 | p969,937,938,1100 | correct | - |
| BNBC 2020 Part 6 Sec 10.5.4 | materials.json:27 | G = 77 200 MPa | p1189 (Ch 10 notation: "G ... 77 200 MPa, 10.5.4") | correct | - |
| Sec 8.3.3.3 (p. 1089) | materials.json:28,29 | f'c >= 21; lightweight f'c <= 35 | p1089 | correct | - |
| Sec 6.1 definitions (p. 868) | materials.json:30 | lightweight density up to 1850 | p868 | correct | - |
| Sec 8.3.3.4(b) (pp. 1089-1090) | materials.json:4,31 | A615 275/420, BDS 300/350/400/420 | p1090 | correct | - |
| Sec 8.3.3.4(b)(i), (ii) | materials.json:33,34 | +125 (+20 retest), fu/fy >= 1.25 | p1090 | correct | - |
| Sec 6.4.10.3, 6.4.10.5 | footing.py:17 | stirrups / studs in footings | p938,941 | correct | - |
| BNBC Part 6 2.7.2 (ASD combos) | footing.py:97-100 | D, D+L+Lr, D+W, D+0.75L+0.75Lr+0.75W, 0.6D+W, D+0.7E, D+0.75L+0.75Lr+0.525E, 0.6D+0.7E | p684 | correct | - (D+L+Lr envelopes BNBC combos 2-4; conservative) |
| BNBC 2.7.3 (1.6W) | footing.py:190 | wind factored 1.6 in strength combos | p685 | correct | - |
| Sec 6.1.6.2, 6.1.6.3 (p 892) | face_forces.py:4-6,60,62,67 | c/c spans; design at faces | p892 | correct | - |
| Sec 6.4.1.3 (p 922), 6.4.1.3.1 | face_forces.py:6-10,63,353; stairs.py:55 | shear at d, conditions (a)-(c) | p922 | correct | - |
| BNBC 6.3.10 | overwrites.py:16,45; walls.py:990 | moment magnification | p910-915 | correct | - |
| Sec 8.3 hoop zones, Eq. 6.8.7, 6.8.8, 8.3.8, 8.3.10.3, 8.1.9.4(c), 8.3.4.3(c), 8.3.5.4(a)(iii), (c), 8.3.4.1, 8.3.5.1 | proposal.py:1030-1040,1204 | Ash, Ve, tie legs, hx <= 350 | p1093,1097,1098,1111,1114,1074 | correct | - |
| Sec 8.3.4.1(c), (d) | proposal.py:1064 | beam b/h >= 0.3, b >= 250 | p1090-1091 | correct | - |
| Sec 8.3.5.1(a), (b) | proposal.py:1070,1074 | column >= 300, ratio >= 0.4 | p1095 | correct | - |
| Sec 8.3.4.2(a) (special frames and members outside the system in SDC D) | proposal.py:1260,1288,1291 | rho_min top/bottom, Mn+ >= Mn-/2 | p1091, p1113 (8.3.9.1 applies 8.3.4.2(a) to non-system members) | correct | - |
| BNBC 2020 Part 6 Sec 6.4.10 | proposal.py:1447 | punching | p937 | correct | - |
| Sec 7.4.3.2 (p. 1015) | lintels.py:10-11,90,127 | bearing >= 100 mm; deflection <= clear span/600 under total load | p1015 | correct | - |
| Sec 7.9.6.3 (p. 1045) | lintels.py:34-35,91 | span <= 3.5 m, bars 600 mm beyond; V > 200 km/h | p1045 | correct | - |
| Sec 2.7.3.1 (p. 685) | lintels.py:21,93; stairs.py:41,97,142 | 1.4D, 1.2D+1.6L | p685 | correct | - |
| Sec 6.2.5.2.3, Eq. 6.6.1-6.6.3, Table 6.6.1 (p. 900); 6.1.7.1 | lintels.py:29-33,92,130,242,434,501,510 | Ie, Mcr, fr = 0.62 sqrt f'c, Ec = 4700 sqrt f'c, L/16 x (0.4+fy/700) | p900,892 | correct | - |
| Sec 8.3.6.7 (p. 1105) | lintels.py:40-47,94 | coupling beam classes; "8.3.7 [sic]" remark | p1105 | correct | - (the [sic] note is right: BNBC text says 8.3.7) |
| Sec 8.3.8.1(a) (p. 1111), 8.3.8.2(a) (p. 1112) | lintels.py:51-53,95 | Ve from Mpr; Vc = 0 rule (0.05 Ag f'c, half the shear) | p1111,1112 | correct | - |
| notation p. 882, 8.3.8.1 | lintels.py:120 | Mpr at 1.25 fy, phi = 1 | p882 | correct | - |
| Sec 6.4.10 (pp. 937-943) and 6.4.10.1.2, .1.3, Eq. 6.6.72-6.6.74 (p. 938), alpha_s 40/30/20 | punching.py:4-11,75-77 | vc least of three | p937,938 | correct | - |
| 6.4.10.6.1 (p. 942) | punching.py:13-15,268 | openings within 10h | p942 | correct | - |
| 6.4.10.7, Eq. 6.6.77-6.6.80 (pp. 942-943) | punching.py:17-19 | eccentric shear | p942,943 | correct | - |
| 6.4.10.3, .3.1-.3.3 (p. 938) | punching.py:20-24,82-83 | d >= 150 and 16 db; vc <= 0.17, vn <= 0.5; d/2, d/2, 2d | p938 | correct | - |
| 6.4.10.5, .5.1-.5.4 (p. 941) | punching.py:25-30,79-81,378 | vc <= 0.25, vn <= 0.66, Av fyt/(b0 s) >= 0.17; 0.75d / 0.5d; 2d | p941 | correct | - |
| 6.4.10.7.2 | punching.py:30-31,84-85 | 0.17 phi sqrt f'c outside last line (stirrups) | p943 | correct | - |
| BNBC Sec 6.7, Part 3 Sec 1.14.5, Part 4 Sec 3.10 | stairs.py:1-2 | basis | p972, p68-69, p309-313 | correct | - |
| Sec 6.7.1.1 (a)-(d) (pp. 972-973) | stairs.py:6,21-30,136,427-437,597,613,672,849 | effective spans; (d) +/- wl^2/8 | p972,973 | correct | - |
| Sec 6.7.1.4 (p. 974) | stairs.py:18,140 | waist perpendicular to soffit | p974 | correct | - |
| Table 6.2.3 (p. 536) | stairs.py:36,94-95,141,352,360 | stairs 4.80, one/two-family 2.00 kN/m2 | p536 (rendered) | correct | - |
| Table 6.2.3 note l | stairs.py:70 | 1.33 kN tread load | p538 | correct | - |
| Table 6.2.1 (p. 530) | stairs.py:38 | 22.8 kN/m3 stone concrete | p530 | correct | - |
| Sec 6.7.1.2 (p. 973) | stairs.py:41 | stairs use Ch 2 combinations | p973 | correct | - |
| Sec 6.7.1.5.1 (p. 974) | stairs.py:43 | beam/one-way slab rules | p974 | correct | - |
| Sec 8.1.11.2(a)-(c) (p. 1075); 6.3.5.4 (p. 907); 8.1.6.5 (p. 1068) | stairs.py:49-52,148-150,860,948,959,969,980 | 0.0020/0.0018/0.0018x420/fy >= 0.0014, x1.5 brick; 3h/450; 5h/450 | p1075,907,1068 | correct | - |
| Sec 6.4.2.1.1, Eq. 6.6.49 (p. 922) | stairs.py:53-54,151,873,936 | phi Vc = 0.75 x 0.17 sqrt f'c b d | p922 | correct | - |
| Table 6.6.1 (Sec 6.2.5.2, p. 900); Sec 6.7.1.5.2 (p. 974) | stairs.py:56-58,151-153,865-868,986 | l/20,24,28; ratio +15% when going >= 60% of span | p900,974 | correct | - |
| Appendix M; 6.7.1.3.1 (150 mm strip); 6.7.1.3 / Fig 6.6.27 | stairs.py:68-69 | not modelled (stated) | p973-974 | correct | - |
| Part 3 Sec 1.14.5.2 (p. 69) | stairs.py:100,155,732 | 610 <= 2R+T <= 648 | p69 | correct | - |
| Part 4 Table 4.3.5 (p. 310) | stairs.py:102-121,689,756-777 | riser/tread pairs, 171/324 as printed, max riser 229, min tread 203 | p310 (rendered) | correct | - |
| Part 3 Sec 1.14.5.3 (p. 69) | stairs.py:122-123,155-156,791 | 3660 / 2440 mm | p69 | correct | - |
| Part 3 Sec 1.14.5.4 (p. 69) | stairs.py:125-126,156,835,846 | 2.15 m (2.03 m <= 3 flights) | p69 | correct | - |
| Part 4 Sec 3.10.6 (p. 313) | stairs.py:128,749-750 | adjacent risers within 5 mm | p313 | correct | - |
| Part 4 Sec 3.10.2 (p. 309) | stairs.py:130-131,157,823 | landing >= stair width, need not exceed 1.2 m in a straight run | p309 | correct | - |
| Part 4 Table 4.3.6 (p. 311) | stairs.py:156,701-714,804 | residential 1120, educational 1120/2235, hospital 2235/1120 | p311 (rendered) | correct | - (table's 2235 is for 130 < occupants <= 250; code applies it above 250 too) |
| BNBC 2020 PDF (Gazette 11 Feb 2021) | stairs.py:9 | edition | p897 header | correct | - |
| Sec 8.3.6.6(b), Eq. 6.8.10; 8.3.6.6(c) | wall_design.py:10,19-22,201,207; walls.py:59-65,684,1243 | c >= lw/(600 du/hw), du/hw >= 0.007; 0.2/0.15 f'c | p1103 | correct | - |
| Sec 8.3.6, 6.6, 6.4.8, Eq. 6.8.9, 8.3.6.5, 6.4.8.9.1 | wall_design.py:11,49-54,61,966-967,995 | wall design basis | p968-970,935-937,1101-1102 | correct | - |
| Sec 2.5.9; Sec 2.5.7.7, Eq. 6.2.45 (p. 631) | wall_design.py:21,357 | du = Cd dxe / I | p631,634 | correct | - |
| Sec 2.5.9.4 (p. 635) | wall_forces.py:61-62,99 | modal combination of each response quantity | p635 | correct | - |
| Sec 8.3.6.5(a),(b), 8.3.6.4(d) (p. 1102), 8.3.6.6(c), (d)(i),(ii) (p. 1103) | wall_flanges.py:7-17,87-91,112 | flange width min(half distance, 25% hw); 300 mm into web | p1102,1103 | correct | - |
| 6.6.3.2-6.6.3.5 (p. 969) | walls.py:10-13,130-132,840 | minimum ratios, two layers > 250 mm, s <= min(3t, 450) | p969 | correct | - |
| 6.6.4, 6.6.5, Eq. 6.6.89, 6.6.5.3, 6.6.6.1 (p. 970) | walls.py:14-26,133-135,1085 | 0.55 phi f'c Ag[1-(k lc/32h)^2], k 0.8/1.0/2.0, phi 0.65, t >= lc/25, 100, 190 mm | p970 | correct | - |
| 6.4.8 (pp. 935-937): 6.4.8.3-6.4.8.9.5, Eq. 6.6.54, 6.6.68-6.6.71 | walls.py:27-36,136,628,641,843-844,1071,1398-1421 | d = 0.8lw, Vc, Vn <= 0.83, rho >= 0.0025, lw/5, lw/3 | p935,936,937 | correct | - |
| 6.4.8.1 (p. 935) | walls.py:37-40 | out-of-plane shear as slab | p935 | correct | - |
| 6.2.3.2.2, 6.2.3.2.4, 6.2.3.3(a),(c) (pp. 897-898) | walls.py:32,55,78,137,171-174,1085 | phi 0.65, 0.75, 0.60, 0.85 | p897,898 | correct | - |
| Sec 8.3.6 (pp. 1100-1107): 8.3.6.2-8.3.6.6(e), 8.3.5.4 (pp. 1097-1098), 8.3.3.4(c) | walls.py:44-73,138-141,155-170,602,660,696-697,922,1166,1204,1349 | alpha_c 0.25/0.17, 0.83 Acw, max(c-0.1lw, c/2), Ash 0.09, so = 100+(350-hx)/3 in [100,150], 2.8/fy, 200 mm | p1097,1098,1100-1104,1090 | correct | - |
| 8.3.6.7 (pp. 1105-1106), Eq. 6.8.11, (d)(ii), (d)(iv) | walls.py:74-79,140,1644 | Vn = 2 Avd fy sin a <= 0.83 Acw sqrt f'c; 4 bars; min(150, 6db) | p1105,1106 | correct | - |
| Sec 6.3.10 (pp. 910-915) | slender.py:3,1787 | slenderness basis | p910-915 | correct | - |
| Figure 6.6.5 (a), (b) | slender.py:12,216,232,844 | alignment charts | p910-911 | correct | - |
| Eq. 6.6.19-6.6.28; 6.3.10.6.1-6.3.10.6.3, 6.3.10.7.2-6.3.10.7.4 | slender.py:45-57,137-141,255-305,326,1206-1208,1273-1274,1570-1583,1818 | Pc, EI 0.4/0.2+EsIse over (1+beta_dns), beta <= 1, k = 1, Cm, M2,min = Pu(15+0.03h), delta_s, sum Pc with EI of 6.3.10.6.1 | p914,915 | correct | - |
| BNBC 6.3.10.2.1 | slender.py:69,102,1592 | M2nd <= 1.4 M1st | p912 | correct | - |
| "BNBC has no such clause" (klu/r 100); "BNBC 6.3.10.7.4 takes EI of 6.3.10.6.1 (beta_dns), ACI takes beta_ds" | slender.py:57,69-70,98 | statements about BNBC | p910-915 | correct | - |
| BNBC 6.1.7.1 / ACI 19.2.2.1 | slender.py:1751 | Ec = 4700 sqrt f'c | p892 | correct | - |
| Sec 8.3 / 2.5.5.6.1 / 2.5.5.6 / 2.5.13.4 | check.py:214,223,294,304 | Omega0 elements and combinations | p625,646 | correct | - |
| ACI 336.2R practice (combined footing strips) | footing.py:135 | transverse strip c + d | - | not in BNBC | ACI 336.2R (external practice document) |
| ACI 318-19 22.5.5.1.3 lambda_s "which BNBC does not have" | punching.py:11-13,77; footing.py:136 | BNBC has no size factor | p922,938 | correct | - |
| External (ACI 318-19) clause groups, see section 4 | rc.py, bars.py, slab.py, footing.py, check.py, required.py, proposal.py, lintels.py:116,385, punching.py:92,137,294,829 | ACI clauses | - | external | external standard, check against the owner's copy; BNBC equivalents in section 4 |


### 2. Wrong values (engineering impact)

1. **Column longitudinal steel ratio maximum 0.08 vs BNBC 0.06**: `codes/packs/bnbc2020/data/concrete.json:68` (`"columnRho": [0.01, 0.08]`, source line 139 "ACI 318 10.6.1.1 ... page not checked") and `design/bars.py:55` (`RHO_MIN, RHO_MAX = 0.01, 0.08`, used by required.py:108/562/683 and proposal.py:355). BNBC 2020 Part 6 Sec 6.3.9.1 (p. 910, text checked): "not less than 0.01Ag or more than 0.06Ag ... preferred not to exceed 0.04Ag unless absolutely essential". Change 0.08 -> 0.06 (and consider a warning above 0.04).
   Impact: for columns of ordinary and intermediate frames (SDC B/C, and columns outside the seismic system), the design mode can propose, and the bar search accepts, layouts with rho from 6% to 8%. BNBC does not allow these. The strength itself is computed correctly by strain compatibility, so the P-M capacity is not overstated. But the design does not comply with the code. At lap splices the steel would reach 12-16%, which cannot be placed or compacted properly, and BNBC's 6% cap (stricter than ACI's 8%, which already includes laps) is there for exactly that reason. Special moment frame columns already use 0.06 (detailing.json:10-13, Sec 8.3.5.3(a)), so only non-special columns are affected. If the fix is wanted, the "no layout with rho up to ..." messages (proposal.py:355, required.py:665) will then ask for larger sections 25% sooner.

No other number in the group differs from BNBC. These were checked against the BNBC text or rendered tables, all correct: phi factors (0.90/0.65/0.75/0.60/0.85), 0.004 strain limit, Vc 0.17, Av,min 0.062/0.35, fyt 420, Vs max 0.66, spacing d/2/600 halved, punching 0.17(1+2/beta)/0.083(alpha_s d/b0+2)/0.33 with 0.17/0.5/0.25/0.66 caps, walls (all ratios, Eq. 6.6.54/68/69/71/89, 0.83, 6.8.9-6.8.11), slenderness (22, 34-12M1/M2 <= 40, 0.05, 1.4, 1.5, 0.75 Pc, 15+0.03h, EI 0.4/0.2), cracked I factors, Tables 6.6.1 and 6.6.3, stair rules and live loads, Part 3/Part 4 stair geometry, seismic materials (21, 35, 125/20, 1.25, 700) and joints (1.25, 1.2, 1.7/1.2/1.0, 0.05).

Related observations (not wrong citations, but BNBC-specific points the code does not follow; low to medium priority):
- **Brick-aggregate x1.5 on minimum steel only in stairs.** BNBC 8.1.11.2(b) (p. 1075) requires 1.5 times the shrinkage/temperature (and through Sec 6.3.5.4, As,min of slabs, footings and rafts) for brick aggregate concrete. stairs.py applies it (stairs.py:859-861). `design/slab.py:395-400` `min_steel_ratio` and the footing minimum "0.0018 Ag (ACI 7.6.1.1)" (footing.py:141-142) do not. With brick chips, which are common in Bangladesh, slab and footing minimum steel is 33% below BNBC.
- **Default covers below BNBC 8.1.7.2 (p. 1069)** (concrete.json:101-105, "SAEngine assumptions when no reinforcement is entered"). Lintel 25 mm is below the 40 mm that BNBC sets for beams (8.1.7.2(c)): d is about 15 mm too large in the assumed section, slightly unconservative. Pile cap 50 mm is below the 75 mm that BNBC sets for concrete cast against earth (8.1.7.2(a)). It is 50 mm only if exposed to earth but cast on blinding (8.1.7.2(b), bars of 19 mm and larger). Stair 20 mm meets 8.1.7.2(c) for slabs.
- **phi transition: ACI 318-19 vs BNBC.** rc.py and bars.py use the ACI 318-19 limit eps_t >= eps_ty + 0.003. BNBC 6.3.3.4 / 6.2.3.2.2 (pp. 897, 906) is tension-controlled at eps_t >= 0.005, with the compression-controlled limit fy/Es (0.002 for Grade 420, 0.0025 for Grade 500). The ACI-19 rule is the same or more conservative: for fy 500 it ends the transition at 0.0055 instead of 0.005.
- **Shear Vc: ACI 318-19 vs BNBC.** The code uses the ACI 318-19 Table 22.5.5.1 size-effect formula (0.66 lambda_s rho^(1/3)) for members without Av,min, slabs and footings. BNBC 6.4.2.1.1 / Eq. 6.6.49 is always 0.17 sqrt f'c bw d, with no lambda_s in BNBC punching either. The ACI-19 rule is more conservative; the modules state this.
- **Column ties.** bars.py:28-29 and :482 flag Ø12 ties for bars over 32 mm (ACI needs Ø13). BNBC 8.1.9.4(a) (p. 1073) asks for "at least 12 mm diameter" for 36-57 mm bars, so Ø12 complies with BNBC and the flag is unnecessary under the BNBC pack.

### 4. External references (deduplicated; ACI 318-19 unless stated; check against the owner's copy)

| Clause | What for | Examples (file:line) | BNBC equivalent |
|---|---|---|---|
| 21.2.2, Table 21.2.2 | phi from eps_t (eps_ty + 0.003) | rc.py:9,83,590; bars.py:68,139; slab.py:72,131,374; check.py:67 | BNBC differs: 6.2.3.2, 6.3.3.3-6.3.3.4 (tension-controlled at 0.005); ACI-19 more conservative |
| 22.2, 22.2.2.1, Table 22.2.2.4.3 | stress block, eps_cu, beta1 | rc.py:6,47,74; walls.py:443; slab.py:373 | 6.3.2.3, 6.3.2.7, Eq. 6.6.7: same |
| 22.4.2.1, 22.4.2.2 | Pn,max 0.80/0.85 | rc.py:15,139,145; check.py:80 | 6.3.3.6, Eq. 6.6.8/6.6.9: same |
| 9.6.1.2, 9.6.1.3 | beam As,min, 4/3 rule | bars.py:148,154; required.py:446 | 6.3.5.1 Eq. 6.6.10, 6.3.5.3: same |
| 7.3.3.1, 8.3.3.1, 9.3.3.1 | eps_t >= 0.004 | slab.py:73,167,1473; bars.py:170; proposal.py:20,186; check.py:1325 | 6.3.3.5: same |
| 7.6.1.1, 8.6.1.1, 24.4.3.2, 7.6.4.1 | slab/footing As,min 0.0020/0.0018 | slab.py:132,398,1536-1575; footing.py:142; bars.py:18 | 6.3.5.4 -> 8.1.11.2(a): same ratios; BNBC adds x1.5 for brick aggregate (8.1.11.2(b)) |
| 7.7.2.3, 7.7.6.2.1, 8.7.2.2, 24.4.3.3 | slab bar spacing 3h / 5h / 2h, 450 | slab.py:1589-1591,1615; required.py:857-861; proposal.py:1503 | 8.1.6.5, 8.1.6.7 / 8.1.11.2(c), 8.1.6.6: same (6.3.5.4 allows 3h for slabs and footings) |
| 22.5, Table 22.5.5.1 (a),(c), 22.5.5.1.3 | Vc (size effect, rho_w^(1/3), lambda_s) | rc.py:12-13,478,496; bars.py:19,215,239; slab.py:140,387,1492; footing.py:123,136; required.py:907,973; check.py:72 | BNBC differs: 6.4.2.1.1 Eq. 6.6.49 Vc = 0.17 sqrt f'c bw d only; ACI-19 more conservative |
| 22.5.1.2 | Vs <= 0.66 sqrt f'c bw d | bars.py:231; proposal.py:31 | 6.4.3.6.9: same |
| 22.5.3.1, 22.6.3.1 | sqrt f'c <= 8.3 MPa | rc.py:499; bars.py:21; slab.py:529 | 6.4.1.2: same |
| 20.2.2.4 | fyt <= 420 | rc.py:499; bars.py:21; punching.py:92 | 6.4.3.2: same |
| 9.6.3.1, Table 9.6.3.1 | Av,min threshold 0.083 phi lambda sqrt f'c bw d; h <= 250 exemption | rc.py:483; check.py:1363,1366; lintels.py:116,385 | 6.4.3.5.1 (Vu > 0.5 phi Vc; (d) h <= 250 mm): equivalent |
| 9.6.3.4 | Av,min | rc.py:475,496; check.py:1341; bars.py:20 | 6.4.3.5.3 Eq. 6.6.55: same |
| 9.7.6.2.2 | s <= d/2, 600; halved above 0.33 | bars.py:22,227 | 6.4.3.4.1, 6.4.3.4.3: same |
| 22.5.8.5.3 | Vs = Av fyt d / s | bars.py:20 | Eq. 6.6.56: same |
| 25.2.1, 25.2.2, 25.2.3 | bar clear spacing | rc.py:197,252-373; bars.py:24-25,318,380,416; proposal.py:269,357; required.py:668 | 8.1.6.1-8.1.6.3: same |
| 25.7.2, 25.7.2.1-25.7.2.3, 25.7.3 | column ties, spirals | bars.py:26-30,473,482; proposal.py:24; required.py:577,714 | 8.1.9.4(a)-(c), 8.1.9.3; BNBC allows Ø12 for 36-57 mm bars |
| 10.6.1.1, 10.7.3.1 | column rho limits, bar count | bars.py:54,415; proposal.py:355; required.py:665,671; concrete.json:139 | BNBC differs: 6.3.9.1 (0.06, see section 2); 6.3.9.2 (4/3/6 bars) same |
| 6.2.5.1(a) | klu/r <= 22 | rc.py:55 | 6.3.10.1 Eq. 6.6.13: same |
| 6.2.5, 6.2.6, 6.6.4, 6.6.4.6.2 | slenderness; klu/r <= 100 | slender.py:57,69-70,98,1560,1787,1802 | 6.3.10; no klu/r 100 rule in BNBC (stated); 6.3.10.7.4 differs (stated) |
| 19.2.2.1 | Ec | slender.py:1751 | 6.1.7.1: same |
| 22.6, 22.6.2.1, 22.6.4.1, 22.6.5.2, Table 22.6.6.1, R22.6.4.2 | punching | slab.py:148-150,467,520-529,1321; footing.py:125,141; punching.py:29,33,294 | 6.4.10.1.2, 6.4.10.2.1 (Eq. 6.6.72-6.6.74), 6.4.10.5.1: same values (BNBC has no lambda_s) |
| 8.4.4.2, 8.4.4.2.3, R8.4.4.2.3 | gamma_v M c / Jc | slab.py:153,433,547; footing.py:127; punching.py:137,829 | 6.4.10.7, Eq. 6.6.77-6.6.80c; 6.5.5.3.2 Eq. 6.6.81 |
| 8.4.1.1-8.4.1.2, 8.4.1.5, 8.4.1.6, 8.4.1.8, 8.10.4.1, 8.11.6.1 | design strips, critical sections | slab.py:5,15,19,107,655,957 | BNBC 6.5 (not chased) |
| Table 7.3.1.1, 8.3.1.1, Table 8.3.1.1, 8.3.1.2 | minimum slab thickness | slab.py:159,565-647 | Table 6.6.1; 6.2.5.3.2 Table 6.6.3 (values in slab.py are BNBC's); 6.2.5.3.3 Eq. 6.6.5/6.6.6 (125/90 mm) same; BNBC 6.2.5.3.3(d) edge-beam +10% rule |
| 13.2.6.2, 13.2.7.1, 13.2.7.2, R13.2.7.1 | footing shear/flexure sections, circular columns | footing.py:94,123,128,136 | BNBC 6.8 footings (not chased) |
| 14.5.1.7, 14.5.2.1 | plain-concrete footing flexure | footing.py:131; required.py:1187 | BNBC 6.2.3.4 (phi 0.60); not chased |
| 23.7.2.1 | strut-and-tie tie phi As fy, phi 0.75 | required.py:1180 | 6.2.3.2.6 (phi 0.75): same |
| 2.2 | notation (effective depth) | footing.py:137 | - |
| ACI 336.2R | combined footing transverse strips | footing.py:135 | not in BNBC |
| ASCE 7-05 2.4.1, ASCE 7-16 2.4.1 | ASD combinations, strength-level wind 0.6W/0.45W | footing.py:98,100 | 2.7.2.1 (p. 684) for nominal wind |
| ASTM A1044 | stud fy 350 MPa | punching.py:88-90 | - |
| BDS ISO 6935-2 | bar sizes | concrete.json:136; bars.py:44 | 8.3.3.4(b) names BDS ISO 6935-2 grades |


## Appendix B: Seismic and loads

Files: design/seismic_rules.py, seismic_detailing.py, ductile_joints.py, ductile_members.py, overstrength.py; fem/** ; library/bnbc.py, settings.py, defaults.py, generator.py, objects.py, materials.py; codes/packs/bnbc2020/pack.json + data/{seismic,wind,zoneCoefficients,combinations,factors,areaLoads,occupancyCategories,locations}.json; codes/{template,tables,manifest,merge,context,registry}.py (all paths below are under python/src/saengine/).
638 hit lines in the group; generic mentions (pack name, "BNBC 2020", codes/*.py examples such as "BNBC Part 6 2.7.3") skipped. Every table value below was checked against the rendered page (Tables 6.2.3, 6.2.13-6.2.21, 6.2.8-6.2.12, Figs 6.8.1/6.8.2/6.8.8/6.8.17, Eq. 6.2.34 page).

**Counts:** checked=91 correct=82 wrong(number+value+clause)=7 (wrong number 4, wrong value 3; plus 1 uncited missing rule, the Eq. 6.2.34 Sa floor, in section 2) not-in-BNBC=1 could-not-find=0 external=1 (one merged row listing the external clauses; see section 4) markers(from memory etc.)=3 (all 3 verified correct: wind.json:46-47 "page not checked" Figure 6.2.6 is part1 p571 with Cp 0.8 / -0.5,-0.3,-0.2; seismic.json:336 eta=1 "page not checked" is Eq. 6.2.36, p613)

### 1. Citation table

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| Table 6.2.14 (p. 615) | zoneCoefficients.json:4,6; pack.json:35; bnbc.py:29,81 | Z = 0.12/0.20/0.28/0.36 for zones 1-4 | part1 p615, p611 | correct | - |
| Table 6.2.15 (p. 615) / Table 6.2.8 (p. 600) | locations.json:4-7; pack.json:34; bnbc.py:31 | 10 towns: zone + V (Dhaka 2/65.7, Chattogram 3/80, Cox's 3/80, Khulna 1/73.3, Rajshahi 1/49.2, Sylhet 4/61.1, Barisal 1/78.7, Rangpur 3/65.3, Mymensingh 4/67.4, Comilla 2/61.4) | p615, p600 | correct | - |
| Table 6.2.13 (p. 609) site classes | seismic.json:320; settings.py:120,885,902; bnbc.py:103 | SA-SE descriptions, Vs/N/su ranges; liquefiable -> S2 | p609-610 | correct | (table runs p609-610) |
| Table 6.2.16 (p. 616) | seismic.json:320; bnbc.py:60 | S/TB/TC/TD: SA 1.0/.15/.40/2; SB 1.2/.15/.50/2; SC 1.15/.20/.60/2; SD 1.35/.20/.80/2; SE 1.4/.15/.50/2 | p616 | correct | - |
| Table 6.2.17 (p. 616) | occupancyCategories.json:5,8; pack.json:36; bnbc.py:37 | I = 1.0 (I, II), 1.25 (III), 1.5 (IV) | p616 | correct | - |
| Table 6.2.9 (p. 601) wind importance | occupancyCategories.json:6,8; pack.json:36; bnbc.py:39 | 0.87/1.0/1.15/1.15 | p601 | correct | (only the non-cyclone column; cyclone-prone V>44 m/s gives 0.77 for Cat I: 0.87 is conservative) |
| Table 6.1.1 (p. 480 / pp. 480-481) | occupancyCategories.json:4,8; settings.py:95; generator.py:95,160,955; bnbc.py:89 | occupancy categories I-IV (III: assembly >300, schools, health care w/o surgery; IV essential) | p480 | correct | - |
| Sec 2.5.5.2, Table 6.2.18 (p. 617) | seismic.json:323; seismic_rules.py:7,40,176; seismic_design.py:106,119,212; generator.py:35 | SDC matrix (SA BCCD/CDDD ... SE DDDD), S1/S2 = SE row | p617 | correct | - |
| Sec 2.5.5.4, Table 6.2.19 (pp. 619-624 / 621-624) | seismic.json:321 + rows :50-186; seismic_rules.py:9,41,73,94-106; overstrength.py:14,51; settings.py:143; bnbc.py:52,98 | R/Ω0/Cd/limits: RC SMF 8/3/5.5 NL; IMF 5/3/4.5 D NP; OMF 3/3/2.5 C,D NP; special wall 6/2.5/5 D 50 m; ordinary wall 5/2.5/4.25 D NP; dual special 7/2.5/5.5; steel SMF 8/3/5.5; steel OMF 3.5/3/3 D NP; SCBF 6/2/5 D 50 m | p619, p622, p623 (rendered) | correct | ("C.5 [sic, the 6th row]" for RC OMF is right: BNBC misnumbers it 5) |
| Table 6.2.20 (p. 628) | seismic.json:322; bnbc.py:129 | Ct/m: RC MRF 0.0466/0.9; steel MRF 0.0724/0.8; other 0.0488/0.75 | p628 | correct | - |
| Sec 2.5.7, seismic weight W (p. 628) | seismic.json:326 (value :309); bnbc.py:143; generator.py:492,1226,1838; fem/derive.py:829; exporters/importers read it | liveShare = 0.25 of floor live load for every floor | p628 | wrong value | Sec 2.5.7 -> Sec 2.5.7.3(a)-(b); 25 % only for L <= 3 kN/m², at least 50 % for L > 3 kN/m² (see section 2) |
| Sec 2.5.9.4 (p. 635) | seismic.json:327; seismic_design.py:16,18,89,100,195,1094; settings.py:409,413 | RS scaled to 0.85 V (forces, not drifts); SRSS/CQC | p635 | correct | - |
| Sec 2.5.7.6.2 (p. 630), eq. 6.2.43 | seismic.json:328; seismic_design.py:22,92,101,311; settings.py:427-428 | accidental eccentricity 0.05 L, same direction all floors | p630 | correct | - |
| Sec 2.5.7.6.3 (p. 631) | seismic_design.py:29,976; settings.py:431 | 5 % shift in one direction at a time with orthogonal loading | p631 | correct | - |
| Sec 2.5.13.1(a)/(b) (p. 645) | seismic.json:329; seismic_design.py:41,44,94,102,149,225,1233; settings.py:420 | 100 % + 30 % in SDC D and C with irregularity type V; B independent | p645 | correct | - |
| Sec 2.5.9.2 (p. 634) | seismic.json:330; seismic_design.py:96,107 | 90 % modal mass | p634 | correct | - |
| Sec 2.5.5.3.1(i) (p. 617) | seismic.json:331-332; seismic_design.py:32,108,113,827; settings.py:430 | torsion irregular > 1.2, extreme > 1.4 | p617 | correct | - |
| Sec 2.5.7.6.2, eq. 6.2.44 (p. 630) | seismic.json:333; seismic_design.py:109,116,828,918 | Ax = (δmax/1.2δavg)² <= 3.0, only C/D irregular | p630-631 | correct | - |
| Sec 2.5.13.2 (p. 646), a_h = (2/3) Z S; eq. 6.2.56 (pp. 645-646) | seismic.json:334-335; seismic_rules.py:54,808; seismic_design.py:52,103,154,234,245; overstrength.py:11,50; settings.py:436; ssi.py:145 | Ev = 0.50 a_h D, a_h = (2/3) Z S | p645-646 | correct | - |
| Sec 2.5.13 (p. 644) | seismic_design.py:50,103 | E = Eh+Ev (comb. 5), Eh-Ev (comb. 7) | p644 | correct | - |
| Sec 2.5.13.4 (p. 646) | combinations.json:119; seismic_rules.py:16,53,807,846; overstrength.py:10,49; objects.py:210; seismic_design.py:56; seismic_detailing.py:73,332 | Em = Ω0 Eh ± Ev; 2.5.13.1(b) applies to Emh; plastic-mechanism cap | p646 | correct | - |
| Sec 2.5.5.6 / 2.5.5.6.1 / .6.2 / .6.3 / .6.4 (pp. 625-626) | seismic_rules.py:16,50-52,571,1076,1083; overstrength.py:5-9,48,52; objects.py:210 | discontinuous walls/frames (H-IV, V-IV) take Ω0; SDC D irregular +25 % connections; collectors C/D; batter piles | p625-626, p618 | correct | - |
| Table 6.2.21 (p. 648), Sec 2.5.14.1 (p. 647) | seismic.json:325; seismic_design.py:57-62,105,129,132,252; story_response.py:23,342,359; settings.py:452 | all other structures 0.020/0.015/0.010 h (I-II/III/IV); Δa/ρ moment frames SDC D, ρ 1.0-1.3; edges count | p647-648 | correct | - |
| Sec 2.5.7.7 (p. 631), Eq. 6.2.45 | seismic_design.py:57,105; second_order.py:680 | δx = Cd δxe / I | p631 | correct | - |
| Sec 2.5.7.9 (p. 632-633), Eq. 6.2.48/6.2.49 | second_order.py:36,63,660,675-686; settings.py:386,400 | θ = Px Δ/(Vx hsx Cd), Px factors <= 1.0, θmax = 0.5/(βCd) <= 0.25, β = 1 | p632-633 | correct | - |
| Sec 2.7.3.1 (p. 685) combinations | combinations.json:4,6,121-123; pack.json:38; seismic_design.py:50,104,970; settings.py:394,582,588; second_order.py:91; fem/derive.py:1439; thermal.py:504 | 1.4D; 1.2D+1.6L+0.5Lr; 1.2D+1.6Lr+(L or 0.8W); 1.2D+1.6W+L+0.5Lr; 1.2D+1.0E+1.0L (comb. 5); 0.9D+1.6W; 0.9D+1.0E (comb. 7); T with 1.2 in comb. 2 | p685 | correct | - |
| Sec 2.7.3.1 exception 1 | seismic_design.py:53; settings.py:444-445 | L factor 0.5 for L <= 5.0 kN/m² except garages/assembly | p685 | correct | - |
| Sec 2.7.2.1 combinations 2 and 4 with T | thermal.py:518 | D+H+F+L+T; D+H+F+0.75(L+T)+(Lr or R) | p684 | correct | - |
| Sec 2.6.4, 2.6.4(a) | thermal.py:3; settings.py:232,240,250 | temperature effects where significant; shade air temperature range; expansion joints | p678 | correct | - |
| Sec 2.4 (pp. 549-603) | wind.json:4,6; pack.json:40 | wind section range | p544-603 | wrong number | pp. 549-603 -> pp. 544-603 (Sec 2.4 starts p544) |
| Sec 2.5 (pp. 609-648) | seismic.json:4,6; pack.json:39 | seismic section range | p604-648 | wrong number | pp. 609-648 -> pp. 604-648 (Sec 2.5 starts p604) |
| Table 6.2.11 (p. 602) "and its α, zg" | wind.json:43; bnbc.py:146 | α/zg: A 7.0/365.76, B 9.5/274.32, C 11.5/213.36 | p602 | wrong number | values are right but they are Table 6.2.10 (Terrain Exposure Constants); Table 6.2.11 is the Kz table |
| Table 6.2.11 (Kz) | fem/loads.py:72 | Kz = 2.01 (max(z,4.57)/zg)^(2/α) | p602-603 (note 2) | correct | - |
| Table 6.2.12 (p. 603) | wind.json:44; bnbc.py:151 | Kd = 0.85 buildings | p603 | correct | - |
| Sec 2.4.8.1 (p. 553) | wind.json:45 | G = 0.85 rigid | p553 | correct | - |
| Figure 6.2.6 (page not checked) [marker] | wind.json:46-47; bnbc.py:156 | Cp windward 0.8; leeward -0.5 (L/B<=1), -0.3 (2), -0.2 (>=4) | p571 | correct | add page: "Figure 6.2.6 (p. 571)" |
| Wind exposure descriptions (with Sec 2.4 / Table 6.2.11 source) | wind.json:19 ("Flat open country, coastal"); bnbc.py:109-110 ("C - flat unobstructed areas and water surfaces, including coastal belts") | exposure C covers flat open country and the coast | p551 (Sec 2.4.6.2-2.4.6.3) | wrong value | C = flat unobstructed areas and water surfaces OUTSIDE cyclone-prone regions; flat open country and water in cyclone-prone (coastal) regions are B |
| η = 1 for 5 % (page not checked) [marker] | seismic.json:336; bnbc.py:140 | η = 1 | p613, Eq. 6.2.36 | correct | add "(Eq. 6.2.36, p. 613)" |
| Table 6.2.3 (pp. 533-539) | areaLoads.json:4,6; pack.json:37; bnbc.py:45,95; settings.py:557; generator.py:81,974 | 18 uses: residential 2.0, public 4.8, office 2.4, lobby 4.8, corridor 3.8, classroom **1.9**, patient room **1.9**, OR/lab 2.9, fixed seats 2.9, movable 4.8, retail 4.8/3.6, storage 6.0/12.0, parking **1.9**, stairs 4.8, roof 1.0, roof garden 4.8 | p533-537 (rendered 534, 536) | wrong value | classroom 1.9 -> 2.00, patient rooms 1.9 -> 2.00, garages 1.9 -> 2.0 (all others correct). Table spans pp. 533-538 |
| Sec 6.2.3.2 (p. 897), 6.2.3 (pp. 897-898) | factors.json:4,6; pack.json:42 | φ 0.90 tension, 0.65 tied, 0.75 spiral, 0.75 shear/torsion, 0.75 strut-tie | p897-898 | correct | - |
| Sec 6.2.3.3(a)/(c) (p. 898) | factors.json:20-22; ductile_joints.py:18,74 | φ shear 0.60 (shear-weak seismic members), 0.85 joints and diagonal coupling beams | p898 | correct | - |
| Eqs. 6.6.19 and 6.6.28 (φK = 0.75) | factors.json:23; settings.py:296-297 | 0.75 Pc in δns, δs | p914-915 | correct | - |
| Sec 6.3.10.4.1 (p 912) | second_order.py:8,83,328; settings.py:322,358,364,378 | 0.70 Ig col, 0.35 beam, 0.25 flat plate, walls 0.70/0.35, area 1.0 Ag, E of 6.1.7.1 | p912 | correct | - |
| Sec 6.1.10.2 (p 893); 2.5.9.1(a) | second_order.py:11; settings.py:360-361 | factored-lateral deflections use 6.3.10.4.1 properties; RS model cracked | p893, p634 | correct | - |
| Sec 6.3.10, 6.3.10.2.2, 6.3.10.4, 6.3.10.6, 6.3.10.6.3, 6.3.10.7 | settings.py:283,288,384-387; second_order.py:52-53,528 | slenderness; k = 1.0 permitted; δns along column | p912-915 | correct | - |
| Eq. 6.6.27 (δs <= 1.5), Sec 6.3.10.7.3 | settings.py:296; generator.py:449,837,910,1854 | δs = 1/(1-Q); above 1.5 second-order analysis | p915 | correct | - |
| Eq. 6.6.21 / 6.6.22 | settings.py:304-305 | EI = 0.4 EcIg/(1+βdns) or (0.2EcIg+EsIse)/(1+βdns) | p914 | correct | - |
| Table 6.6.1 (p. 900) + note (b) | generator.py:20-23,234,256,1044,1063,1118,1805 | slabs l/20,24,28; beams l/16,18.5,21; ×(0.4+fy/700) | p900 | correct | - |
| Sec 6.2.5.3.2 (p. 901), Table 6.6.3 (p. 902), (p. 903) | generator.py:24-27,231,261,1143,1260-1262 | ln/30, 33, 33 at 420 (33/36/36 at 280; 28/31/31 at 520), >=125 mm, ln face to face | p901-903 | correct | - |
| Sec 6.2.5.3.3 (p. 903), Eq. 6.6.5/6.6.6 | generator.py:28-31,1803 | αfm bands, 125/90 mm mins, +10 % edge | p903 | correct | - |
| Sec 1.2.7.3 | ssi.py:4; settings.py:488 | SSI included where required | p484 | correct | - |
| Sec 3.10.1.19 | ssi.py:50; settings.py:511 | group efficiency 1.0 | p751 | correct | (BNBC excepts friction piles in cohesive soil) |
| Eq 6.3.9 (Vesic), Sec 3.9.6.3 | ssi.py:60,70,336,819 | subgrade modulus, raft analysis | p736 | correct | - |
| Sec 1.8.5.1, 1.8.5.2(b) (p 507) | ductile_joints.py:36-37,1077 | piles: 8.3 detailing over 120 % flexural length; ties 10 % of larger load | p507 | correct | - |
| Sec 8.3.1 / 8.3.2(a)-(e) (pp. 1088-1089) | seismic_rules.py:2,11,38-39,109-110,758,779-783,941,952; ductile_members.py:13-17; seismic_detailing.py:53; generator.py:295,316; seismic.json:324 | D special (8.3.3-8.3.8), C intermediate (8.3.10), B ordinary (8.3.9); higher level allowed; no flat slab in SMF | p1088-1089 | correct | - |
| Sec 8.3.3.1 (c)/(d), 8.3.3.2 (p. 1089) | seismic_rules.py:42-43,780,1092; ductile_members.py:17,919 | below-base members; non-SFRS members to 8.3.9; φ per 6.2.3.2-6.2.3.4 | p1089 | correct | - |
| Sec 8.3.3.3 (p. 1089) | seismic_rules.py:44,112-115,347,358; seismic_detailing.py:9,54 | f'c >= 21 MPa; lightweight <= 35 MPa | p1089 | correct | - |
| Sec 6.1 definitions (p. 868), 6.1.8 (p. 893) | seismic_rules.py:48,116 | lightweight 1450-1850 kg/m³; λ | p868, p893 | correct | - |
| Sec 8.3.3.4(a)-(d) (pp. 1089-1090) | seismic_rules.py:45,118-133,301,388-492; materials.py:79,85; ductile_members.py:46 | A706 Gr 420 or BDS ISO 6935-2 300/350/400/420, A615 275/420; fy,act <= fy+125 (+20); fu/fy >= 1.25; elongation 14/12/10 %; fyt conf <= 700; shear fy per 6.4.3.2 | p1090 | correct | - |
| Sec 6.4.3.2 (p. 924) | seismic_rules.py:49,132; ductile_joints.py:707 | shear fy, fyt <= 420 MPa | p924 | correct | - |
| Sec 8.3.3.5 (p. 1090); 8.3.4.2(b), 8.3.5.3(b) splices (pp. 1091, 1096) | seismic_rules.py:46-47,499-510 | no welding except 8.3.4.2(d)/8.3.5.3(b); alternate bars, 600 mm, not within 2h | p1090-1091, p1096 | correct | (8.3.3.5 itself cites "8.3.4.2(d)", which does not exist in BNBC; ACI-inherited typo, not SAEngine's) |
| Sec 8.3.4.1(a)-(d), Figure 6.8.1 (pp. 1090-1091) | ductile_members.py:22-27,844; generator.py:32-33,1073,1373; seismic_detailing.py:57 | Pu <= 0.1Agf'c; ln >= 4d; b/h >= 0.3; b >= 250; b <= c2+2min(c2,0.75c1) | p1090-1092 (fig rendered) | correct | - |
| Sec 8.3.4.2(a), Figure 6.8.2 | ductile_members.py:28-32,553; generator.py:458 | ρ >= max(0.25√f'c,1.4)/fy (text prints f'c, figure √f'c), <= 0.025; 2 bars; Mn+ >= Mn-/2; >= Mmax/4 | p1091-1092 (rendered) | correct | - |
| Sec 8.3.4.2(b), Figure 6.8.3 / 6.8.8 | ductile_members.py:33-34; objects.py:165 | hoops over laps <= min(d/4, 100 mm) | p1091, p1093 | correct | - |
| Sec 8.3.4.3 (a)-(c) | ductile_members.py:35-38; objects.py:150; seismic_detailing.py:58 | hoops over 2h, first <= 50 mm, <= min(d/4, 8db, 24dh, 300), d/2 elsewhere | p1093 | correct | - |
| Sec 8.1.9.4(c) | ductile_members.py:37-38 | corner + alternate bars held, <= 150 mm clear | p1074 | correct | - |
| Sec 8.3.5.1(a)-(b) (p. 1095) | ductile_members.py:41; generator.py:33,1819; ductile_joints.py:72 | least dim >= 300 mm, ratio >= 0.4, Pu > 0.1Agf'c | p1095 | correct | - |
| Sec 8.3.5.2 (b)/(c), Eq. 6.8.5 (p 1096) | ductile_joints.py:11-17,69,192,447-486; seismic_detailing.py:13,69,139,602; generator.py:454,1858 | ΣMnc >= 1.2 ΣMnb; failing: full-height confinement, ignore strength (8.3.5.2(a),(c)) | p1096 | correct | - |
| Sec 8.3.5.3(a)/(b), Figure 6.8.8 | ductile_members.py:42-43 | 0.01 <= ρg <= 0.06; laps centre half; ties <= min(b/4, 100) | p1096, p1099 (rendered) | correct | - |
| Sec 8.3.5.4(a)-(f), Eq. 6.8.6-6.8.8, Eq. 6.6.12 | ductile_members.py:44-52,763,769,1159,1172; seismic_detailing.py:59-60; objects.py:150 | ρs >= max(0.12f'c/fyt, 0.45(Ag/Ach-1)f'c/fyt); Ash 0.3/0.09; so = 100+(350-hx)/3 in [100,150]; <= b/4, 6db; hx <= 350; lo >= max(h, ln/6, 450); first so/2; elsewhere min(6db, 150); (e) full height | p1097-1099 | correct | - |
| Sec 8.3.6.6, 8.3.6.6(d)(iii), 8.3.6.7 | objects.py:274,294-295,305 | special boundary elements, hoops; coupling beams | p1102-1106 | correct | - |
| Sec 8.3.7.1(a)-(d), 8.3.7.2(b) | ductile_joints.py:18-23,62-63,507-512,613-646; seismic_detailing.py:140-142,351,401 | 1.25 fy; column >= 20 db (26 lightweight); bars to far face; half hoops, 150 mm with 4 confining members >= 3/4 width | p1108-1109 | correct | - |
| Sec 8.3.7.3 (p 1110) | ductile_joints.py:19-21,76,509,614,654; seismic_detailing.py:70,140 | Vn = 1.7 / 1.2 / 1.0 √f'c Aj; face confined at >= 3/4 cover; φ 0.85 | p1110 | correct | (BNBC 1.2, not ACI's 1.25; code uses 1.2) |
| Sec 8.3.7.4(a)-(c), Eq. 6.8.12 (p 1111) | ductile_joints.py:23,541-546,642 | ldh >= max(8db, 150, fy db/(5.4√f'c)); LW 10db, 190, 1.25×; 10-36 mm bars | p1111 | correct | (BNBC text says "Eq. 6.8.9", the printed formula is 6.8.12, as the docstring notes) |
| Mpr notation (p 882); Sec 8.3.8.1(a)/(b) (p 1111) | ductile_joints.py:9,63,206,757-785,850-870,914; seismic_detailing.py:71,143-144,516,771 | Mpr at 1.25 fy, φ = 1; Ve = ΣMpr/ln + Vg; columns over axial range, capped by beams' Mpr, >= analysis shear | p882, p1111 | correct | - |
| Sec 8.3.8.2(a) (p 1112) | ductile_joints.py:25-29,78,689-703; seismic_detailing.py:72 | Vc = 0 if EQ shear >= Ve/2 and Pu < 0.05 Ag f'c | p1112 | correct | - |
| Sec 8.3.9.1(a)/(b), 8.3.9.2 (p 1113) | ductile_members.py:64-70,469-480,938; ductile_joints.py:40,734,1097,1127,1198-1208; seismic_detailing.py:14,63,716,833; objects.py:150 | twice lateral displacement; ties so <= min(8db, 24dt, b/2), lo >= max(ln/6, hmax, 450), first so/2, <= 2so | p1113 | correct | - |
| Sec 8.3.10.1-8.3.10.6 (pp. 1114-1117), Figure 6.8.17 | ductile_members.py:54-62; seismic_detailing.py:61,516,879; ductile_joints.py:30,763,798,855,886; seismic_rules.py:1050-1053 | IMF: shear = smaller of Mn-based and 2E; beams Mn+ >= Mn-/3, /5; stirrups 2h, 50 mm, min(d/4, 8db, 24ds, 300), d/2; columns so <= min(8db, 24dt, b/2, 300), lo >= max(ln/6, hmax, 450); Pu <= 0.1 -> 8.3.10.4 | p1114-1116 (Fig 6.8.17 rendered) | correct | - |
| Sec 8.3.11.1-8.3.11.4 (pp. 1120-1122) | ductile_joints.py:33-35,995-1078; seismic_rules.py:1059 | bars developed into footing with 90° hooks; 8.3.5.4 ties near footing edge; grade beam ties <= min(b/2, 300); piles 5×dim / 1.8 m | p1120-1121 | correct | - |
| Sec 8.2.6 (p 1079) | ductile_joints.py:34,979,998,1010 | ldh of standard hooks | p1079 | correct | - |
| Sec 8.3.12.1-8.3.12.4 (pp. 1122-1124) | ductile_joints.py:39,1095,1116-1181; ductile_members.py:72-75,478; seismic_detailing.py:615,716,746-749; seismic_rules.py:958,1065; objects.py:202 | SDC D gravity members: 8.3.12.2 (a) Pu <= Agf'c/10, (b) so <= min(6db, 150), (c) > 0.35Po half Ash; 8.3.12.3 if not computed; flat slabs 8.3.12.4 | p1122-1124 | correct | (BNBC 8.3.12.1 itself points to "8.3.12.5"; the slab rule is 8.3.12.4, as the code says) |
| Sec 8.3 (pp. 1088-1122 / 1088-1123) | pack.json:44; seismic_rules.py:2; ductile_*.py:1-6; seismic_detailing.py:1 | Sec 8.3 page range | p1088-1124 | wrong number | pack.json:44 "pp. 1088-1122" -> "pp. 1088-1124" (8.3.12.4 is on p1124); the "1088-1123" ones likewise -> 1088-1124 |
| Sec 8.3.3 (pp. 1089-1090) materials | pack.json:41 | material rules | p1089-1090 | correct | - |
| Table 6.3.10a (p. 750) | pack.json:46 | deep foundation FS | p750 | correct | - |
| Sec 6.4.10.3, 6.4.10.5 | objects.py:242 | stirrups / headed studs for punching | p938-941 | correct | - |
| Sec 6.6.5.2, 6.6.3.4, 6.6.5.3 | objects.py:490,495,499 | wall k factors (braced, restrained); basement walls single layer exception / 190 mm | p969-970 | correct | - |
| Sec 6.7.1.1 (a)-(d) | objects.py:518 | stair effective span cases | p972 | correct | - |
| Sec 10.10, Table 6.10.10 | objects.py:351,359 | bolted connections, bolt grade table | p1183, p1187 | correct | - |
| Sec 8.2.3, 8.2.3.2, 8.2.3.3, Eq. 6.8.1 | settings.py:675-677 | development length simplified / general | p1076-1077 | correct | - |
| CONCRETE_DENSITY 2400 kg/m³ "~23.6 kN/m³ (BNBC 2020 Part 6)" | defaults.py:31 | RC unit weight 23.6 kN/m³ | p530 Table 6.2.1 | not in BNBC | BNBC Table 6.2.1 (p. 530) gives stone-aggregate concrete 22.8 kN/m³ + 0.63 per 1 % steel (23.4 at 1 %, 24.1 at 2 %), brick-aggregate 20.4; 23.6 is the ACI/practice figure. Cite "Table 6.2.1 (p. 530)" with that rule |
| External standards (ACI/ASCE/AISC/FEMA/WSDOT) | see section 4 | - | - | external | external standard, check against the owner's copy |

### 2. Wrong values (engineering impact)

1. **Seismic weight live load share fixed at 25 %** (seismic.json:309 `"liveShare": 0.25`, used by fem/derive.py:829-832, generator.py:1226, exporters/etabs.py:1578, importers/etabs.py:1107). BNBC Sec 2.5.7.3 (p628): (a) at least 25 % for L <= 3 kN/m², **(b) at least 50 % for L > 3 kN/m²**, (c) 100 % of permanent equipment and retained liquid (that part is in mep loads, not checked here). Floors with L > 3 kN/m² in the pack: storage 6/12, lobbies/corridors 4.8/3.8, assembly 4.8, retail 4.8/3.6, stairs 4.8, roof gardens 4.8, public residential rooms 4.8. **Unconservative**: equivalent static base shear, RS masses, P-delta and drift are too low on those floors. Example: heavy storage, 12 kN/m², dead + SD about 7 kN/m²: W = 7 + 3 = 10 vs 7 + 6 = 13 kN/m², that floor's mass -23 %; for a commercial podium (4.8 kN/m²) W is about 7 + 1.2 vs 7 + 2.4, -13 %. Fix: make the share depend on the floor's live load (0.25 when L <= 3.0, 0.50 above), per area use.
2. **Live loads 5 % low** (areaLoads.json:30 classroom 1.9, :34 hospital patient rooms 1.9, :66 parking 1.9). Table 6.2.3 (p534, p536, rendered): classrooms **2.00**, patient rooms **2.00**, garages (passenger vehicles) **2.0** kN/m². 1.9 is ASCE 7's 40 psf (1.92). **Unconservative by 5 %** on the live load of schools, hospitals and car parks (beams, slabs, columns and footings in gravity combinations; about 2-3 % on 1.2D+1.6L). The generator's "live load below the Table 6.2.3 minimum" check (generator.py:974) uses the same low values.
3. **Missing lower bound on Sa (not a cited clause, but a rule of the cited spectrum).** BNBC Eq. 6.2.34 (p612, rendered): Sa >= 0.67 β Z I S with β = 0.11 (= 0.0737 Z I S). `fem/loads.py:48-52 design_acceleration` and the RS spectrum built from it (fem/derive.py:1037, 1301; generator.py:483) have no floor. **Unconservative for long periods**: with R = 8, SD, T = 4 s the formula gives Sa = 0.028 Z I vs the floor 0.0995 Z I (3.5× low); for R = 8 the floor governs from about T = 2.7 s on SD (earlier with lower S·TC). Hits tall or flexible buildings, the RS spectrum tail and so the 85 % scaling base. Fix: `max(..., 0.67*0.11*z*importance*S)`, β in the pack.
4. **Wind exposure C description** (wind.json:19 "Flat open country, coastal"; bnbc.py:109-110 "C - ... including coastal belts"). BNBC Sec 2.4.6.2-2.4.6.3 (p551): flat open country and water surfaces in cyclone-prone regions are **B**; C is flat unobstructed areas and water surfaces **outside** cyclone-prone regions. Engineers following the label pick C for coastal sites: conservative (Kz about +15-20 %), but the wrong exposure is reported, and an inland flat site described as "open country" might be taken as C or B inconsistently. Text fix only.

Not wrong but noted: Table 6.2.9 wind I for category I is 0.77 in cyclone-prone regions with V > 44 m/s; the pack uses 0.87 everywhere (conservative). Group efficiency 1.0 (Sec 3.10.1.19) excludes friction piles in cohesive soils.

### 4. External references (not verifiable here: external standard, check against the owner's copy)

- ACI 318-19 18.8.4.3: joint effective width bj (ductile_joints.py:567,615; seismic_detailing.py:70). BNBC 8.3.7.3 gives no bj.
- ACI 318-19 Table 18.8.4.1 / 18.8.4.3: joint confinement by beam depth; lower coefficients at a column end (ductile_joints.py:513,655). BNBC differs: 8.3.7.3 1.7/1.2/1.0, no depth condition.
- ACI 318-19 18.7.3.2: slab bars in ΣMnb (ductile_joints.py:454).
- ACI 318-19 18.2.7: Type 1/2 mechanical splices (seismic_rules.py:508).
- ACI 318-19 22.5.2.2: d = 0.8D for circular sections (ductile_members.py:730; ductile_joints.py:819).
- ACI 318-19 Eq. 22.5.6.1: axial increase of Vc (ductile_joints.py:857).
- ACI 318-19 6.6.3.1.1 / Table 6.6.3.1.1(a): cracked I (second_order.py:8,83). BNBC equivalent: Sec 6.3.10.4.1, p912, same values.
- ACI 318-19 6.6.4.5: nonsway magnification (second_order.py:52-53). BNBC equivalent: Sec 6.3.10.6, same.
- ACI 318-19 20.2.2.2: Es = 200,000 MPa (defaults.py:29). BNBC equivalent: Sec 6.1.7.2, same value.
- ACI 318-08 (joint confinement by width only, ductile_joints.py:512).
- AISC 360-22 (defaults.py:29; settings.py:56), generic.
- ASCE 7 (SDS/2.5, 0.2 SDS D) for comparison only (overstrength.py:14; ssi.py:146).
- ASCE 7-05 Table 19.2-1: G/G0 ratios 0.81/0.64/0.49/0.42 at 0.10/0.15/0.20/0.30 g (ssi.py:102,156,609; settings.py:502).
- ASCE 41-06 Sec 4.4.2.1.2: footing springs and embedment factors (ssi.py:24,235,251,743,899; settings.py:488,517).
- FEMA 356, Gazetas 1991 (ssi.py:24); Imai & Tonouchi 1982 Vs = 97.0 N^0.314 (settings.py:500); WSDOT BDM M 23-50.24 (2025) Sec 7.2.7 Tables 7.2.7-1/-2 (ssi.py:26).


## Appendix C: Steel

Files: python/src/saengine/design/steel/** , design/steel_design.py, design/steel_connections.py, design/steel_proposal.py, codes/packs/bnbc2020/data/steel.json, library/steel_sections.py, library/section_designer.py (paths below relative to python/src/saengine/).

Page convention: the steel files cite **Gazette** pages ("p 3841"); Gazette = part2 pdf page + 3781 (so p 3841 = part2 p60). steel_connections.py / steel.json / steel_proposal.py cite **part2 pdf** pages ("p. 130"). Both conventions checked; all page numbers found right.

**checked=73 correct=54 wrong(number+value+clause)=3 not-in-BNBC=6 could-not-find=0 external=10 markers(from memory etc.)=6**

Overall: the Ch 10 implementation is a faithful transcription of BNBC 2020 Part 6 Ch 10 (which is AISC 360-05 renumbered). Every phi factor, width-thickness limit, equation coefficient, table value and equation number used in design/steel/** and steel_connections.py was compared against the rendered BNBC pages and matches. The errors are in section_designer.py (two RC clause numbers) and one stand-in slenderness limit.

### 1. Citation table

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| BNBC 2020 Part 6 Ch 10, Gazette Feb 11 2021 pp 3825-3880 | design/steel/members.py:1-2 | scope of the member provisions | part2 p44-p99 | correct | - |
| Sec 10.2.3.12 (p 3824): ERW design wall t = 0.93 t, SAW nominal | design/steel/properties.py:15,34,351,397 | 0.93 | part2 p43 | correct | - |
| Sec 10.2.4.2(a),(d): flat widths less corner radius, else outside - 3t | design/steel/properties.py:13-14,299; classify.py:6-9 | widths for λ | part2 p45 | correct | - |
| Sec 10.2.4 / Table 6.10.1 (pp 3825-3829) | design/steel/classify.py:1-2,23,34,62,95,122 | λp/λr: case 1 0.38/1.0; 3 0.56; 5 0.45; 6 0.54/0.91; 7 0.38/1.0; 8 0.75; 9 3.76/5.70; 10 1.49; 12 1.12/1.40; 13 2.42/5.70; 14 1.49; 15 0.11E/Fy, 0.07E/Fy / 0.31E/Fy (all √(E/Fy) except case 15) | part2 p44-48 (rendered) | correct | - (note: BNBC Table 6.10.1 case 15 prints λp = "0.07√(E/Fy)", a misprint of AISC 0.07E/Fy; the code's 0.07E/Fy is right, keep it) |
| Eq 6.10.26 r̄o², Eq 6.10.27 H | design/steel/properties.py:82,87 | r̄o² = xo²+yo²+(Ix+Iy)/A; H = 1-(xo²+yo²)/r̄o² | part2 p62 | correct | - |
| Sec 10.3.1.2.1: K = 1.0 braced frames / shear walls | design/steel/lengths.py:31; members.py:84 | K = 1.0 | part2 p46 | correct | - |
| Sec 10.3.2.2.2(a), Eq 6.10.9: K = 1 by first-order analysis if αPr ≤ 0.5 Py | design/steel/lengths.py:32-33; members.py:1145 | α = 1.0, 0.5 Py | part2 p53 | correct | - |
| Sec 10.6.1, p 3853: Cb = 1.0 for cantilevers with free end unbraced | design/steel/lengths.py:20-22,345 | Cb = 1.0 | part2 p72 | correct | - |
| K = 2.0 for compression of a cantilever segment (cited with "Sec 10.6.1") | design/steel/lengths.py:20,345 | K = 2.0 | part2 p71-72, p46-53 | not in BNBC | theoretical value (AISC 360 Commentary App. 7 Table C-A-7.1: 2.0 theoretical, 2.1 recommended); BNBC Sec 10.6.1 covers only Cb. Reword so the clause attaches to Cb only (see sec 3) |
| Eq 6.10.55 (p 3852): Cb = 12.5Mmax/(2.5Mmax+3MA+4MB+3MC)·Rm ≤ 3.0, Rm = 1.0 | design/steel/lengths.py:37-39,189 | coefficients, cap 3.0 | part2 p71 | correct | - |
| Sec 10.4 (pp 3834-3838), Eqs 6.10.11-13: φt 0.90 Fy Ag, φt 0.75 Fu Ae, Ae = An U | design/steel/members.py:6-8,77,183,201; steel.json phi.tensionYield/Rupture | 0.90 / 0.75 | part2 p53-55 | correct | - |
| Table 6.10.2 defaults: Case 7 bf ≥ 2/3 d 0.90 else 0.85; Case 8 0.60; Case 6 RHS x̄ = (B²+2BH)/(4(B+H)); Case 5 CHS 1 - x̄/l, x̄ = D/π; Case 1 1.0 | design/steel/members.py:78-79,144-175 | U values | part2 p56-57 (rendered) | correct | - (channel U = 0.85 is a stated assumption, not a table value; tee: see sec 2 note on d) |
| Sec 10.4.3.3: U ≥ 0.60 for single/double angles, WT | design/steel/members.py:153 | 0.60 | part2 p55 | correct | - |
| Sec 10.4.1: L/r ≤ 300 (tension) | design/steel/members.py:10,71,1115; steel.json:20,26 | 300 | part2 p53 | correct | - (BNBC writes the limit as KL/r) |
| Sec 10.5 (pp 3840-3851): φc = 0.90 | design/steel/members.py:11; steel.json phi.compression | 0.90 | part2 p59 | correct | - |
| Eqs 6.10.16-19 (Sec 10.5.3, part2 p. 60): Fcr = 0.658^(Fy/Fe)Fy if Fe ≥ 0.44Fy else 0.877Fe | design/steel/members.py:11-12,211,300; steel_proposal.py:138-139,155; steel_connections.py:31-32,596 | 0.658, 0.44, 0.877 | part2 p60 | correct | - |
| Sec 10.5.4, Eqs 6.10.20-30 (6.10.21 tees, 6.10.22 Fcrz, 6.10.23 doubly symmetric torsional, 6.10.24 singly symmetric) | design/steel/members.py:12-14,263,269,278,321,334,339 | Fe formulas | part2 p60-62 | correct | - |
| G = 77200 MPa, Sec 10.5.4 (p 3843) | design/steel/members.py:64; steel_proposal.py:43 | 77 200 | part2 p62 | correct | - |
| Sec 10.5.5(a), Eqs 6.10.31-32: KL/r = 72 + 0.75 L/ra (≤ 80), 32 + 1.25 L/ra | design/steel/members.py:14-15,292,311-314 | 72/0.75, 32/1.25, break 80 | part2 p63 | correct | - (BNBC caps Eq 6.10.32 at 200; code does not cap: conservative) |
| Sec 10.5.2 (p 3841): KL/r ≤ 150 | design/steel/members.py:18-19,70,1135; steel.json:19,26 | 150 | part2 p60 | correct | - (BNBC differs from AISC 360's 200 recommendation; 150 is the BNBC value) |
| Sec 10.5.7, Eqs 6.10.36-54: Qs (6.10.39-41: 0.56/1.03, 1.415-0.74, 0.69E; 6.10.45-47: 0.45/0.91, 1.34-0.76, 0.53E; 6.10.48-50: 0.75/1.03, 1.908-1.22, 0.69E); be (6.10.52 k 0.34, 6.10.53 k 0.38, 1.92t); Qa CHS 0.038E/(Fy D/t)+2/3 (6.10.54); f = Fcr at Q = 1 (p 3850); D/t < 0.45E/Fy (10.5.7.2(c)) | design/steel/members.py:16-18,211-250,345,358,376,381 | coefficients | part2 p66-70 (rendered) | correct | - |
| Sec 10.6 (pp 3851-3869): φb = 0.90 | design/steel/members.py:20; steel.json phi.flexure | 0.90 | part2 p70 | correct | - |
| Sec 10.6.2, Eqs 6.10.56-63: Lp = 1.76 ry√(E/Fy); Lr = 1.95 rts E/(0.7Fy)√(Jc/Sxho)√(1+√(1+6.76(...)²)); Fcr 0.078; rts² = √(IyCw)/Sx; c = 1 / (ho/2)√(Iy/Cw) | design/steel/members.py:21-22,432,447 | coefficients | part2 p73-74 (rendered) | correct | - |
| Sec 10.6.3.2, Eqs 6.10.64-65: FLB, 0.9 E kc Sx/λ², kc 0.35-0.76 | design/steel/members.py:22,382-383,454,457 | coefficients | part2 p75 (rendered) | correct | - |
| Sec 10.6.4, Eqs 6.10.66-78: Rpc, Mp ≤ 1.6 Sxc Fy, FL = 0.7Fy, Lp = 1.1 rt√(E/Fy), Lr 1.95/6.76, rt Eq 6.10.75 | design/steel/members.py:23,484,503,510,513 | coefficients | part2 p76-78 (rendered) | correct | - |
| Sec 10.6.5, Eqs 6.10.81-89: Rpg = 1 - aw/(1200+300aw)(hc/tw-5.7√(E/Fy)) ≤ 1, aw ≤ 10, Lr = π rt√(E/0.7Fy), 0.3Fy | design/steel/members.py:23,521,530,537,542 | coefficients | part2 p80-81 (rendered) | correct | - |
| Sec 10.6.6, Eqs 6.10.91-94: Mp = FyZy ≤ 1.6FySy, Fcr 0.69E/(bf/2tf)² | design/steel/members.py:24,722,727,731,739 | 1.6, 0.69 | part2 p82 (rendered) | correct | - |
| Sec 10.6.7, Eqs 6.10.95-99: 3.57 b/t√(Fy/E) - 4.0; be 1.92t, 0.38; 0.305 h/tw√(Fy/E) - 0.738 | design/steel/members.py:24-25,585,588,595,600,603,610 | coefficients | part2 p83 (rendered) | correct | - |
| Sec 10.6.8, Eqs 6.10.100-103: (0.021E/(D/t)+Fy)S; Fcr = 0.33E/(D/t); D/t < 0.45E/Fy | design/steel/members.py:25,563,567,573,578 | coefficients | part2 p83-84 (rendered) | correct | - |
| Sec 10.6.9, Eqs 6.10.104-111: Mp ≤ 1.6My stem in tension, ≤ My stem in compression; B = ±2.3(d/Lb)√(Iy/J); Fcr = Fy(1.19-0.50λ√(Fy/E)); 0.69E/λ² | design/steel/members.py:25-26,636,640,646,649 | coefficients | part2 p84-85 (rendered) | correct | - |
| Sec 10.6.10, Eqs 6.10.112-120: 1.5My; My = 0.80 FyS unrestrained; Me = 0.66Eb⁴tCb/L²(√(1+0.78(Lt/b²)²) - 1) (Eq 6.10.115a, toe in compression); 0.92-0.17, 1.92-1.17 ≤ 1.5My; Cb ≤ 1.5; 2.43-1.72; 0.71E | design/steel/members.py:26,661,673,681,684,690,693 | coefficients | part2 p85-87 (rendered) | correct | - |
| Sec 10.7 (pp 3873-3878), Eqs 6.10.136-140: Vn = 0.6FyAwCv; rolled I h/tw ≤ 2.24√(E/Fy) → φv 1.0, Cv 1.0; else φv 0.90, Cv 1.10/1.37, 1.51Ekv/((h/tw)²Fy); kv 5 (h/tw < 260), 1.2 tee stems; Aw = d tw | design/steel/members.py:27-29,68,751,785,791,799,809; steel.json phi.shear | 0.90/1.00 etc. | part2 p92-93 (rendered) | correct | - |
| Sec 10.7.4: single angle Cv = 1.0, Aw = b t | design/steel/members.py:29,818,865 | Cv 1.0 | part2 p96 | correct | - |
| Sec 10.7.5: RHS Aw = 2ht, kv = 5 | design/steel/members.py:30,836 | 2ht, 5 | part2 p96 | correct | - |
| Sec 10.7.6, Eqs 6.10.145-146: Vn = FcrAg/2, 1.60E/(√(Lv/D)(D/t)^1.25), 0.78E/(D/t)^1.5, ≤ 0.6Fy | design/steel/members.py:30-31,771 | coefficients | part2 p96-97 (rendered) | correct | - (Lv = segment length is ≥ the code's Lv: conservative, as stated) |
| Sec 10.7.7: weak-axis Aw = bf tf, kv = 1.2 | design/steel/members.py:31,855 | 1.2 | part2 p97 | correct | - |
| Sec 10.8.1 (pp 3879-3880), Eqs 6.10.147a/b: Pr/Pc ≥ 0.2: P + 8/9(Mx+My); else P/2 + Mx + My; tension Pc = φtPn | design/steel/members.py:32-33,92,881-887,1216,1231 | 0.2, 8/9 | part2 p98-100 | correct | - |
| "H1-1 interaction (from memory of AISC 360)" [marker] | design/steel_proposal.py:156,186-188 | 0.2, 8/9 | part2 p98 | correct | BNBC equivalent: Sec 10.8.1.1 Eqs 6.10.147a/b, same values (see sec 3) |
| Sec 10.8.2 (unsymmetric members) not applied to single angles | design/steel/members.py:1232 | - | part2 p101 | correct | - |
| Sec 10.3.2.1, Eqs 6.10.4/6.10.6/6.10.7 (p 3832): B1 = Cm/(1-αPr/Pe1) ≥ 1, α = 1.0 LRFD; Cm = 0.6-0.4M1/M2, 1.0 with transverse load; Pe1 = π²EI/(K1L)² | design/steel/members.py:34-36,92,891,900-901,1254 | α 1.0, 0.6/0.4 | part2 p50-51 | correct | - |
| Sec 10.8.3 torsion; Sec 10.12 serviceability | design/steel/members.py:94-95 | headings | part2 p103, Sec 10.12 | correct | - |
| Sec 10.10 connections (LRFD) | design/steel_connections.py:1-2; steel_design.py:32 | scope | part2 p109 | correct | - |
| Sec 10.10.3.6 Eq 6.10.168, φ 0.75; Table 6.10.10 (p. 127, 130): A307 310/165, A325-N 620/330, A325-X 620/414, A490-N 780/414, A490-X 780/520 | design/steel_connections.py:26-27,61-67,137,272,398,527; steel.json:14,25 | φ 0.75, Fnt/Fnv | part2 p127, p130 (rendered) | correct | - |
| Sec 10.10.3.10 Eq 6.10.173a (p. 132-133): φ0.75 · min(1.2 Lc t Fu, 2.4 d t Fu) | design/steel_connections.py:27-28,142,285,295,406,414,538,548; steel.json:15,25 | 1.2 / 2.4, φ 0.75 | part2 p132-133 (rendered) | correct | - |
| Table 6.10.11 standard holes M16 18, M20 22, M22 24, M24 27, M27 30, M30 33, ≥ M36 d+3 | design/steel_connections.py:28,79-80,119 | hole sizes | part2 p128 (rendered) | correct | - |
| Sec 10.10.3.3: min spacing 2⅔ d | design/steel_connections.py:28,186,188 | 2⅔ d | part2 p128 | correct | - |
| Table 6.10.12 min edge distance (sheared 28/34/38/42/48/52/64, rolled 22/26/28/30/34/38/46; > 36: 1.75d / 1.25d) | design/steel_connections.py:28,81-82,129,189-190 | table values | part2 p128-129 (rendered) | correct | - |
| Sec 10.10.3.5: max edge distance 12 t ≤ 150 mm | design/steel_connections.py:28-29,197 | 12t, 150 | part2 p129 | correct | - |
| Sec 10.10.4.1 Eqs 6.10.174-175 (φ 0.90 Fy Ag, φ 0.75 Fu Ae, bolted splice plates Ae = An ≤ 0.85 Ag) | design/steel_connections.py:29-30,561,571; steel.json:22,27 | 0.90/0.75/0.85 | part2 p134 (rendered) | correct | - (applying 0.85 Ag to the gusset Whitmore section extends the splice-plate rule; conservative) |
| Sec 10.10.4.2 Eq 6.10.176 φ 1.00 (0.60FyAg), Eq 6.10.177 φ 0.75 (0.60FuAnv) | design/steel_connections.py:30,307,317,424,434,468 | φ 1.00/0.75 | part2 p134-135 | correct | - |
| Sec 10.10.4.3 Eq 6.10.178 block shear, φ 0.75, Ubs = 1 uniform | design/steel_connections.py:30-31,155,330,447,585; steel.json:16,25 | φ 0.75 | part2 p135 (rendered) | correct | - |
| Sec 10.10.4.4 Eq 6.10.179: KL/r ≤ 25 → Pn = FyAg, φ 0.90; else Sec 10.5 | design/steel_connections.py:31,593 | 25, 0.90 | part2 p135 | correct | - |
| Table 6.10.7 min fillet (≤6: 3, 6-13: 5, 13-19: 6, > 19: 8); max size along edges t (< 6 mm) / t - 2 mm, "Sec 10.10.2.2, p. 116" | design/steel_connections.py:32,166-172,204,211 | sizes | part2 p116 (rendered) | correct | - (more precise clause: Sec 10.10.2.2.2) |
| Eq 6.10.162-163 (p. 121-122): Fw = 0.60FEXX(1.0+0.50 sin^1.5 θ), φ 0.75 | design/steel_connections.py:32-33,160,355,458,615; steel.json:17,25 | 0.60, 0.50, φ 0.75 | part2 p120-122 (rendered) | correct | - |
| "From memory, to be checked": fillet throat 0.707 w [marker] | design/steel_connections.py:35,160 | 0.707 w | part2 p114 (Sec 10.10.2.2.1) | correct | BNBC Sec 10.10.2.2.1: effective throat = shortest root-to-face distance (= 0.707 w for an equal-leg fillet) |
| "dh + 2 mm (from memory, to be checked)" [marker] | design/steel_connections.py:35-36,124 | +2 mm | part2 p44 (Sec 10.2.3.13.2), p55 (Sec 10.4.3.2) | correct | BNBC Sec 10.2.3.13.2 / 10.4.3.2: hole width = nominal hole + 2 mm |
| Whitmore width, 30° spread (from memory) [marker] | design/steel_connections.py:36,174-178 | 30° | part2 p109-136 | not in BNBC | AISC Steel Construction Manual Part 9 / Whitmore (1952); external practice |
| Gusset buckling K (user input, from memory) [marker] | design/steel_connections.py:36-37 | K | part2 p134-135 | not in BNBC | AISC Manual Part 9 (Thornton/Dowswell); BNBC only gives Sec 10.10.4.4 |
| Elastic bolt-group and weld-line methods for eccentricity [marker] | design/steel_connections.py:37,256-262,349-352 | method | part2 p109-136 | not in BNBC | AISC Manual Parts 7/8 (elastic method) |
| Plate flexure φ 0.9 Fy Z (from memory) [marker] | design/steel_connections.py:37,341; steel.json:18,25 (phi.plateFlexure) | φ 0.9 | part2 p134-136 | not in BNBC | BNBC 10.10.4 has no flexure-of-connecting-element clause (that is AISC 360-10+ J4.5); φ = 0.90 is consistent with BNBC Sec 10.6.1 φb |
| ISO 8.8 / 10.9 bolts taken as A325 / A490 | design/steel_connections.py:38,69-77 | equivalence | part2 p127 | not in BNBC | practice; Table 6.10.10 lists ASTM grades only (as the file says) |
| "BNBC 2020 Part 6 Sec 6.2.2: 0.85 f'c over β1 c, εcu = 0.003" | library/section_designer.py:16-17 | stress block | part1 p896 (Sec 6.2.2 = Required strength), p904-905 | wrong number | Sec 6.2.2 -> Sec 6.3.2 (6.3.2.3 εcu 0.003; 6.3.2.7.1 0.85 f'c; 6.3.2.7.3 β1, Eq 6.6.7); values match |
| "Table 6.6.2.1 / ACI 21.2.2": φ linear from εty to εty + 0.003 | library/section_designer.py:20-21,470-474 | φ transition | part1 p897-898 (Sec 6.2.3.2.2, Fig 6.6.1), p905-906 (6.3.3.3-6.3.3.4) | wrong number | Table 6.6.2.1 does not exist (Table 6.6.2 = deflections) -> Sec 6.2.3.2.2 with Sec 6.3.3.3-6.3.3.4 (Figure 6.6.1). BNBC differs: tension-controlled limit fixed at εt = 0.005 (not εty + 0.003); same for Grade 420, code conservative for Grade 500 (see sec 2) |
| slenderness flag KL/r ≤ 200.0 in the stand-in checks (no citation) | design/steel_proposal.py:199 | 200 | part2 p60 (Sec 10.5.2) | wrong value | 200.0 -> 150.0 (BNBC Sec 10.5.2), consistent with members.py KL_R_COMPRESSION |

### 2. Wrong values (engineering impact)

1. `design/steel_proposal.py:199` stand-in slenderness limit **200 -> 150** (BNBC Sec 10.5.2, part2 p60, verified). Impact: it is only a flag (`flag=True`), and only on the fallback path (`stub_member_checks`, used if `saengine.design.steel` cannot be imported, and in tests). On that path, members with 150 < KL/r ≤ 200 would not be flagged. It does not change strength, because buckling capacity still comes from Eq 6.10.16-19. Low impact. The main checker (`members.py:70`) already uses 150.
2. `library/section_designer.py:20` / `:470-474` φ transition **upper strain εty + 0.003 vs BNBC 0.005** (Sec 6.2.3.2.2 / 6.3.3.4, part1 p897, p906). Grade 420 (εty = 0.0021): 0.0051 vs 0.005, so φ is under 1 % lower in the transition band. Grade 500 (εty = 0.0025): 0.0055 vs 0.005. Between εt = 0.005 and 0.0055 the code gives φ < 0.90 where BNBC allows 0.90, at most about 0.03 lower. **The code is conservative, never unconservative.** The bottom of the band (εty) matches BNBC 6.3.3.3. BNBC also lets Grade 420 use 0.002, which is slightly less conservative than the code. Recommendation: no change to the numbers (ACI 318-19 behaviour, safe side). Fix the clause text only.
3. Interpretation note, not a mismatched number: `design/steel/members.py:148` uses Table 6.10.2 Case 7 for tees with `d` taken as the tee's own depth. So bf ≥ 2/3 d almost always holds and U = 0.90. The case says "Tees cut from these shapes", and in AISC d is the depth of the parent W. With the parent depth, many WTs would get U = 0.85. Impact: tee rupture capacity up to 0.90/0.85 = **+5.9 % unconservative** for tee braces whose parent W has bf < 2/3 d. BNBC does not define d for tees, so this is not a "wrong value" verdict. Suggest comparing bf with 2 × (tee depth), or with the parent W depth when known.
4. Conservative deviations, for information only: Eq 6.10.32 is not capped at 200 (members.py:309), which is conservative. The Lv of Eq 6.10.146a is taken as the segment length, which is conservative and already stated. 0.85 Ag is applied to the gusset Whitmore section, which is conservative.

### 4. External references

- **AISC 360-05** (the base of BNBC Ch 10). Table B4.1 at classify.py:2. Provisions in general at design/steel/__init__.py:1, members.py:2,63, and steel.json:6 (`source`). External standard, check against the owner's copy. Every provision used was found in BNBC Ch 10 with the same values: BNBC equivalent.
- **AISC 360 H1-1**: steel_proposal.py:156. BNBC equivalent: Sec 10.8.1.1 Eq 6.10.147a/b, same values.
- **AISC 360-10+/-16 J4.5** (flexure of connecting elements, implied by plate flexure φ 0.9 Fy Z): steel_connections.py:37,341 and steel.json:18,25. Not in BNBC 2020.
- **AISC Steel Construction Manual** practice: Whitmore section with 30° spread, gusset K, and elastic bolt-group / weld-line methods. steel_connections.py:36-37,177,256-262,349-352.
- **AISC Design Guide 9** (torsion): Cw closed forms for channels and angles, library/steel_sections.py:25-26.
- **ACI 318-19 22.4.2.2** (P0): section_designer.py:602. BNBC equivalent: Sec 6.3.3.6 Eqs 6.6.8/6.6.9 bracket, 0.85 f'c(Ag - Ast) + fy Ast, same.
- **ACI 318-19 Table 22.4.2.1 / 22.4.2.1** (φPn,max = 0.80 φP0 tied, 0.85 φP0 spiral): section_designer.py:619,737. BNBC equivalent: Sec 6.3.3.6.1/6.3.3.6.2 Eqs 6.6.8 (0.85) and 6.6.9 (0.80), same.
- **ACI 318-19 21.2.2** (φ by εt): section_designer.py:20-21. BNBC differs in the upper strain limit (0.005); see sec 2.
- **ACI 318-19** stress block: section_designer.py:16. BNBC equivalent: Sec 6.3.2, same.
- **Section standards**: EN 10365 (IPE/HEA/HEB), IS 808 (ISMB/ISMC/angles), EN 10056 (angles), EN 10219 / EN 10219-2 (hollow sections, corner radii 2t / 2.5t / 3t). library/steel_sections.py:6-13,349,387,445,817.
- **ASTM A307 / A325 / A490** bolt grades. These are in BNBC Table 6.10.10 and the values match. ISO 898-1 property classes 8.8 / 10.9 are mapped to them at steel_connections.py:38,69-77; that mapping is practice, not BNBC.

Not cited in this group: BNBC Ch 13 (composite, part2 p370) and Appendices N/Q/S. No composite or Appendix provisions are implemented in these files.


## Appendix D: Soil, substructure, drawings

Scope: python/src/saengine/{soil,substructure,drawings (bbs.py, detailing.py, sheets),gis,boq}/**, library/soil.py, library/substructure.py, codes/packs/bnbc2020/data/foundations.json. (workbench/*saengineSoil*, *saengineSubstructure* TS files were in hits.txt but are outside this group.) Citations not caught by hits.txt (the long docstring of drawings/detailing.py, its `_page(...)` calls) were checked too. Every table value below was checked on a rendered page.

checked=114 correct=55 wrong(number+value+clause)=5 not-in-BNBC=2 could-not-find=0 external=52 markers(from memory etc.)=11

(BNBC rows 62: 55 correct, 2 wrong number, 3 wrong value, 2 not in BNBC. Markers: soil/lab.py x4 (sulphate thresholds: now confirmed by BNBC Table 6.5.2), drawings/detailing.py x3 (0.30 ln beam top bars: practice, not in BNBC), drawings/bbs.py x3 (BS 8666 radii/end projections/formulas: external), soil/liquefaction.py:31-34 x1 ("a visual check would settle it": checked on the printed page, no 0.65 factor).)

### 1. Citation table

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| BNBC 2020 Table 6.3.8 (shallow foundations, adapted from NBCI 2005) | soil/settlement.py:36-37, 70-77, 84-106, 197; soil/report.py:350; library/soil.py:876; substructure/pilecap.py:37, 940 | Max settlement (RCC / framed bldg with panel walls): isolated sand 50/60, isolated plastic clay 75/75, raft sand 75/75, raft clay 100/125 mm; "a guide" | part1 p733 | correct | - |
| BNBC 2020 Part 6 Table 6.3.8, raft of RCC structures | substructure/raft.py:38-41, 116-120, 626, 665, 677, 948-950 | sand: 75 mm, 0.0021 L, 1/500; plastic clay: 100 mm, 0.002 L, 1/500; L = c/c of columns | part1 p733 | correct | - |
| Table 6.3.10a (p. 750) | substructure/piles.py:45-47, 79-85, 159; foundations.json:7-25, 44; library/substructure.py:210, 228 | Monument 2.3/3.0/3.5/4.0, Permanent 2.0/2.5/2.8/3.0, Temporary 1.4/2.0/2.3/2.8 (good/normal/poor/v.poor); downward and upward | part1 p750 | correct | - |
| Table 6.3.10b (10a assumes load test data) | substructure/piles.py:47, 154 | load-test data assumed by the control levels | part1 p750-751 ("Load Test Data": Yes/Yes/Yes/No) | correct | - |
| Sec 3.10.1.18 | substructure/piles.py:43-52, 87-95, 107, 123, 133, 152; library/substructure.py:211, 218, 236, 243; foundations.json:45-47 | min overall FS 2.0 with site load test + good QC, else 3.0; partial 1.5 skin / 3.0 base; allowable = min of overall and partial | part1 p750 | correct | - |
| Sec 3.10.4.10 | substructure/piles.py:52, 93, 133; library/substructure.py:212, 220; foundations.json:47 | bored piles: same FS as driven | part1 p766 | correct | - |
| Secs 3.10.1.13, 3.10.1.16, 3.10.4.5, 3.10.4.7 (FS 3.5) | substructure/piles.py:37-38, 90-91, 148; foundations.json:35, 46 | FS 3.5 with the SPT relations | part1 p747, 749, 762, 763 | correct | - |
| Eqs 6.3.21, 6.3.22, 6.3.25-6.3.28 (driven, SPT) | substructure/piles.py:22-33, 185-210 | clay fs 1.8N̄≤70, fb 45N≤4000; sand fs 2N̄≤60, silt 1.7N̄≤60; sand fb 40N(L/D)≤400N,≤11000; silt 30N(L/D)≤300N,≤11000 | part1 p747, 749 | correct | - |
| Eqs 6.3.29-6.3.34 (bored, SPT) | substructure/piles.py:22-33, 111, 185-210 | clay fs 1.2N̄≤70, fb 25N≤4000; sand 1.0N̄≤60, silt 0.9N̄≤60; sand fb 15N(L/D)≤150N,≤4000; silt 10N(L/D)≤100N,≤4000; N60 at tip down to 3D | part1 p762-763 (rendered p763) | correct | - |
| BNBC 2020 Eqs 6.3.29 and 6.3.31-32 | library/substructure.py:262 | "SPT N values by" these equations | part1 p747-749, 762-763 | wrong number | Only bored skin-friction eqs listed; code uses 6.3.21-6.3.22, 6.3.25-6.3.28 (driven) and 6.3.29-6.3.34 (bored, incl. end bearing) |
| Sec 3.10.1.10, Eqs 6.3.11-6.3.14; Eq 6.3.12 | substructure/piles.py:40-42, 96, 105; substructure/pilecap.py:726 | Qult = Qs + Qb - W; uplift ≤ 0.7Qs + W; Qallow = Qult/FS; Qs = As fs, Qb = Ab fb | part1 p743 | correct | - |
| Sec 3.10.1.31 | substructure/piles.py:56-60, 517, 562 | 0.33 f'c on precast pile; fully embedded pile in cu > 10 kPa not a long column | part1 p756 | correct | - |
| BNBC Table 6.3.11 | substructure/piles.py:569-590 | 400-450: 6Ø16, Ø8@200; 500-600: 8Ø16, Ø8@250; 750-900: 10Ø16, Ø10@300; 1050-1200: 12Ø16, Ø10@300; 1500-1800: 12Ø20, Ø10@400; 2100: 16Ø20, Ø10@400; 2400: 16Ø25, Ø12@500; fy 420; ≥3 m below cut-off; compression only | part1 p764 | correct | - |
| Sec 3.10.1.19 | substructure/pilecap.py:22, 31, 740, 790-797, 837, 936 | group efficiency 1.0 except friction piles in cohesive soil; min spacing 2.5 D; two-pile group braced along its axis only | part1 p751 | correct | - |
| Sec 3.10.1.20 | substructure/pilecap.py:15-16, 32-33, 92-96, 790, 810, 820, 826-827, 939 | soil under cap carries nothing; cap ≥100 mm beyond piles; 75 mm levelling course, clear cover ≥50 mm; piles embedded ≥75 mm, cut to sound concrete | part1 p751 | correct | - |
| Sec 3.10.1.30 | substructure/pilecap.py:31-32, 795-797 | spacing > max(750 mm, 2.5 D); friction piles ≥3.0 D | part1 p755 | correct | - |
| Sec 3.10.4.11 | substructure/pilecap.py:832 | single pile not recommended unless Ø ≥ 600 mm | part1 p766 | correct | - |
| Sec 3.10.5 (group as solid foundation at 2/3 L; shallow limits) | substructure/pilecap.py:34-38, 786, 915, 922, 939 | equivalent footing at 2/3 L, 2:1 spread, 10 % stress cut-off; limits of shallow foundations | part1 p766, 769 | correct | - (note: BNBC 3.10.5 itself says "(Table 6.3.7)", a misprint for Table 6.3.8; the code's 6.3.8 is the right table) |
| BNBC 2020 Sec 3.9.5; Eqs 6.3.6, 6.3.7a, 6.3.7b, 6.3.8 | soil/liquefaction.py:1, 25-34, 182-186, 219, 469, 519-521; library/soil.py:833, 855-856 | FL = CRR/CSR; τmax = amax rd γt z/g; rd = 1 - 0.015z; CSR = (amax/g) rd σv/σ'v with NO 0.65; CRR "by several procedures" | part1 p734 (rendered), p735 | correct | - |
| "liquefaction ... when FL < 1" | soil/liquefaction.py:27, 519; soil/site_class.py:60 ("FS < 1") | boundary FL < 1 | part1 p734 (rendered: "FL is ≤ 1") | wrong value | "< 1" -> "≤ 1" (text only; code at liquefaction.py:425 already uses fs <= 1.0) |
| BNBC 3.9.5 screening: clays don't liquefy, N > 30 rule, Finn et al. 1994 | soil/liquefaction.py:49-66, 103-104, 293-338, 385-431 | sand/silt liquefy, clays not except sensitive; SPT > 30 won't liquefy; fines <0.005 mm ≤10 %, LL ≤36 %, w ≤0.9 LL, LI ≤0.75 | part1 p735 | correct | - |
| Sec 2.5.13.2 ("expected horizontal PGA (in g) for design" = (2/3) Z S) | soil/liquefaction.py:84-86, 266 | default amax = (2/3) Z S | part1 p645-646 (definition under Eq 6.2.56) | correct | - |
| Sec 2.5.4.2, Table 6.2.14 (Z = MCE PGA on rock) | soil/liquefaction.py:79-83, 268; library/soil.py:779-780; gis/towns.py:5, 35 | Z = MCE PGA on SA; 0.12/0.20/0.28/0.36 for zones 1-4 | part1 p611, 615 | correct | - |
| Table 6.2.16 (soil factor S) | soil/liquefaction.py:83, 268; library/soil.py:780 | S by site class (SA 1.0, SB 1.2, SC 1.15, SD 1.35, SE 1.4) | part1 p616 | correct | - |
| "empty: Z × S from the project settings" | library/soil.py:778 | default amax = Z S | part1 p646 | wrong value | UI text says Z × S; code (soil/liquefaction.py:263) uses (2/3) Z S per Sec 2.5.13.2. Fix the description |
| Sec 2.5.3.1 | soil/site_class.py:25-26, 261, 268; soil/liquefaction.py:84 | S1/S2 need site-specific studies; liquefaction evaluated for design EQ motions | part1 p607-608 | correct | - |
| Sec 2.5.3.2 (field N, uncorrected) | soil/liquefaction.py:57 | site-class N is field N without correction | part1 p608-609 | correct | - |
| BNBC 2020 Part 6 Table 6.2.13 | soil/site_class.py:1-24, 58-60, 171, 212, 259, 267, 304; soil/report.py:164, 248; gis/site.py:380 | SA >800; SB 360-800 / N>50 / su>250; SC 180-360 / 15-50 / 70-250; SD <180 / <15 / <70; S1 ≥10 m soft clay PI>40, su 10-20; S2 liquefiable | part1 p609-610 | correct | - (averages: BNBC equivalent of the ASCE 7-16 20.4 harmonic means is Eqs 6.2.31-6.2.33, Sec 2.5.3.2, same form) |
| Table 6.2.15 (Z of towns) | gis/towns.py:4, 29, 38-114; gis/site.py:153, 179; gis/__init__.py:5 | Z of 64 towns | part1 p615 (all 64 compared) | correct | - |
| Table 6.2.8 (basic wind speed V) | gis/towns.py:6, 31, 38-114; gis/site.py:153, 184; gis/__init__.py:5 | V of 75 locations, Mongla not listed | part1 p600 (all 75 compared) | correct | - |
| Figure 6.2.24 / Figure 6.2.1 | gis/towns.py:14-15; gis/site.py:154 | zoning map / wind map govern | part1 p614 / p550 | correct | - |
| Sec 1.8.5.2 (b) (zones 2, 3, 4) | substructure/shallow.py:33-35, 124-128, 1493, 1511, 1546, 1550 | ties resist ±10 % of larger footing/column load unless friction/passive restraint; not required in zone 1 | part1 p507 | correct | - |
| Sec 8.3.11.3 (b) | substructure/shallow.py:130-132, 1512, 1591, 1597 | grade-beam least dimension ≥ clear spacing/20, need not exceed 450 mm | part1 p1120 | correct | - |
| Sec 8.3.11.2 (uplift: top bars in pile cap) | substructure/pilecap.py:406 | top flexural reinforcement under EQ uplift | part1 p1120 (8.3.11.2(d)) | correct | - |
| Sec 8.3.11.2(a), (b), p 1120 | drawings/detailing.py:62-63, 1991 | column bars developed in footing; 90° hooks at bottom turned to column centre | part1 p1120 | correct | - |
| BNBC 2020 Part 6 2.7.2 (D, D + L + Lr, D + W, D + 0.75L + 0.75Lr + 0.75W, 0.6D + W, D + 0.7E, D + 0.75L + 0.75Lr + 0.525E, 0.6D + 0.7E) | substructure/loads.py:12-17, 61-63; substructure/shallow.py:65-68 | service combinations | part1 p684 (rendered) | wrong value | "D + L + Lr" is not a BNBC combination: 2.7.2.1 has D + L (+T) (2), D + (Lr or R) (3), D + 0.75(L+T) + (Lr or R) (4). D + L + Lr envelopes all three (conservative). Others match combos 5-8 |
| Sec 2.7.2.1 combinations 2 and 4 (T) | substructure/loads.py:39 | T in combos 2 and 4 | part1 p684 | correct | - |
| BNBC 2.7.3 (1.6W) | substructure/loads.py:170 | strength combos factor W by 1.6 | part1 p685 | correct | - |
| 8.1.2.1, pp 1065-1066 (standard hooks) | drawings/detailing.py:10-14, 240-252; drawings/bbs.py:18-19 | 180° + max(4db, 65); 90° + 12db; ties 90° + 6db (≤16), +12db (19-25), 135° + 6db (≤25); closed ties 135° + max(6db, 75); seismic hook 135° (circular 90°) + max(6db, 75) | part1 p1065-1066 (rendered) | correct | - |
| 8.1.1.1, p 1062 (cross tie) | drawings/detailing.py:13-14 | 135° + max(6db, 75) one end, 90° + 6db other | part1 p1062 | correct | - |
| 8.1.2.2, Table 6.8.1, p 1066 | drawings/detailing.py:14-16, 203-209; drawings/bbs.py:14-17, 112-120, 586 | 6db 10-25, 8db >25-40, 10db >40-57; ties ≤16 mm 4db | part1 p1066 (rendered) | correct | - |
| 8.2.2, p 1076 (√f'c ≤ 8.3) | drawings/detailing.py:26, 149, 264 | √f'c ≤ 8.3 MPa | part1 p1076 | correct | - |
| 8.2.3.1-8.2.3.5, pp 1076-1078; Eq 6.8.1, 6.8.2 | drawings/detailing.py:17-27, 152, 279, 302-330, 828-865 | ld ≥ 300; 2.1/1.7/1.1 table, blank cell for ≤19 mm "other cases" (1.4 of ACI taken, flagged); (cb+Ktr)/db ≤ 2.5; Ktr = 40Atr/(sn); ψt 1.3; ψe 1.5/1.2/1.0, ψtψe ≤ 1.7; ψs 0.8/1.0; excess As factor | part1 p1076-1078 (rendered p1077: cell is blank) | correct | - |
| 8.2.4, p 1078 | drawings/detailing.py:28-29, 153, 359 | ldc = max(0.24 fy db/(λ√f'c), 0.043 fy db) ≥ 200; 0.75 in spirals / 12 mm ties @100 | part1 p1078 (rendered) | correct | - |
| 8.2.6, p 1079 | drawings/detailing.py:30-34, 386 | ldh = 0.24 ψe fy db/(λ√f'c) ≥ max(8db, 150); 0.7 / 0.8 factors; hooks not in compression | part1 p1079 (rendered) | correct | - |
| 8.3.7.4(a), Eq. 6.8.12, p 1111 | drawings/detailing.py:34-36, 398 | max(8db, 150, fy db/(5.4√f'c)) | part1 p1111 (eq printed as 6.8.12; BNBC text says "Eq. 6.8.9", a BNBC misprint) | correct | - |
| 8.2.7.3, 8.2.7.4, 8.2.8.1, 8.2.8.2, 8.2.9.1, 8.2.9.3 (pp 1080-1081) | drawings/detailing.py:37-43, 84-87, 154, 498, 504, 1515, 2208, 2218 | max(d, 12db) beyond cut-off; ld beyond for continuing bars; 1/3 / 1/4 into support, beams ≥150 mm; 1/3 negative steel beyond PI by max(d, ln/16, 12db) | part1 p1080-1081 | correct | - |
| `_page('8.2.9.2, 8.2.7.4', 1081)` | drawings/detailing.py:603 | page of 8.2.7.4 | part1 p1080 (8.2.7.4), p1081 (8.2.9.2) | wrong number | 1081 -> "1081, 1080" |
| 8.2.12-8.2.15, pp 1083-1085 | drawings/detailing.py:44-53, 441, 456, 477-481, 1370, 2641; drawings/sheets/project.py:839 | no laps ≥36 mm; class A 1.0 ld / B 1.3 ld ≥300; class A conditions; different sizes; compression 0.071 fy db (fy ≤ 420) or (0.13fy - 24)db ≥300, +1/3 if f'c < 21; column laps (b)-(e), 0.83, 0.75 | part1 p1083-1085 | correct | - |
| 8.1.9.3(d), (e), p 1073 | drawings/detailing.py:53-54, 489 | spiral laps 48db / 72db ≥300; 1.5 extra turns | part1 p1073 | correct | - |
| 8.1.9.4(d), p 1074 | drawings/detailing.py:77, 2036 | lowest tie within half spacing | part1 p1074 | correct | - |
| 8.1.12.2(b), pp 1075-1076 | drawings/detailing.py:55-56, 1263 | perimeter beams: top spliced at mid-span, bottom at supports, class B | part1 p1075 | correct | - |
| 8.3.4.2(a), (b), p 1091 | drawings/detailing.py:57-59, 618, 1262 | ≥2 continuous bars top/bottom; no laps in joints / within 2h; hoops over laps ≤ min(d/4, 100) | part1 p1091 | correct | - |
| 8.3.4.3(b), 8.3.10.4(b) | drawings/detailing.py:76, 159 | first stirrup ≤50 mm from face | part1 p1093, p1114 | correct | - |
| 8.3.5.3(b), p 1096; Figure 6.8.7, p 1097 | drawings/detailing.py:59, 623, 1783 | SMF column laps only in centre half, tension splices | part1 p1096-1097 | correct | - |
| 8.3.6.2(c), pp 1100-1101 | drawings/detailing.py:60-61, 2599 | 1.25 ld where wall bars may yield | part1 p1100-1101 | correct | - |
| 8.3.6.6(d)(v), (e)(ii), p 1104 | drawings/detailing.py:78-79 | horizontal wall bars hooked at the ends | part1 p1104 | correct | - |
| Figure 6.6.20, p 948; 6.5.3.8.1, 6.5.3.8.2 | drawings/detailing.py:66-68, 154-156, 608-611, 2468 | slab top bars 0.30 ln from face (column strip, no drop panel); longer span governs; bottom ≥150 mm into support | part1 p947-948 (rendered) | correct | - |
| Sec 7.4.3.2, p 1015; 7.9.6.3, p 1045 | drawings/detailing.py:2789-2791 | lintel bearing (min 100 mm); bars 600 mm beyond opening | part1 p1015, p1045 | correct | - |
| BNBC 2020 Part 6 Sec 8.2 (lap table) | drawings/sheets/project.py:806, 839 | ld/lap/ldh per bar size by the detailing rules | part1 p1076-1085 | correct | - |
| "Practice where BNBC gives no figure (from memory, to be checked)": beam extra top bars to max(0.30 ln, ld) | drawings/detailing.py:70-73, 158, 595-603, 1222-1225 | 0.30 ln | part1 p1080-1081, p948 | not in BNBC | Practice (ACI SP-66 style). BNBC only requires 8.2.7.3 (max(d, 12db) past the theoretical cut-off), 8.2.7.4 and 8.2.9.3; 0.30 ln is not guaranteed to satisfy 8.2.7.3 for unequal spans/high live load. Reword to "practice, not in BNBC; checked against ld only" |
| "ACI 318-19 as BNBC 2020 adopts it" | substructure/pilecap.py:40 | BNBC 2020 adopts ACI 318-19 | part1 p922-924 (Sec 6.4.2: Vc = 0.17λ√f'c bw d, no size factor λs) | not in BNBC | BNBC Ch 6 follows an earlier ACI 318 (no λs, no ρw^(1/3) form); ACI 318-19 is what the code uses (more conservative at low ρ / large d) |
| ACI 318-19 Table 19.3.1.1 sulphate thresholds "from memory, to be checked" | soil/lab.py:47-50, 87-95, 399-400 | S0 <0.10 % / 150 ppm; S1 0.10-0.20 / 150-1500; S2 0.20-2.00 / 1500-10 000; S3 >2.00 / >10 000 | part1 p846 Table 6.5.2 | external | BNBC equivalent: Part 6 Table 6.5.2 (part1 p846), same thresholds (Negligible / Moderate / Severe / Very severe), max w/c 0.50 / 0.45 / 0.45, cement other than CEM I and B type. The marker can be removed by citing it |
| chloride exposure C2 (ACI 318-19 Table 19.3.1.1, from memory) | soil/lab.py:408 | moist buried RC = C2 | - | external | external standard, check against the owner's copy (BNBC Table 6.5.3 p846 gives chloride limits in concrete, not soil classes; Sec 3.10.1.29 p754: site corrosive if Cl ≥ 500 ppm, SO4 ≥ 2000 ppm or pH < 6) |
| ACI 318-19 Table 20.5.1.3.1 (75 mm cast against earth) | substructure/sizing.py:54-56 | cover 75 mm | part1 p1071 | external | BNBC equivalent: Part 6 Sec 8.1.7.4, same value (75 mm) |
| ACI 7.6.1.1 / Table 7.6.1.1 (0.0018 Ag) | substructure/sizing.py:12, 229; substructure/shallow.py:109-110, 361, 985; substructure/pilecap.py:63, 446 | As,min 0.0018 Ag (fy 420) | part1 p1075 | external | BNBC equivalent: Sec 8.1.11.2(a), same 0.0018 (fy 420; 0.0020 for fy 275/350), BUT 8.1.11.2(b): ×1.5 for brick-aggregate concrete (0.0027) |
| ACI 7.7.2.3 (min(3h, 450)) | substructure/sizing.py:13, 229; substructure/shallow.py:995 | max bar spacing | part1 p1075 | external | BNBC equivalent for S&T steel: Sec 8.1.11.2(c) min(5h, 450) |
| ACI shear Table 22.5.5.1 (c), 22.5.5.1.3 λs; Table 22.6.5.2 | substructure/shallow.py:91-93, 104, 325-340; substructure/pilecap.py:47-48, 429, 603; substructure/raft.py:854 | Vc = 0.66 λs ρw^(1/3) √f'c bd; punching least of 0.33, 0.17(1+2/β), 0.083(2+αs d/b0) × λs λ √f'c | part1 p922 | external | BNBC differs: Sec 6.4.2.1.1 Vc = 0.17λ√f'c bw d (Eq 6.6.49), no λs; ACI 318-19 values used are lower (conservative) |

(The other external rows are listed in section 4; each counted once.)

### 2. Wrong values (engineering impact)

No BNBC-cited NUMBER used in a calculation was found wrong. Every factor of safety (Table 6.3.10a, 3.0/2.0, 1.5/3.0, 3.5), settlement limit (Table 6.3.8), SPT pile relation (Eqs 6.3.21-6.3.34), pile-cap rule (100 mm, 50 mm, 75 mm, 2.5 D, 750 mm, 3 D), Table 6.3.11 row, liquefaction constant (0.015, no 0.65, N 30, Finn limits), site-class limit, Z (64 towns) and V (75 locations) value, and Ch 8 hook, bend, development and lap value matches the rendered BNBC pages. The wrong values are text, or a conservative combination:

- soil/liquefaction.py:27, :519 and soil/site_class.py:60: "FL < 1" -> "FL ≤ 1" (BNBC p734). Text only: the code (liquefaction.py:425 `liquefiable = fs <= 1.0`) already uses ≤. No design impact.
- library/soil.py:778: the UI description says an empty PGA means "Z × S", but the code uses (2/3) Z S (Sec 2.5.13.2). No calculation impact. Risk: a user who believes the help text and wants the default may type Z × S, which is 1.5× the design PGA (conservative, but it disagrees with what is reported).
- substructure/loads.py:13 / shallow.py:66: "D + L + Lr" is given as a BNBC 2.7.2 combination. BNBC has D + L (+T), D + (Lr or R) and D + 0.75(L+T) + (Lr or R). D + L + Lr envelopes all three, so bearing pressures and pile loads are CONSERVATIVE by up to Lr (the roof live load, usually small; only the top-storey columns see it in full). Safe; fix the wording or add the BNBC combos.

Gaps found while checking (not wrong citations, worth a ticket):
- Pile minimum reinforcement is not checked against BNBC: driven precast Sec 3.10.1.31 (p757): main steel ≥ 1.0 % (L < 30 B), 1.5 % (30-40 B), 2 % (> 40 B); lateral ≥ 0.4 % (ends) / 0.2 % (body) of volume, hoops ≥ 6 mm; f'c ≥ 21 MPa (28 MPa hard driving). Bored Sec 3.10.4.9 (p765): ≥ 0.5 % Ag (Ag ≤ 0.5 m²), 0.375 % (0.5-1 m²), 0.25 % (> 1 m²), ≥ 6 bars, ≥ Ø16 for D ≥ 600, cover ≥ 75 mm, hoops not closer than 100 mm. piles.py only gives the Table 6.3.11 note. A thin design could pass the structural check with less steel than BNBC asks for (unconservative for handling and driving of precast piles).
- Brick-aggregate concrete: BNBC Sec 8.1.11.2(b) (p1075) asks for 1.5× the S&T minimum (0.0027 instead of 0.0018). Footing / cap / raft As,min uses 0.0018 (ACI 7.6.1.1). If the project uses brick chips (common in Bangladesh), the minimum steel is up to 33 % low. Whether 8.1.11.2(b) covers footings is a judgement; flag it.
- Shallow-foundation load cases: BNBC Sec 3.9.2 (p727) lists its own cases (D + L; D + L + W or E; 0.9D + buoyancy; settlement in clay D + 0.5L) and Sec 3.9.3 (p728) allows a 33 % increase in allowable pressure with W/E, FS 2.0-3.0. The code uses the 2.7.2 combinations without the 33 % increase: conservative. Default FS 3.0 (library/soil.py) is inside BNBC's 2.0-3.0.

### 4. External references (not verifiable here: external standard, check against the owner's copy)

- ACI 318-19 (footings, caps, rafts, piles): 13.2.6.1, 13.3.1.1 (service vs factored loads; substructure/shallow.py:10, loads.py:9); 13.2.6.2, 13.2.7.1, 13.2.7.2, R13.2.7.1, 13.3.1.2 (d ≥ 150 mm; sizing.py:49), 13.3.3.3 (band steel; shallow.py:831), 13.3.4.1, 13.4.2.5 (pile reaction share; pilecap.py:267, 602); 7.6.1.1 / Table 7.6.1.1, 7.7.2.3 (sizing.py:12-13, shallow.py:985, 995); 2.2 (effective depth; shallow.py:105, 448); 8.4.2.2.2, 8.4.4.2.3, R8.4.4.2.3 (γv, Jc; shallow.py:95, 350-356; raft.py:953); 14.5.1.7, 14.5.2.1, 14.5.3.1 (plain concrete; shallow.py:99, 375; pilecap.py:397-402; piles.py:58, 539); 18.13.3 (grade beams; shallow.py:132; BNBC equivalent Sec 8.3.11.3(b), same /20 and 450 mm); 20.5.1.3.1 (cover; sizing.py:54; BNBC 8.1.7.4 same 75 mm); 21.2.1, Table 21.2.1 (g), 21.2.2 (φ; shallow.py:393, pilecap.py:59, 463); 22.4.2 (φPn,max; piles.py:55, 515); 22.5.5.1 / Table 22.5.5.1 (c), 22.5.5.1.3 (λs), 22.6, 22.6.2.1, 22.6.5.2 / Table 22.6.5.2 (one-way and punching shear; shallow.py:91-93, 109, 325-340, 1637-1652; pilecap.py:47, 429, 603; raft.py:46, 854); 23.7.2.1, 23.8.3, 23.9, 23.9.1, Table 23.9.2 (strut-and-tie, βn 1.0 / 0.8; pilecap.py:54-61, 456-555; foundations.json:38-41); 25.4 (pile bar development; pilecap.py:827); Table 6.6.3.1.1 (0.35 Ig; shallow.py:134); Table 19.3.1.1 (sulphate/chloride classes; soil/lab.py:48, 87, 399, 408; BNBC Table 6.5.2 same sulphate thresholds); 25.4.2.3 (1.4 for the blank BNBC cell; detailing.py:22, 330).
- ACI 336.2R (combined/strip footing strip width c + d; shallow.py:103, 544, 771). ACI SP-66 (beam top-bar extents; detailing.py:71).
- ASCE 7-05 2.4.1 (ASD combinations behind BNBC 2.7.2; loads.py:12, 61; shallow.py:66). ASCE 7-16 2.4.1 (0.6W, 0.45W strength-level wind; loads.py:16, 62; shallow.py:68). ASCE 7-16 20.4, eqs 20.4-2/20.4-3 and 20.4.3 (harmonic N̄, s̄u, softer of the two; soil/site_class.py:32, 42; BNBC equivalent Eqs 6.2.31-6.2.33, Sec 2.5.3.2, same averages).
- EN 1998-1 Table 3.1 (site classes behind Table 6.2.13; soil/site_class.py:28).
- BS 8666:2020 Table 2 (min scheduling radius r and end projection P, drawings/bbs.py:70-95) and Table 3 / shape codes (cutting-length formulas, bbs.py:139-295); marked "from memory" (bbs.py:23, 71, 154). The radii (6:12 ... 50:175) look like the usual B500 values; the end projections P (e.g. 10 mm: 130, 12 mm: 160, 16 mm: 210) could not be checked and differ from what this reviewer recalls (smaller P for 10-16 mm). Check against the standard before issuing schedules. bbs.py makes the bend radius max(BS 8666 r, BNBC Table 6.8.1 / 2), which is safe for BNBC.
- Literature, not codes (listed, not verified): Youd et al. 2001; Idriss & Boulanger 2014; Boulanger & Idriss 2006; Finn et al. 1994 (as quoted by BNBC, verified above); Iwasaki et al. 1978/1982 (LPI); Liao & Whitman; Peck, Hanson & Thornburn; Skempton; Terzaghi & Peck 1967; Skempton 1951 Nc; Converse-Labarre; Meyerhof; Schmertmann; Steinbrenner; RFC 7946 (GeoJSON; gis/geojson.py:3-5).


## Appendix E: MEP

checked=175 correct=171 wrong(number+value+clause)=2 (1 value, 1 number) not-in-BNBC=2 could-not-find=0 external=30 markers(from memory etc.)=33

Sub-part counts: plumbing checked=79 correct=75 wrong=2 not-in-BNBC=2 external=12 markers=2 | hvac checked=34 correct=34 external=9 markers=15 | electrical+mep+library checked=62 correct=62 external=9 markers=16.
Page numbers are pdf pages (part1/part2 = bnbc-2020-part1/2.pdf). Tables were rendered and checked cell by cell.

### Summary: wrong values (engineering impact)

1. plumbing/tanks.py:166 (roofLive default 1.0 kPa), used for every tank kind at tanks.py:980-990 (also 1553, 1690): septic tank roof/cover 1.0 -> at least 7.0 kPa (BNBC Part 8 Sec 6.9.12.14, part2 p1107). Unconservative: for a 150 mm roof, factored 1.2D+1.6Lr goes 7.1 -> 16.7 kPa, so roof moments/shears about 2.3x what SAEngine designs; service moments for crack width about 2x. tables.SEPTIC_COVER_LIVE = 7.0 exists and septic.py:183 reports it, but tanks.py never uses it. Fix: live = max(options.roofLive, T.SEPTIC_COVER_LIVE) for kind == "septic".
2. (label only, value right) plumbing/tables.py:530 "Table 8.S.1 (iv) kindergarten": row (iv) is "community centre", kindergarten is under it; 0.08 correct.

Observation (owner to decide, not counted): plumbing storage keeps a 1 h fire reserve (Part 8 Sec 5.9.1.2(c), literal); Part 4 Table 4.4.1 durations reach 75-112 min for ordinary hazards / buildings above 51 m (Part 8 Sec 5.5.3.3 refers storage to Part 4).

### 1. Citation tables and per-sub-part details

#### 1a. plumbing/**

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| Table 8.5.1(a), part2 p1034 | tables.py:18, 90-123; demand.py:54 | A1 260/200, A3 200/150, y1 180/135, y2 -/120, z1 -/80 lpcd | part2 p1034 | correct | - |
| Table 8.5.1(b), p1035 | tables.py:19, 124-154 | A1 150, A3 135, A3 120, z1 80 (restricted) | part2 p1035 | correct | - |
| Table 8.5.1(c), p1035 (upper value of range) | tables.py:20, 155-157 | z1 50-60 -> 60, z2 40-50 -> 50 | part2 p1035 | correct | - |
| Table 8.5.1(d), p1036-1037 | tables.py:21, 158-260 | all 40 rows (A4 135/70 ... M2 -/3) | part2 p1036-1037 | correct | - |
| Sec 5.5.2, 5.6: population x lpcd | demand.py:3, 117; report.py:41 | daily demand = population x lpcd | part2 p1033-1034, 1039 | correct | - |
| Sec 5.6.3 / 5.6.4, p1039 | tables.py:22, 265-268; demand.py:5 | family size 5; office 7.4-9.3 m²/person (7.4 used) | part2 p1039 | correct | - |
| Sec 5.5.3.3 -> Part 4 Sec 4.2 | storage.py:8 | fire water storage per Part 4 Sec 4.2 | part2 p1038 | correct | - |
| Sec 5.9.1.2(c)(i),(iii), p1041 | tables.py:23, 272-276; storage.py:3; report.py:45 | roof tank 1/2 daily, UGR 1 x daily, each + 1 h fire reserve (tall bldg) | part2 p1041 | correct | - |
| Sec 5.9.1.2(c)(ii) | supply.py:16, 224, 237; hydraulics.py:181, 1050, 1085 | delivery pump = peak hourly demand; 2 fillings of roof tank/day | part2 p1041 | correct | - |
| Eq 8.5.1 (Sec 5.10.1(a)), p1043 | tables.py:28, 278-281; demand.py:8, 125; report.py:42 | daily / 16 h (15-17) x 2.2 | part2 p1043 | correct | - |
| Sec 5.9.2.1, p1042 | tables.py:24; storage.py:13; report.py:47, 491; tanks.py:327 | >= 2 compartments; drain Table 8.5.2, overflow Table 8.5.3 | part2 p1042 | correct | - |
| Table 8.5.2, p1042 | tables.py:26, 283-284; storage.py:46 | 2800/25, 5500/38, 11000/50, 19000/63, 28000/75, >100 | part2 p1042 | correct | - |
| Table 8.5.3, p1042 | tables.py:27, 285-294; storage.py:51 | 190/50, 570/63, 760/75, 1500/100, 2650/125, 3800/150, >200 | part2 p1042 | correct | - |
| Sec 5.9.2.2, p1043 | hydraulics.py:9-10, 84, 674; supply.py:297 | outlet >= 50 mm above tank bottom; tank bottom above highest fixture | part2 p1043 | correct | - |
| Sec 5.9.2.3, p1043 | tables.py:25 | ground tank: compartments, two chambers | part2 p1043 | correct | - |
| Sec 5.10.1(c)(ii), p1044 | tables.py:29, 296-302; supply.py:10, 38; hydraulics.py:27, 73, 692, 802, 863, 872, 1163 | 13/50 mm 0.30-0.60, 75/100 mm 0.75-0.90, 150/200 mm 1.15-1.30 m/s; head loss 1.5-1.6 m/100 m (1.6 used). Pairwise-interpolated reading is SAEngine's, stated as such | part2 p1044 | correct | - |
| Sec 5.10.3 (Hazen-Williams) | supply.py:13; hydraulics.py:20, 668 | HW formula named for building pipes | part2 p1045 | correct | - |
| Table 8.5.4, p1045 | tables.py:30, 363, 367; demand.py:10 | wash basin (domestic) 1 FU, washing machine 3 FU | part2 p1045 | correct | - |
| Table 8.5.5, p1046 | tables.py:31, 317-340; demand.py:11, 184; hydraulics.py:16, 110, 173, 677 | 20 rows, flush tank and flush valve flows | part2 p1046 | correct | - |
| Table 8.5.6, p1047 | tables.py:32, 307-310, 359-368; hydraulics.py:67, 78-82, 217, 289, 844 | min. supply pipe (wc 19, wc valve 25, urinal 13/19, basin 19, others 13); 55 / 100 kPa; flows wc 11.4, urinal 56.8, shower 11.4, bathtub 15.1, kitchen sink 9.5, wc valve 132 l/min | part2 p1047 | correct | - |
| Sec 5.10.4.2, p1047 | tables.py:33, 311-313; supply.py:19; hydraulics.py:25, 70, 689, 854, 935 | <= 35 m head (345 kPa) on any fitting | part2 p1047 | correct | - |
| Sec 5.10.4.3 | hydraulics.py:24, 844 | pressure >= Table 8.5.6 during the peak | part2 p1048 | correct | - |
| Sec 5.10.5, Eq 8.5.2, Eq 8.5.3 | hydraulics.py:29, 182, 1194 | H = hs + hd + hf + hv; BHP = HQ/3960E; hv = v²/2g | part2 p1048 | correct | - |
| Sec 5.11.1(a),(b), p1049 | tables.py:34; hydraulics.py:26, 71, 934, 993-995, 1016; supply.py:19 | 350 kPa; zones of 5-6 storeys by intermediate tanks (own down-take, floor fed from storey above) or PRVs | part2 p1049 | correct | - |
| Table 8.5.7, p1051 | tables.py:35 | hot water min pipe sizes (page ref only) | part2 p1051 | correct | - |
| Sec 5.8, 5.8.1-5.8.4 | hydraulics.py:105, 588, 659, 888, 1213-1287; supply.py:8, 312 | floor control valve; direct main; balancing roof tank; ground tank via ball valve, no pumping from main; DTW individual supply | part2 p1040 | correct | - |
| Appendix O Sec O.3-O.4, p1195; Eq 8.O.1 9.807 | tables.py:36-37, 354; hydraulics.py:55; supply.py:3 | wsfu per Table 8.O.1; kPa per m = 9.807 | part2 p1195 | correct | - |
| Table 8.O.1, p1196 (+ 75 % note) | tables.py:36, 358-370 | wc 5 / 10, urinal 3 / 5, shower 3/3/4, bathtub, kitchen sink, bidet 1.5/1.5/2; 75 % note | part2 p1196 | correct | - |
| Tables 8.O.2(a)-(c), pp1197-1199 | hydraulics.py:21, 87-101, 128 | elbow, tee branch, tee run, gate, swing check, 13 sizes 13-200 mm | part2 p1197-1199 | correct | - |
| Figure 8.O.4 (HW nomograph C = 100) | hydraulics.py:75, 669 | BNBC gives only C = 100 | part2 p1207 | correct | - |
| Table 8.6.2, p1087 | tables.py:38, 379-396; drainage.py:4, 9; demand.py:160 | outlets wc 100, urinal 40 (stall/lipped), basin 32, shower 40, bath 50, sink 40, floor trap 65, bidet 32 | part2 p1087 | correct | - |
| Sec 6.9.3(a),(c), p1090 | tables.py:39; drainage.py:10, 17 | soil branch >= 100 mm; two-pipe system with septic tank | part2 p1090 | correct | - |
| Sec 6.9.12.1 | septic.py:279 | septic tank discharging to disposal field or seepage pit | part2 p1104 | correct | - |
| Sec 6.9.12.4 | drainage.py:17 | sullage not into the septic tank | part2 p1106 | correct | - |
| Sec 6.9.12.7-6.9.12.13, p1106 | tables.py:40, 509-519; septic.py:5-12, 99-107, 136-164 | 2000 l; B >= 1 m; D >= 1 m; L 3-4 B; <= 300 users (residential); sludge 0.04 m³/cap/yr; 300 mm clearance; t >= 1 day; desludging 6 months-1 yr; 2 chambers > 3000 l; inlet 2/3 | part2 p1106 | correct | - |
| Sec 6.9.12.14 (7 kPa) | tables.py:520; septic.py:183 | cover and roof live load >= 7 kPa | part2 p1107 | correct | - |
| Sec 6.9.13.2, p1107 | tables.py:42; septic.py:13, 136-164; report.py:299, 306 | Imhoff tank above 300 residential users | part2 p1107 | correct | - |
| Table 8.6.8, p1106 | tables.py:41, 541-548; septic.py:24-26; report.py:316 | septic 1.5/8/-/1.5/-; disposal field 3/15/7.5/6/6; seepage pit 4.5/15/15/6/6; dry well 3/15/-/6/- | part2 p1106 | correct | - |
| Table 8.6.9 (Sec 6.9.14), p1108 | tables.py:43, 549-563; septic.py:25 | 12 separations (building 1.5 ... spring 15) | part2 p1108 | correct | - |
| Sec 6.9.15.2-6.9.15.4, p1108-1109 | tables.py:44, 569-572; septic.py:17-21, 220, 268, 272 | >= 3 percolation holes; seepage capacity >= 2 x tank; bottom >= 1 m above highest WT | part2 p1108-1109 | correct | - |
| Table 8.6.10, p1110 | tables.py:45, 565-568; septic.py:226 | 2/128/172, 5/96/128, 10/68/92, 30/32/44, 60/16/24; >60 unsuitable | part2 p1110 | correct | - |
| Sec 6.10.1, Table 8.6.12, p1112-1113 | tables.py:46, 383-396; drainage.py:3; demand.py:13, 159 | wc 3 / 6, urinal 4, basin 1, shower 2, bathtub 2, sink 2, floor trap 1, bidet 2 | part2 p1112-1113 | correct | - |
| Table 8.6.13, p1113 | tables.py:47, 398-399 | 30/1, 40/2, 50/3, 65/4, 75/5, 100/6 | part2 p1113 | correct | - |
| Sec 6.10.2.1, p1113 | tables.py:48, 503-505; drainage.py:243 | half full, 0.75 m/s (>= 0.6), <= 2.5 m/s | part2 p1113 | correct | - |
| Table 8.6.14, p1114 | tables.py:49, 401-417; drainage.py:7, 35, 57, 108, 116 | all 12 rows, "b" -> None | part2 p1114 | correct | - |
| Table 8.6.15, p1115 | tables.py:50, 419-428; drainage.py:15, 204, 241 | 6 rows x 4 slopes | part2 p1115 | correct | - |
| Table 8.6.16, p1116-1117 | tables.py:51, 430-470; drainage.py:12, 142, 187 | 38 rows, column alignment checked | part2 p1116-1117 | correct | - |
| Table 8.6.17, p1118 | tables.py:52, 472-501; drainage.py:14 | 25 rows, NL / "-" handling, column alignment checked | part2 p1118 | correct | - |
| Sec 7.4.1, p1129 | tables.py:53, 595-596; rainwater.py:14; report.py:56 | harvesting on plots >= 300 m² | part2 p1129 | correct | - |
| Sec 7.8.4, p1132 | tables.py:54; rainwater.py:7 | flat catchment + 50 % of adjoining wall | part2 p1132 | correct | - |
| Sec 7.8.9, p1134 | tables.py:55, 597-598; rainwater.py:14; report.py:56 | D x N x Dp/1000 + floating; 90 / 210 days | part2 p1134 | correct | - |
| Sec 7.8.10 and 7.21.1, p1134 / p1141 | tables.py:56; rainwater.py:11 | >= 2 drains and leaders per independent roof | part2 p1134, p1141 | correct | - |
| Sec 7.8.11 | rainwater.py:12 | leader inlet one size bigger | part2 p1134 | correct | - |
| Table 8.7.2, p1135 | tables.py:57, 599-608; rainwater.py:8, 84 | 7 leaders (area, flow) at 25 mm/h | part2 p1135 | correct | - |
| Table 8.7.3, p1136 | tables.py:58, 609-618; rainwater.py:98 | 7 gutters x 4 slopes | part2 p1136 | correct | - |
| Table 8.7.4, p1141 | tables.py:60, 619-629; rainwater.py:106 | 8 drains x 3 slopes | part2 p1141 | correct | - |
| Tables 8.7.2-8.7.4 for 25 mm/h | tables.py:589-591; rainwater.py:8 | area scales by 25 / intensity (notes, App. U) | part2 p1135-1141 | correct | - |
| Sec 7.10.6.3 | tables.py:630-631; rainwater.py:12 | subsurface rainwater drain >= 100 mm | part2 p1138 | correct | - |
| Sec 7.17, p1140 | tables.py:59; rainwater.py:13 | storm drain 0.6-2.5 m/s | part2 p1140 | correct | - |
| Appendix R Figure 8.R.1, p1213; Dhaka about 88 mm | tables.py:61, 592-594; rainwater.py:3 | Dhaka between the 85 and 90 isohyets, about 88 | part2 p1213 (zoomed) | correct | - (the Dhaka dot sits just east of the 85 line, so the map reads about 86-87; 88 is slightly conservative) |
| Appendix S Eq 8.S.1, Table 8.S.1, p1214-1215 | tables.py:62, 521-539; septic.py:1-9, 76-98, 169 | V = PQt + PSY; flow 120 lpcd (A, C, D, cities), 10 lpcd others; factors 0.25/0.25/0.08/0.50/0.70/0.25/0.50/0.03 | part2 p1214-1215 | correct | - (the printed equation is "V = PQ + PSY" with t defined but left out; the code's PQt is the intended form and gives the same result at t = 1 day) |
| "Table 8.S.1 (iv) kindergarten" | tables.py:530 | kindergarten factor 0.08 | part2 p1214 | wrong number | row (iv) is "Community Centre", kindergarten is a sub-row: "Table 8.S.1 (iv) kindergarten" -> "Table 8.S.1 (iv) community centre, kindergarten" (value 0.08 correct) |
| Part 4 Table 4.4.1 (Sec 4.2.1), part1 p322 | tables.py:63, 633-673; storage.py:7, 83-95; report.py:46 | flows 1000/1000, 1900/1900, 2650/1900, 3200/1900, 4800/1900; note ** 1000 m² per riser; hazard classes of groups | part1 p322 | correct | - |
| Part 3 Sec 2.4.4, part1 p94 | tables.py:64, 314-315; storage.py:6, 56; report.py:46 | high-rise above 33 m | part1 p94 | correct | - |
| Part 6 Sec 2.6.5.1, part1 p680 | tanks.py:20-21 | submerged unit weight + full hydrostatic pressure | part1 p680 | correct | - |
| Part 6 Sec 2.6.5.2, p680 | tanks.py:22, 85, 976 | uplift = full hydrostatic from underside of base | part1 p680 | correct | - |
| Part 6 Table 6.2.3, part1 p536 (ordinary flat roof 1.00) | tanks.py:26-27, 166, 990 | Lr = 1.00 kN/m² | part1 p536 | correct (as a value) | - (see the next row for septic tanks) |
| Septic tank roof live load = TankOptions.roofLive (1.0 kPa, all tank kinds) | tanks.py:26, 166, 980-990 | septic tank roof designed for 1.0 kPa | part2 p1107 (Part 8 Sec 6.9.12.14) | wrong value | septic tank roof and cover: 1.0 -> 7.0 kPa minimum (Part 8 Sec 6.9.12.14); tables.SEPTIC_COVER_LIVE already holds 7.0 but tanks.py never uses it |
| Part 6 Sec 2.7, part1 p684-685; Sec 2.7.3.1 (1),(2),(3),(6) | tanks.py:29-33, 997-1020 | 1.4(D+F); 1.2(D+F)+1.6H+0.5Lr; 1.2D+1.6Lr; 0.9D+1.6H | part1 p685 | correct | - |
| Part 6 Sec 2.7.2.1 (1),(2),(3),(7) | tanks.py:34-35, 1021-1029 | D+F; D+H+F; D+H+F+Lr; 0.6D+H | part1 p684 | correct | - |
| Part 6 Sec 6.6.3.2 / 6.6.3.3, part1 p969 | tanks.py:59-61, 664-672 | vertical 0.0012 (<= 16 mm, fy >= 420) / 0.0015; horizontal 0.0020 / 0.0025 | part1 p969 | correct | - |
| Part 6 Sec 6.6.3.5 | tanks.py:80 | spacing <= 3h and <= 450 mm | part1 p969 | correct | - |
| Part 6 Sec 8.1.7, Table 6.8.3, part1 p1069-1071 | tanks.py:71-74, 138-147, 676-692, 695 | full Table 6.8.3 cover grid (mild ... extreme x 20-50 N/mm²) | part1 p1069-1070 | correct | - |
| Sec 8.1.7.2(a),(b); 8.1.7.4 | tanks.py:74-75, 148-149, 698 | 75 mm against earth; 50 mm (>= 19 mm bar) / 40 mm (<= 16 mm) for earth or weather; take the larger | part1 p1069, p1071 | correct | - |
| Part 6 Sec 5.5.1.1, p844 | tanks.py:76, 1973 | w/c <= 0.50 for low permeability | part1 p844 | correct | - |
| Part 6 Table 6.3.8, part1 p733 | tanks.py:91-92, 150-151, 1947 | water tank on raft: 100 mm (sand/hard clay), 125 mm (plastic clay), "a guide" | part1 p733 | correct | - |
| Part 6 Table 6.2.2 | tanks.py:1516, 1522, 1535 | burnt clay brick 1.910 kN/m² per 100 mm = 19.1 kN/m³ | part1 p530 | correct | - |
| "SAEngine (from memory, to be checked)" outside diameters, ISO metric / ISO 65 / BS EN 10255 | tables.py:683-729 | plastic OD 20...400; metal OD 21.3...406.4 | - | not in BNBC | manufacturer / ISO 4065 / EN 10255 practice; the values match those series (spot-checked) |
| "SAEngine (from memory, to be checked)" Hazen-Williams C | tables.py:730-731; hydraulics.py:669 | uPVC/PPR/HDPE 150, GI 120, CI 100 | part2 p1207 (BNBC gives only C = 100) | not in BNBC | usual textbook values; BNBC's nomograph is for C = 100 only |

##### 2. Wrong values (engineering impact)

1. tanks.py:166 (default `roofLive: float = 1.0`), used for every tank kind at tanks.py:980-990, including `septic`. Old -> new: for septic tanks, 1.0 kPa -> at least 7.0 kPa (BNBC Part 8 Sec 6.9.12.14, part2 p1107: "The manhole cover and the roof of the tank shall be designed for at least 7 kPa live load"). Impact: unconservative design of the septic tank roof slab (flexure, shear, cracking) and of the walls' top line loads. Example, a 150 mm roof with 1 kPa finish (D = 3.6 + 1.0 = 4.6 kPa): strength combination (3) 1.2D + 1.6Lr = 7.1 kPa at 1.0 kPa vs 16.7 kPa at 7.0 kPa, so the roof moments and shears are about 2.3 times what SAEngine designs for, and service moments for crack width are about 2 times. The roof live load also enters the bearing pressure and the flotation and support weights (tanks.py:1553, 1690), which matters less. tables.SEPTIC_COVER_LIVE = 7.0 already exists and septic.py:183 reports it, so the sizing report and the structural design disagree. Fix: for `kind == "septic"`, use `max(options.roofLive, T.SEPTIC_COVER_LIVE)` and cite Part 8 Sec 6.9.12.14. Underground reservoirs and rainwater tanks under driveways need a user override (Table 6.2.3 driveways 12.0 kPa); BNBC sets no tank-specific value for them.

No other numeric value in plumbing/** differs from BNBC. All Part 8 tables (8.5.1a-d, 8.5.2-8.5.6, 8.O.1, 8.O.2a-c, 8.6.2, 8.6.8-8.6.10, 8.6.12-8.6.17, 8.7.2-8.7.4, 8.S.1), Part 4 Table 4.4.1 and the Part 6 values used by tanks.py were checked cell by cell against rendered pages.

Observation, not counted as wrong: storage.py:3-10 / tables.py:276 hold a 1 h fire reserve (Part 8 Sec 5.9.1.2(c), literal). Part 8 Sec 5.5.3.3 refers storage to Part 4 Sec 4.2, whose Table 4.4.1 durations are 30-112 min by hazard and height: 75 min (light hazard-II above 102 m) and 75/95/112 min (ordinary hazards) exceed 60 min. A building over 51 m with ordinary-hazard occupancies would get a smaller reserve than Part 4's duration. The owner should decide which governs.

##### 4. External references (not verifiable here: external standard, check against the owner's copy)

| Standard + clause | What for | Where |
|---|---|---|
| ACI 318-19 21.2.2 | phi from net tensile strain | tanks.py:46, 478 |
| ACI 318-19 Table 22.5.5.1 (c) (+ Nu/6Ag) | one-way shear with axial tension | tanks.py:47, 716, 1268 |
| ACI 318-19 7.6.1.1 | slab minimum steel | tanks.py:61, 664 |
| ACI 318-19 7.7.2.3 | slab bar spacing 3h / 450 | tanks.py:80 |
| ACI 318-19 22.4.2.2 | P0 = 0.85 f'c Ag (0.65 x) for the soak-well ring | tanks.py:1746 |
| ACI rectangular stress block (generic) | flexure As | tanks.py:436 |
| EN 1992-1-1:2004 Eq. (7.1) | minimum steel for early thermal / shrinkage restraint | tanks.py:54, 657 |
| EN 1992-1-1 3.1.2, Table 3.1 | fctm, fctm(t), beta_cc | tanks.py:57-59, 599 |
| EN 1992-1-1 7.3.4 | crack width wk, sr,max, k1-k4, kt | tanks.py:63-70 |
| ISO 65 / BS EN 10255; ISO metric plastic series | pipe outside diameters | tables.py:683-729 |
| Jaky K0 = 1 - sin phi' (literature, not a standard) | earth pressure at rest | tanks.py:18 |
| Hunter curve (via BNBC Table 8.5.5) | already covered by BNBC row | demand.py:11 |

BNBC equivalents (quick): ACI 318 one-way shear, phi and minimum slab steel have Part 6 Ch 6 equivalents (BNBC Ch 6 is ACI-based). Not chased, because tanks.py cites ACI by design. The wall minimums are already cited to BNBC Sec 6.6.3.2/6.6.3.3 and are correct.

#### 1b. hvac/**

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| Table 8.2.2 (Sec 2.7.2.2), part2 p862, notes p863 | tables.py:19, 31-133; gains.py:34,41; energyplus.py:14; report.py:53; __init__.py:7 | 20 stations x 13 columns (DB/MWB 0.4/1/2 %, WB/MDB, range); Dhaka 0.4 % DB printed 35.55 | part2 p860-863 | correct | - (all 260 cells match) |
| Table 8.2.2 note b: May through September | tables.py:139-141; gains.py:58 | design months 5-9 | part2 p863 | correct | - |
| Sec 2.12.2.1, 2 % columns for cooling | tables.py:21,136-138; report.py:53; gains.py:34 | DESIGN_LEVEL "2" | part2 p915 | correct | - |
| Sec 2.12.2.2, indoor >= 24 °C | tables.py:142-144; report.py:58 | INDOOR_DB 24 | part2 p915 | correct | - |
| Sec 2.12.2.3, RH from Table 8.2.1 range for least energy | tables.py:509,517 | upper RH of row | part2 p915 | correct | - (taking the upper RH is SAEngine's reading of "minimum energy") |
| Sec 2.7.2.1(b), part2 p860 | tables.py:28,145-146 | indoor/outdoor DB difference <= 11 °C else ante-room | part2 p860 | correct | - |
| Table 8.2.1 (Sec 2.7.2.1), part2 p859-860 | tables.py:18,162-205; report.py:58 | 26 rows of DB and RH ranges | part2 p859-860 | correct | - (all rows match) |
| Table 8.2.3, part2 p863-869 (and GROUP_PAGE pages) | tables.py:20,207-367; air.py:12-13,89,124-129,144-150,180; gains.py:94-115; report.py:62,97; __init__.py:7 | ~95 rows: l/s per person, l/s per m², density, exhaust | part2 p863-869 | correct | - (every row and every group page matches) |
| Table 8.2.3 Living areas, p866 | air.py:18-19; tables.py:226,304 | 0.35 ACH but >= 7.5 l/s per person | part2 p866 | correct | - |
| Table 8.2.3 public toilets, note e (p. 867/869) | air.py:20-21,93,262; tables.py:314-315 | 25/30 l/s per WC or urinal | part2 p867 (value), p869 (note e) | correct | - |
| Table 8.2.3 private toilets, note f, p. 866 | air.py:21-22,94 | 10 l/s continuous / 25 intermittent per room | part2 p866 (value), p869 (note f) | correct | - (optional: "note f, p. 866" -> "p. 866, note f p. 869") |
| Table 8.2.3 hotel bathrooms (p. 865) | air.py:22,95,257; tables.py:284-285 | 12.5/25 l/s per room | part2 p865 | correct | - |
| Table 8.2.3 dwelling kitchens (p. 866) | air.py:23,96,253; tables.py:302-303 | 12.5/50 l/s per kitchen | part2 p866 | correct | - |
| Table 8.2.3 kitchens (cooking) (p. 865) | air.py:24,279; tables.py:274 | 3.5 l/s per m² | part2 p865 | correct | - |
| Table 8.2.3 enclosed parking (p. 868) | air.py:24,628; energyplus.py:340,346; tables.py:348 | 3.75 l/s per m² | part2 p868 | correct | - |
| BNBC 2020 Part 8 Sec 2.11.3.4, p. 905 | air.py:17,73,208 | outdoor air >= 2.5 l/s per person (mandatory) | part2 p905 | correct | - (Sec 2.7.2.3(a), p861, says the same) |
| Sec 2.11.5.1(d), p. 912 | air.py:31-32,86,336 | kitchen exhaust duct 7.62-12.7 m/s | part2 p912 | correct | - |
| Sec 2.8.1.5(b), p. 873 | air.py:32-33 | linings above 10 m/s need mechanical fastening | part2 p873 | correct | - |
| Sec 2.8.1.5(a) | air.py:74-75 | supply and return ducts insulated (25 mm is SAEngine's) | part2 p873 | correct | - |
| Sec 2.11.5.1(f), p. 912 | air.py:41-42,833-834; openings.py:10-11,67,290 | kitchen duct enclosure clearance >= 75 mm; one exhaust duct per enclosure | part2 p912 | correct | - (BNBC also caps it at 300 mm) |
| Sec 2.11.5.1(g) and Table 8.2.8 (pp. 912, 914) | air.py:97-122,214-240 | 17 rows of l/s per kW, electric/gas | part2 p912, p914 | correct | - (all 17 rows match) |
| Part 3 Table 3.1.9, Part 1 volume p. 66 | air.py:132-138,155; openings.py:24,88 | AC ceiling 2.6 m (educational/institutional/health/assembly), 3.0 m (industrial/storage) | part1 p66 | correct | - |
| Part 3 Sec 1.14.2.1(b), Part 1 volume p. 66 | air.py:134,140; openings.py:22-23,89; | 2.44 m clear under a duct in an AC room | part1 p66 | correct | - |
| Part 3 Table 3.4.5 (Sec 4.5.2), part1 p192 | tables.py:27,370-382; gains.py:122; report.py:67 | LPD 9/13/9/11/7/11/3/1.6 W/m² | part1 p191-192 | correct | - |
| Table 8.2.9(a), part2 p916 = Table 3.4.2 (Sec 4.4.1), part1 p186 | tables.py:22-23,399-403,428 | SHGC/SC at WWR 10-90 % | part2 p916; part1 p186 | correct | - |
| Table 3.4.3 (Sec 4.4.1.3), part1 p187 | tables.py:24,404-408; fallback.py:13,98 | overhang A 0.00-0.47 | part1 p186-187 | correct | - |
| Sec 4.4.3.1 and Figure 3.4.2, part1 p188-189 | tables.py:25,409-410; fallback.py:13-14,98 | sunshade depth 0.234 x window height | part1 p188 | correct | - (note: 4.4.3.1 is for naturally ventilated buildings; the SHGC/(SHGC+A) scaling is SAEngine's derivation from Eq 3.4.2 / Eq 8.2.1, SHGCadj = SHGC + A) |
| Part 3 Sec 4.5.1.2(a)-(c), part1 p191 | tables.py:26,411-424; geometry.py:10,210; report.py:47-50 | least window 20 % (<8 m), 30 % (8-14 m), 35 % (>14 m) of external wall | part1 p191 | correct | - |
| BNBC Table 8.2.11 (p. 919) | plant.py:17,20,58,70-74,145,342 | min COP: air-cooled 2.90/3.05; centrifugal 5.80/5.80/6.30; screw 4.70/5.40/5.75; size breaks 530/1050 kW | part2 p919 | correct | - |
| Part 8 Sec 2.6.2.4 and 2.6.2.5, pp. 853-854 | plant.py:3-6 | plant rooms; roof "structurally strong enough ... dynamic load of the chiller"; isolators | part2 p853-854 | correct | - |
| Sec 2.6.2.4(b) (p. 853) | plant.py:6-8,60,553,560 | >= 500 TR water-cooled: 4.5 m centrifugal, 3.6 m screw/reciprocating below beam soffit | part2 p853 | correct | - (BNBC says "should", i.e. advisory) |
| BNBC 2020 Part 6 Sec 2.3.12, Table 6.2.6 impact allowance | report.py:380-381; plant.py:39 | rotating plant vibrates; impact allowance | part1 p540-541 | correct | - |
| BNBC Part 8 Ch 2 gives no supply temperature / no duct velocity table | air.py:9-10,30-31 | silence of the code | part2 p843-924 (searched) | correct | - (only 0.12-0.25 m/s room air, 10 m/s linings, 7.62-12.7 m/s kitchen ducts exist) |
| Table 8.2.2 gives no latitude/longitude | tables.py:48,472 | silence of the code | part2 p862 | correct | - |

##### 2. Wrong values (engineering impact)

None. Every BNBC number in hvac/** (Table 8.2.1, 8.2.2, 8.2.3, 8.2.8, 8.2.9(a)/3.4.2, 3.4.3, 3.4.5, 3.1.9, 8.2.11, 2.44 m, 2.5 l/s, 11 °C, 24 °C, 7.62/12.7 m/s, 75 mm, 4.5/3.6 m, 0.234, 20/30/35 %) matches the rendered page.

##### 4. Markers ("from memory / to be checked"), 15 distinct, verified against BNBC

BNBC is silent on all of them (confirmed by searching Part 8 Ch 2, part2 p843-924), except where noted:
- tables.py:48,472 station lat/long: BNBC gives none.
- tables.py:439-453,474 equipment W/m²: none in BNBC.
- tables.py:455-459,478 metabolic heat: none.
- tables.py:461-464,483 supply air 13 °C / 0.008: none.
- tables.py:465-467,481 design wind 2 m/s, elevation 10 m: none.
- air.py:28-29,67 duct roughness 0.09 mm: none.
- air.py:34-35,82-87 duct velocity limits (7.5/6/6/5/10 m/s): none (only kitchen 7.62-12.7, Sec 2.11.5.1(d)).
- constructions.py:186-187 film resistances (ISO 6946): none. (BNBC Part 8 Sec 2.? p858 gives a desirable roof U <= 0.58 W/m²K and 1.16 W/m²K for walls next to non-AC spaces, not cited by the code; could serve as a check.)
- energyplus.py:342 1 ACH default: BNBC Table 8.2.6 (p904-905) gives ACH by application, see section 3.
- fallback.py:22-23 irradiances, absorptance, ho, people split, blinds: none.
- plant.py:21 chilled water 12.2/6.7 °C: none.
- plant.py:23 VRF 56 kW modules: none.
- plant.py:30,76,116,418 TYPICAL weights/sizes: none (manufacturer data).
- plant.py:101 pipe velocity 3 m/s: none.
- plant.py:33,106 refrigerant pipe sizes: none.

##### 5. External references (external standard, check against the owner's copy)

- ASHRAE 62.1 ventilation rate procedure (Vbz = Rp Pz + Ra Az, the origin of Table 8.2.3): air.py:16; report.py:63.
- ASHRAE Handbook Fundamentals Ch 1 psychrometrics (Eq 3 pressure, Eq 6 Hyland-Wexler, Eq 33 humidity ratio): fallback.py:18,52-79.
- ASHRAE Handbook Fundamentals Ch 18 (Table 1 metabolic heat; office load factors 5.4/10.8 W/m²): tables.py:440,456,474,478.
- ASHRAE Handbook Fundamentals Ch 21 (duct roughness 0.09 mm, rectangular equivalent diameter, velocity practice): air.py:28,34,37,67,82-85.
- ASHRAE Handbook Fundamentals Ch 22 (pipe velocity 3 m/s): plant.py:101.
- ASHRAE clear-sky solar model (EnergyPlus ASHRAEClearSky): energyplus.py:15,237; report.py:55.
- ASHRAE 2005 HOF materials dataset (EnergyPlus DataSets): constructions.py:4,38,69.
- ISO 6946 surface film resistances: constructions.py:186,194.
- ARI 550/590 (test standard printed in BNBC Table 8.2.11; not cited by code beyond the table).

#### 1c. electrical/**, mep/**, library/mep.py (paths relative to python/src/saengine/)

checked=62 correct=62 wrong=0 not-in-BNBC=0 could-not-find=0 external=9 markers(from memory etc.)=16

| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| Part 8 Sec 1.3.2 (p763-764) | electrical/tables.py:18; demand.py:1-6; report.py:63; library/mep.py:899 | list the room, floor and building loads plus lifts, pumps, basement ventilation | part2 p763-764 | correct | - |
| Table 8.1.17, Sec 1.3.2.5 (p765-767) | electrical/tables.py:19, 52-83; demand.py:6, 37, 202, 214; report.py:63, 97; library/mep.py:876-887 | 13 rows non-A/C / A/C W/m²: 20/75, 20/75, 32/80, 24/75, 28/75, 16/-, 28/75, 20/75, 16/75, 32/75, 12/70, 4/-, 2/- | part2 p766-767 (rendered) | correct | - (table is on p766-767; 1.3.2.5 on p765) |
| Appendix A Table 8.A.1 (p1167-1168) | electrical/tables.py:20; demand.py:15 | diversity allowances are for final circuits, a guideline | part2 p1167 | correct | - |
| Sec 1.3.13.1 (p790-791) | electrical/tables.py:21, 171-175, 186; rooms.py:18, 286; risers.py:14; report.py:81 | >6 storeys or 20 m: one 200 x 400 mm shaft per 1500 m²; floor gaps filled with RCC or non-inflammable material; not beside sanitary shafts | part2 p790-791 | correct | - |
| Sec 1.3.13.2(a), (d) (p791) | electrical/tables.py:176-179 | 5 storeys or fewer with < 600 m² a floor: PVC cables in PVC/GI pipes; > 9 storeys: busbar trunking | part2 p791 | correct | - |
| Sec 1.3.13.2(e) (p791) | electrical/tables.py:180-181; risers.py:10 | 37 mm between cables fixed on the wall | part2 p791 | correct | - |
| Sec 1.3.13.3(a) (p792) | electrical/tables.py:182-183; risers.py:8 | busbar trunking typically 200-3000 A | part2 p792 | correct | - |
| Sec 1.3.18.1 (p796) | electrical/tables.py:24, 86-91; supply.py:4, 30; demand.py:15; report.py:66; library/mep.py:830, 836 | substation when the load exceeds 50 kW; load factor at least 80 %; future expansion | part2 p796 | correct | - |
| Sec 1.3.20.1(e) (p805) | electrical/tables.py:34, 89-91; supply.py:4, 30; library/mep.py:811 | HT 11 kV with substation for connected loads of 50 kW and above (code uses >=) | part2 p805 | correct | - |
| Sec 1.3.18.2, 1.3.18.7(a), (g) (p796-800) | electrical/rooms.py:4-5; report.py:75, 176 | substation on the lowest floor with street access; transformer in a corner; not in a basement; higher voltage "may also be considered" in a basement | part2 p796-800 | correct | - |
| Sec 1.3.18.3(a) (p797) | electrical/tables.py:100-102; rooms.py:10 | room height 3.0-3.6 m | part2 p797 | correct | - |
| Sec 1.3.18.3(b) (p797) | electrical/tables.py:103-106; rooms.py:210 | 0.75 / 1.0 / 1.25 m to walls; 1.5 m between transformers (11 kV), 2.5 m higher | part2 p797 | correct | - |
| Sec 1.3.18.3(c) (p798) | electrical/tables.py:107-108; rooms.py:13 | soak pit above 2000 l oil | part2 p798 | correct | - |
| Table 8.1.23 (p798) | electrical/tables.py:27, 110-123; supply.py:62; rooms.py:13, 255; report.py:69 | 10 rows (1x150 12/45 ... 3x1000 45/220) | part2 p798 | correct | - |
| Sec 1.3.18.4 (p799) | electrical/tables.py:28; rooms.py:14; library/mep.py:845 | dry type for hospitals, multistoried shopping centres, fire risk | part2 p799 | correct | - |
| Sec 1.3.18.6 (p799) | electrical/tables.py:29 | substation ventilation | part2 p799 | correct | - |
| Sec 1.3.19.2 (p801) | electrical/tables.py:31, 135-138, 153-156; supply.py:8; demand.py:280; rooms.py:212 | essential light, A/C, equipment, services, lifts, one or all pumps (no share given); 1.0 m to walls, 1.25 m between sets | part2 p801 | correct | - |
| Sec 1.3.19.3 (p801) | electrical/tables.py:32; rooms.py:15-17; report.py:176 | ground floor or first basement; shock absorbing mountings | part2 p801 | correct | - |
| Table 8.1.24 (p802) | electrical/tables.py:33, 139-140; supply.py:73; report.py:260 | 25/20, 48/24, 100/30, 150/36, 300/48, 500/56 | part2 p802 | correct | - |
| Sec 1.3.19 / 1.3.19.5 | library/mep.py:814-815 | standby generator; UPS | part2 p800, p802 | correct | - |
| Part 8 Sec 4.2.1.1, 4.2.1.3 (p982-983) | electrical/tables.py:44, 163-167; supply.py:12, 100; report.py:72 | lifts above 6 storeys or 20 m; standby power above 10 storeys or 32 m and in hospitals | part2 p982 | correct | - |
| Sec 1.3.32.7 (p818) | electrical/tables.py:35, 201-202; lightning.py:21 | system earth around 1 ohm | part2 p818 | correct | - |
| Sec 1.3.32.7(e) (p819) | electrical/tables.py:203-204; lightning.py:21, 451 | electrodes >= 1.8 m apart | part2 p819 | correct | - |
| Sec 1.3.32.10 (p820) | electrical/tables.py:36, 205-206 | pit 600 x 600 x 600 mm inside | part2 p820 | correct | - |
| Sec 1.3.33.8(b) (p826) | electrical/tables.py:207-208; lightning.py:20; library/mep.py:1063 | 10 ohm up to 10 storeys, 2 ohm high rise | part2 p826 | correct | - |
| Table 8.1.27(a)-(c) (p821-822) | electrical/tables.py:37, 210-251, 410, 418; lightning.py:4, 67; library/mep.py:1035-1049 | indices A, B, C, D, E, F (2/4/5/8/11/16/22/30 to 53 m), G (2...20, over 21: 21) | part2 p821-822 (rendered) | correct | - |
| Table 8.1.27(c) note c | electrical/tables.py:255-258; lightning.py:6 | above 53 m: protection in all cases | part2 p822 | correct | - |
| Sec 1.3.33.5 (p823) | electrical/tables.py:255-257; lightning.py:6; report.py:86 | marginal risk index 40 | part2 p823 | correct | - |
| Table 8.1.28 (p824) | electrical/tables.py:38, 253-254; lightning.py:7; library/mep.py:1049 | BNBC's examples use G = 21 | part2 p824 | correct | - |
| Sec 1.3.33.7 (p825) | electrical/tables.py:40, 260-261; lightning.py:9, 260 | one air spike per 80 m² to begin with | part2 p825 | correct | - |
| Sec 1.3.33.6(a) (p825) | electrical/tables.py:39, 262-263; lightning.py:10 | air terminal >= 300 mm above the highest point | part2 p825 | correct | - |
| Sec 1.3.33.6(e) (p825) | electrical/tables.py:274-276; lightning.py:22 | inspection box 1000 mm above plinth | part2 p825 | correct | - |
| Sec 1.3.33.8(a) (p826) | electrical/tables.py:264-266; lightning.py:12 | <= 9 m to a roof conductor, + 0.3 m per 0.3 m below | part2 p826 | correct | - |
| Sec 1.3.33.8(c) (p827) | electrical/tables.py:267-273; lightning.py:14, 103-112; library/mep.py:1055 | one up to 100 m²; else 1 for the first 80 m² + 1 per 100 m² or part; or 1 per 30 m perimeter (code: 1 + ceil((A-80)/100)) | part2 p827 | correct | - |
| Table 8.1.29 (p827) | electrical/tables.py:42, 277-283 | 12 mm rods, 20 x 3 strip, 19 x 1.8 mm cable, copper clad steel 50 mm, GI 38/50 mm | part2 p827 (rendered) | correct | - |
| Eq 8.1.1, Sec 1.3.33.8(g) (p828) | electrical/tables.py:43; lightning.py:23; report.py:89; library/mep.py:1062 | D = 0.3 R + H / (15 n) | part2 p828 (rendered) | correct | - |
| Sec 1.3.33.8(j): rolling sphere per NFPA 780 | electrical/tables.py:285-286 | BNBC allows NFPA 780 rolling sphere, uses no protection levels | part2 p828 | correct | - |
| Part 6 Sec 2.1.4 (symbols D, F) | electrical/report.py:649-654; mep/loads.py:35-36 | D includes "permanent equipment"; F fluids of well-defined pressure and maximum height | part1 p522-523 | correct | - |
| Part 6 Sec 2.2.6 | mep/loads.py:6, 36; mep/report.py:25; electrical/report.py:650 | fixed service equipment = dead load | part1 p532 | correct | - |
| Part 6 Sec 2.3.12, Table 6.2.6 | mep/loads.py:23-28, 90-101, 164, 712; mep/report.py:29; library/mep.py:102-111, 944 | impact as live load: lifts 100 %, light machinery 20 %, reciprocating / power driven 50 % | part1 p540-541 (rendered) | correct | - |
| Part 6 Sec 2.7.3.1 | mep/loads.py:9-13, 301; mep/report.py:25; library/mep.py:1107 | F only in 1.4(D+F) and 1.2(D+F+T)+..., not in 0.9D combinations; effects of loads not acting investigated | part1 p685 (rendered) | correct | - |
| Part 6 Sec 2.5.7.3(c) | mep/loads.py:38; mep/report.py:30 | 100 % of permanent heavy equipment and retained liquid in W | part1 p628 | correct | - |
| Part 6 Sec 5.16.3.3 | mep/openings.py:9-11, 90, 94; mep/report.py:36 | sleeves passing through: "not impair significantly", no number | part1 p863 | correct | - |
| Part 6 Sec 5.16.3.5(a), (b) | mep/openings.py:11-14, 91, 95; mep/report.py:37 | 1/3 thickness, 3 diameters, for embedded pipes other than those passing through (SAEngine adopts for sleeves) | part1 p863 | correct | - |
| Part 6 Sec 6.4.1.1.1 | mep/openings.py:18, 88; mep/report.py:34 | effect of openings considered in Vn | part1 p921 | correct | - |
| Part 6 Sec 6.5.4.1 | mep/openings.py:31, 716 | openings of any size if shown by analysis | part1 p949 | correct | - |
| Part 6 Sec 6.5.4.2.1-6.5.4.2.3 | mep/openings.py:34-38, 456, 615, 647-649, 709, 726; mep/report.py:39 | middle-middle any size; column-column 1/8 of strip width; column-middle 1/4 of bars; replace interrupted bars | part1 p949 | correct | - |
| Part 6 Sec 6.5.2.1 | mep/openings.py:38-39, 540, 595 | column strip 0.25 l1 or 0.25 l2 each side, lesser | part1 p945 | correct | - |
| Part 6 Sec 6.4.10.6, 6.4.10.6.1 | mep/openings.py:45-47, 483, 553, 735, 772, 799; mep/report.py:39 | within 10 h of a column, or in a flat slab's column strip: perimeter between tangents ineffective | part1 p942 | correct | - |
| Part 6 Sec 6.4.8 | mep/openings.py:54, 922 | in-plane wall shear | part1 p935 | correct | - |
| Part 6 Sec 6.6.3.4 | mep/openings.py:929 | walls > 250 mm thick: two layers | part1 p969 | correct | - (BNBC excepts basement walls; the note could say "except basement walls") |
| Part 6 Sec 6.6.3.7 | mep/openings.py:56, 935; mep/report.py:40 | 2 x 16 mm (two layers) / 1 x 16 mm (single layer) around openings | part1 p969 | correct | - |
| Part 8 Sec 5.9.1.2(c)(ii); Table 8.5.6; Table 8.5.1; Table 8.5.3 | library/mep.py:263, 269, 273, 285, 334 | restatements of plumbing clauses | part2 p1034, 1041, 1042, 1047 | correct | - (same as plumbing rows) |
| Part 4 Table 4.4.1 with Sec 5.9.1.2(c) | library/mep.py:292 | 1 h of standpipe flow for a tall building | part1 p322; part2 p1041 | correct | - (see the fire reserve observation in section 2) |
| Tables 8.6.12 / 8.6.13; Sec 5.6.3 / 5.6.4 | library/mep.py:308, 341 | drainage units; 5 per dwelling, 7.4 m² per office person | part2 p1039, 1112-1113 | correct | - |
| Sec 7.8.9; Appendix R Dhaka 88; Sec 7.4.1 300 m² | library/mep.py:445, 451, 463, 467 | harvesting 90/210 days; 88 mm/h; harvesting from 300 m² | part2 p1129, 1134, 1213 | correct | - |
| Part 8 Sec 2.7.2, 2.12.2.1-2.12.2.3; Table 8.2.1; Table 8.2.2 col 14 | library/mep.py:540-574 | 2 % DB, 24 °C, upper RH of range, daily range column | part2 p859-863, 915 | correct | - |
| Part 3 Sec 4.4.3.1 (0.234); Sec 4.5.1.2(a) (0.2) | library/mep.py:609-617 | overhang 0.234 x window height; default WWR 20 % | part1 p188, 191 | correct | - |
| Table 8.2.3; Part 3 Table 3.4.5 | library/mep.py:632-639 | occupant density; lighting maximum | part2 p863-869; part1 p192 | correct | - |
| "BNBC gives none" (power factor, fuel hours, essential share) | electrical/tables.py:92-94, 150-156; demand.py:16, 247; library/mep.py:822, 865 | silence of the code | part2 p730-842 (searched "power factor", "fuel"): only the 1.65 current factor (Sec 1.3.2.4) and capacitor mention (p806) | correct | - |

Markers in this sub-part (16 distinct, all non-BNBC values; BNBC Part 8 Ch 1 is silent on each, confirmed by search of part2 p730-842): electrical/tables.py:126 IEC 60076 transformer ratings; :142 generator kVA sizes; :146 ISO 8528 pf 0.8; :148 fuel 0.27 l/kWh; :159 oil density 880; :194 + risers.py:21, 345 tray fill 40 %; :287 + lightning.py:13, 120, 462 IEC 62305 levels; :296 + lightning.py:26, 430 rebar 0.2 ohm; :304 transformer dimensions/masses; :322 dry-type mass 0.9; :326 generator set data; :350 busbar data; :365 cable OD; :380 target pf 0.95; mep/loads.py:714 HVAC plant weights "from memory"; tables.py:157 diesel density (typical). Note: Sec 1.3.32.7(a) gives copper rod electrodes 12.5 mm x 3.33 m and GI pipe 38 mm x 6.5 m, which the code does not use (Table 8.1.29's 12 mm is what it quotes, fine).

External (this sub-part): IEC 60076 (transformer ratings, tables.py:126); ISO 8528 (generator rating pf, tables.py:146); IEC 62305-3 Tables 2 and 4 (rolling sphere/mesh/down-conductor spacing by level, tables.py:285-294; lightning.py:12, 116-120; library/mep.py:1014); IEC 62305-3 natural down conductor 0.2 ohm (tables.py:295-297; lightning.py:24-26, 430, 462); NFPA 780 rolling sphere (tables.py:286, referred by BNBC Sec 1.3.33.8(j)); ACI 318-19 Table 22.5.5.1 / 22.5 (beam net-section shear, openings.py:16-17, 127-146; report.py:34; BNBC differs: Sec 6.4.2.1.1 Vc = 0.17 lambda sqrt(f'c) bw d with no size effect or rho term; the ACI-19 branch without Av,min is more conservative, the Vs cap 0.66 sqrt(f'c) bw d is the same); ACI 318-19 8.5.4.2 (= BNBC 6.5.4.2, same, openings.py:35); ACI 318-19 22.6.4.3 (= BNBC 6.4.10.6, same, openings.py:46); ACI 318-19 22.6.5.2 punching vc (openings.py:49); Mansur and Tan 1999 (literature, Vierendeel openings, openings.py:20).


## Appendix F: Docs, UI strings, report, verification

checked=157 correct=119 wrong(number+value+clause)=6 (number 5, value 0, clause 1) not-in-BNBC=0 could-not-find=0 external=29 markers(from memory etc.)=3
(+1 BNBC-internal value issue under Wrong values: pile uplift FS 2.5 vs Sec 3.11.3; the cited Table 6.3.10a value itself is correct.)

Scope: docs/**, README.md, python/src/saengine/{report,verification,importers,exporters,rpc,pipeline,project,cli,codes/schemas}/**, codes/packs/bnbc2020/README.md, workbench saengine*/browser and services/saengineProject. "generated.ts" = workbench/src/vs/workbench/services/saengineProject/common/projectLibraries.generated.ts, generated from python/src/saengine/library: fixes belong in the Python source named. README.md, pipeline/**, project/**, cli/** and codes/schemas/** have only generic BNBC mentions (schema examples "BNBC Part 6 2.7.3" are correct). BNBC table values were checked on rendered pages wherever the text layer is a table.

### 1. Citation table
| Citation (as written) | Where (file:line) | Claim (value/rule) | BNBC checked | Verdict | Correction |
|---|---|---|---|---|---|
| Table 6.2.13 (site class) | docs/manual/01-soil-report.md:118,140; verification/cases/soil.py:70; docs/verification/README.md:95; soilDocument.ts:484,595,914; soilEditor.ts:1292; settingsEditor.ts:112,114; report/build.py:487 | N limits 15/50 between SD/SC/SB; S1 >=10 m soft clay PI>40; S2 liquefiable | part1 p609-610 | correct | - |
| Table 6.2.14 Z (p.615) | docs/manual/02-project-settings.md:158; settingsEditor.ts:102; bnbc2020/README.md:16; soil.py:574 | Z 0.12/0.20/0.28/0.36; MCE PGA on rock (Sec 2.5.4.2) | part1 p611, p615 | correct | - |
| Table 6.2.15 towns (p.615) | bnbc2020/README.md:15; soilDocument.ts:385 | town zone coefficients | part1 p615 | correct | - |
| Table 6.2.16 S, TB | soil.py:574; analysis.py:346; generated.ts:9406 | SD: S=1.35, TB=0.2 s | part1 p616 | correct | - |
| Table 6.2.17 / 6.2.9 importance | settingsEditor.ts:105,106; 02-project-settings.md:159; bnbc2020/README.md:17 | seismic / wind importance | part1 p616, p601 | correct | - |
| Table 6.2.8 V (p.600) | settingsEditor.ts:104; 02-project-settings.md:158; bnbc2020/README.md:15; code-packs.md:251; soilDocument.ts:385 | basic wind speed | part1 p600 | correct | - |
| Table 6.1.1 (pp.480-481) | new-building.md:30,102; 02-project-settings.md:41; generated.ts:3817; bnbc2020/README.md:17 | occupancy categories I-IV | part1 p479-480 | correct | - |
| Sec 2.5.4.3 spectrum | docs/verification/README.md:84; analysis.py:346,354; rs_design.py:45 | Sa=(2/3)(ZI/R)Cs | part1 p612 (Eq 6.2.34) | correct | - |
| Sec 2.5.9.4 (p.635) scaling | rs_design.py:69,117,130; 02-project-settings.md:137; 08-fem.md:63; femSeismicDesign.ts:38,203; generated.ts:3280,3282 | forces (not drifts) scaled to 0.85V when Vrs<0.85V | part1 p635 | correct | - |
| Sec 2.5.7.7 design drift | rs_design.py:70 | Cd·δ/I | part1 p631 Eq 6.2.45 | correct | - |
| Part 6 Sec 2.5.7.1 (design drift Cd·δ/I) | workbench/.../saengineFem/browser/femChartData.ts:198 | design drift = Cd·δ/I | part1 p626 (2.5.7.1 = base shear), p631 | wrong number | Sec 2.5.7.1 -> Sec 2.5.7.7 (Eq 6.2.45) |
| Sec 2.5.9.2 modal mass | femResultsView.ts:610; femChartData.ts:358 | >=90 % mass each direction | part1 p634 | correct | - |
| Sec 2.5.7.6.3 (p.631) | report/build.py:949-950 | 5 % mass shift in one direction at a time with 100/30 | part1 p631 | correct | - |
| Sec 2.5.13.1 (b) | generated.ts:3288 (python library settings schema) | 100%+30% in SDC D, and C with plan irregularity V | part1 p645 | correct | - |
| Sec 2.5.7.6.2 Eq 6.2.43, Eq 6.2.44 | generated.ts:3296 | ±0.05 L accidental eccentricity; Ax <=3.0 | part1 p630-631 | correct | - |
| Sec 2.5.13.2 | generated.ts:3302; soil.py:572 | Ev = 0.50 ah D, ah=(2/3)ZS | part1 p645-646 Eq 6.2.56 | correct | - |
| Sec 2.5.14.1 | generated.ts:3322 | moment frames SDC D: Δa/ρ, ρ 1.0 or 1.3 | part1 p647 | correct | - |
| Table 6.2.21 | femResultsView.ts:592 | allowable drift Δa/hsx | part1 p648 | correct | - |
| Sec 2.5.7.9, Eq 6.2.48 | report.typ:577,580; generated.ts:3270 | θ = Px Δ/(Vx hsx Cd) <= 0.10 | part1 p632 | correct | - |
| Sec 2.5.5.6(.1), 2.5.13.4 | new-building.md:146; generated.ts:737,1217 | overstrength combos for members under discontinuous walls/frames, collectors | part1 p625-626, p646 | correct | - |
| Sec 2.5.5.2, Table 6.2.18 | report/build.py:1594; new-building.md:83 | SDC from zone, site, category | part1 p617 | correct | - |
| Sec 2.5.3.1 | soilDocument.ts:917,918; soil.py:573 | S1/S2 need site-specific study; liquefaction under design EQ | part1 p607-608 | correct | - |
| Sec 2.7.3.1 (p.685) | bnbc2020/README.md:19; settingsEditor.ts:58; report/build.py:604-605,2411; beta.py:141; generated.ts:3265,3317,3783,3797,14383; report.typ:208; glossary.md:14 | 7 strength combos; T only in 1.2(D+F+T)+1.6(L+H)+0.5(Lr or R); exception 1: 0.5L for L<=5.0 kN/m² except garages/assembly; F in 1.4(D+F) | part1 p685 | correct | - |
| Sec 2.7.2.1 service | report/build.py:2411 | allowable stress combos | part1 p684 | correct | - |
| Sec 2.3.12 + Table 6.2.6 | generated.ts:11777,12366,12382; report.typ:1110 | machinery impact as live load; light machinery 20 %, lifts 100 % | part1 p540-541 | correct | - |
| Sec 2.2.6 + Table 6.2.6 | verification/cases/mep.py:105 | fixed equipment = dead load; impact 20 % light machinery | part1 p532, p541 | correct | - |
| "6.2.9.3" (exposure) | docs/manual/02-project-settings.md:86; settingsEditor.ts:116 | Exposure A urban/suburban/wooded, B, C | part1 p551-552 (Sec 2.4.6.3) | wrong number | 6.2.9.3 -> Sec 2.4.6.3 |
| Table 6.2.3 live loads (pp.533-539) | new-building.md:30,64; 02-project-settings.md:90,99-100; bnbc2020/README.md:18; report/build.py:2408; generated.ts:3426 | residential minimum 2.0 kN/m² | part1 p535 | correct | - |
| Table 6.2.19 / 6.2.20 / 6.2.11 / 6.2.12 | 02-project-settings.md:69,159; settingsEditor.ts:109; report/build.py:495,743,1598; bnbc2020/README.md:21; generated.ts:3971 | R, Ω0, Cd; Ta = Ct hn^m; Kz; Kd | part1 p621, p628, p602-603 | correct | - |
| Sec 2.6.4 temperature | report/build.py:604; generated.ts:4138,4142,4148 | temperature effects where significant; shade air temperature range (a) | part1 p678 | correct | - |
| Sec 2.6.5 / 2.6.5.2 | tanks.py:99; report/build.py:2407 | full hydrostatic uplift over the entire area | part1 p680 | correct | - |
| Sec 1.2.7.3 | report/build.py:576; generated.ts:3369 | soil-structure interaction in the model | part1 p484 | correct | - |
| Sec 1.8.5.2 (b) | substructure.py:302,317; 09-substructure.md:92; substructure.py:359 | ties resist 10 % of larger footing/column load, tension or compression | part1 p507 | correct | - |
| Sec 3.9.5, Eqs 6.3.6, 6.3.7b, 6.3.8 | soil.py:516-616,686-688; docs/verification/README.md:101; 01-soil-report.md:41,141; soilDocument.ts:296; generated.ts:8981 | FL=CRR/CSR; rd=1-0.015z; CSR=(amax/g) rd σv/σ'v, no 0.65; CRR "several procedures" | part1 p733-734 | correct | - |
| Table 6.3.8 | 01-soil-report.md:127; 09-substructure.md:91; tutorials/03:113; soilDocument.ts:590,618,654; soilEditor.ts:1323,1339; report/build.py:2417; generated.ts:9005 | permissible total/differential settlement | part1 p732-733 | correct | - |
| Table 6.3.10a (p.750) | substructure_deep.py:112-113,125; substructureEditor.ts:81,82,2158; substructureDocument.ts:142; 09-substructure.md:53-54; bnbc2020/README.md:27; generated.ts:10515,10529 | permanent, normal control 2.5 (good 2.0, poor 2.8, v. poor 3.0); "downward and upward" | part1 p750 | correct | (see Wrong values: uplift FS vs Sec 3.11.3) |
| Sec 3.10.1.18 | substructure_deep.py:111,124,377; substructureEditor.ts:81,2143,2151; substructureDocument.ts:145; generated.ts:10515,10523,10537,10545 | FS >= 3.0 without site load test (2.0 with, good control); partial 1.5 skin / 3.0 end | part1 p750 | correct | - |
| Table 6.3.10b | substructure_deep.py:112-113 | normal control presumes load test data | part1 p751 ("Load Test Data: Yes" for good/normal/poor) | correct | - |
| Sec 3.10.4.10 | substructureEditor.ts:81,2143; substructureDocument.ts:145; generated.ts:10523 | bored-pile FS as for driven | part1 p766 | correct | - |
| Sec 3.10.1.19 | generated.ts:3392 (python library) | group efficiency 1.0 | part1 p751 | correct | - |
| Sec 3.10.1.30 | substructureDocument.ts:469,493,912,937,940,941,948,949; substructureEditor.ts:1988 | end-bearing driven > max(750 mm, 2.5D); friction generally >= 3D; pile side to cap edge >= 100 mm | part1 p755 | correct | - |
| Secs 3.10.4.5, 3.10.4.7, Eqs 6.3.29, 6.3.31, 6.3.33 (FS 3.5) | substructure_deep.py:184-211,386; generated.ts:10472; substructureEditor.ts:2116 | fs=1.2N̄60<=70 clay; 1.0N̄60<=60 sand; fb=15N60 L/D<=150N60, <=4000; FS 3.5 | part1 p762-763 (rendered) | correct | generated.ts:10472 "Eqs 6.3.29 and 6.3.31-32" omits end bearing: could read "Eqs 6.3.29-6.3.34" (cosmetic) |
| Eqs 6.3.11-6.3.13 | substructure_deep.py:124,198,377; 09-substructure.md:90 | Qult=Qs+Qb-W; uplift <= 0.7Qs+W; Qa=Qult/FS | part1 p743 | correct | - |
| Eqs 6.3.21 to 6.3.34 | 09-substructure.md:90 | BNBC SPT equations (driven 6.3.21-28, bored 6.3.29-34) | part1 p747-749, p762-763 | correct | - |
| Part 6 2.7.2 service combos | 09-substructure.md:74-75 | D, D+L+Lr, D+W, D+0.75L+0.75Lr+0.75W, 0.6D+W, D+0.7E, D+0.75L+0.75Lr+0.525E, 0.6D+0.7E | part1 p684 | correct | (D+L+Lr merges BNBC combos 2 and 3: conservative) |
| Sec 6.2.3 (pp.897-898); 6.2.3.3(a); 6.2.3.3(c) (p.898) | bnbc2020/README.md:23; code-packs.md:193; walls.py:178-179; seismic_detailing.py:146 | shear 0.75; seismic shear 0.60 (a); joints & diagonal coupling beams 0.85 (c) | part1 p897-898 | correct | - |
| Table 6.6.1 (+ note b) | new-building.md:93,94 | beams l/16, l/18.5, l/21; ×(0.4+fy/700) | part1 p900 (rendered) | correct | - |
| Sec 6.2.5.3.3, Eq 6.6.5/6.6.6 | new-building.md:94 | h from αfm | part1 p903 | correct | (BNBC min 90 mm for αfm>2; app's 125 mm is conservative) |
| Table 6.6.3, Sec 6.2.5.3.2 | new-building.md:95 | flat plates ln/30 ext. w/o edge beams, ln/33 interior at fy 420; >=125 mm | part1 p901-902 (rendered) | correct | - |
| Sec 6.3.10.4.1 | 08-fem.md:38; report/build.py:1022; exporters/etabs.py:85; importers/etabs.py:1069; importers/neutral.py:1083; importers/sap2000.py:25; tutorials/04:50,123; generated.ts:3235,3237,3251 | columns 0.70Ig, walls 0.70/0.35Ig, beams 0.35Ig, flat plates 0.25Ig, area 1.0Ag | part1 p912 (rendered) | correct | - |
| Sec 6.3.10 / 6.3.10.1 Eq 6.6.14 / 6.3.10.5.2 Eq 6.6.17 / 6.3.10.6 Eqs 6.6.19-6.6.23 / 6.3.10.6.3 / 6.3.10.7 Eqs 6.6.25-6.6.28 / 6.3.10.7.4 / Fig 6.6.5 | slenderness.py:1,75,226-232,279-280; report.typ:578,594,769-770,782; femDesign.ts:45; generated.ts:3257,4085,4089,4097,4105 | Q<=0.05 nonsway; δns=Cm/(1-Pu/0.75Pc)>=1; EI 0.4EcIg/(1+βdns) or (0.2EcIg+EsIse)/(1+βdns); k=1.0 permitted; δs=1/(1-Q), >1.5 -> second order or 6.6.28 | part1 p910-915 (rendered 912-915) | correct | - |
| Sec 6.3.2 strain compatibility | walls.py:114; beta.py:96 | stress block | part1 ~p904 | correct | - |
| Sec 6.4.8.4-6.4.8.9 (pp.935-937), Eqs 6.6.68-6.6.70; 0.83√f'c h d | walls.py:1,68,75,211; report.typ:657; verification/README.md:61 | wall in-plane shear | part1 p935-937 | correct | - |
| Sec 6.4.10.1, 6.4.10.5.1 (pp.937-941), Eqs 6.6.72-6.6.74; 6.4.10.3; 6.4.10.5 | beta.py:41; new-building.md:141; report.typ:753; generated.ts:1998,11006 | punching; stirrups; headed studs | part1 p937-941 | correct | - |
| Sec 6.4.10.6.1 | verification/cases/mep.py:7,214 | perimeter within tangents to opening ineffective | part1 p942 | correct | - |
| Sec 6.4.1.1.1 | verification/cases/mep.py:158 | openings considered in Vn | part1 p921 | correct | - |
| Sec 6.6 (pp.968-970), 6.6.3, 6.6.3.4, 6.6.4, 6.6.5.2, 6.6.5.3 | walls.py:1,115; report.typ:657; report/build.py:2415; generated.ts:2761,2767,2773 | walls: min bars, two layers >250 mm except basement, k for braced/restrained, basement wall | part1 p968-970 | correct | - |
| Sec 6.7, 6.7.1.1(a)-(d) | report.typ:722; femWallsStairs.ts:98; generated.ts:2412 | stair effective span, centre-to-centre of beams (a) | part1 p972 | correct | - |
| Sec 7.4.3.2 (p.1015) | beta.py:141; new-building.md:138; report.typ:738-739 | elements supporting masonry / lintels (deflection 1/600, bearing 100 mm) | part1 p1015 | correct | (the 45° load rule is not in 7.4.3.2: beta.py already says "stated 45° rule") |
| Part 6 Sec 5.16.3.5(a) h/3 | verification/cases/hvac_air.py:147-148 | conduit/pipe outside size <= 1/3 member thickness (used as opening limit) | part1 p863 | correct | (BNBC rule is for embedded conduits; use for sleeves is SAEngine's own, as the text says) |
| Sec 8.1.7 covers | report/build.py:2416 | nominal cover | part1 p1069 | correct | - |
| 8.2.3 / 8.2.3.2 / 8.2.3.3 Eq 6.8.1 | generated.ts:3678 (library settings) | simplified or general ld | part1 p1076-1077 | correct | - |
| Sec 8.3 (pp.1088-1123) / 8.3.3 (pp.1089-1090) | report.typ:816; seismic_detailing.py:1; bnbc2020/README.md:22,25; femSeismicDetailing.ts:10; report/build.py:1587 | seismic detailing chapter | part1 p1088-1123 | correct | - |
| Sec 8.3.2 | cli.md:140; report/build.py:1607; report.typ:822 | SDC D -> special detailing 8.3.3-8.3.8 | part1 p1088 | correct | - |
| Sec 8.3.3.3 | cli.md:144 | f'c >= 21 MPa | part1 p1089 | correct | - |
| Sec 8.3.3.4(b)(i),(ii) | generated.ts:552,566 (library) | actual yield / tensile from mill tests | part1 p1089 | correct | - |
| Sec 8.3.4.2(a) | tutorials/02-six-storey-building.md:202 | ρ <= 0.025 | part1 p1091 | correct | - |
| Sec 8.3.4.2(b), Figure 6.8.8 (lap-splice ties) | generated.ts:2258,11071 <- python/src/saengine/library/objects.py:165 | hoops over lap splices | part1 p1091, p1093 (Fig 6.8.3 = SMF flexural-member laps), p1099 (Fig 6.8.8 = column hoops) | wrong number | for beams: Figure 6.8.8 -> Figure 6.8.3 (columns: Sec 8.3.5.3/8.3.5.4, Figure 6.8.8) |
| Sec 8.3.4.3, 8.3.5.4, 8.3.9.2, 8.3.10.4, 8.3.10.5 | femDesignProposal.ts:39; generated.ts:2608,11223 | hoop zones | part1 p1093-1115 | correct | - |
| Sec 8.3.5.2(a),(b), Eq 6.8.5 | femSeismicDetailing.ts:22,67,71,479; report.typ:857; femResultsBar.ts:98 | ΣMnc >= 1.2 ΣMnb for columns with Pu > 0.1 Ag f'c | part1 p1096 | correct | - |
| Sec 8.3.5.4 (pp.1097-1099), Eqs 6.8.7/6.8.8 | seismic_detailing.py:61,76-77,183; verification/README.md:58; femSeismicDetailing.ts:28 | Ash = 0.3 s bc f'c/fyt (Ag/Ach-1), 0.09 s bc f'c/fyt | part1 p1097 | correct | - |
| Sec 8.3.6.2 | femWallsStairs.ts:82 | two curtains when Vu large | part1 p1100 | correct | - |
| Sec 8.3.6.4(a) Eq 6.8.9 (p.1101) | walls.py:44; femWallsStairs.ts:21 | wall shear | part1 p1101 | correct | - |
| Sec 8.3.6.5(b) | new-building.md:132; beta.py:96 | effective flange widths | part1 p1102 | correct | - |
| Sec 8.3.6.6(b)-(d) (pp.1103-1104), Eq 6.8.10; (d)(iii); (e)(i) | walls.py:145; femWallsStairs.ts:33,40; report.typ:669; generated.ts:772,2784 | boundary elements, displacement/stress methods | part1 p1102-1104 | correct | - |
| Sec 8.3.6.7(a),(b),(d)(i) Eq 6.8.11 (pp.1105-1106) | walls.py:178; new-building.md:136; femWallsStairs.ts:62; report.typ:679; generated.ts:1229 | coupling beams | part1 p1105-1106 | correct | - |
| Sec 8.3.7.1(a), 8.3.7.3 (pp.1108-1110) | seismic_detailing.py:146,194; femResultsBar.ts:98 | joint shear 1.7/1.2/1.0 √f'c Aj | part1 p1108-1110 | correct | - |
| Sec 8.3.8.1 | report.typ:872 | Mpr with 1.25 fy | part1 p1111, p882 (Mpr def.) | correct | - |
| Sec 8.3.11, 8.3.11.2(a),(b), 8.2.6 | report/build.py:1711; tutorials/01-sample-project.md:101-102 | column bars developed into footing; hooks | part1 p1120, p1079 | correct | - |
| Sec 8.3.11.3(b) | substructure.py:306,317,325; 09-substructure.md:92 | least side >= clear spacing/20 (<=450 mm) | part1 p1120 | correct | - |
| Sec 8.3.12 | generated.ts:730,1210 (library) | gravity (non-SFRS) members | part1 p1122 | correct | - |
| Part 6 Ch 10 (AISC 360-05 provisions) | verification/cases/steel.py:1,21; 02-project-settings.md:32; 08-fem.md:130; report.typ:694; femSteelDesign.ts:11 | steel LRFD | part2 p228 (ANSI/AISC 360-05 referenced) | correct | - |
| Sec 10.5.3, Eqs 6.10.16-19 (Gazette p 3841) | steel.py:54,240; femSteelDesign.ts:136 | flexural buckling | part2 p60 (gazette 3841) | correct | - |
| Secs 10.4.2, 10.4.3.3, Table 6.10.2 Case 6 (pp 3835-3841) | steel.py:138 | tension, shear lag | part2 p54-56 | correct | - |
| Sec 10.3.2.1 (Eqs 6.10.4, 6.10.6, 6.10.7); 10.8.1.1 (Eq 6.10.147a) | steel.py:220 | B1/B2 second order; H1-1a interaction | part2 p49-51, p98 | correct | - |
| Sec 10.6.2 | femSteelDesign.ts:341 | LTB of compact I | part2 p73 | correct | - |
| Sec 10.10 | report.typ:707 | connections | part2 p109 | correct | - |
| Table 6.10.10 | generated.ts:913,1292,1410 (library) | bolt grades | part2 p127 | correct | - |
| Table 8.5.1(a) (p1034, gazette 4815), 8.5.1(d) | plumbingDocument.ts:293-314; plumbing.py:111,115,268; hydraulics.py:169,181,188; 07-mep.md:59; report.typ:981; rpc/server.py:90; rpc/handlers.py:1055; mepEditor.ts:2813,3101; plumbingResults.ts:23,80-81; generated.ts:13643,13727 | A1 260, A3 200, y1 180; A4 135, A5 300, B1 70, B2 100, D1 340, >100 beds 450, E1 45, F1 45, G1 40 (full facility) | part2 p1034-1036 (rendered) | correct | - |
| Sec 5.6.3 (p1039), Sec 5.6.4 | plumbing.py:110,115; generated.ts:13660 | about 5 persons per dwelling; 7.4-9.3 m²/person offices | part2 p1039 | correct | - |
| Eq 8.5.1 (p1043) | plumbing.py:112,115; hydraulics.py:170,181,188 | daily / hours of consumption (15-17, 16 used) × 2.2 | part2 p1043 | correct | - |
| Sec 5.9.1.2(c), (c)(ii) (p1041) | plumbing.py:116; hydraulics.py:181,187; report.typ:994; report/build.py:2422; plumbingResults.ts:81; generated.ts:13708,13764 | roof tank = ½ daily + 1 h fire reserve (tall bldg); delivery pump = peak hourly demand | part2 p1041 | correct | - |
| Tables 8.5.2-8.5.3 (p1042) | plumbing.py:116; report.typ:994; generated.ts:13750 | tank drain, overflow sizes | part2 p1042 | correct | - |
| App O Table 8.O.1 (p1196), Table 8.5.4 (p1045), Table 8.5.5 (p1046) | plumbing.py:148,154-160,277; report.typ:982; plumbingResults.ts:133 | wsfu; flush tanks 200 u -> 243.5, 220 u -> 260.5 l/min | part2 p1045-1046 (rendered), p1196 | correct | - |
| Sec 5.10.1(c)(ii) (p1044) | plumbing.py:155,277; hydraulics.py:84 | velocity by tentative diameter | part2 p1044 | correct | - |
| Tables 8.O.2(a)-(c), Secs 5.9.2.2, 5.10.3, 5.10.5 | hydraulics.py:5,84,181; report/build.py:2423 | fittings equivalent length; roof tank; pipe size; pump head | part2 p1043-1048, p1197-1199 | correct | - |
| Sec 5.10.4.2 / Sec 5.11 / 5.11.1, 35 m; Table 8.5.6 | hydraulics.py:7,9,275,333; report.typ:1044; report/build.py:2421; generated.ts:13722 | no fitting under > 35 m head (5.10.4.2); tall buildings <= 350 kPa (5.11.1); residual heads | part2 p1047-1049 | correct | - |
| Table 8.6.12 (p1112-1113) | plumbing.py:180,184; report.typ:982; generated.ts:13475 | flush-tank WC 3 units | part2 p1112 (rendered) | correct | - |
| Table 8.6.14 (p1114) | plumbing.py:184,188,286 | 75 mm: 60 per stack, 16 per storey | part2 p1114 (rendered) | correct | - |
| Table 8.6.2 (p1087) | plumbing.py:184,189,286 | WC outlet 100 mm | part2 p1087 | correct | - |
| Table 8.7.2 (p1135), App R (p1213) | plumbing.py:211,296; 07-mep.md:69; plumbingResults.ts:134; generated.ts:13589 | leaders; Dhaka one-hour rainfall 88 mm/h | part2 p1135, p1213 (rendered: Dhaka between 85 and 90 isohyets) | correct | - |
| App S Eq 8.S.1 (p1214), Sec 6.9.12.8-6.9.12.13 (p1106); Table 8.6.10 | plumbing.py:240,304; 07-mep.md:69; plumbingResults.ts:138 | septic volume; >= 2000 l, L >= 3W; two chambers > 3000 l; soak well absorption | part2 p1106, p1110, p1214 | correct | - |
| Sec 7.8.9; Sec 7.4.1 | generated.ts:12565,13610 | rainwater storage volume; harvesting on plots >= 300 m² | part2 p1129, p1134 | correct | - |
| Table 4.4.1 (Part 4) | generated.ts:13764 | standpipe flow for fire reserve | part1 p322 | correct | - |
| Table 8.2.3 (pp.863-867) rows | hvacDocument.ts:330-353; hvac_loads.py:60,85,211,320; hvac_air.py:71-72,186; hvacResults.ts:69-70; hvacView.ts:97; rpc/handlers.py:1144-1166; rpc/server.py:98; 07-mep.md:80; generated.ts:13034,13051 | office 2.5 L/s·p + 0.3 L/s·m², 5/100 m²; conference 50; reception 30; lobby 10; dwellings 0.35 ACH >= 7.5 L/s·p; hotel bedroom 10, lobby 3.75/0.3/30; patient 12.5/10; OR 15/20; dining 3.75/0.9/70; cafeteria 100; classroom 9+ 5/0.6/35; lecture 3.75/0.3/65; sales 3.75/0.6/15; mall 40; supermarket 8; worship 120; library 2.5/0.6/10; corridors 0.3; per-row page refs 864-867 | part2 p864-867 (rendered) | correct | - |
| Table 8.2.2 (p.862, gazette 4643), Sec 2.12.2.1 (p.915) | hvacDocument.ts:36,58,282,290-317; hvacView.ts:88,97; hvacResults.ts:69-70; rpc/handlers.py:1144; generated.ts:12680,12694,12749 | 2 % DB/MWB cols 6-7 (Dhaka 34.5/27.0), range col 14 (all 20 stations) | part2 p862 (rendered), p915 | correct | - |
| Sec 2.12.2.2, 2.12.2.3, Table 8.2.1; Sec 2.7.2 | generated.ts:12667,12720,12735 | indoor >= 24 °C; RH from Table 8.2.1 | part2 p859, p915 | correct | - |
| Table 8.2.11 (p.919) | hvac_air.py:103,196 | water-cooled screw 530-1050 kW: COP 5.40 | part2 p919 (rendered) | correct | - |
| Table 8.2.9(b) | hvacView.ts:118 | overhang SHGC correction | part2 p916 | correct | - |
| Part 3 Sec 1.14.2.1(b) (p.66) | hvac_air.py:148-149 | 2.44 m clear under duct in A/C room | part1 p66 | correct | - |
| Part 3 Sec 4.5.1.2(a) | generated.ts:12432 | WWR 0.2 (window >= 20 % of external wall, rooms < 8 m deep) | part1 p191 | correct | - |
| Part 3 Sec 4.4.3.1; Table 3.4.5 | generated.ts:12840,12842,13065 | sunshade depth 0.234 × window height; LPD | part1 p188, p192 | correct | (BNBC rule is for naturally ventilated buildings, S/E/W windows) |
| Table 8.1.17 (pp.766-767) | electricalDocument.ts:32,63,271-300,500,866; electrical.py:115,121,238; electricalView.ts:77; electricalResults.ts:59; 07-mep.md:94; report.typ:1202; rpc/handlers.py:1225-1232; rpc/server.py:103; generated.ts:12010,12022,12038 | all 13 rows non-A/C / A/C (e.g. residence 20/75, hospital 32/80, office 28/75, school 12/70, parking 4, warehouse 2); office A/C 75 W/m² | part2 p766-767 | correct | - |
| Sec 1.3.18.1 (p796); Sec 1.3.20.1(e) | electrical.py:121; generated.ts:12130,12173,12178 | substation > 50 kW (>= 50 kW in 1.3.20.1(e)); load factor >= 80 %; future expansion | part2 p796, p804 | correct | - |
| Table 8.1.23 (p798) | electrical.py:122,128 | 1×400 kVA: transformer 13 m², substation 48 m² | part2 p798 | correct | - |
| Sec 1.3.19.2 (p801), Table 8.1.24 (p802); 1.3.19.5; 1.3.18.4 | electrical.py:152,158,248; generated.ts:12136,12142,12201 | generator capacity; 1×300 kW room 48 m²; UPS; transformer types | part2 p799-802 | correct | - |
| Sec 1.3.2 (p763), 1.3.13 (p790-792) | electrical.py:121,182; generated.ts:13255 | loads incl. lifts/pumps; risers | part2 p763, p790 | correct | - |
| Tables 8.1.27-8.1.28 (p821-824), Sec 1.3.33.7-1.3.33.8 (p825-828), Eq 8.1.1 | electrical.py:212-213,265-266; electricalDocument.ts:651; generated.ts:13120,13180-13246 | risk index A..G; one down conductor per 30 m perimeter; one air spike per 80 m²; clearance Eq 8.1.1 | part2 p821-828 | correct | - |
| "BNBC 2020 Part 6 Table 6.2.14, p. 3160" (doc-comment example) | workbench/.../saengineLibrary/browser/codePacksModel.ts:44 | page of Table 6.2.14 | part1 p615 = gazette 3196 (gazette 3160 = pdf p579, wind chapter) | wrong number | "p. 3160" -> "p. 615" |
| "(BNBC 2020 6.2)" for equivalent static loads | python/src/saengine/report/templates/report.typ:453 | loads chapter | part1 p512-686 (Part 6 Ch 2) | wrong number | "BNBC 2020 6.2" -> "BNBC 2020 Part 6 Chapter 2" (Sec 6.2 is the RC design-method section) |
| "BNBC 2020 Part 6 Chapter 6 adopts ACI 318-19, so the clauses are the same" | verification/cases/design.py:6; design_mode.py:3; docs/manual/02-project-settings.md:35-36; docs/manual/08-fem.md:6 | BNBC Ch 6 = ACI 318-19 | part1 p922 (Sec 6.4.2.1.1 Eq 6.6.49 Vc = 0.17λ√f'c bw d, no size-effect λs, no ρw term), clause numbering differs throughout | wrong clause | say "BNBC 2020 Part 6 Chapter 6 is based on ACI 318 (an earlier edition: e.g. Vc = 0.17λ√f'c bw d, Eq 6.6.49); SAEngine checks to ACI 318-19, which matches or is stricter" |
| allowable story drift "of BNBC 2020 Part 6 Chapter 2" | report/build.py:880 | drift limit | part1 p648 | correct | could name Table 6.2.21 |
| Sec 2.5 (pp. 609-648) | bnbc2020/README.md:20 | seismic section pages | part1 p604-648 | correct | cosmetic: Sec 2.5 starts p604 |
| new-building.md category preselection | new-building.md:102 | IV health care, III educational/assembly, II otherwise ("on the safe side") | part1 p479-480 | correct | - |
| exception: no orthogonal combos in SDC B | generated.ts:3288 | one direction at a time in B (and C regular) | part1 p645 | correct | - |

### 2. Wrong values (engineering impact)

No number in this group differs from the clause it cites. Every BNBC value restated in the docs, UI strings, report text and verification cases matched the rendered BNBC page (spectrum S/TB, Z, drift, 0.85V scaling, Ev, combinations, cracked factors, slenderness, phi, Tables 6.6.1/6.6.3, SMF limits, pile SPT equations and FS 3.5, Table 6.3.10a, and all rows used from Tables 8.5.1, 8.5.5, 8.6.12, 8.6.14, 8.2.2, 8.2.3, 8.2.11, 8.1.17, 8.1.23, 8.1.24).

One value issue that the cited clause does not show (BNBC contradicts itself here), flagged for the engineer:

- Pile uplift factor of safety 2.5 (Table 6.3.10a, permanent, normal control). Locations: substructureEditor.ts:82, 2158; substructureDocument.ts:142; docs/manual/09-substructure.md:53-54; verification/cases/substructure_deep.py:113,118,125; generated.ts:10529 (<- python library settings and bnbc2020 pack foundations.json defaults). BNBC Part 6 **Sec 3.11.3** (part1 p796): uplift capacity found by analysis needs a **minimum FS of 3.0**; where the uplift comes from wind or seismic load, 2.0 by analysis (1.5 by load test). Table 6.3.10a's 2.5 for normal control assumes load-test data (Table 6.3.10b), the same reason SAEngine already raises compression to 3.0 without a site load test (Sec 3.10.1.18). Old -> new: uplift FS 2.5 -> 3.0 for sustained uplift (buoyancy, permanent uplift) without a load test; 2.0 is allowed for wind/seismic uplift. Impact: allowable uplift Ta = (0.7 Qs + W)/FS is 20 % too high (unconservative) for permanent/buoyancy uplift on piles (basement and ground-tank flotation, pile tension check in 9 Substructure); 25 % conservative for wind/EQ uplift. Suggest applying the same "no load test -> 3.0" rule to uplift, or 3.0/2.0 by load type.

### 4. External references (not verifiable here: check against the owner's copy)

- ACI 318-19 21.2.2 (φ by εt), 22.2 (stress block), 22.2.2.4.3 (β1), 2.2 (d): design.py:69,314,377,497; design_mode.py:58,118,194; docs/verification/README.md:90,93. BNBC equivalent: Sec 6.2.3.2, 6.3.2, same values.
- ACI 318-19 Table 22.5.5.1 (a),(c), 22.5.5.1.3 λs, 22.5.8.5.3, 9.6.3.4: design.py:128,582; design_mode.py:153; mep.py:6,157; substructure.py:108; docs/verification/README.md:91; report/build.py:2414. BNBC differs: Sec 6.4.2.1.1 Eq 6.6.49 Vc = 0.17λ√f'c bw d (no λs, no ρw term), so ACI-19 is equal or more conservative.
- ACI 318-19 22.4.2, 22.4.2.1, Table 22.4.2.1 (φPn,max = 0.80φP0): design.py:213; design_mode.py:244; docs/verification/README.md:92.
- ACI 318-19 8.6.1.1 / Table 24.4.3.2 (As,min 0.0018): design_mode.py:194.
- ACI 318-19 13.2.7, 13.2.7.1-2, 13.4.2.5, 22.6, 22.6.4.3, Table 22.6.5.2, 8.4.4.2, 8.4.1.5, Ch 13, 14.5: substructure.py:93,108; substructure_deep.py:263,273,397; mep.py:214; design.py:497; docs/verification/README.md:94; femDesign.ts:105; 09-substructure.md:88.
- ACI 318-19 6.2.5, 6.2.6, 6.6.4.x, Table 6.6.3.1.1: slenderness.py:2,227,280; femDesign.ts:45,528; femSeismicDesign.ts:116; rs_design.py:38; substructure.py:292,318. BNBC equivalent: Sec 6.3.10, 6.3.10.4.1, same cracked factors (verified).
- ACI 318-19 18.8.4.3 (bj): seismic_detailing.py:147.
- ACI 318 10.6.1.1 (ρ <= 0.08), 25.7.2 (ties): tutorials/02-six-storey-building.md:162; 08-fem.md:156,168. (For SMF columns BNBC 8.3.5.3(a) limits ρ to 0.06; the detailing check already uses 0.06.)
- ACI 336.2R (combined footing): substructure.py:192.
- AISC 360-22; AISC 360 Commentary C-A-7.1, C-A-7.2: 00-getting-started.md:40; 02-project-settings.md:32; 08-fem.md:7,130; slenderness.py:76.
- ASCE 7-16 20.4 / eq. 20.4-2 (harmonic mean N): docs/verification/README.md:95; soil.py:71.
- ASCE 7-05 Table 19.2-1 (G/G0): ssi.py:51; generated.ts:3387.
- ASCE 41-06 Sec 4.4.2.1.2 (Gazetas footing springs, embedment): ssi.py:142; report/build.py:577; generated.ts:3369,3400.
- EN 1992-1-1 7.3.4 (crack width): report/build.py:2415.
- BS 8666 / BS 8666:2020 (shape codes, marked "to be checked"): 11-exports.md:97,108-109; glossary.md:45.
- IEC 62305 (lightning level): generated.ts:13138.
- ASHRAE (loads), Chopra Table 5.4.2, O'Neill & Reese FHWA-IF-99-025, Youd et al. 2001, Idriss & Boulanger 2014, Imai & Tonouchi 1982, ASCE GT8 (soil.py:212): hvac_loads.py:85; analysis.py:386,423; substructure_deep.py:123; soil.py:212,599; 01-soil-report.md:41,141; generated.ts:3387.

Markers ("from memory / to be checked"), 3: hvac_loads.py:186-187 (irradiance, absorptance, film coefficients: not BNBC values); docs/manual/07-mep.md:108-109 (equipment weights, 40 % tray fill, fallback irradiance: practice, not BNBC); docs/manual/11-exports.md:108-109 (BS 8666 shape codes: external). None marks a BNBC value.
