# Engineering decisions

This is the record of the engineering choices behind SAEngine's results. Each one was made by the
owner, a structural engineer, where the code text is silent, garbled or open to more than one
reading, or where SAEngine had to pick a default.

When a result surprises you, look here first. When a session makes a new judgment call, add it
here, newest first, with the date, the question, the decision, the reason and where it lives.

## How SAEngine labels these choices

- **Code value.** A value or rule printed in the active code pack's code. It is cited with
  Part / Section / Equation / Table and page.
- **Read as.** The printed text is garbled or clearly misprinted, so SAEngine uses the reading
  named in the report. That is usually the source equation or the safer value.
- **SAEngine practice.** The code gives nothing. SAEngine picks a value or method, the report
  labels it that way, and the code pack can usually change it.
- **Placeholder.** Not built yet. The feature shows as not covered instead of giving a number.

## Principles

- **The design code is a setting.** BNBC 2020 is the default code pack. It is not built into the
  engine. Every code value, table, combination, method choice and clause reference comes from
  the active pack, and no engine or UI code asks which code is active (2026-11-01). See
  [code-packs.md](code-packs.md).
- **Any code, changed at any time, without friction (2026-11-02).**
  - Any design code and its parameters can be adopted as a pack.
  - Every pack value an engineer may disagree with can be overridden in the project (in
    settings, or on the member or material). When it is not overridden, it follows the pack.
  - Changing a setting, or switching the whole pack in the middle of a project, takes effect on
    the next run. There is no migration step, no stale cached value and no error in older
    projects.
  - A pack that doesn't define a value still works. SAEngine falls back to a generic default and
    names it in the report.
  - Defaults SAEngine picks itself (a template's depth or jacking stress, say) are ordinary
    editable defaults, never code values.
- **One home per feature.** A feature lives in one part only, and other parts link to it.
- **Run All never writes member bars.** If a beam or column type has no bars, the design step
  fails honestly and offers *Design Reinforcement*. Footings are the exception: they get minimum
  bars with a "review them" warning (2026-10-27).
- **No unlicensed software.** ETABS, SAP2000 and STAAD are not used for cross-checks or cited.
  Open-source tools are used instead (2026-10-25).

## 2026-11-04: checks BNBC requires without a method (alpha 9 track P7)

Owner decision 6 of the BNBC review left these as placeholders; alpha 9 builds them with
established methods chosen by pack method id. In the default pack each is labelled **SAEngine
practice where BNBC 2020 is silent**, except the non-building structures, which BNBC 2020 Sec
2.5.18 itself sends to ASCE/SEI 7-05 Chapter 15. Every value is overridable per project.

- **Floor vibration** (BNBC Part 6 Sec 1.4.2(e), 10.12.5). Floors on steel beams by the AISC
  Design Guide 11 walking acceleration, concrete floors by the CCIP-016 / SCI P354 response
  factor (the Eurocodes pack uses the response factor for both). fn = 0.18 √(g/Δ) with Δ the
  panel's deflection from the analysis (D + SD + the use's service live load), relative to the
  slab's supported nodes; the panel is the bay round the largest deflection. Damping is the
  pack's "ceilings" fit-out. The modal mass of the response factor is 1/4 of one bay's mass: on
  the safe side (continuous floors engage more), to be refined. Parking, storage and roofs have
  no criterion.
- **Wind comfort** (BNBC Sec 10.12.6). Along-wind peak acceleration of the top floor from the
  modal mass and shape of the run (ASCE 7-05 Commentary C6.5.8 form, EN 1991-1-4 Annex B.4 in
  the Eurocodes pack), 10-year wind (V_T/V_50 = 0.36 + 0.10 ln 12T), damping 1.5 % concrete /
  1 % steel, limits 15 / 18 / 25 milli-g (residential / hotel / office). Across-wind and
  torsional motion are not computed (stated in the report).
- **Non-building structures**: 07 MEP equipment marked as a non-building type gets Cs = Sa I / R
  of the project spectrum (at least 0.044 SDS I and 0.03; rigid: 0.30 SDS I), R / Ω0 / Cd of
  ASCE 7-05 Tables 15.4-1/-2; supported structures below 25 % of the building's W stay
  components (the existing component force governs). Without a period: the plateau.
- **Laterally loaded piles**: Broms soil failure (soil averaged over the top 10 D, allowable Hu /
  2.5 × group ratio, My = φMn at no axial force) and a p-y analysis (Matlock soft clay, Welch &
  Reese stiff clay, API sand; beam finite elements, the group ratio as a p-multiplier). Both are
  new checks of every pile cap with soil strengths in the soil report. Our own solver is used,
  not OpenSees PySimple1 (deterministic, no extra run).
- **Embedded excavation walls**: per metre, cantilever (Blum, d = 1.2 d0), propped free earth
  support (d = d0) and fixed earth support (Blum's equivalent beam, d = 1.2 d0), Rankine
  pressures with the passive divided by 2.0, the least surcharge 10 kPa and an overdig of 10 % of
  H up to 0.5 m; the Eurocodes pack uses EN 1997-1 M2 strengths and q × 1.3. Wall sections,
  walers, struts and anchors stay with track P1.

## 2026-11-04: bar bending schedules by the pack's standard (alpha 9 track C14)

- **Where.** The schedule standard is the code pack's `barSchedule` table: `standard` picks one
  of `standards` (shape codes, dimension letters, cutting-length formulas as expressions, minimum
  radii, end projections, rounding, size label, columns, sheet title, sketches). Override per
  project with `barSchedule.standard`; a standard the pack lacks is taken from the built-in pack
  that gives it (stated in the schedule notes).
- **Defaults.** BNBC 2020 and BS 8110: BS 8666 (unchanged output); Eurocodes: EN ISO 3766 (a UK
  National Annex pack sets `bs8666`); IS: IS 2502; US: ACI 315 / CRSI bar list.
- **SAEngine practice.** EN ISO 3766 gives no length formulas: lengths along the centre line
  from the outside dimensions with the code's mandrel. IS 2502 shapes keep the BS 8666 / ISO
  numbers as references, sketched on the sheets. Rounding: ISO 25 mm, IS 10 mm, US 1 in, all up.
  Link hooks in every standard: the code's 135° seismic extension + r + d. Bar mass stays
  d²/162 kg/m for every standard (US: of the soft-metric designation), so the BOQ keeps taking
  the schedule's bars unchanged (BOQ = BBS).
- **Shape key.** The sketches of the shape codes used are drawn on the schedule sheets when the
  pack's `barSchedule.shapeKey` is true: on for EN ISO 3766, IS 2502 and ACI 315, off for the
  default pack so its drawings stay as they were (owner to decide whether to turn it on).
- **Units seam.** Lengths stay in mm; `bbs.length_display()` is the one place the project's
  display units (track C13) are to be applied.

## 2026-11-04: the legacy packs BS 8110 and BNBC 2006 (alpha 9 track C10)

Two built-in packs that extend BNBC 2020 (owner: wanted after all, gaps CD-4): `bs8110` (BS 8110,
BS 6399, BS 5950) and `bnbc2006` (BNBC 1993 / 2006). No text of either code was available: every
value is in the packs' `VERIFY.md` (bs8110 rows L1-S18 with two transcribed tables, bnbc2006
rows Q1-F14 with the district list). A pack without the new generic keys (BNBC 2020 and the
others) runs exactly as before. SAEngine practice where the code leaves a gap (each overridable
per project):

- **No earthquake under BS.** The British Standards give no seismic loading: every BS location
  has Z = 0, so no EX / EY cases are made and the derivation reports it. A Z entered per project
  uses the parent's spectrum and systems and the report names them BNBC 2020.
- **BS 8110 forms.** x <= 0.5 d (K' = 0.156) for every section; vc of Table 3.8 tabulated from its
  formula with the depth factor applied to every member; punching vc as 0.10 √fcu (the punching
  rows carry no slab steel ratio) on SAEngine's d/2 sections; Table 3.10's M/bd² from pt at 0.95
  fy and z = 0.9 d; the compression lap 1.25 × folded into the compression bond (the anchorage
  then 25 % long); biaxial column bending by the interaction surface; Nbal from the balanced
  strains; creep and shrinkage of the calculated deflection as fixed values.
- **BS 6399-2.** The effective height is the height (no displacement height), Ca = 1.0, Sd = 1.0,
  Cpe of D/H <= 1 for every building, the dynamic augmentation not applied.
- **BS 5950.** The generic limit state steel method with Perry-Robertson curves, the moment factor
  in Mcr (not mLT on the moment), the member interaction with K = 1 on the plastic moment
  capacities, single angles λ = 0.85 L/r, rupture 0.9 An fu / 1.1 for Ke An py.
- **BNBC 1993 / 2006.** The default pack's site classes read as soil types (SA, SB S1; SC S2; SD
  S3; SE S4); the dynamic spectrum rises from 1.0 to the plateau at 0.1 s; the member detailing by
  zone (1 ordinary, 2 intermediate, 3 special); drift, Ω0 and Cd stay BNBC 2020's; the wind
  tables Cz and CG by their power-law forms (k2 = √(Cz CG)).

## 2026-11-04: the rest of the Eurocodes concrete, foundation and load parts (alpha 9 track C5c)

The `eurocodes` pack (0.5.0) now designs the parts C4, C5 and C5b left to BNBC 2020. Every value
is in `codes/packs/eurocodes/VERIFY.md` (rows C5c-1 to C5c-72). Each area is a method chosen by
id (`design/method_selection.py`: `strutAndTie`, `interfaceShear`, `ties`, `footingPunching`,
`wallSlenderness`, `barShapes`, geotechnical `retaining`; the seismic table's `regularity`,
`torsionalEffects`, `modalCombination`, `verticalComponent`, `foundationCapacity`; the wind
table's `orography`, `structuralFactor.detailed`, `localPressures`; the snow drift method
`shapeCoefficient`). A pack without them (BNBC 2020) runs exactly as before. SAEngine practice
where the code leaves a gap (each overridable per project):

- **Strut-and-tie on the design strengths** for deep beams (span below 3 h, and the parent's
  concentrated-load rule), corbels and the deep pile caps: prism struts fcd, cracked struts and
  the support struts 0.6 ν' fcd, nodes k1-k3 ν' fcd, ties fyd, no φ; least strut angle 21.8°
  (cot θ 2.5); the corbel's z0 = 0.8 d and HEd at least 0.2 FEd. The general D-region models
  keep the parent's procedure.
- **Slab and stair deflection** by the span/depth ratio replaces the parent's least thickness
  table: the shorter span of two-way slabs, the longer of flat slabs, the continuous edges along
  it for K, ρ of the bottom bars, As,req = As,prov.
- **Confinement ωwd** of every DCM/DCH column critical region by the base region's rule, the
  hoops' legs evenly spaced for αn; μφ from the analysis's q (kw = 1) and T1 = Ct H^(3/4).
- **Punching of column bases** (footings, pile caps, interior raft columns) by the perimeters
  within 2d with the soil pressure (pile reactions) inside deducted, searched at 16 distances;
  the raft's edge and corner columns on u1 with β. The punching reinforcement of footings and
  rafts is not laid out under the pack (a failing row says to thicken).
- **Retaining walls** per combination of the design approach: Ka(φ'd)/Ka(φ'k) by Rankine on the
  soil's part of the thrust, sliding with δd = φ'd under a cast base, bearing on B', overturning
  by EQU (EN 1990 Table A1.2(A)); the stem and base under γG = 1.35 on the earth pressure with
  MRd and VRd,c; the parent's factors of safety reported only.
- **Detailing**: EN mandrels, 5 φ past bends and hooks, links' 135°/90° tails, compression laps
  with α6 of all bars lapped, the transverse bars at their ends named in the formula; column
  tension laps with α6 of all bars.
- **Walls out of plane** as a 1 m strip column (β 1.0 held by both floors, 2.0 free-standing,
  single curvature); flanged groups' shear the webs' VRd summed with ε of the largest class.
- **Construction joints** by 6.2.5 with the parent's surfaces read as monolithic = indented,
  roughened = rough, not roughened = smooth, steel = very smooth.
- **Ties (9.10)**: perimeter beams carry the peripheral and the column tie, inner beams the
  internal tie with (l1 + l2)/2 taken as the beam's span; the beam type's bars at fyk.
- **Footing sizing assistant** proposes footings for the bearing resistance of the design
  approach (the allowable pressure where the soil gives no strength parameters).
- **Wind**: torsion by e = b/10 with the full pressure (Case 2 of the design wind cases; no
  simultaneous cases, so the BNBC/ASCE Cases 3 and 4 are optional fields of `designCases`);
  orography with Lu = 2 Lh and Ld = Lu of the project's topography; the detailed cscd with
  n1 = 46/h unless the project gives n1, δs 0.10 (a steel building gives its damping ratio),
  the aerodynamic damping left out; cladding pressures at qp(h) with cpi +0.2/-0.3.
- **Snow drift** at a roof step (5.3.6, μs = 0) or, without one, at the parapet height of the
  wind settings (6.2); reported for the lower roof, not applied.
- **Seismic regularity** is judged from the building model before the analysis so that q × 0.8
  (not regular in elevation) and αu/α1 averaged (not regular in plan, Ω0 standing for αu/α1)
  reach the same run's spectrum and static forces; the centre of mass at the floor's centroid,
  the stiffness centre from the sections' moments of inertia (4.2.3.2(8)), a setback symmetric
  when its sides differ by at most 25 %. A project's own R is not reduced. The analysis's
  stiffness and mass indicators (70 % of the storey above, 150 % of an adjacent storey; the code
  gives no numbers) and the criteria are the irregularity findings that decide the dynamic
  analysis requirement.
- **δ (4.3.3.2.4)** only where the analysis has no accidental eccentricity (no EXP/EXN cases,
  no accidental torsion parts of the spectrum design): per element the larger direction's δ,
  rounded up to 0.05, the centre of mass at the plan's centre; combinations per δ value act on
  their elements only (the soft-storey mechanism).
- **Vertical component** where avg > 0.25 g: Ev = 0.3 × avg × 3.0/1.5 × D on every member (the
  code names long spans, cantilevers, transfer beams and isolated structures: on the safe side).
- **SRSS or CQC** by the independence of all the analysis's modes (Tj <= 0.9 Ti).
- **Foundations' capacity design**: the earthquake parts × min(γRd Ω, q) with Ω = q unless the
  project gives one (the elastic response the code allows as the bound; conservative).
- **Settings**: under another pack than the default the Project Settings no longer show the
  default pack's Seismic Design Category, its warning or its system switch (the pack's own
  category comes with the analysis and the report).
- Where it lives: `design/stress_fields.py`, `design/limit_state_members.py`,
  `substructure/limit_state_retaining.py`, `substructure/foundation_capacity.py`,
  `fem/seismic_regularity.py`, `fem/torsional_effects.py`, `fem/local_pressures.py`; hooks
  marked "Alpha 9 C5c" in `curvature_ductility.py`, `perimeter_punching.py`, `bar_rules.py`,
  `check.py`, `corbels.py`, `deep_beams.py`, `rc_detailing.py`, `slab.py`, `stairs.py`,
  `walls.py`, `wall_design.py`, `wall_flanges.py`, `drawings/detailing.py`, `shallow.py`,
  `pilecap.py`, `raft.py`, `retaining_walls.py`, `sizing.py`, `substructure/loads.py`,
  `fem/derive.py`, `fem/loads.py`, `fem/peak_velocity_pressure.py`, `fem/snow_load.py`,
  `fem/irregularity.py`, `fem/seismic_design.py`, `report/build.py`, `settingsEditor.ts`.
## 2026-11-04: detailing clause references from the code pack (alpha 9, track C11)

- **Row clauses come from the pack.** The RC frame detailing, capacity design and seismic system
  rows (beams, columns, joints, capacity shear, members outside the seismic-force-resisting
  system, materials, system permitted) take their clause numbers from the pack's
  `designClauses` groups `ductileMembersRows`, `ductileJointsRows`, `seismicDetailingRows` and
  `seismicRulesRows`. The default pack's rows read exactly as before.
- **No inherited clause numbers (SAEngine practice).** A pack that extends another and does not
  give a row's clause itself names the row without a clause, rather than showing the clause
  number of the pack it extends. This also applies to the wall rows (`wallsRows`). A project
  override of a clause still shows.
- **Worksheet formula text follows the method.** The wind and seismic worksheets print the
  formula of the method the pack picks (power-law Kz with the pack's factor, the speed-factor or
  peak velocity pressure methods, the behaviour-factor spectrum, the pack's spectrum factor)
  instead of the default pack's.

## 2026-11-04: Indian Standards remainder (alpha 9 track C9b)

The `is-codes` pack now also covers the checks that fell back to BNBC 2020 under C7-C9 where
SAEngine has the check (entries 294-330 of the pack's `VERIFY.md`, to be checked against the
printed codes). Behaviour choices:

- **Column shear by τc × δ (IS 456 40.2.2).** Per axis, τc at the ratio of the bars in the far
  half; under net tension the line 1 + 3 Pu/(Ag fck) continued, not below 0 (IS gives no rule:
  SAEngine practice, on the safe side); ties carrying shear at most min(0.75 d, 300 mm).
- **Near-support enhancement (40.5): beams checked at d from the face, no enhancement.** The
  2 d/av τc is used for corbels only (SAEngine reading, on the safe side).
- **Walls: IS 456 32.2.5 in place of the parent's empirical method**, informative as the parent's
  (the P-M3-M2 surface governs); Hwe/t <= 30 is a check; Hwe from SAEngine's bracing flags (0.75 H
  braced and restrained, 1.0 H, 2.0 H unbraced).
- **Corner steel of restrained slabs (D-1.8 to D-1.10)** replaces the parent's corner rows under
  the restrained panel method; the panel's own meshes are taken as reaching the corners.
- **Deep beams by the lever arm (IS 456 29)**, method `leverArm` of `concreteMethods.deepBeams`:
  a beam of more than one span counts as continuous; the sectional shear rows stay the shear check
  (IS 456 has no deep-beam shear method); the parent's strut-and-tie model is not run; the hogging
  steel zones of 29.3.2 are not checked. SAEngine practice where noted.
- **Corbels by the tie at the root (IS 456 28)**, method `rootTie`: the tie by the pack's stress
  block at fy/1.15, shear at the face with 2 d/av τc plus the closed links, at most τc,max.
- **Stairs by the slab rules (IS 456 33)**: k τc b d without shear bars, the slab steel rows,
  span/d with kt; no 15 % stair increase (not in IS 456: SAEngine reading). Design Reinforcement
  takes the IS spacings and shear for the stairs.
- **Torsion links (IS 456 41).** Design Reinforcement puts the whole Asv/sv of 41.4.3 on the
  closed links (not added to the shear's stirrups), at the IS spacing (not the parent's ph/8), and
  asks for them wherever τve exceeds the least τc of the table, because the first pass runs on
  assumed bars; the required steel report lists the links and their spacing. On the safe side.
- **Joints view under IS 13920**: the design report's `joints` lists the IS joints (strong column
  and joint shear rows), as the other packs do.
- **Steel.** IS 800 7.4.1 base plate bearing 0.6 fck (no φ, no A2/A1 increase: SAEngine reading);
  ISLB, ISWB and ISHB sections from IS 808 dimensions recalled and checked against the published
  masses (one section per size, root radius derived from the mass: to verify); bolts of property
  class 4.6 in the object library (A307 in the default pack, an additive alias). The column side
  under flange forces, HSS joints, steel torsion, stability bracing, EBF, IS 801 cold-formed
  members and the composite columns stay the parent's.
- **Loads.** Damping factors of IS 1893 Table 4 by a tabulated damping correction (a new generic
  method `table`); the vertical motion as Ev = 2/3 × Z/2 × D (6.4.6, the vertical response taken
  rigid: SAEngine reading); a cyclone-prone site (`wind.speedFactors.cyclonic`, off by default, set
  in Code Values) takes k4 1.30 for the 100-year risk class and Kd 1.0 (IS 875-3 6.3.4, 7.2.1).
  The gust factor method, cladding and roof Cp, Annex C k3, 1.5 esi, the RC wall period form and
  IS 16700 stay not covered.
- **Masonry earthquake strengthening by IS 4326 zones**: the parent's arrangement rows read with
  IS zones (III-V; zone V as the parent's highest group); IS 4326's building categories are not
  modelled.
- **Still the parent's**: the column construction joint (IS 456 13.4 has no shear-friction
  rule; owner decision wanted), prestress (IS 1343), IS 8009 settlement, IS 2950 rafts, IS 3370
  tanks (crack limit 0.2 mm already the IS 3370 (Part 2) value), reinforced masonry.

## 2026-11-04: the rest of the US pack (alpha 9, track C3b)

SAEngine practice where the NDS 2018, TMS 402-22, AISC 360-22 or AISC 341-22 leave a gap or the
engine has no method (pack values, overridable per project; every value in the pack's
VERIFY.md):

- **Timber by reference design values** is a method of its own (`timber.method =
  referenceDesign`, `saengine.design.timber.reference`), beside the default pack's permissible
  stresses. ASD is the pack's format (the usual US timber practice); LRFD by
  `timber.reference.format` takes the strength combinations with KF, φ and λ.
- The load cases map to the NDS load durations by name (D, SD, F, H, T permanent 0.9; L the
  material's live load duration, continuous = ten years 1.0; Lr and R 1.25; S 1.15; W, E and
  the flood load 1.6); λ by the governing load (dead 0.6, occupancy live 0.8, impact 1.25, roof
  live / snow / rain 0.8, wind / earthquake 1.0). Storage live loads (λ 0.7) are not told
  apart.
- A timber material "wet" or "outside" is in wet service; le of columns is the member length
  (Ke = 1.0); lu of beams the type's restraint spacing; CL uses the 'any loading' le of NDS
  Table 3.3.3. A material that names no reference species takes Douglas Fir-Larch No.2 (the
  pack's default), with a note.
- Glulam beams take Fbx- where the top is in tension (Mx > 0) and in cantilevers.
- Bolted and nailed timber joints: side members of the member's species and depth; Cg by NDS
  11.3.6 for bolts (nails 1.0); CΔ by the end distance and spacing only. Split rings and
  disc-dowels are flagged not covered under this method.
- Timber deflection limits L/240, L/360 with brittle finishes, L/120 cantilevers, with Kcr 1.5
  (IBC Table 1604.3 is not in the pack).
- **Masonry by allowable stresses follows TMS 402-22 Chapter 8** under the US pack (it stays the
  default masonry method; strength design is the wall type's choice). The pack's mortar grades
  M1, M2 are taken as Type M or S, M3, M4 as Type N; beams and the out-of-plane shear take
  M/(V d) = 1.0; walls h'/t at most 30; no one-third increase and no halving of the stresses.
- **AISC 360-22**: built-up members by Ki (Sec E6), Appendix 6 bracing values (0.005 Pr,
  0.005 Mr Cd/ho, Mbr = 0.02 Mr), the G2.3 stiffener inertia of tension field panels, the
  Chapter K φ (round gapped K joints 0.95: the BNBC 2020 misprint decision does not apply to
  the US pack); the HSS connection equations keep the forms SAEngine has (AISC 360-10 based),
  cited by their AISC 360-22 sections and tables. Appendix 4 (fire) has no home and stays
  planned.
- **AISC 341-22**: the expected moment of SMF and IMF beams by Cpr = (Fy + Fu)/(2 Fy) <= 1.2
  (AISC 358), the fixed 1.1 when Fu is unknown; beam bracing by Ry Fy.
- **New Building, steel systems**: the generator takes the first of the pack's
  `seismic.generatorSystems` the category and height permit, least ductile first: steel not
  specifically detailed (R = 3) in Seismic Design Categories B and C, so the AISC 341-22
  provisions do not apply and ASD can be used; then OMF, IMF, SMF or OCBF, SCBF. Columns HEB,
  beams IPE, X braces SHS (no BRBF: the braces are hollow sections), RC slabs without composite
  action, every member within the system's width-thickness limits; the sizes are rules of thumb
  (the notes state them), Design mode sizes the members.

## 2026-11-04: Indian Standards steel and the other materials (alpha 9 track C9)

The `is-codes` pack now covers IS 800:2007 (members, connections, Section 12 frames, Table 6
deflections), the IS 808 section list, IS 1905:1987 masonry, IS 883:1994 timber and IS
11384:1985 composite beams; every value is in the pack's `VERIFY.md` (entries 200-293) with its
clause and a confidence, to be checked against the printed codes. Behaviour choices:

- **One limit state steel method, chosen by its table.** A pack with `steelLimitState` designs
  steel members by partial factors and buckling curves (`design/steel/limit_state.py`, the same
  method family as EN 1993-1-1, so C6 can reuse it); `members.check_member` hands the member to
  it, so the design run, Design Steel Sections and the report all use it. A pack without the
  table keeps the LRFD checks of its `steel` table (the default pack unchanged). Each group
  names its method id (`classification: epsilonLimits`, `compression: bucklingCurves`,
  `flexure: elasticCriticalMoment`, `shear: postCritical`, `interaction: sectionMember`,
  `connections.bolts: partialFactorBolts`, `seismic: prescriptiveFrames`). SAEngine practice
  (the mechanism).
- **Mcr with SAEngine's moment factor (SAEngine practice).** c1 of Mcr is the equivalent moment
  factor SAEngine computes from the moment diagram (the Cb of the parent's method), the load at
  the shear centre, K = Kw = 1; tees and angles with the warping constant SAEngine gives them.
- **Effective area of slender sections (read as).** Each slender element counts up to its
  semi-compact width (IS 800 7.3.2); in flexure βb = Ze/Zp times the worst slender element's
  share.
- **Tension of single angles (SAEngine practice).** The end connection is not known to the
  member: α of 6.3.3 with 2 bolts (0.6), the member's net ratio and shear lag options override.
  Single angles in compression by λe with "two or more bolts, hinged" (Table 12).
- **Hollow sections on the nominal wall.** IS 800 has no ERW wall reduction: the 0.93 t of the
  parent is not applied (`nominalHollowWall`).
- **Connections: the shared checks with the IS strengths.** Fin plates, end plates, gussets,
  flange plates, splices and base plates keep their geometry and limit states; the bolt shear
  (threads in every plane, Anb 0.78 Asb), bearing (kb from the end or pitch distance; fub/fu
  not known, taken ≥ 1), bolt tension and its interaction, friction grip slip (μf 0.20 / 0.50
  for the library's surface classes A / B), block shear (Atg taken as Atn), fillet welds (fu
  of the electrode, no directional increase, shop γmw) and βlj come from IS 800; the elements'
  yield and rupture factors are the IS strengths written as factors of the shared 0.6 fy / 0.6
  fu forms. The rules IS 800 has no counterpart for in SAEngine (the column side under flange
  forces, HSS joints, base plate bearing) stay the parent's and their notes name BNBC 2020.
  SAEngine practice.
- **Section 12 in place of the parent's seismic provisions.** With the pack's `seismic` group
  the AISC-based steel seismic provisions and braced frames of the parent are not run; IS 1893's
  "concentric braced frame" is taken as SCBF (the stricter rules), EBF is not covered; the rules
  apply whenever a steel frame system is in use (`rAbove` 0); the brace lines' tension share is
  a flag on braces grouped by plan direction; K bracing is a note (not detected); the
  connection design moment 1.2 Mp and 0.04 rad are flags. SAEngine practice, overridable.
- **Table 6 by the shared deflection rows.** Cantilevers take the limits of their double length
  (span/150 = 2 L/300), so one row per use holds both.
- **Masonry by the basic stress method.** `masonry.method: "basicStress"`
  (`design/masonry_basic_stress.py`): the wall's mortar mix picks the IS grade with at least
  its sand; the effective height 0.75 H for every wall supported top and bottom, kp = 1 (bricks)
  and a 25 % increase with wind or earthquake (to verify) are SAEngine choices; bars of a
  reinforced wall type are not counted (IS 1905 is unreinforced masonry). The pack's working
  stress combinations (IS 875 Part 5 8.1 at full factors) serve masonry and timber.
- **Timber: the parent's values with IS 883 clauses.** BNBC 2020 Chapter 11 follows IS 883; the
  pack keeps its numbers and species list (an Indian species not listed is designed by its
  strength group) and cites IS 883 at the section level.
- **Composite beams by design strengths.** `composite.beam.limitState` (method
  `partialFactors`): the concrete 0.36 fck over xu as 0.4286 fck over 0.84 xu (same force and
  lever arm), the steel fy/1.15, no φ, studs by the tabulated design strength (the nearest
  smaller stud of the table). Composite columns and the deck rules stay the parent's.
- **India left the planned code packs.** The planned-feature page and the wizard's planned entry
  for India are removed: the built-in pack covers loads, concrete, foundations, steel, masonry,
  timber and composite beams.

## 2026-11-04: Indian Standards concrete and foundations (alpha 9 track C8)

The `is-codes` pack now covers IS 456:2000, IS 13920:2016, IS 6403 and IS 2911 (Part 1/Sec 2);
every value is in the pack's `VERIFY.md` with its clause and a confidence, to be checked against
the printed codes. Behaviour choices:

- **One mechanism with C5, chosen by method id.** The groups of `concreteMethods` hold one
  method each, named by its id (`shear.method` `variableStrut` (EN) or `tabulatedStress` (IS),
  `torsion`, `punching`, `deflection`, `cracking`, `cover`, `anchorage`, `seismic`); C8 adds the
  groups with no EN counterpart (`memberLimits`, `columns`, `twoWaySlabs`, `flatSlabs`, `walls`,
  `footings`). The design strengths are C5's `partialFactors` method with the IS values. SAEngine
  practice (the mechanism).
- **The IS stress block as a rectangle (read as).** 0.36 fck xu at 0.42 xu (Annex G) as η fcd
  over λ x with fcd = 0.67 fck/1.5, λ = 0.84, η = 0.9595: the same force and centroid as the
  parabola-rectangle, with the sections' closed-form integration. The parabola-rectangle is the
  pack's other choice (`ultimate.stressBlock`). The bars are elastic-perfectly plastic at fy/1.15
  (Fig. 23A's curve is not modelled). The 3/7 D pivot of sections wholly in compression is not
  modelled; the axial force is capped at 0.4 fck Ac + 0.67 fy Asc (39.3) with the minimum
  eccentricity also applied (on the safe side). SAEngine practice.
- **fc is fck.** Under the pack the project's concrete strength is read as the characteristic
  cube strength. A new building under the pack takes the weakest default concrete that meets
  the least grade of the pack's exposure (moderate: M25, IS 456 Table 5), so the generator's
  C24.1 becomes C27.6. SAEngine practice; the exposure is `concreteMethods.defaultExposure`,
  overridable in Code values.
- **Least stirrups where τv > τc/2 (read as).** IS 456 26.5.1.6 allows them to be left out in
  members of minor importance below half τc; SAEngine applies that to every beam.
- **Slenderness by the additional moments (IS 39.7).** lex = k lu with SAEngine's alignment-chart
  k (Annex E's charts are of the same kind); Ma is added at every station (the braced columns'
  0.4 M1 + 0.6 M2 initial moment is not used). Biaxial bending by the load contour (39.6) with
  Mux1, Muy1 from the interaction surface at Pu; `columns.biaxial.method: "surface"` keeps the
  surface's own utilisation. SAEngine practice (on the safe side).
- **Deflection.** Span/depth with the curve fits of Fig. 4 and 5 (As,req/As,prov taken 1), a
  span continuous at one end counted as continuous; the calculation scales the analysis
  deflection to Ieff of Annex C with creep (θ at 28 days) and shrinkage. Crack widths by Annex F
  at the soffit's corner bar under the service moment. SAEngine practice where noted.
- **Punching.** ks τc on the parent's critical section (with its moment transfer); SAEngine does
  not lay out punching shear reinforcement under the pack (a failing section says so).
- **Ductile detailing replaces Sec 8.3.** Where the detailing level is special (IS 1893 zones
  III-V) the IS 13920 rows of beams, columns, joints and special walls take the place of the
  parent's earthquake-resistant detailing; special walls are checked by the ordinary wall rows
  plus the IS rows; coupling beams by the IS rule. The capacity design shear and the joint
  shear take 1.4 × the beams' design moment capacities (read as: the bars at 1.4 fy with the
  design strengths in Design Reinforcement). Design Reinforcement sizes the hoops by the
  parent's need functions with the IS coefficients (Ash 0.18 / 0.05, the legs' factor taken at
  2, on the safe side) and caps the zones at the IS spacings, never below the least spacing
  offered (a shortfall then shows in the checks). SAEngine practice.
- **Design Reinforcement runs under the project's pack** when the project names a pack other
  than the default (it ran under the default pack before; the default pack's projects are
  unchanged).
- **Foundations.** IS 6403 factors (`foundations.shallow.bearingFactors.method: "flowValue"`)
  in place of Vesic / De Beer / Hansen, vertical loads only; IS 2911 static capacity
  (`piles.staticMethod: "earthPressure"`) with K = 1.5 in the code's 1-2 range, δ = φ, the
  critical depth 15 D, FS 2.5. IS 8009 settlement, IS 2950 rafts and IS 3370 tanks keep the
  parent's methods (placeholder; the tank crack width 0.2 mm is stored).
- **Not covered by the IS methods** (the parent's, named in their rows): column shear and the
  construction joint, corbels, deep beams, stairs, prestress, the walls' axial capacity (32.2.5
  stored), the near-support shear enhancement (40.5 stored), the slab corner steel of D-1.8.

## 2026-11-04: Indian Standards loads pack (alpha 9 track C7)

- **The IS loads pack extends BNBC 2020 until the IS material packs exist.**
  - Question: `is-codes` covers the loads only (IS 875 Parts 1, 2, 3:2015, 5; IS 1893 (Part
    1):2016). How does a project under it design its members?
  - Decision: the pack `extends` `bnbc2020` and replaces its load tables whole (`$replace`);
    concrete, steel, masonry, timber, foundations, services, serviceability and every other
    table come from BNBC 2020 and the report names the pack "BNBC 2020, modified by Indian
    Standards (IS)". Placeholder for the IS materials (tracks C8, C9); the planned entry stays.
- **IS 1893 has no Seismic Design Category (SAEngine practice).** Zone II reads as category B
  (ordinary detailing permitted), zones III-V as C (ductile detailing, IS 13920); 100 % + 30 %
  only for non-parallel systems (IS 1893 6.3.2.2). Ordinary systems carry height limit 0 in C
  (not permitted in zones III-V, a reading of the Table 9 note).
- **IS spectrum in the generic form.** Ah = (Z/2)(I/R)(Sa/g) as S = 1 and TC = 1.36/2.5 =
  0.544 s (soil II), 1.67/2.5 = 0.668 s (soil III), so the falling branch is the code's; the
  printed plateau ends (0.55, 0.67 s) differ by under 1.2 % (read as). The equivalent static
  method takes Figure 2(a) (no rising branch), the response spectrum Figure 2(b).
- **Drift and displacement (read as).** The drift of the design forces is checked as computed
  against 0.004 (7.11.1; `driftAmplification: designForces`); Cd = R stands for the displacement estimate of 7.11.3, used for the
  separation (R × the sum, R/2 for equal floor levels). Ω0 = 2.5 where the design names it
  (SAEngine practice: IS gives no system overstrength).
- **Torsional irregularity as Δmax/Δavg.** IS compares Δmax with 1.2 Δmin at the two ends;
  with two ends that is Δmax/Δavg > 2·1.2/2.2 = 1.091 (1.4: 1.167). No Ax amplification.
- **Wind area averaging Ka = 1.0 for the storey forces (SAEngine practice, conservative)**;
  Kc = 0.9, Kd = 0.9, Kd·Ka·Kc ≥ 0.7. k3 is the topographic factor setting, k4 the Code Values
  override `wind.speedFactors.importance`. The wind risk class (k1) of a category is its
  `windImportance` marker (0.9 / 1.0 / 1.07), k1 interpolated by Vb in Table 1.
- **Live load reduction by floors carried (IS 875-2 3.2)** as a pack method (`floorCount`);
  storage, industrial, wholesale and parking floors and loads over 5.0 kN/m² are not reduced
  (SAEngine reading of 3.2.1).
- **Generation under the pack.** The New Building generator runs under a chosen pack that
  names its own default system (`seismic.defaultSystem`: is-codes), so the system, period and
  loads are the pack's; a town or site class the pack does not list falls to its defaults.
- Every value and its confidence: `python/src/saengine/codes/packs/is-codes/VERIFY.md`.

## 2026-11-02: decisions from the feature and code-completion tracks

| # | Track | Question | Decision | Why |
|---|---|---|---|---|
| 1 | B1 live loads (#114) | BNBC 2.3.6 calls the partition allowance a live load, but SAEngine had it as a superimposed dead load (×1.2). | **Live load (L, ×1.6).** The pack sets which load case partitions belong to, so another pack can keep them as dead. In the seismic weight they count in full (owner decision 2026-11-03, below). | Follow the code text. Results change by a few percent. |
| 2 | B12 irregularities (#125) | BNBC has no penthouse exemption, so a small stair or machine room on the roof flags a diaphragm discontinuity. Most buildings over 12 m in zones 2–4 then need dynamic analysis. | **Keep the literal reading.** | It matches the code and is conservative. SAEngine runs the response spectrum automatically, so it only costs run time. |
| 3 | B35 steel moment frames (#146) | At the default rigid-zone factor of 0.5, the special moment frame panel-zone check fails under the response spectrum. | **Steel moment frames default to 0 (centreline).** RC frames keep 0.5. A factor the engineer sets always wins. SAEngine practice. | This is the usual model when the panel zone is checked separately. |
| 4 | B8 pile capacity (#121) | Eq 6.3.36 is printed with D, which makes skin-friction settlement about 35× larger than the source equation's L. | **Use L (source form).** The pack switch `skinDenominator: "diameter"` restores the printed D. | The printed D is a misprint. |
| 5 | B30 prestressed concrete (#142) | The template tendon, jacked at 0.80 fpu, fails the 0.74 fpu limit after transfer. | **Jack the template at 0.75 fpu.** User models keep their own values. | A new project shouldn't open with a failing check. |
| 6 | B21 RC detailing (#132) | Brick-aggregate projects kept E = 4700√f'c and were only flagged. | **Brick aggregate sets the default E to 3750√f'c automatically.** A typed E is never overwritten. | It is the code value for brick aggregate, which is common in Bangladesh. Deflections and drift go up, as they should. |
| 7 | B5 shallow foundations (#118) | With no soil report, the 2 m minimum depth for cohesionless soil applies, so exterior footings at the 1.5 m default failed. | **The default founding depth is 2.0 m** for new projects and templates. With a soil report, the engineer's depth is used. | New projects should pass out of the box. |
| 8 | T33 joint check | Both directions' top bars sat in the same outer layer, so most two-way joints were flagged as clashes. | **The secondary direction's top bars go in the second layer.** Its effective depth drops by the main bars' diameter. | This is how joints are detailed on site. The clash flag now means a real clash. |
| 9 | T19 driven piles (#79) | Driven piles had become squares (perimeter 4B, area B²), which changed existing results. | **The engineer chooses square or round. Square is the default.** Old projects read as square. | Precast RC driven piles in Bangladesh are usually square, but round ones exist. |
| 10 | B16 flood loads (#130) | Should the moving-water (hydrodynamic) load and the breaking-wave load be summed, or should the larger one be taken? | **Both methods are offered. Sum is the default** (SAEngine practice, conservative). The report names the method used. | The wave acts on the front face while the current loads the whole element. Some engineers read them as alternatives. |
| 11 | T3 diaphragm chords | Floor edges without an edge beam had no chord capacity, so the sample's chords failed and nothing proposed a remedy. Count the slab's own edge bars as the chord, or propose chord bars? | **Both.** The slab's bars parallel to the edge within an edge strip count first; only for a shortfall does the design proposal add chord bars along the free edges. The strip width is a pack value (SAEngine practice where the code gives none). | The slab's edge bars are there anyway; added bars are needed only where they fall short. |

### Where they live, and how to change them

Each item gives the pack value, the project override, and the fallback when the pack is silent.

Since D7, every pack value can also be overridden in the project, by the general mechanism:
Project Settings > Code Values (the setting `codeOverrides`, see
[code-packs.md](code-packs.md#how-to-override-a-code-value)). The items' own settings below
stay, and win over an override of the same value. A value the pack lacks comes from the generic
defaults (`codes/generic/data`), named "generic default (SAEngine practice), not given by
<pack>"; the fallbacks of items 1, 3 and 10 are those generic defaults.

1. **Partitions.**
   - Pack: `areaLoads.partitions.loadCase` (`"L"` or `"SD"`).
   - Project: a setting with the same choice.
   - Fallback: `"L"`, named in the report.
   - Engine: one helper, `partition_case_basis` in `library/settings.py`. Every load, mass,
     live-load-reduction, design, generator and ETABS-export path goes through
     `AreaLoad.superimposed()` and `AreaLoad.floor_live()`.
   - Seismic weight (owner decision, 2026-11-03; it replaces the 2026-11-02 reading, where the
     allowance counted with the live-load share and the threshold was judged on live load plus
     partitions):
     - Count partitions in full in the seismic weight W.
     - BNBC 2020 Part 6 Sec 2.5.7.3 defines W as the dead load "including partition walls". The
       25 %/50 % live share (Sec 2.5.7.3 (a)/(b)) is judged on the floor live load without the
       partition allowance and applies to that live load only.
     - Keep an option so the user can override this as they like.
   - Where it lives: pack `seismic.partitionWeight` (`"full"` or `"withLiveShare"`; the default
     pack gives `"full"`, citing Sec 2.5.7.3), also through `codeOverrides`. Project:
     `analysis.massSource.partitions` (`"pack"`, `"full"`, `"withLiveShare"` or `"factor"`, with
     `analysis.massSource.partitionShare` 0 to 1 for the factor), which wins. Fallback: `"full"`,
     the generic default (ASCE 7-22 Sec 12.7.2 also counts partitions in W), named in the report.
   - Engine: one helper, `seismic_weight_rule` (with `partition_weight_basis`) in
     `library/settings.py`, read by the analysis masses and the static W and base shear
     (`fem/derive.py`; the response spectrum scaling and the irregularity and mass checks use
     those), the grid wizard's preliminary W, the report's W rows and note, the ETABS export's
     mass source (the allowance in a pattern `PART`, in the mass source in full and combined as
     L, when it counts apart from L) and the ETABS import (which restores `PART` as the
     allowance and its mass-source share as the setting, 2026-11-03 below). The default
     floor (2.0 + 1.2 kN/m²) now adds 1.2 + 0.25 × 2.0 = 1.7 kN/m² to W, against 0.5 × 3.2 =
     1.6 kN/m² before.
2. **Literal reading:** no change.
3. **Steel rigid zone.**
   - Pack: `steelSeismic.practice.rigidZoneMax`.
   - Project: `analysis.steelRigidZoneFactor`. Concrete keeps `analysis.rigidZoneFactor`.
   - Fallback: 0.
   - Engine: `design/steel/seismic.py` (`steel_rigid_zone_factor`) and `fem/derive.py`. The
     source is written into `faces.json`.
4. **Pile settlement:** no change. The pack switch is `skinDenominator`.
5. **PT template:** `library/templates.py`, `SlabTendon` template, `jacking: 0.75`. The
   after-transfer ratio becomes 0.948 and the anchorage ratio 0.988. The stress limits come from
   the pack, and a user's tendons keep their own jacking.
6. **Brick E.**
   - Pack: `concrete.modulus` and `concrete.aggregates`.
   - Project: the aggregate setting, or a typed E on the material.
   - Engine: one helper, `material_modulus` in `design/rc_detailing.py`, used by analysis,
     design, nonlinear, SSI, substructure, tanks, lintels, worksheets, the report and the ETABS
     export. Nothing is written back to the material file.
   - Limit: a typed E that equals the stone default can't be told apart from the default yet.
     That needs an "E follows f'c" flag on the material.
7. **Founding depth.**
   - App default: `DEFAULT_FOUNDING_DEPTH` in `library/substructure.py` and the substructure
     editor.
   - Project: each foundation's founding level overrides it.
   - Code minimum: stays in the pack (`foundations.json`).
   - Note: any foundation saved without a founding level now founds at 2.0 m.
8. **Joint top bars.**
   - Project: `construction.jointTopBars` (`auto`, `x`, `y` or `sameLayer`).
   - Auto rule: the deeper beam stays outer. On a tie, the direction with the longer mean span
     stays outer.
   - Engine: `design/rc_detailing.py`, `design/check.py`, `design/proposal.py`,
     `drawings/detailing.py` and `drawings/cages.py`.
   - Not changed: the bottom-bar crossing flag.
   - Torsion (2026-11-02): the second-layer beam's closed stirrups are lowered with its top
     bars, so the torsion cage is that much shallower (`design/torsion.py`, `top_drop`) and its
     top bars sit in the cage's corners. The proposal keeps a bar in every corner and the
     stirrup spacing within ph / 8 of that cage.
9. **Driven pile shape.**
   - Member: the pile type's `shape` (`square` or `round`). Old files read as square.
   - Engine: one rule, `is_square_pile` in `library/substructure.py`, used by capacity,
     settlement, downdrag, pile-cap design, precast handling, detailing, SSI, BOQ, IFC and the
     drawings.
10. **Flood.**
    - Pack: `flood.waveCombination` (`"sum"` or `"larger"`).
    - Project: `site.flood.waveCombination` (`pack`, `sum` or `larger`).
    - Fallback: `"sum"`.
    - Engine: `fem/flood.py`. The report names the method and, with `larger`, which load governs.
11. **Diaphragm chords.**
    - Pack: `transfer.diaphragm.chordStrip`, the edge strip width (1000 mm in the default pack:
      SAEngine practice, the code gives no width).
    - Project: an override of that value (Code Values). Fallback: the generic default, 1000 mm.
    - Engine: `design/diaphragms.py` (capacity: the edge beams' bars, the slab's bars along the
      edge within the strip and, at a free edge, the slab type's `chordBars`) and
      `design/proposal.py` (adds `chordBars` to the slab type's reinforcement in 04 Objects
      for a shortfall). The chord check's note names the strip, its source and the chord bars.
    - Quantities: the bill measures the chord bars along each slab's free edges (no parallel
      beam within 1 m). The drawings don't detail them yet.

## 2026-11-04: pushover hinges, performance levels and the performance point (alpha 9, track P3)

- **Target displacement by method id** (`pushover.targetDisplacement.method`): `coefficient`
  (the default pack's, unchanged), `displacementCoefficient` (ASCE 41-17 Eqs 7-28 to 7-31, the
  US pack's), `equivalentLinearization` (FEMA 440 performance point, selectable in the US pack
  by an override) and `n2` (EN 1998-1 Annex B, the Eurocodes pack's). A pack may list hazard
  levels (`hazards`: BSE-1N/BSE-2N, SD/NC/DL) with a spectrum scale and the performance level
  checked there; the first is the main target. Code values (the formulas); the hazard scales of
  the Eurocodes pack (NC × 1.73, DL × 0.78 by (TLR/TL)^(1/3)) are SAEngine practice.
- **Hinges are assigned, not modelled.** The pushover stays the fibre model it was: the hinges
  (`fem/hinges.py`) sit at every frame member end and fibre wall storey segment and are read
  from the run. The plastic rotation of a concrete end is its chord rotation beyond the one at
  the first yield of its tension bars in the analysis; steel uses θy = Z·Fy·L/(6EI) (× (1 −
  P/Pye) for columns); braces their axial deformation beyond yield or buckling; walls with
  hw/lw ≤ 1.5 their storey drift. The modelling parameters a, b, c and the limits per level come
  from the pack's tables (`table`, `columnRegression`, `chordRotationCapacity` models) with the
  variables at the target displacement. SAEngine practice (the assignment), code values (the
  tables). Results of the default pack are unchanged: it has no hinges and keeps `fibreStrain`.
- **Safe-side fallbacks:** ties not readable (no 04 Objects) count as not conforming, profiles
  other than I shapes as noncompact, ASCE 7-22 site classes BC/CD/DE take the softer
  neighbour's C1 factor, Cm = 1.0. SAEngine practice.
- **The pushover results follow the project's code pack** (with its overrides): until now they
  were worked out under the default pack whatever the project chose. Projects on the default
  pack see the same results.
- Where: `fem/pushover_target.py`, `fem/hinges.py`, `fem/acceptance.py`, the packs'
  `data/pushover.json` (values in their `VERIFY.md`).

## 2026-11-04: the US loads pack (alpha 9, track C1)

The built-in pack `aci318-asce7-22` (ASCE 7-22 loads; values in its `VERIFY.md`, to be checked
against the printed standard). Its behaviour choices:

- **Seismic hazard from mapped values (method `mappedSpectral`).** ASCE 7 has no zone table:
  the engineer enters SDS and SD1 (or SMS, SM1, or the multi-period MCER spectrum), S1 and TL
  from the ASCE Hazard Tool (Project Settings > Site > Mapped spectral values). SAEngine ships
  no hazard data. Inside the program the site's values travel as the derived "Z" (a number equal
  to SDS that carries SD1, S1 and TL), so every path that scales by the hazard keeps working;
  the Seismic Design Category table is read by the band of SDS and SD1 the way the zone packs
  read it by zone. SAEngine practice (the mechanism), code values (the numbers).
  Where: `fem/spectral_hazard.py`, `library/settings.derived`.
- **Peak ground acceleration a_h = 0.4 SDS** (Sa at T = 0 of the two-period spectrum), so the
  engine's Ev = 0.5 a_h D is ASCE's 0.2 SDS D and the diaphragm bound 2.5 a_h is SDS. SAEngine
  practice (the mapping).
- **Storage share of the seismic weight.** ASCE 12.7.2 counts 25 % of the floor live load in
  storage areas. SAEngine takes live loads above 100 psf (4.79 kN/m²) as storage, 0 % for the
  others; the mass source's live share overrides it. SAEngine practice.
- **Wind exposure ids are the pack's.** ASCE's B, C, D are not BNBC's A, B, C (BNBC A is ASCE
  B). The settings now check the exposure against the pack: switching a project to the US pack
  asks for its exposure (a settings problem names it); the New Building wizard takes the pack's
  first exposure (B) and asks to confirm it. SAEngine practice.
- **Materials fall back to BNBC 2020.** Until the ACI 318 and AISC tracks, the pack extends
  `bnbc2020`: concrete, steel, foundations and the other material tables are BNBC 2020's and
  cited as such. Placeholder (not ACI).
- **One mechanism per shared idea (merged with C4, 2026-11-04).** The design spectrum is one
  selector, `seismic.designSpectrum.method`: `reducedElastic` (BNBC), `behaviourFactor` (EN
  1998-1), `mappedSpectral` (ASCE 7). θ is `seismic.stability.method`: `elasticOverImportance`,
  `designDrift`, `elasticDrift` (ASCE Eq 12.8-16). Snow is one table and one module
  (`fem/snow_load.py`): `snow.method` `shapeCoefficient` (EN μ1) or `slopeFactor` (ASCE Cs with
  the low-slope minimum), `snow.loadCase` Lr (enveloped with the roof live load) or S (its own
  case), and an optional `drift` by method id. The wind exposure list and its check are the
  pack's `wind.exposures`, and `wind.method` picks the pressure method. A new pack picks among
  these ids, or adds one.
- **Snow (case S).** The uniform roof snow (the larger of ps and the low-slope minimum pm) is
  applied to the roof slabs as case S, taking the place of Lr in the combinations ("Lr or S or
  R"). The drift at a roof step is computed and reported for the lower roof's design, not
  applied to the model; the snow's share of the seismic weight (20 % above 30 psf) is in the
  pack but not yet added to the masses. SAEngine practice.
- **Irregularity thresholds the table does not number.** Non-parallel systems: elements more
  than 5° off the major axes; in-plane discontinuity: an offset above 1 % of the element's
  length (7-16 and later count any offset that loads the supporting members). SAEngine
  practice.
- **F left out of 0.9D combinations; service wind 0.6W.** An empty tank does not resist uplift
  or overturning; the commentary's serviceability combinations leave the wind's return period
  open, so the ASD wind factor is used. SAEngine practice.
- **Not covered in this version:** the analysis procedure selection (Table 12.6-1), the
  soft-storey factors (BNBC only), linear response history, the C&C roof figures of 7-16/7-22
  (the 7-05 values stay, flagged in VERIFY.md), nonstructural components (Ch 13), ice (Ch 10).

## 2026-11-04

- **Release plan: alpha 9 completes the features, alpha 10 is speed** (owner). Alpha 9 builds the
  other code packs (ACI 318-19 + ASCE 7-22, Eurocodes, IS codes, then BS 8110 and BNBC 2006), the
  features that were planned-feature pages only, and the items earlier set aside as low value.
  Speed (Design Reinforcement on the Sample Frame now takes minutes, not seconds) moves to alpha 10.
  Only the BNBC 2020 text is at hand: the other packs list every value with its clause in the pack's
  `VERIFY.md`, to be checked against the printed codes.
  Owner, later the same day: alpha 9 also gets US customary units throughout, bar schedules by
  the pack's standard (ACI 315, IS 2502, EN ISO 3766 beside BS 8666), National Annex packs,
  packs for the codes that adopt ACI/ASCE (Saudi Arabia, Pakistan, the Philippines, Indonesia),
  Canada, Mexico, Australia and New Zealand, Japan, China, Turkey, Nepal and Sri Lanka, and an
  opt-in hazard lookup by site coordinates. Report and drawing languages come with i18n.
  Owner, later still: packs for Myanmar, Bhutan, Malaysia, Singapore, Qatar and the Gulf, Hong
  Kong, Korea, Iran, Egypt, South Africa, Brazil, Chile, Peru and Russia; SAEngine must work with
  any country's code (a readiness audit, a conformance test every pack passes, and pack
  authoring an office can do itself). Eurocode foundation capacity design computes Ω from the
  dissipative members with q as the cap; under the IS pack, column construction joints keep
  the shear-friction check, labelled SAEngine practice (IS 456 has no such rule).
  The US pack's steel shapes come from SAEngine's own shape list, not the AISC shapes
  database, whose redistribution terms are not checked (owner).
- **Eurocodes pack, loads and seismic (alpha 9 track C4).** The built-in pack `eurocodes`
  (recommended values) covers EN 1990, EN 1991-1-1, -1-3, -1-4, -1-7 Annex D and EN 1998-1; its
  values are listed with their clauses in `codes/packs/eurocodes/VERIFY.md`. Decisions:
  - It `extends` BNBC 2020, so the material and member design tables (and the load tables with
    no Eurocode counterpart here) come from BNBC 2020 until the EN 1992-1999 packs exist. The
    report's design basis names them (`basis`). SAEngine practice.
  - The ids of shared lists stay SAEngine's: ground types A-E are the site classes SA-SE (the
    soil report classifies by the same limits), and the structural systems reuse the ids where
    the detailing level matches (rcSmf = RC frame DCH, rcImf = DCM, rcOmf = DCL ...). A project
    can then switch packs and still run. SAEngine practice.
  - R stands for q, Cd for qd = q (EN 1998-1 4.3.4), and Ω0 for αu/α1. EN 1998-1 has no Ω0, so
    this is SAEngine practice. Drift is qd·de, without dividing by γI (`seismic.driftAmplification`
    "displacementFactor"). θ = Ptot·dr/(Vtot·h), at most 0.3.
  - EN 1998-1 has no Seismic Design Category. SAEngine bands agR (0.02/0.06/0.10/0.30 g) to
    B (very low), C (low: DCL allowed) and D (DCM at least). SAEngine practice.
  - ψE = φ·ψ2 with φ = 1.0 (the largest; the code allows 0.5-0.8 for storeys). Loads above
    5 kN/m² take ψE 0.8 (category E). SAEngine practice, overridable.
  - The roof's Lr is the larger of the category H imposed load and the snow (EN 1991-1-1
    3.3.2(1): not together). The combinations take Lr with the snow ψ. SAEngine practice.
  - Where αA and αn could both apply, the lesser one is used, alone. The code leaves this to the
    National Annex.
  - 6.10 is the default set. 6.10a/b is chosen with the override `combinations.strengthSet`
    "6.10ab". Type 1 is the default spectrum; Type 2 is chosen with `seismic.spectrumType` "2".
    A National Annex is a pack that extends `eurocodes` and sets only these parameters.
  - Owner, 2026-11-04: these defaults, and the US pack's (SDS/SD1 entry, exposure B/C/D, the
    storage share above 4.79 kN/m²), are accepted; each stays overridable per project.

- **Eurocodes pack, concrete and foundations (alpha 9 track C5).** The `eurocodes` pack (0.2.0)
  adds two method tables, `concreteMethods` (EN 1992-1-1, EN 1998-1 Section 5) and
  `geotechnicalMethods` (EN 1997-1); every value is in `codes/packs/eurocodes/VERIFY.md`
  (rows 99-190). A pack without them (BNBC 2020) designs exactly as before. Decisions:
  - Partial factors replace φ only where the pack's method is wired: beam and column flexure
    and axial force (design strengths, φ = 1, the rectangular block η, λ, εcu3 so the closed-form
    section integration stays; `stressBlock: "parabolaRectangle"` is available and slower),
    beam and column shear (variable strut), and the new member-steel and DCM/DCH rows. The
    other concrete checks (torsion, deflection, slenderness, slabs, walls, punching, stairs, the
    parent's special-frame detailing) keep BNBC's method and φ; the design report says so.
    SAEngine practice.
  - Shear resistance VRd = max(VRd,c, min(VRd,s, VRd,max)) (no calculated links where VEd ≤
    VRd,c), cot θ chosen in 1-2.5 for the largest resistance. Beams always need ρw,min: below it
    the "Minimum stirrups" row fails whatever the shear. SAEngine reading of 6.2.1 and 9.2.2.
  - The minimum eccentricity e0 is applied about both axes at once (conservative). SAEngine
    practice.
  - The ductility class comes from the system's frame level (special → DCH, intermediate →
    DCM), consistent with C4's q mapping. νd uses the largest axial force of all combinations
    (on the safe side). SAEngine practice.
  - EN 1997-1: the design approach is a National choice; the pack sets DA1 (overridable). The
    footing design stays allowable-pressure (BNBC); the limit state functions (Annex D bearing,
    sliding, ξ factors) exist, and a pile type's initial load tests report Rc,k (ξ1, ξ2) and
    Rc,d per DA combination. Owner-approved practice defaults, all overridable (owner,
    2026-11-04).
  - Fix of C4's `areaLoads`: the engine reads `stairsDwelling`; the Eurocodes table replaced
    the uses without it, so the stair design failed. Added as category A stairs (2.0 kN/m²).
  - Where it lives: `codes/method_tables.py`; `design/design_strength.py`, `strut_shear.py`,
    `perimeter_punching.py`, `crack_control.py`, `bar_rules.py`, `curvature_ductility.py`;
    `substructure/limit_state_geotechnics.py`; glue in `design/rc.py`, `design/check.py`,
    `substructure/load_tests.py`.
- **Eurocodes pack designs with its own methods (alpha 9 track C5b).** Every design area asks
  `design/method_selection.py` which method the pack picks (`concreteMethods.<area>.method`,
  `geotechnicalMethods`); no id is the default strength design with φ, so BNBC 2020 is
  unchanged. The `eurocodes` pack (0.3.0) now designs by EN 1992-1-1, EN 1998-1 and EN 1997-1:
  beam torsion, span/depth deflection, crack widths and stress limits, column slenderness by
  the nominal curvature method, slabs, stairs and walls on the design strengths with the member
  steel, punching on the control perimeter, DCM/DCH capacity design (joints, ΣMRc ≥ 1.3 ΣMRb,
  capacity shear, ductile walls), Design Reinforcement's sizing, anchorage and laps, footings by
  the design approach and piles with ξ. VERIFY.md rows 191-216 list the new values. Decisions
  (SAEngine practice unless said otherwise; each one overridable):
  - One set of rules per area: where the pack has a method, the parent's rows for the same rule
    are dropped (bar-spacing crack control, slab and wall minimum steel and spacing, wall
    in-plane shear, the special-frame detailing of Sec 8.3); where the pack's limit state rows
    decide a footing or a pile, the allowable-pressure and allowable-load rows stay as
    reported-only rows (serviceability indication).
  - A project sets an area back to the default method with the override
    `concreteMethods.parentMethods` (or `geotechnicalMethods.parentMethods`), a list of areas.
  - Slenderness: l0 = k lu with SAEngine's frame k (the alignment chart); φef = 2.0 × the
    sustained share of the axial force (0.65 without one); i of the gross section, d = h/2 + is.
  - Slabs, stairs and the proposal's beams keep xu/d ≤ (1 - k1)/k2 = 0.448 (EN 1992-1-1 5.5(4)
    with δ = 1) as their ductility limit, in place of the parent's εt ≥ 0.004.
  - Crack and stress rows use the pack's quasi-permanent (6.16b) and characteristic (6.14b-Q)
    service combinations of the analysis cases, αe = Es/Ecm, the exposure class XC1 by default.
  - Span/depth takes As,req = As,prov and beff,i = 0.2 l0; a span that exceeds the ratio shows
    the parent's calculated deflection after it, which then decides.
  - Capacity design: VEd of beams with both end moments in full (min(1, ΣMRc/ΣMRb) = 1),
    columns with 2 MRc at the largest moment over the axial range, joint shear with VC = 0
    (all on the safe side); DCH beams' critical regions with cot θ = 1; walls VEd × 1.5. A DCL
    system has no capacity design (EN 1998-1 5.3), and the report says so.
  - Walls: in-plane shear by 6.2 with bw = t, d = 0.8 lw and the horizontal bars as links.
  - Footings: A2 actions from the A1 strength combinations scaled by γG and γQ; the founding
    layer's characteristic parameters of the nearest borehole; φ'cv,k = φ'k; cast in place;
    water may reach the base. Without strength parameters there the allowable pressure decides
    and a note says so.
  - Piles: Rc,k from load tests (ξ1, ξ2) where they reached failure, else from the calculated
    resistance at every borehole (ξ3, ξ4, n = the boreholes), split into base and shaft by the
    mean shares; tension from the shaft's uplift share plus the pile's weight.
  - A pack with partial factors integrates every section on the design strengths
    (`rc.stress_block`): the walls' and flanged walls' P-M diagrams, lintels and footing strips
    took φ = 1 with characteristic strengths before (C5's φ = 1 reached them); the prestressed
    strips and tank walls, which a pack does not replace yet, keep their φ (`rc.phi_strength`).
  - The required steel (`required.design_required`) and the detailing model (bar schedule,
    drawings) ran under the default pack whatever the project's. They now run under the
    project's pack by the rule C8 gave Design Reinforcement (`proposal._in_project_pack`):
    another pack than the default one; a BNBC 2020 project runs exactly as before.
  - One selection mechanism with C8: a `concreteMethods` group holds one method by id; the
    partial-factor strip, section and sizing functions serve the EN and IS packs alike, C8's
    tabulated rules first where their ids are in force.
  - C4's fixes: the equivalent-frame, direct design, wall, stair and composite clause lines
    named BNBC clauses after the pack in force ("Eurocodes Part 6 Sec 6.5.7"): a clause a pack
    inherits is now named after the pack that wrote it. A pack's systems without height limits
    (EN 1998-1) made the seismic detailing scope fail (KeyError): they are open now.
  - Still the parent's (listed in the design report): deep beams and corbels, slab and stair
    deflection, column and wall confinement ωwd, the footings' and pile caps' structural shear
    and punching, rafts, retaining walls, hooks, compression laps and column splices in the
    detailing, the footing sizing assistant, flanged wall group shear, out-of-plane wall rows.
  - Where it lives: `design/method_selection.py`, `design/limit_state_rows.py`,
    `design/capacity_design.py`, `substructure/limit_state_footings.py`,
    `substructure/limit_state_piles.py`; hooks in `check.py`, `slab.py`, `slab_frames.py`,
    `stairs.py`, `slender.py`, `bars.py`, `proposal.py`, `walls.py`, `wall_design.py`,
    `wall_flanges.py`, `lintels.py`, `rc.py`, `drawings/detailing.py`, `shallow.py`,
    `pilecap.py`, `substructure/report.py` (each marked "Alpha 9 C5b").
- **Wall piers and the remaining coupling-beam checks of special structural walls.**
  - Question: SAEngine checked special walls' piers as walls only, and diagonally reinforced
    coupling beams by 8.3.6.7(d)(iv) hoops alone. What do wall piers (BNBC 2020 Part 6 Sec
    8.3.6.8, pp. 1109-1110 of the PDF, Gazette pp. 3687-3688) and the rest of 8.3.6.7(d)
    (pp. 1108-1109, Gazette pp. 3686-3687) ask, and does the Sample Frame's W1 meet them?
  - Findings:
    - 8.3.6.8(a): wall piers take the special moment frame column rules, with the joint faces
      at the top and bottom of the clear height (the text cites 8.3.5.3 only; SAEngine applies
      8.3.5.3(a), 8.3.5.4 and the capacity-design shear). Piers with lw/bw > 2.5 may instead
      meet (i)-(vi): design shear by 8.3.8.1 (capacity design), not above Ω0 times the
      analysis shear; Vn and web bars by 8.3.6.4; hoops (single-leg bars with 180° bends where
      there is one curtain); vertical spacing ≤ 150 mm; hoops 300 mm beyond the clear height
      above and below; boundary elements by 8.3.6.6(c). (b): at a wall's edge, horizontal
      bars above and below the pier carry its design shear into the wall (Figure 6.8.14).
    - BNBC 2020 does not define a wall pier's proportions. ACI 318-19 2.3 does: lw/bw ≤ 6.0
      and clear height / lw ≥ 2.0.
    - 8.3.6.7(d)(ii): diagonal bars are embedded at least 1.25 ld (tension) into the wall.
      (iii), the alternative to (iv): hoops around each group, out to out at least bw/2 and
      bw/5, Ash of 8.3.5.4 on the group with cover on all sides, spacing along the bars by
      8.3.5.4 and ≤ 6 db, legs ≤ 350 mm apart, through the intersection, and bars round the
      beam's perimeter ≥ 0.002 bw s each way at ≤ 300 mm. (iv): each hoop leg and crosstie
      engages a longitudinal bar of equal or larger diameter.
    - Sample W1 (W250, piers 1500 / 800 / 800 mm, doors 2200 and 2100 mm high): P1 is a wall
      (lw/bw 6.0, hc/lw 1.47); P2 (3.2, 2.75) and P3 (3.2, 2.63, at the wall's end) are wall
      piers taking the alternative. With its PR #173 bars W1 now fails four rows: no pier
      hoops in P2 and P3, and the coupling hoops' 7 legs down the depth have only 5 (S1) and 6
      (S2) of the wall's Ø10 @ 200 horizontal bars per face to engage. The diagonal embedment
      passes: 1.25 ld = 815 mm against (800 - 25) / cos α = 1017 mm (S1) and 1127 mm (S2).
  - Decision:
    - Wall piers are found per pier beside openings by the pack's `detailing.walls`
      `pierLengthRatioMax` 6.0 and `pierHeightRatioMin` 2.0 (generic and default-pack values
      from ACI 318-19 2.3, the pack's source says BNBC has none). The clear height is the
      taller opening beside the pier. lw/bw ≤ `pierAlternativeRatio` 2.5 takes the column
      rules, otherwise the alternative.
    - The alternative's checks: Ve = 2 Mpr / hc (1.25 fy, the pack's `lintels.probable`), at
      most Ω0 Vu, against φ Vn of 8.3.6.4 with ρt of the web and the pier hoops (φ 0.60 where Vn
      is below 2 Mn / hc); hoops provided; spacing ≤ `pierHoopSpacingMax` 150 mm; boundary
      elements by the stress method; at an edge, the horizontal bars within lw above and below
      the clear height carry Ve (φ As fy, φ 0.75). The hoops' extension (`pierHoopExtension`
      300 mm) is a note in the checks and is measured in the bill and schedule.
    - The column rules' checks: ρ 1 %–6 % (8.3.5.3(a)), Ash both ways and spacing ≤ min(least
      dimension/4, 6 db, so) over the clear height (8.3.5.4), hx ≤ 350 mm, and capacity-design
      shear with Vc = 0 (conservative). The 8.3.5.1 size limits are not applied to wall piers.
    - Wall types get `pierHoop` (hoops in every wall pier of the type, in addition to the web
      bars). `CouplingDiagonal` gets `groupHoop` (option (iii)) and `longitudinal` (the beam's
      own bars along each face, the bars the legs engage; none: the web's horizontal bars).
      (iii) is checked when a type has no hoops over the section. The (iii) spacing limit is
      min(bw/4, so, 6 db): owner, 2026-11-04, reads "satisfying 8.3.5.4" as including
      bw/4 (ACI 318-19 18.10.7.4(c) has only so and 6 db).
    - New pack values: `couplingEmbedment` 1.25, `couplingGroupWidthShare` 0.5,
      `couplingGroupDepthShare` 0.2, `couplingGroupLegSpacingMax` 350, `couplingPerimeterRatio`
      0.002, `couplingPerimeterSpacingMax` 300, `pierLengthRatioMax`, `pierHeightRatioMin`,
      `pierAlternativeRatio`, `pierHoopSpacingMax`, `pierHoopExtension`. Generic defaults come
      from ACI 318-19 2.3, 18.10.7.4(b)-(c) and 18.10.8.1.
    - Design Reinforcement proposes pier hoops for wall piers (the type's own kept where they
      pass), and coupling-beam longitudinal bars where the wall's horizontal bars leave a hoop
      leg without a bar.
    - The sample's W250 gets `pierHoop` Ø10 @ 150 (2 × 2 legs) and coupling-beam longitudinal
      bars Ø10 @ 150 along each face. The BOQ is regenerated (Ø10 steel +81.5 kg: pier hoops
      48.7 kg, longitudinal bars 32.8 kg; concrete unchanged).
  - W1 numbers:
    - Before (PR #173 bars, new checks): fails P2 and P3 "Wall pier hoops provided"
      (8.3.6.8(a)(iii)); S1 legs 7 against 5 bars, S2 7 against 6 (8.3.6.7(d)(iv)).
    - After, with the starting bars: passes, governing utilisation 1.00 (4 diagonal bars per
      group against 4, the 200 mm leg limit, the 150 mm pier hoop spacing). P2 Ve = 3 × 7.1 =
      21.3 kN, P3 Ve = 3 × 17.7 = 53.1 kN (Ω0 Vu below 2 Mpr / hc of 162 and 164 kN), φVn = 587
      kN; P3's edge bars carry 247 kN.
    - After Design Reinforcement → Apply: W250 status "ok". The web proposal becomes Ø12 @ 350
      V and Ø12 @ 450 H. The diagonals, the coupling hoops and longitudinal bars, and the pier
      hoops stay as they are. W1 passes; every element of the sample passes.
  - Owner, 2026-11-04: the column rules' Vc = 0 stands, and 8.3.6.8(b) keeps the horizontal
    bars within lw above and below the clear height.
  - Check-row names come from the pack (owner, 2026-11-04). The wall and coupling-beam rows
    of `design/walls.py` name their clause from the pack's `designClauses.wallsRows` (clause
    numbers only, e.g. "8.3.6.8(a)(iv)"). A pack without an entry names the row without a
    clause. The PR #173 rows, the new rows, the existing walls rows and the 8.3.6.7(a)/(c)
    waiver notes of `design/lintels.py` all read it. With the default pack the names are
    unchanged except "Coupling beam hoops provided (8.3.6.7(d)(iii), (iv))".
  - Where it lives:
    - Checks: `design/walls.py` (`pier_kind`, `pier_segments`, `wall_pier_rows`,
      `pier_design_shear`, `propose_pier_hoops`, `coupling_engagement_rows`,
      `coupling_group_rows`, `coupling_perimeter_rows`, `coupling_embedment_row`, `named`).
    - Glue: `design/wall_design.py` (`_wall_pier`, `_pier_hoop_proposal`,
      `coupling_proposal`).
    - Schema: `library/objects.py` (`WallReinforcement.pierHoop`,
      `CouplingDiagonal.groupHoop`, `.longitudinal`, `CouplingGroupHoops`).
    - Quantities: `boq/quantities.py` (`wall_pier_parts`; "pier hoops", "group hoops",
      "coupling bars"). The schedule's marks are Q and Z (pier hoops and crossties), U
      (coupling longitudinal bars) and W (group hoops) in `drawings/detailing.py`.
  - Open: the column-rule shear takes Vc = 0 whatever the axial force; and 8.3.6.8(b) is
    checked with the horizontal web bars within lw of the clear height. The figure shows no
    length, so the owner may want another reach.

## 2026-11-03

- **Slab openings carry no area load, and the ETABS import keeps shell slabs as shells.**
  Question: the Sample Frame read back from its e2k had W 659 kN for 608 kN (54 m² of floor
  loaded on 65 m²). Findings: the import left `analysis.slabs` at its default "loads to
  beams" for the file's ShellThin floors, and slabs as loads to beams loaded the whole panel,
  openings included (a shell slab's mesh leaves them out). Decision (SAEngine practice): with
  slabs as loads to beams the area loads (self-weight, finish, live, partitions, rain) act on
  the panel's net area (less the union of its openings within it, MEP shafts included),
  spread to the edges by the panel's shape; the live load's intensity, and so its share in W,
  is the given one. The e2k import sets `analysis.slabs` to "shells" when every floor is
  ShellThin or ShellThick, keeps "loads to beams" for membrane floors and reports a mix.
  Where: `fem/derive.py` (`_opening_fraction`), `importers/etabs.py` (`_slab_modelling`).
- **The ETABS import restores the partition allowance** (PR #172). Question: the e2k export
  writes the allowance as its own pattern `PART`, in the mass source at its share; should the
  import read it back as plain live load (×0.25 in W, with a note) or restore it? Decision
  (owner): restore it. The area loads of a partition pattern become the area loads'
  `partitions`, in the pattern's case (Live → L, Superimposed Dead → SD; the project's
  `analysis.partitionAllowanceCase` is set only when it differs from the pack's). The mass
  source's factor on it sets `analysis.massSource.partitions`: 1 → in full, the file's L
  factor → `withLiveShare`, else `factor` with `partitionShare` (0 when the pattern is not in
  the mass source); left at `pack` when the pack's rule gives the same share, and untouched
  when the file has no mass source. Recognised patterns: `PART`, or a Live or Superimposed
  Dead pattern without self-weight, named as partitions (`PART`, `PARTS`, `PART 2`,
  `Partition(s)`, any name containing "partition", `PW`; not `PARTIAL`), with area loads only;
  others named so are read as their type says, reported. Why: an exported project read back
  keeps its seismic weight W and base shear V (tested on the Sample Frame's loads, a generated
  four-storey frame and the three-bay model with each rule), and the allowance is not mixed
  into the floor live load, whose share in W and heavy-live threshold it would change. Where: `importers/etabs.py`
  (`_partition_pattern`, `_Importer._partition_patterns`, `_partition_case`,
  `_partition_mass`), `importers/common.py` (case `P` of `add_area_load` → `AreaLoad.partitions`),
  [import.md](import.md).
  Owner, 2026-11-04: the recognition rule stands, and a partition pattern left out of the
  mass source keeps factor 0 (the file's own choice), not the pack's rule.
- **W250 boundary elements and spandrel hoops (PR #173).**
  - Question: the Sample Frame's special wall W1 (W250) failed four checks: boundary element
    provided (8.3.6.6(d)), the spandrels' capacity-design shear Ve (8.3.8.1(a)), spandrel width
    to depth ≥ 0.3 (8.3.4.1(c)) and hoop spacing at the ends (8.3.4.3(b)). Can bars fix them?
  - Findings:
    - The boundary element was needed only in a 100 mm pier between the two doors (D2 ended
      100 mm short of D1). A 100 × 250 mm sliver cannot hold a confined boundary element. Its
      hoops would have to be about 33 mm apart (one-third of its least dimension), and two
      rows of bars do not fit. No bars fix this; only the layout does.
    - The spandrels over the doors are coupling beams with ln/h of 0.8 and 1.0 and a low shear.
      BNBC 2020 Part 6 Sec 8.3.6.7(c) (p. 1108) lets these take diagonal bars, or the beam
      rules "8.3.7.2 to 8.3.7.4" [sic: 8.3.4.2 to 8.3.4.4]. Neither option includes the
      member limits of 8.3.4.1, so the b/h ≥ 0.3 rule does not apply to them. SAEngine had
      waived only 8.3.4.1(a) and (b).
    - With the beam rules, the least flexural steel over a 0.9 to 1.0 m span gives Ve of about
      1 MN. That is above any stirrup capacity, so these spandrels need diagonal bars
      (8.3.6.7(d)).
  - Decision:
    - The sample's door D2 moves from offset 500 to 3300 mm. The piers are now 1500, 800 and
      800 mm, none needs a boundary element, and the doors keep their sizes.
    - W250 gets coupling-beam diagonal bars, 4 Ø16 per group, with hoops Ø10 @ 75 over the
      whole section: 7 legs down the depth and 2 across (8.3.6.7(d)(iv)). The wall mesh stays
      Ø10 @ 200 each way.
    - "Either" coupling beams (8.3.6.7(c)) no longer check any 8.3.4.1 member limit.
    - Hoops over a diagonally reinforced coupling beam are now checked: provided, spacing
      ≤ min(150 mm, 6 db), legs and crossties ≤ 200 mm apart, and Ash of 8.3.5.4 each way.
    - Design Reinforcement proposes diagonal bars and hoops where 8.3.6.7(b) requires them, or
      where (c) allows them and the beam rules fail.
  - Why: the code reading above. The 100 mm pier was a layout error, not a reinforcement
    problem. Boundary elements stay available on the type (`reinforcement.boundary`) wherever a
    pier needs them.
  - Owner, 2026-11-04: door D2 at offset 3300 mm is accepted, and W250 carries no boundary
    elements, since none is required.
  - Where it lives:
    - Schema: `CouplingDiagonal.hoop` in `library/objects.py`. The object editor gets it from
      the generated schema.
    - Limits: the pack's `detailing.walls` values `couplingHoopSpacingMax`, `couplingHoopDb`
      and `couplingLegSpacingMax`. The generic defaults come from ACI 318-19 18.10.7.4(d).
    - Checks: `design/walls.py` (`coupling_hoop_rows`). The 8.3.4.1 waiver is in
      `design/lintels.py`.
    - Proposal: `design/wall_design.py` (`coupling_proposal`).
    - Quantities: the bill of quantities and the bar bending schedule measure the diagonals and
      hoops (marks G, J, Y).
- **Partitions count in full in the seismic weight W** (Sec 2.5.7.3). See item 1 above.
- **The Sample Frame's wall W1 is 250 mm** (type W250, was W200). Every structural wall in
  Seismic Design Category D is a special wall, and at 200 mm W1 was too thin for its boundary
  elements and its spandrels (8.3.4.1(c), (d)). At 250 mm it still failed. The layout and
  coupling-beam change above (PR #173) makes it pass.

## 2026-11-04

- **The ETABS e2k carries the shell mesh size** (owner decision). Question: the Sample Frame
  read back from its e2k came back at the 500 mm default mesh, not its 250 mm, and its W was
  1.05 kN (0.14 %) low. Decision: the export writes the project's `analysis.meshSize` as a
  SAEngine comment line after the file's header comment, `$ SAEngine mesh size 0.25` (the
  file's length unit), which ETABS skips. It writes no mesh keyword on the AREAASSIGN lines:
  public e2k samples show ETABS writing `OBJMESHTYPE "DEFAULT"` there, but its other values
  and the spelling of a maximum mesh size are unverified, and an unknown keyword could make
  ETABS reject the file. The import reads the comment first. As a fallback for files of other
  tools it reads an area's largest element side from `MAXSIZE1`/`MAXSIZE2`, `MAXSIZE`,
  `MAXMESHSIZE`, `AUTOMESHSIZE` or `MESHSIZE` (none, `AUTOMESH "NO"` or `OBJMESHTYPE
  "DEFAULT"`: no size): one size on every meshed area is the project's, mixed sizes take the
  most common, reported. With neither, the default stays. Sizes under SAEngine's 100 mm
  minimum are raised to it, reported. "Mesh by slab span" is not carried and keeps its
  default. Where: `exporters/etabs.py` (`MESH_COMMENT`), `importers/etabs.py` (`parse`,
  `_area_mesh`, `_mesh_size`).
- **US pack concrete (ACI 318-19, alpha 9 C2): SAEngine practice where the code leaves a gap**
  (pack values, overridable per project; listed in the pack's VERIFY.md).
  - Bar sizes are the US soft-metric sizes (No. 10-36 as 10, 13, ... 36 mm).
  - Brick aggregate concrete has no ACI rule: it is treated as normal weight (Ec 4700 √f'c,
    shrinkage steel × 1.0).
  - Special walls' design shear Ve = Ωv ωv Vu (18.10.3.3): Ωv is taken as its lower bound 1.5
    where hw/lw > 1.5 (Mpr/Mu is not computed), ns as the wall height over the storey height.
  - Joints whose column ends at the joint (Table 18.8.4.3, "other" columns): γ 1.2, 1.0, 0.7 by
    the same confined-faces count the engine uses for 1.7, 1.2, 1.0.
  - The two-way slab coefficient method and the stair spans have no ACI 318-19 counterpart:
    the pack keeps BNBC 2020's and cites them as BNBC 2020's; lintel bearing and span/600 are
    cited as TMS 402.
  - Least slab strain 0.005 (εty + 0.003 at Grade 420, rounded); the 0.0018 shrinkage steel of
    every grade.
  - A pack names the code of each table's clauses (`tableCodes`, `designClauses.shortNames`), so
    one pack can cite ACI 318-19 and ASCE 7-22 side by side.
- **US pack steel and masonry (AISC 360-22, AISC 341-22, TMS 402-22, alpha 9 C3): SAEngine
  practice where the code leaves a gap or the engine has no method** (pack values, overridable
  per project; listed in the pack's VERIFY.md).
  - Steel shapes are SAEngine's own shape list (library/steel_sections.py and the steelSections
    table), not the AISC shapes database (owner).
  - LRFD is the pack's design basis; ASD (`steel.designMethod`) designs the steel members and
    their connections by Rn / Ω under the pack's allowable stress combinations. Ω is the pack's
    `omega` of each limit state, else 1.5 / φ (`omegaFromPhi`). Composite members, the members
    of a steel seismic force-resisting system and runs by the direct analysis method stay LRFD,
    with a note: those modules work with φ and the strength combinations. α = 1.6 on Pr (B1 and
    the K = 1 check) of members checked by ASD.
  - AISC's KL/r ≤ 200 and L/r ≤ 300 user notes are checked as limits (flags for beams).
  - Short-slotted holes take the slip factor of slots along the load (0.85) whatever their
    direction; the long-joint reduction (0.833 beyond 950 mm) is applied to the tension splices
    SAEngine checks, as before.
  - The connection notes are written with the default pack's references; a pack maps them to its
    own (`steel.connections.references`). The HSS connection equations (Chapter K) keep their
    BNBC 2020 numbers, named as BNBC 2020's, and the default pack's φ.
  - Built-up members, stability bracing, ponding and the tension field stiffener area are the
    default pack's rules, cited as BNBC 2020's.
  - AISC 341-22 width-thickness limits use the member's own Ry (Table A3.2 by its grade); IMF
    beams and columns, SCBF beams and OCBF braces are checked against the moderately ductile
    limits. The seismic rules not revised (connections, panel zones, links, BRBF, SPSW,
    composite systems ...) are the default pack's, cited as BNBC 2020's.
  - Composite columns: C1 and C3 from As / Ag (the bars' area left out: conservative); filled
    sections are designed as compact only (noncompact and slender walls are refused).
  - Masonry: TMS 402-22 strength design is the wall type's `masonryMethod` "strength"; the
    default method stays the allowable stress design of BNBC 2020 Chapter 7 (TMS 402-22 Chapter 8
    is not in the pack), named so. εmu 0.0025 (the clay masonry value) for all units, γg = 1.0.
  - Timber stays BNBC 2020 Chapter 11: the NDS needs its own reference values and method.

## 2026-11-04: Eurocodes steel and the other materials (alpha 9, track C6)

- **One selector for limit state steel.** The EN 1993 methods are method ids of the limit state
  steel table `steelLimitState` that C9 (IS 800) introduced, not a second selector:
  `memberResistance` (`crossSectionClasses`: classes 1-4 with effective widths, curves a0-d,
  the rolled or general LTB case, Annex A or B), `connections` (`partialFactors`: EN 1993-1-8
  bolts, bearing, welds, block tearing, slip) and `seismic` (`dissipativeZones`: EN 1998-1
  Section 6). The IS groups of the table became optional when `memberResistance` is given;
  χ of the buckling curves is shared. SAEngine practice (owner direction of the integrator).
- **Pack defaults** (all overridable per project): LTB by the rolled case 6.3.2.3 with f = 1,
  interaction factors by Annex B (Annex A an option), the simplified weld method, masonry
  γM 2.0, timber service class from the location of use (inside 1, outside 2, wet 3), wind as
  a short-term action for kmod. SAEngine practice.
- **SAEngine practice where the codes leave it open or the model does not know**: C1 of Mcr from
  the moment diagram's equivalent moment factor (load at the shear centre, k = kw = 1); Cm 1.0 for
  diagrams with transverse load (Annex B); αm = 1 in the sway imperfection; αcr estimated from
  Δ2nd/Δ1st; bearing k1 at 2.5 (the transverse edges not known to the bolt line); EBF links
  taken as short links; the gravity and earthquake parts of the forces from each earthquake
  combination and its opposite-sign partner; masonry unit group 1 (solid) / 2 (hollow); the
  heat-affected zone over the whole section of a welded aluminium member; Weff = ρ Wel of class 4
  shapes other than I, channel and RHS.
- **Aluminium** is a material category (`aluminium`, the alloy and whether welded); its members
  use the steel members' shapes, lengths and stations. Timber materials gain an optional
  `strengthClass` for the limit state method.

## 2026-11-04: steel remainder of the US, Eurocodes and IS packs (alpha 9, track C12, steel half)

- **Method ids, one place each.** The new steel methods are groups of the existing selectors:
  `steelLimitState.torsion` (`elasticStresses`), `.bracing` (`equivalentImperfection`,
  `forceShare`), `.columnSide` (`effectiveWidth`, `dispersion`), `.hssJoints` (`chordFace`),
  `steelLimitState.seismic.links` (the EBF links of `dissipativeZones`); two new tables,
  `coldFormed` (method `effectiveSection` with the effective width, distortional and resistance
  methods by id) and `steelFire`. The default pack has none of them: its results are unchanged.
  The US pack keeps its AISC paths (H3 torsion, Chapter K joints, J10, F3 links) and lists the
  Appendix 6 brace requirements as flagged rows (`steel.bracing.rows`).
- **Cold-formed sections** are two new 04 Objects profiles, `C` (IfcCShapeProfileDef, a lipped
  channel) and `Z` (a lipped Z, exported to IFC as IfcZShapeProfileDef without the lips),
  computed geometrically (A, I, S, Z of square-cornered plates, J, Cw and the shear centre on the
  centreline). Any steel member of such a profile is checked by the pack's `coldFormed` table;
  a pack without it says the section is not covered.
- **Steel in fire** uses the members' fire ratings of Project Settings (the same ratings as the
  least-size checks), the protection as a project value (`steelFire.protection`, default none),
  μ0 = ηfi × the ambient utilisation, the steel temperature by the lumped heat capacity in the
  standard fire (ISO 834 for ASTM E119 and IS 3809 as well), the critical temperature for members
  without compression and the buckling resistance at temperature for compression members (IS:
  the limiting temperature for every member). A pack with the table checks its steel members by
  it instead of the least-size rows.
- **SAEngine practice** (all overridable): torsion of IS members by the EN 1993-1-1 6.2.7 form
  with γm0 (IS 800 has no rule); δq of EN 5.3.3 at its limit L/2500; the IS restraint share 2.5 %
  also for columns; the IS column panel as web shear and the parent's flange local bending; the
  distortional critical stress of the AISI and IS methods by the EN 1993-1-3 edge-stiffener spring
  model; Cb = 1 of cold-formed LTB; the IS 801 working forces as the factored ones / 1.5; the fire
  load ratio 0.6 (US, IS) and 0.65 (EN); ca constant 600 J/kgK; the EBF link rotation from the
  drift limit (the whole drift as plastic).

## 2026-11-04: concrete, foundations and loads leftovers of the IS and US packs (alpha 9, track C12, concrete half)

Each is a pack value or method id, overridable in Code Values; the default pack is unchanged.

- **SAEngine practice, US foundations.** Where IBC 2021, ASCE 7-22 and ACI 318-19 give no value
  (permissible settlements, subgrade moduli, pile static methods, machine foundations, FS 3 on a
  static pile analysis, FS 1.5 against sliding and overturning of footings), the US pack keeps
  the default pack's numbers and cites them as SAEngine practice, no longer as BNBC. The soil
  pressure uses the ASCE 7-22 Sec 2.4 combinations without the one-third increase (IBC 1806.1);
  the presumptive rows keep the ids the Substructure editor lists, mapped to the IBC classes;
  soft clay has no presumptive value (by investigation).
- **SAEngine practice, tanks.** A pack picks the crack control of water tanks:
  `crackWidth` (IS 3370 limit state, 0.2 mm) or `steelStress` (the service stress of the bars:
  the IS 3370 working stress method, ACI 350's fs limits). ACI 350: the flexural fs taken at the
  20 ksi floor of its relation, and the durability factor Sd not applied separately (the service
  stress check stands for it). The surface zone minimum steel is an added lower bound.
- **SAEngine practice, IS 1343.** The tension limits are stresses (`tensionForm: absolute`);
  Types 1 and 2 are taken together as Class U (3 MPa) and Type 3 as Class C; two-way slabs use
  the Type 2 limit. The flexural strength, punching and the bonded reinforcement stay the
  parent's rules.
- **SAEngine practice, settlement and rafts.** The IS 8009 rigidity factor 0.8 reduces only the
  elastic (Steinbrenner, flexible centre) settlement of clay under isolated footings. The raft
  class (rigid when the column spacing < 1.75/λ, IS 2950 / ACI 336.2R) is reported as a note:
  the plate on springs analysis covers both classes.
- **SAEngine practice, IS 1893.** The design eccentricity 1.5 esi ± 0.05 bi adds 0.5 esi to the
  static torsion case on esi's side; esi is estimated from the centre of mass and a centre of
  rigidity from the vertical members' b d³ (columns, structural walls), the code giving no
  method. The wall-building period takes the first storey's structural walls within about 25° of
  the shaking.
- **SAEngine practice, IS 875-3.** Annex C k3 uses s = 1.0 (the figures' peak at the crest)
  unless set in Code Values, and L = 2 Lh of the topography settings. The gust factor method
  scales the static storey forces level by level by G (k̄2/k2)² (the code's Cf taken as the wall
  coefficients). Cladding Cp (Tables 5-8), the across-wind response and the IS 16700
  slenderness and acceleration limits are not built (SAEngine has no matching checks).

## Earlier owner decisions

- **2026-10-28, piling.** Typical foundations are bored piles with pile caps, on a pile grid of
  their own (independent of the column grid). Caps may be eccentric to the column, with the
  eccentricity moment. Piled rafts come later.
- **2026-10-24, ETABS parity.**
  - Seismic mass is lumped at storey levels, with the lower half of storey 1 going to the base.
    The old method stays available as a setting.
  - Slabs are meshed at 500 mm (or span/8 if smaller), with a Run All convergence warning when
    beam moments change by more than 5 %.
  - Beams have rigid end zones (factor 0.5, a setting; see decision 3 for steel) and are designed
    at the support faces.
- **2026-10-21, BOQ materials.**
  - Cement is in kg and in 50 kg bags; sand and stone are in cft.
  - Practice defaults, editable and flagged as not code values: dry-volume factor 1.54 for
    concrete and 1.30 for mortar, and cement bulk density 1440 kg/m³.
