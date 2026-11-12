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

## 2026-11-12: shared editing actions (actions round, track A)

Owner, 2026-11-12: "make it so that the AI can actually do entire projects from scratch". The
catalogue is [actions.md](actions.md); these are the choices made building it.

- **Only what an action made worse refuses it.** After each step the changed parts are checked by
  their models and the input guardrails (the editors' check). A problem the file had before the
  step is not the step's: it is neither a refusal nor repeated. So an engineer's half-finished
  project can still be edited by the assistant.
- **A setting not entered yet is a warning, a wrong one an error.** Switching to a pack whose
  hazard comes from mapped spectral values, or to a custom location, leaves SDS, SD1 or V to
  enter: the settings are incomplete, not wrong, and the next action (settings.site) gives them.
  A value that is entered and outside the pack's range or below its minimum is refused.
- **A run step is a commit point.** Run All, Design Reinforcement, Size Footings and the exports
  work on the saved files. With write, the edits before a run step are written first and stay
  written if a later step is refused (the batch says which files); without write a run step
  after unsaved edits is refused, since it would not see them.
- **Run All does not refuse the batch when a step fails** (the design of types without bars, a
  failing check): its steps' messages come back as warnings, as the app's Run All reports them,
  so a batch can go on to Design Reinforcement. `strict: true` makes a failed step a refusal.
- **Design Reinforcement stays an explicit action.** Run All never writes bars (2026-10-27);
  `design.reinforcement.apply` is the only action that applies the proposal.
- **Typical floors.** Placing members on a storey of a typical family places them on the whole
  family, as the floor plan editor does; a member load given by storeys goes on one storey of
  each family, since a load on a typical floor applies to its family.
- **Ids** as the floor plan editor makes them: the letter and the lowest free number (C1, B1,
  W1, S1, F1), LL1 and PL1 for member loads, BH-1 for boreholes, AL1 for new area loads.
- **Fixed in passing:** `saengine status` called the building model stale when it recorded the
  floor plan's stamp without the view-only keys (as the app and Run All record it); it now
  compares the floor plan as the app's part list does.

## 2026-11-09: any-code readiness (alpha 9 track C26)

Owner, 2026-11-04: "make sure our software works at ease with any country code".

- **Response spectrum combinations from the pack** (behaviour change for packs other than the
  default). The response spectrum design forms its combinations from the pack's strength rows
  with E (the chosen `strengthSet` included), E's factor on every spectrum part: the rows with
  the least dead load factor take E = Eh - Ev, the others Eh + Ev; where every row has the same
  dead load factor (EN 1990 6.4.3.4: G + AEd + ψ2 Q) each row is formed with both signs of Ev
  (SAEngine practice). Before, every pack got 1.2D + L ± 1.0E and 0.9D ± 1.0E. The default
  pack's combinations 5 and 7 give exactly the same combinations as before. A pack without any
  row with E keeps those two as the generic default (SAEngine practice). The live load factor is
  the project's static earthquake combination's of the same dead load factor, else the row's.
- **Inherited clause text names its owner.** A clause or source text a pack inherits that
  starts "SAEngine practice" (such as "SAEngine practice where BNBC 2020 is silent" under the
  IS, BS 8110 and other packs that extend BNBC 2020) is printed with "[inherited from BNBC
  2020; not given by <code>]"; the report's design basis lists the tables each pack inherits,
  by the pack that supplies them, and its labels quote the default pack's table numbers only
  where the pack takes that table from it ("Site class (BNBC 2020 Table 6.2.13)" under BS 8110,
  "Site class" under the IS pack). The default pack's texts are unchanged.
- **Bar names in every unit system.** A pack's bar names (#5, N16, HD16, 16M, D16, Φ16) show in
  SI too, not only in US customary units; a size the pack does not name stays "Ø16". The
  default pack has none: its texts are unchanged.
- **Bar masses from the pack** (owner, test-pass item of C14). The bill of quantities, the bar
  schedules, the precast pieces and the BVBS files weigh a bar by the pack's nominal mass of its
  size (`concrete.barMasses`), else d²/162 as before. The US pack gives the ASTM A615 masses
  (No. 10 is 0.560 kg/m, not 0.617); Korea the KS D 3504 masses; packs that extend the US pack
  with metric bars at the same keys replace them with none (d²/162 of their diameters).
- **Eurocode foundation capacity design: Ω from the dissipative members** (owner, 2026-11-04;
  EN 1998-1 4.4.2.6(2)P, (3)). Each foundation takes Ω = MRd / MEd of the base section of the
  column it carries in the seismic design situation, the least over the strength combinations
  with earthquake (MRd at each combination's axial force, from the column's bars), at least 1
  (SAEngine practice), with γRd Ω at most q. A base without such a ratio (a wall, a steel
  column, a column without bars) keeps the pack's Ω, else q. The two ways the global moments may
  map onto the section's axes give two ratios: the larger is taken (on the safe side). Packs
  without the rule (the default) are unchanged.
- **IS column construction joints** (owner, 2026-11-04). Under the IS pack the column
  construction joint keeps the parent's shear-friction check, labelled "IS 456:2000 13.4 (places
  the construction joints, gives no shear-friction rule): ... SAEngine practice".
- **Pack verification status** (owner). A pack whose `VERIFY.md` has rows not ticked
  ("Verified <date>", ✓ or [x] in a cell) shows "values not yet verified against the printed
  code" in the pack chooser (Project Settings, the New Building wizard), on the Packages page and
  in the report's design basis, until its `pack.json` says `"verified": true` or a date. Every
  built-in pack, the default one included, shows it today: their VERIFY.md rows are not ticked.
- **Hazard lookup trust** (owner question pending; built as asked: a trust step, default
  untrusted). A user or project pack that names an online hazard lookup service is asked only
  after the user trusts its `hazardLookup` file on the Packages page (stored with the hooks'
  trust, keyed by the file's content: any edit revokes it). Built-in packs need no trust.
- **Conformance checks and `notCovered`.** `saengine codepack check` and the test over every
  installed pack check coverage, sources, clause ownership, earthquake and wind combinations,
  bar names and masses, and the verification status. A pack may declare areas its code does not
  design for in `pack.json` `notCovered` (BS 8110 and its children: seismic).
- **Project Settings under another pack** no longer shows the default pack's preview of the
  site and seismic values (BNBC 2020 tables) or its structural-system check; the values come
  from the chosen pack when the project is analysed.
- Where it lives: `fem/seismic_design.py` (`_earthquake_rows`), `codes/context.py`
  (`attribute`), `codes/registry.py` (`value_owner`, `inherited_from`, `verification_status`,
  `set_lookup_trusted`), `codes/bars.py`, `codes/conformance.py`, `units.py`
  (`si_bar_names`), `substructure/foundation_capacity.py`, `codes/template.py`, the packs'
  `concrete.json` / `detailing.json`, `docs/code-packs.md` ("Write your own country's pack").

## 2026-11-09: exchange formats, office server, visual programs, studies, drawing automation (alpha 9 track L12)

- **SAEngine practice, what the exchange files hold.** The `.s2k`, `.std`, SAF, SDNF and CIS/2
  exports are written from SAEngine's own analysis model (derived as Run All derives it), not from
  the building model as the `.e2k` export is: the other program gets the members, plates,
  sections, supports, diaphragms and every load case SAEngine analyses, loads included, and the
  combinations of Project Settings. The self-weight is part of the dead case's loads (no
  self-weight multiplier), pinned steel ends are end releases, rigid end zones, lumped masses and
  the staged dead load are left out and reported. Each file has an export report (what was
  written, approximated and left out) like the `.e2k` export.
- **Not verified against the other programs.** The formats are written from their public
  descriptions and SAEngine's own readers of `.s2k`, `.std` and SAF read them back; no other
  program was run. docs/exchange.md lists what is unverified (field names, local axes,
  SDNF and CIS/2 layouts) for the owner to check with a licensed copy or the format owners.
- **Detailing programs.** No proprietary link: IFC is the route (with SDNF and CIS/2 for programs
  that read them).
- **Owner decision needed, office server security.** The office server is off by default and
  sends project data only to the address the engineer configures; no third-party cloud. It
  listens on 127.0.0.1 unless started with `--host`; a token (shown once, only its SHA-256 kept on
  the server, compared in constant time; five failures lock an address out for a minute) guards
  every request; without TLS (`--certfile/--keyfile`) on a network address it warns, and the app
  asks before sending to an `http` address that is not this machine. Open for the owner: whether to
  require TLS on network addresses (refuse rather than warn), per-engineer tokens instead of one
  office token, and how long jobs are kept on the server (7 days by default).
- **SAEngine practice, design studies.** A study runs each variant on a copy of the project
  (`12 Automation/studies/<id>/variants`, a computed cache kept out of versions and archives),
  at most 32 variants, one after the other. The base is saved as a version first, but only in a
  project that already keeps versions (a study never starts a history); applying a variant copies
  its part files back and saves a version. Steel is the bill's steel and rebar mass, cost the
  priced bill (the sample rates when the project has none: the table says so).
- **SAEngine practice, drawing automation.** Rule-based, on the generated sheet DXFs: chain and
  overall grid dimensions where a sheet has none, a mark beside members whose mark (from the
  drawing set's own XDATA) is not near them, overlapping labels moved apart. Each change is
  tagged so Undo Drawing Automation takes it back; regenerating the drawing set drops them, as any
  hand edit. The AI assistant calls them only while AI edits are allowed.

## 2026-11-09: steel shop drawings, NC files (DSTV) and rebar CNC (BVBS) (alpha 9 track L10)

- **Made only when asked.** Three rows of 11 Exports: Steel Shop Drawings (`11 Exports/Shop
  Drawings/`, sheets `SD-101` on, DXF per sheet and one PDF), NC Files (DSTV, `11 Exports/nc/`,
  one `.nc1` per part mark) and Rebar CNC (BVBS, `11 Exports/bvbs/`, one `.abs`). The structural
  drawing set and its connection details are unchanged. Options: Project Settings > Drawings >
  Fabrication (weld symbols, marks' prefixes, end clearance, sheet size, NC order and phase,
  part marking, BVBS schedule number).
- **Code independence.** The pack's `fabrication` table picks the weld symbols (AWS A2.4 in
  the default pack, ISO 2553 system A in the Eurocodes and IS packs), the anchor hole clearance
  and the cope clearance; a pack without it takes the default pack's; the project can override
  each. Bolt holes are the pack's steel table's standard holes. The BVBS shape geometry is data
  of the pack's bar schedule standard (`bvbs` of each shape code); a shape without it is sent
  without geometry, which the guideline allows.
- **Assemblies (SAEngine practice).** One assembly per member (two at a cover-plate splice).
  Parts welded in the shop go with the member they are welded to: end plates, tabs, base and
  cap plates with the member; fin plates, gussets, flange plates, column stiffeners and doublers
  with the supporting member, else loose with a note. Splice plates are loose. A beam framing
  into a beam at the same level is coped (the supporting flange and root radius plus the cope
  clearance). A bolted end plate drills the support to match. A tab slot of a hollow brace is
  stated on the drawing, not cut in the NC contour.
- **Cut lengths (SAEngine practice).** To the face of the support: the end clearance (12 mm by
  default) for fin plates, gussets of channels and angles and members without a designed
  connection; the end plate's thickness; the flange plate connection's setback; the gusset
  geometry of the connection details for braces. Cap plate welds take the wall thickness as
  their leg.
- **Marks.** Identical parts (profile or plate, grade, length, holes, cuts, outline) share one
  part mark (`p1`, ...; main parts first); identical assemblies one assembly mark (`B1`, `C1`,
  `BR1`). The marking plans are the structural steel plans and braced elevations with the
  assembly marks.
- **Formats.** DSTV NC after the DSTV standard description (7th edition, 1998): ST, BO, AK,
  SI, EN; a plate's thickness written in the flange width and both thicknesses, AK for every
  plate. BVBS BF2D records after the BVBS guideline with its checksum; `l` is the scheduled
  cutting length, `s` twice the bend radius. Both files are ASCII with CR LF line ends. The
  details to verify are listed in the PR and the packs' VERIFY.md.

## 2026-11-09: CFD wind tunnel as an optional OpenFOAM link (alpha 9 track L3)

- **OpenFOAM is the user's.** SAEngine does not bundle or download OpenFOAM (GPL, large; the
  owner decides later). It finds an installed one: in WSL on Windows (the distribution set in
  Settings > SAEngine > CFD Wind, else the default), on the host on Linux/macOS; the location
  setting (`etc/bashrc` or the install folder), then the login shell's PATH, then the usual
  install places. Otherwise it shows how to install it. Nothing runs until the user presses Run.
- **Where it lives.** FEM part: SAEngine > CFD Wind Tunnel (Project menu). Settings in Project
  Settings > Wind > CFD wind tunnel (one home); the page shows them read-only with a link.
  Files: `08 FEM/cfd-wind/results.json` (kept, versioned and archived) and
  `08 FEM/cfd-wind/cases/` (OpenFOAM cases, logs, run status; computed, left out of archives).
- **The case (SAEngine practice).** Envelope from the BIM slabs per level (else columns/walls,
  else the analysis nodes), storeys of one outline joined; courtyards filled. Domain 5H
  upstream, 15H downstream, 5H to the sides and above; cubic background cells of
  H / 8 (coarsened to 4 million at most), 3 halvings at the building, 1 in a wake box;
  snappyHexMesh without layers (wall functions). Log-law inlet (`atmBoundaryLayerInlet*`),
  Uref 10 m/s at H (Reynolds only: the loads scale with the code's pressure), rough ground with
  the same z0; k-ε by default or k-ω SST; simpleFoam (or `foamRun -solver incompressibleFluid`
  on OpenFOAM.org 11+), 1500 iterations or p residual 1e-4; one case per direction, the
  building turned so the wind is along +x. Every file is written from Python templates.
- **Code-dependent values in the pack (`cfdWind`).** Directions every 30° (SAEngine practice in
  every pack), z0 by exposure (BNBC A/B/C read as ASCE 7 B/C/D: 0.3/0.02/0.005 m; ASCE 7-22
  Commentary; EN terrain categories from the wind table; IS 875-3 categories 1-4), the lower
  limit 0.8 of the code's base shear (ASCE 7-22 Sec 31.4.3; SAEngine practice in the others),
  and the code's wind-tunnel requirement for the report. All overridable per project.
- **Post-processing.** Cp = p / (½ Uref²) of every building face (zero-gradient p: the cells'
  values, read from the ASCII mesh and fields); per level band (half storey below and above, the
  base the lower half of the first storey, as the code's storey forces): CF = Σ Cp A [m²],
  CMz about the plan's centre, Cf along the wind; Cp mean/min/max per facade zone (X+, X-, Y+,
  Y-, roof, soffit) and storey, with its role (windward, leeward, side).
- **Design forces.** F = q·CF, q = the code's velocity pressure at H × its gust factor, with
  the project's overrides (a quasi-steady scaling of mean coefficients; no peak or dynamic
  response: stated in the report).
- **"CFD wind" cases.** Off by default (existing results unchanged). With Project Settings >
  Wind > CFD wind tunnel > Use in the analysis, each direction becomes the wind case of its
  nearest axis (WX, WY, WXN, WYN, the largest along-axis base shear first, the others WX2,
  WX3, ...), so the existing wind combinations (opposite-direction cases, variants) take every
  direction; scaled up to the pack's lower limit; the code's torsional cases WTX/WTY are kept on
  top; a flexible building's gust factor scales them with WX/WY. Results for other levels than
  the model's are refused (the code's wind is used, with a note).
- **Validation.** The page and the report say first that these are engineer-supplied loads, not
  a code wind tunnel test, with the pack's own requirement (BNBC 2020 Part 6 Sec 2.4.16, ASCE 7-22
  Ch 31, EN 1991-1-4 Sec 1.5, IS 875-3 Sec 10).

## 2026-11-09: bridges and special structures (alpha 9 track L9)

Moving loads and influence lines, girder bridges (design, bearings, joints, load rating),
lattice towers, silos, chimneys, cooling towers, offshore jackets and piping stress, entered in
Project Settings → Bridges and Special Structures (`specialStructures`, left out of the file
while empty) and computed by `python/src/saengine/special`. New tables `movingLoads`,
`bridgeDesign`, `latticeTowers`, `shellStructures`, `offshore`, `pipingStress`; the default pack
(BNBC 2020) has none of them, so its results do not change (the building's analysis only gains
the wind of towers marked "on the roof").

- **SAEngine practice (owner's brief), traffic loads without a pack table.** A pack without
  `movingLoads` / `bridgeDesign` (BNBC 2020: buildings only; the RHD bridge loading is not
  reliably known here) takes SAEngine's practice data on the HL-93 basis
  (`special/data/movingLoads.json`, `bridgeDesign.json`: the HL-93 truck, tandem and lane load,
  multiple presence, IM 33 %, Strength I 1.25 / 1.50 / 1.75 and the MBE rating factors), every
  result naming it "SAEngine practice (HL-93 basis), not given by <pack>". This is the one
  place a whole table falls back (the generic defaults never do); the girders' resistances stay
  the pack's own concrete methods.
- **SAEngine practice, influence lines.** A girder line is a continuous beam on knife-edge
  supports with constant EI (the beam model of the post-tensioned slabs), unit loads at stations
  at most 0.5 m apart; a grillage: girders of the tee section and transverse deck strips (the
  station spacing wide, torsion b t³/6), unit loads at every girder node (OpenSees), wheels
  shared by the lever rule between girders, all on the outer girder beyond it (no cantilever
  overhang). Lanes side by side from either kerb, loads on their centre line; the code's lane
  1, 2, ... loadings go to the lanes that give the most (every assignment up to six lanes).
  Line girders share the traffic by Courbon's rigid cross-section; the dead loads are shared
  equally among the girders in both models.
- **SAEngine practice, girder checks.** Sagging flexure on the flange-wide rectangle (a note when
  the neutral axis leaves the slab), hogging on the web with the top bars, shear on the web with
  its stirrups without the prestress (on the safe side); prestressed girders: stresses at the
  section of the largest sagging moment with the losses as entered (no time-step), strength
  with fps of bonded strands from the pack's prestress rules (γp 0.28 where the pack has none).
  A pack's `bridgeDesign` without prestress limits takes its building prestress limits (said).
  Load rating only where the pack gives rating factors (the US pack; practice for BNBC):
  RF = (φc φs φRn - γDC DC - γDW DW) / (γL (LL + IM)), φc φs at least the pack's least.
- **SAEngine practice, towers.** Wind panel by panel at the corner nodes (no member wind
  between), feed lines and ladders Ca 1.2, antennas by their EPA; the EN pack's Kθ at 45° is a
  constant 1.11 (K1 0.55, K2 0.2) and its round members take the flat-member coefficient (on the
  safe side). Members by the pack's steel method with |N| / NRd + |M| / MRd. A pack without
  `latticeTowers` takes the trussed tower coefficients of its wind table (BNBC 2020 Figure
  6.2.23). A rooftop tower adds its wind (normal to a face) to the roof level's storey force;
  its weight is entered as joint loads and its base moment is not applied.
- **SAEngine practice, shells.** Silo walls by Janssen's membrane forces (no FE): the wall's own
  weight × 1.35 with the friction. Chimneys: vm = √(2 qz / ρ) at the top (on the safe side for
  the vortex trigger), b the mean diameter of the top third, clat,0 log-linear in Re between
  the pack's points. Cooling towers: a ShellMITC4 model fixed at its base ring with the cp of
  EN 1991-1-4 Table 7.12 joined by cos² curves (SAEngine practice), internal suction -0.5.
- **SAEngine practice, offshore.** The stream function wave (12 Fourier terms) is used for
  "Stokes 5th"-type nonlinear waves; Airy with Wheeler stretching. Members fixed at the mudline
  (no pile-soil), no buoyancy, load factors 1.1 / 1.35 and 0.9 / 1.35 (the table's and 0.9
  practice), members by the pack's steel method (API WSD's allowable stress formulas are not
  used).
- **SAEngine practice, piping.** Bends as sharp corners (no flexibility factor: stiffer, on the
  safe side for the expansion stresses at anchors), the larger of the in- and out-of-plane SIF
  on the resultant moment, guides and stops on the run's nearer global axis, missing directions
  held at the first support for stability (said).

## 2026-11-09: special members (alpha 9 track L7)

Steel joists, castellated and cellular beams, aluminium joints, structural glass, tensile
membranes and concrete-filled composite plate shear walls. New tables `steelJoists`,
`webOpenings`, `glass`, `membranes`, `compositePlateWalls` and the `aluminium.joints` group;
the default pack (BNBC 2020) has none of them, so its results do not change.

- **SAEngine practice, joists.** A joist is a beam type with a `joist` (04 Objects): placed like
  a beam, analysed with the type's profile (a light I section of about the joist's weight), then
  designed as a parallel-chord truss from the member's M and V: chords N = M / d, webs V / sin θ,
  each part by the pack's own steel member method (`design/steel/pack_resistance.py`: the
  buckling-curve, limit-state or φ/Ω family the pack chooses). Two angles back to back are taken
  as a tee of their legs (the gap neglected, on the safe side). Without a `steelJoists` table the
  truss is checked alone (top chord panel moment w l² / 8 of a simple panel, linear interaction);
  with it, the joist specification's slenderness, panel moments, least web shear, bridging and
  catalogue load tables apply. The deflection uses the pack's serviceability limits on the
  analysis deflection × I(profile) / I(effective), the effective I being the chords' reduced for
  the webs' shear deformation by virtual work. The SJI load tables are not copied: the US pack's
  `loadTables` is empty (project data).
- **SAEngine practice, castellated and cellular beams.** The type's I profile is the finished
  (expanded) section. The tees are checked at each opening centre (axial force and Vierendeel
  moment on the tee at the opening's centre, the elastic modulus: on the safe side); the
  deflection is scaled by the net-section stiffness along the openings plus the table's
  Vierendeel share (0.1 in both packs). The design mode does not propose sections for these
  types. A pack without `webOpenings` fails the beam with a "not covered" row (the gross-section
  checks alone would be unsafe).
- **SAEngine practice, aluminium joints.** The joint is checked for the largest resultant end
  force; fillet welds and the heat-affected zone take the whole force as shear (the criterion's
  least favourable direction). The US Aluminum Design Manual is not built (planned feature): the
  US pack does not cover aluminium.
- **SAEngine practice, glass.** Glass panels, floors, balustrades and fins are designed per type
  from their own size and actions (characteristic wind, snow, live load; balustrades the pack's
  barrier line load), on linear plate theory (Timoshenko's simply supported plate; no
  large-deflection relief, on the safe side). Laminated glass by the Wölfel-Bennison ω; for more
  than two plies SAEngine's generalisation (Is about the package's centroid, hs between the outer
  plies). The ASTM E1300 load charts are approximated by an allowable 3 s surface stress of
  annealed glass (23.3 MPa) × the glass type and load duration factors: owner to check against
  the charts before release. Deflection limits span / 60 (US) or / 65 (EU), 25 or 50 mm, and the
  fins' Mcr × 1 / (2.0 or 1.5) are SAEngine practice.
- **SAEngine practice, membranes.** Four-corner membranes and cable nets only (other boundaries,
  masts inside the surface and cutting patterns are planned). Form found by force density, then
  each pack case is analysed on the found form by dynamic relaxation with tension-only links at
  characteristic loads; the fabric's strip strength / 4 (short) or / 6 (long) and the cables'
  breaking force / 2.2 (both packs, after the TensiNet guide; not code values).
- **Code value (to verify), filled plate walls.** AISC 341-22 H7 / AISC 360-22 Chapter I in the
  US pack only: shear Vn = (Ks + Kc) / √(3 Ks² + Kc²) As Fy, Pno, the plastic in-plane flexure
  at the axial force, and the detailing limits. The plates' end closures are not counted. The
  wall's analysis stiffness is the fill's (set its modifiers for the composite stiffness).

## 2026-11-09: slope stability, 2D geotechnical FE and AGS4/DIGGS exchange (alpha 9 track L8)

- **Where it lives.** Slopes are a list of 9 Substructure (`substructure.json` `slopes`), next to
  the excavations whose wall, stages and supports (P1) the 2D FE reuses; the section cut from the
  site's strata reads 01 Soil Report's stratigraphy (linked, never copied). The AGS4 and DIGGS
  exchange lives in 01 Soil Report beside the CSV/Excel import (one import command, by the file's
  extension; the fields it cannot map are listed as notes).
- **Code pack table `slopeStability`.** BNBC 2020 gives no slope method or factor of safety (Part
  6 Sec 3.21 lists landslides as a geo-hazard, Sec 3.14 the stability of adjoining buildings):
  the default pack's values are **SAEngine practice**: factors of safety 1.5 (permanent), 1.3
  (temporary), 1.1 (pseudo-static) as in USACE EM 1110-2-1902 Table 3-1 practice, kh = 0.5 PGA
  (Hynes-Griffin and Franklin 1984), kv = 0; Bishop, Spencer and Morgenstern-Price checked,
  Janbu reported. The Eurocodes pack checks by the partial factors of its design approach
  (geotechnicalMethods: M sets on the strengths, A sets on the variable surcharges, F ≥ γR;e of
  Annex A Table A.14) and EN 1998-5 4.1.3.3 (kh = 0.5 α S, kv = ± 0.5 kh) on M2; the US pack
  keeps the factors of safety with US sources. Other packs inherit through `extends`.
- **SAEngine practice in the methods.** The soil's own weight is not factored under partial
  factors (single-source principle, `partialFactors.soilWeight` 1.0); a slice with mα < 0.2 makes
  its surface unreliable and it is left out of the search (Whitman and Bailey 1967); Bishop's
  method is run on circles only; Janbu's corrected factor uses b1 of Abramson et al. (2002);
  Spencer and Morgenstern-Price find λ by bisection between ±2; pore pressures from a phreatic
  line are hydrostatic below it (no seepage correction); free water above the ground is not
  weighed; nails and anchors act as resisting forces along their axis where the slip surface
  crosses them, min(tensile / 1.8, pull-out / 2.0) per metre (FHWA-NHI-14-007 factors in the
  default pack); a vertical seismic coefficient is checked with both signs.
- **The search.** Circles over a grid of centres above the slope (or the box given) and radii
  tangent to levels down to the base, refined twice about the best; non-circular surfaces by a
  random walk (seeded, so results repeat) of eight vertices from the critical circle, kept
  concave and under the ground; every method of the check then runs on the best surfaces and
  reports its lowest factor.
- **2D FE (optional, for experienced users).** Plane strain on a Gmsh mesh of the section
  (`saengine.fem.mesh`), OpenSees quad/tri31 with Drucker-Prager matched to Mohr-Coulomb in plane
  strain (or PDMY/PIMY multi-yield, or J2 for undrained clay), K0 stresses from an elastic gravity
  stage with ν = K0/(1+K0) when ν is not given, P1's wall (EI per metre, EA of a solid plate of
  that EI, no weight, bonded to the soil) wished in place with its forces reported as the change
  after gravity, P1's supports as springs to fixed points (compression-only struts and rakers,
  tension-only anchors) placed at their stage, excavated elements released over the stage's load
  steps, the excavation taken as half of a symmetric one. The strength reduction factor (each
  trial a fresh analysis, Griffiths and Lane 1999) is reported beside the limit equilibrium as a
  flagged row: the limit equilibrium is the check.
- **AGS4 / DIGGS.** SAEngine keeps the SPT's 150 mm increments, AGS4 the 75 mm ones: the export
  writes N1, N2, a refusal without its penetration and the sample number into `ISPT_REM`, the
  soil type and USCS group into `GEOL_REM`, the method into `LOCA_REM` (read back by the import);
  positions in a national grid other than BTM come in relative to the first borehole. DIGGS
  output is written by the 2.6 element names as known and is not validated against the schema.

## 2026-11-09: nonlinear buckling (GMNIA), cables and the FE check of steel joints (alpha 9 tracks L4 and L6)

- **Nonlinear stability (L4, `fem/nonlinear_stability.py`).** An analysis the engineer sets in
  Project Settings, Analysis, Nonlinear stability (one combination) and runs from the FEM
  results. The frames, trusses, links, supports and diaphragms of the derived model (walls,
  slabs and solids left out, as in the linear buckling model, so that λu compares with αcr);
  each frame element cut into pieces; co-rotational frames and trusses; steel members as
  fibre elements (Steel02) at the pack's design yield and modulus; load control to λ = 1, then
  arc length (cylindrical) or displacement control past the peak. The limit load factor λu is
  the path's peak; a path still rising when it stops is reported as a lower bound.
  *SAEngine practice*: the pieces (4 by default), the stopping rules (a 20 % drop past the
  peak, a displacement of the height / 10), the first-order axial forces taken for αcr and
  the bow directions (each compressed member about its weak axis), residual stresses left
  to the equivalent imperfections.
- **Imperfections by the pack** (`nonlinearStability` table, `codes/stability_tables.py`):
  bow by curve ratio (EN 1993-1-1 Table 5.1) or one ratio (AISC L/1000); sway φ0 αh αm
  (EN 1993-1-1 5.3.2(3)) or one ratio (AISC L/500); the first buckling mode scaled so that the
  member that bows most in it gets the pack's bow (a simplification of EN 1993-1-1 5.3.2(11),
  *SAEngine practice*); a pure sway mode scaled to φ h. **BNBC 2020 gives no GMNIA method**:
  the default pack's table is *SAEngine practice* on the AISC 360 basis BNBC Part 6 Ch 10
  adopts (L/1000, L/500, 0.9 Fy and 0.9 E), stated in the results.
- **Cables** (`fem/cables.py`): a brace type's `cable` (pretension, breaking force, modulus,
  pieces) becomes a tension-only chain of co-rotational trusses with the pretension as an
  initial strain, its own weight on its interior nodes; sag and tension read at λ = 1. The
  linear analysis keeps the brace as it was (no change to existing results). A cable needs a
  pretension (a straight slack cable has no stiffness). Design tension = the pack's share of
  the breaking force (EN 1993-1-11 6.2, Fuk / (1.5 γR), γR 0.9, in all three packs: *to verify*;
  the US pack has no ASCE 19 values yet).
- **CBFEM (L6, `design/connection_fe.py`).** "FE Check..." on a steel member whose end
  connection is an end plate or a fin plate (FEM results, Properties). Plates as layered shells
  (J2 plasticity, linear hardening E/1000), bolts as tension-only links with shear springs
  (EN 1993-1-8 Table 6.11 stiffness in all packs: *SAEngine practice* outside the Eurocodes),
  compression-only contact links, welds as stiff elastic links; the member's governing end
  (largest shear of the combinations) loaded at a stub with the stub's lever arm taken off;
  checks: plastic strain ≤ 5 % (EN 1993-1-5 C.8 Note 1; *SAEngine practice* for the default and
  US packs), bolts and welds by the pack's own connection rules (reused), Sj,ini classified by
  the pack's bounds (EN 1993-1-8 5.2.2.5; AISC 360 Commentary B3 20 / 2).
  *SAEngine practice*: a mapped (structured) quad mesh instead of gmsh, so that the plates'
  nodes meet at every bolt, weld and contact point without interpolation links; the supporting
  member as a plate held along its web line (end plate) or rigid (fin plate); no holes,
  preload, friction or plate buckling.
- **Not built (stays for later):** shells (walls, slabs, plated girders) in the GMNIA model
  (the `plates` imperfection values are in the packs for it), the fem-viewer strain contour
  (the result carries the mesh and each shell's plastic strain for it), CBFEM of the other
  connection kinds.

## 2026-11-05: floor response spectra (alpha 9 track L5)

- **Where it lives.** Project Settings, Analysis, Floor response spectra (off unless set):
  `saengine.fem.floor_spectra` with the code pack's `floorSpectra` table; the results view's
  chart and Summary table, and the report. No code in the default pack gives floor spectra
  (BNBC 2020 Part 6 Sec 2.5.15 is by height only), so the method is SAEngine practice there.
- **Methods by id.** `timeHistory`: the floors' absolute accelerations of the run's time-history
  cases through oscillators, the mean of the spectra from the pack's `meanFrom` records (as
  P5), else the largest. `spectrumToSpectrum`: the site's elastic spectrum (R = I = 1) as a
  power spectral density, through the modal transfer function of the floor and the component's
  oscillator, with the Davenport peak factor (20 s strong motion). "By the code pack" takes the
  time history when the run has one.
- **Broadening ±15 %** and component damping 2/3/5/7 % (5 % for the components): ASCE 4-16
  practice, in the pack and overridable per project.
- **Components.** With "Use for the components" on, the nonstructural components (the existing
  nonstructural table, not a copy) take F = Sa(Tc) Wc Ic / Rc at their floor within the
  table's least and largest force; their period is not entered, so a rigid one (αc = 1) takes
  Sa at 0.06 s and a flexible one the spectrum's peak (on the safe side). Off by default:
  existing results do not change.

## 2026-11-05: point-cloud references (alpha 9 track L2)

- **Formats.** LAS 1.2-1.4 uncompressed (point formats 0-10) and text scans (XYZ, PTS) are read
  by SAEngine's own reader (numpy). No point-cloud library is in the environment, so LAZ needs
  `lazrs` or `laszip` and E57 needs `pye57`: both are refused with a message until the owner
  decides to add the dependency.
- **As an underlay.** A scan attached to a story is shown as the slice at the story level + a
  cut height (default 1200 mm, 100 mm thick, one point per 20 mm cube; SAEngine practice, set per
  underlay), drawn as dashes, with straight lines traced through it by RANSAC. The traced lines
  are the plan's object snaps, so as-built walls, columns and grids are drawn over the scan
  with the existing tools. A scan starts at 1000 mm per unit (metres); Calibrate Underlay Scale
  corrects it. `elevationOffset` gives the scan's height of the project's ±0.
- **3D view.** The viewer package has `setPointCloud` (decimated points, grey by intensity) in
  its source; the backend gives the points (`cad/pointCloudView`). The viewer is not rebuilt
  this week, so the BIM view does not call it yet.

## 2026-11-05: precast pieces and their shop drawings (alpha 9 track L1)

- **Where it lives.** A precast type is an object type of 04 Objects with `precast` (hollow-core
  and double-tee slab types, precast beams, columns with corbels, wall panels). The analysis
  takes the type as any other of its kind; the piece checks (`saengine.design.precast`), the
  piece shop drawings (`drawings/sheets/precast.py`) and the piece schedule
  (`saengine.boq.precast`, `precastPieces` of the bill) follow from it. Corbels are designed by
  the existing corbel method and welds by the pack's fillet welds (no second copy).
- **Code values (default pack).** BNBC 2020 Part 6 Sec 6.10: bearing ln/180, 50 mm slabs, 75 mm
  beams and stemmed members, pads 13 mm from unarmoured edges, bearing 0.85 f'c A1; dowels by
  shear friction (Sec 6.4.5); integrity ties 4.4 kN/m, 1.4 Ag, two 44 kN ties per panel.
- **SAEngine practice** (Sec 6.10.2.1 and 6.10.9 ask for the handling stages and give no
  values): PCI Design Handbook multipliers (stripping 1.3-1.7 by mould, yard 1.2, travel 1.5,
  erection 1.2), handling tension 0.62 √f'ci / 1.5, f'ci = 0.7 f'c when not entered, four-point
  rigid rigging on two inserts, insert safety 4 on an ultimate load, erection wind 0.5 kPa and
  safety 1.5, a hanging member by Mast's method with the whole sweep L/960 + 6 mm (on the safe
  side), the least bearing tension 0.2 Vu. All are in the pack's `precast` table and can be
  overridden per project; a pack without the table shows precast as not covered.
- **Methods by id.** Bearing `spanRatio` (BNBC, ACI 318-19 16.2.6) or `netBearing` (EN 1992-1-1
  10.9.5); dowels `shearFriction` or `dowelAction` (fib Bulletin 43). Pieces of one type with
  the same length and width share a mark. A slab is covered by units of the unit width
  spanning in the span direction, the last one cut to fit.
- **Known limit.** The bill's slab items still measure a precast floor type as a slab of its
  thickness; the piece schedule gives the units' net concrete (cores and voids deducted).
## 2026-11-05: composite beams, columns and slabs on deck (alpha 9 track P8)

- **Composite slabs on steel deck are a new pack table.** A slab type's `compositeDeck` makes it
  a composite slab, checked by the pack's `compositeSlab` table (only the Eurocodes pack, EN
  1994-1-1 Section 9). A pack without it reports the deck as not checked and designs the slab as
  concrete; the default pack's results are unchanged. With the table, the slab's own concrete
  checks become advisories and the composite slab's rows decide.
- **SAEngine practice: one way, simply supported, per metre.** The slab spans along the ribs
  between its supports (the slab's extent along them unless the span is given), designed simply
  supported (the bars over the supports are crack control). The deck's section values come from
  its trapezoidal geometry (gross, no embossments or effective widths) unless the manufacturer's
  are given; without the manufacturer's MRd the construction stage bending row is an advisory.
  The longitudinal shear needs the deck's test values (m and k, or τu,Rk); without them the row is
  an advisory asking for them. The working area of the construction load is placed at mid-span.
  The service deflection limit is L/250 overall (the code gives none).
- **SAEngine practice: the camber of unshored composite beams** (US and Eurocodes packs): 80 %
  of the steel beam's deflection under the wet concrete, in 5 mm steps, none below 20 mm.
  Reported in the summary and the drawings' notes, not checked.
- **The slab's longitudinal shear of composite beams** (Eurocodes pack, EN 1994-1-1 6.6.6): the
  planes beside the beam (top and bottom bars) and, in solid slabs, round the studs (bottom bars
  twice); the deck's own contribution is not counted (safe side).
- **SAEngine practice: composite floors' vibration.** The analysis carries the steel beams
  alone, so a floor on composite beams has its deflection scaled by Is / It,dyn of its composite
  beams (full interaction, Ec × the pack's `compositeDynamicModulus`: 1.35 US, 1.1 Eurocodes);
  the default pack has none and is unchanged.
- **The design mode checks composite types as composite.** The lightest section is found with
  the composite checks (and the studs designed when the type gives no spacing); the proposal
  notes the studs.
- **BOQ.** Shear studs (number, from the type's spacing) and the steel deck (m², the slab's
  soffit) are a new group, "Composite" (SC), kept out of the structural steel's kg. A composite
  slab's concrete is the volume over and in the ribs; the deck replaces the soffit formwork.
- **Planned.** The fire resistance of composite members (EN 1994-1-2, AISC 360 Appendix 4) stays
  a planned feature; the US pack's composite slabs (ANSI/SDI C-2017) are not entered.

## 2026-11-05: base isolators and supplemental dampers (alpha 9 track P6)

- **What was built.** B37's isolation design now takes its procedure from the pack
  (`isolation.procedure.method`): `twoLevel` (the default pack's DD/DM form, unchanged) or
  `singleLevel` (`fem/isolation_single_level.py`): one earthquake level, the displacement with
  the lower- and the upper-bound properties, Vb = k·D of the governing bound,
  Vst = Vb (Ws/W)^(1 − c β), Vs = Vst / RI with the pack's minima, k = 14 β Tfb or a fixed
  exponent, the base level force (Vb − Vst)/RI, γx on the devices' displacements, the total
  displacement by the rigid deck or (`torsion.method: "periodRatio"`) the closed form with PT
  and a floor. Isolator kinds: lead-rubber, high-damping rubber, elastomeric, single and triple
  friction pendulum, flat slider; a sliding unit's curve from μ and R (Qd = μP, Kd = P/R);
  property modification factors λ combined by the pack (`propertyModification`). The US pack
  gets ASCE 7-22 Ch 17, the Eurocodes pack EN 1998-1 Section 10 with EN 15129; BNBC keeps its
  procedure and results.
- **Dampers** (`fem/dampers.py`, new `dampers` table, not in the default pack): a brace type's
  `damper` (viscous, viscoelastic, metallic, friction). The pack's method `modalStrength` (the
  ASCE 7-22 Ch 18 fundamental and residual mode ELF with the effective ductility and the
  hysteretic damping) or `dampedSpectrum` (generic); the static earthquake cases scaled to the
  damped base shear (never below the pack's minimum), the response spectrum divided by the
  damping ratio, the damper schedule (stroke, velocity, force, energy at the pack's earthquake
  level) against the devices' capacities, a report section, BOQ items. The US pack gets
  ASCE 7-22 Ch 18; EN 1998-1 has no damped-structure procedure, so the Eurocodes packs model the
  dampers but take no reduction (the same for the default pack).
- **Nonlinear time history.** The isolators become bearing elements of their kind in the NLTH
  model (Bouc-Wen elastomeric bearing, single friction pendulum, flat slider; before P6 the NLTH
  model kept the fixed bases), the dampers twoNodeLink elements (a new Maxwell `ViscousDamper`
  material in the solver, Kelvin for viscoelastic, Steel02, elastic-perfectly-plastic). The
  results give each device's design displacement, force, velocity and energy over a suite, and
  hysteresis loops.
- **SAEngine practice (no code gives it):**
  - The NLTH takes the isolators' nominal properties; the bounds are run by setting the types'
    bound factors and deriving again. A triple friction pendulum runs as its equivalent single
    pendulum (the solver has no triple pendulum element yet).
  - A sliding unit's vertical load P is the type's test vertical load, else the seismic weight
    per unit.
  - A damper brace in the linear model keeps 0.1 % of its area for a viscous damper (no static
    stiffness), K′ for a viscoelastic one, the device's initial stiffness for metallic and
    friction ones; the brace member is designed for the analysis forces and the device force
    comes from the schedule.
  - The damped response spectrum is divided by B1D/B(ξ) from 0.8 T1 up, as the isolation
    spectrum (0.8 TD) already is.
  - The fundamental mode of the damper design is φ = h/hr (Ch 18 permits it for the ELF), and
    the devices are designed at 1.5 × the design-earthquake response for the MCER.
  - The damped base shear is used even where it is above the fixed-base one (with a note).
  - Dampers together with isolators: the isolation design sets the earthquake forces.
  - EN 1998-1: the superstructure drift limit of an isolated building is taken as
    0.005 h / ν with ν = 0.5 (Sec 4.4.3.2), and the importance factor γI is not applied by the
    isolation design (to check).
- **Packs that extend the US pack** (Saudi, Pakistan, Philippines, Indonesia, Myanmar, Canada,
  Mexico) now inherit ASCE 7-22 Ch 17 and Ch 18 in place of the default pack's isolation table
  they inherited before; the National Annex packs inherit EN 1998-1 Section 10.
- **Placeholder removed:** "Viscous Dampers" (fem.dampers). Placement uses the existing tools:
  isolators go under the columns of isolator types that stand on supports (the isolation
  plane), dampers in the braces of damper types.
- **Where:** `fem/isolation.py`, `fem/isolation_single_level.py`, `fem/dampers.py`,
  `fem/device_response.py`, `codes/damper_tables.py`, `library/objects.py`
  (`SeismicIsolator`, `SupplementalDamper`), the packs' `VERIFY.md` (P6 sections).

## 2026-11-05: online hazard lookup by site coordinates (alpha 9 track C22)

- **Opt-in and asked every time (owner).** A global setting "Allow online hazard lookups"
  (`saengine.hazard.allowOnlineLookups`, default off, application scope so a project cannot turn
  it on) and a confirmation before every request that names the service, its host and every
  query value. The Python backend refuses to send without that consent.
- **Only the coordinates and the code parameters leave the machine (owner).** A pack's query
  templates may use only `{latitude}`, `{longitude}`, `{riskCategory}` and `{siteClass}`; the
  endpoint must be https and redirects are followed only on the same host (upgraded to https).
  The request is a plain GET by urllib with a user agent naming SAEngine, no cookies.
- **The pack names the service (code independence).** The `hazardLookup` table holds each
  provider as data (endpoint, query, the pack's risk categories and site classes in the service's
  words, where each value is in the JSON answer and its unit, regions, terms). The engine has no
  service of its own. Only the US pack names one (USGS Seismic Design Web Services, ASCE 7-22).
  A pack without a provider shows "Enter values by hand". SAEngine practice: a provider is used
  only by the pack whose own data file names it (`inheritable: false` by default), so packs that
  extend the US pack for another country never send their sites to USGS.
- **SAEngine practice: project overrides cannot change a provider.** The lookup reads the pack
  without the project's Code Values overrides, so a project file cannot redirect the request.
- **Values stay the engineer's.** The values are shown before they are applied, go into the
  existing fields (`site.spectral` etc.) and stay editable. The project keeps the source
  (`site.hazardSource`: service, date, query, values) so reopening needs no network. The report's
  design basis names the source and which values were edited since. Offline, a timeout or a failed
  answer shows a message and changes nothing.
- **Not covered.** Wind and snow lookups (the ASCE Hazard Tool's API needs a subscription key),
  Canada (the NRCan seismic hazard calculator has no documented public API), New Zealand and the
  other packs: values by hand.
## 2026-11-05: Russia / CIS SP pack (alpha 9 track C25)

Pack `russia-sp` (extends `bnbc2020`): SP 20.13330.2016, SP 14.13330.2018, SP 63.13330.2018,
SP 16.13330.2017, SP 22.13330.2016, values entered from knowledge of the codes (no text on this
PC); `VERIFY.md` lists every value with its clause, most marked uncertain. Nothing was run this
week (owner, 2026-11-05): the tests are written, not run.

- **SAEngine practice, limit state groups.** The first group is the strength combinations with
  the design values; the second the service combinations with γf 1. One γf on D (1.1) for the
  self-weight and the superimposed dead load (the site-made layers' 1.3 not told apart: the
  combinations have one D factor); live γf 1.3 at every intensity (1.2 from 2.0 kN/m²: on the
  safe side). The seismic combination's factors 0.9 / 0.5 are on the design values; the floor
  live load is all short-term (its long-term share at 0.8 not split).
- **SAEngine practice, earthquake.** The map of the OSR-2015 set by the occupancy category: A for
  I-II, B for III, C for IV (the client's choice in SP 14 4.3); 6 points take A = 0.05 g and 10
  points 0.8 g (outside SP 14). The soil category's one-point shift is the soil factor S 0.5 / 1 /
  2 on the design spectrum (C24's `soilFactors`; A doubles per point); category IV takes III with the site-specific study warning. R = 1/K1
  with Kψ 1 and Cd = R; Ω0 1; the storey drift limits 2 % / 1.5 % / 1 % (SP 14 gives none); the
  SP 14 Section 6 detailing as SAEngine's intermediate level at 8 and 9 points; the accidental
  eccentricity 0.1; orthogonal 100 % + 30 %; no scaling of the modal results to the static ones.
- **SAEngine practice, wind.** ze by the windward width (the EN 1991-1-4 split); the pulsation
  with ν of Table 11.6 at ρ = b, χ = h; ξ = 1 for flexible buildings; G 1.7 for the parent's
  roof and wall pressures.
- **SAEngine practice, concrete.** γb1 0.9 on Rb and Rbt in every combination; the rectangular
  block is the default section method and the nonlinear deformation model's diagrams are a
  project override (`concreteMethods.ultimate.stressBlock` bilinear / trilinear); shear Q at the
  support face; the columns' shear by τc = 0.5 × 0.9 Rbt with the ties on d (no φn); ψs = 1 in
  the crack width; the deflection by the generic long-term stiffness B = Bs/θ in place of SP 63's
  curvature, with the SP 20 Table E.1 limits at the stricter end of each step; durability limits
  of the cover conditions not from SP 63.
- **SAEngine practice, steel and soil.** γc 1.0; cx 1.05; φb by the parent's χLT; the SP 22
  design resistance R for the soil report's founding layer with γc1 1.25 (sands) / 1.1 (clays),
  γc2 1.0, k 1.1, qa = R - σv; the deeper layers keep the parent's check.
- **Generic mechanisms (no existing pack sets them):** `locations.*.mapZones` with
  `seismic.hazardMaps`, `seismic.lateralForce.correctionMethod` "linearMode", `wind.referenceHeight`
  "proportions", `wind.pulsation` with `exposures.*.pulsationZeta`,
  `concreteMethods.ultimate.designStrengths`, `cubePrefix`, `stressBlock` "bilinear" /
  "trilinear", `concreteMethods.shear.inclinedSection` with `stirrupYieldShare` /
  `stirrupYieldMax`, `foundations.shallow.designResistance` (method `frictionAngleFactors`).

## 2026-11-05: assessment and retrofit of existing buildings (alpha 9 track P4)

- **What was built.** A project marks itself as an existing building with
  `analysis.existingBuilding` (Project Settings, Analysis model, Existing building): the knowledge
  level (κ, CF, overridable), the material tests (cores, tensile tests; rebound and pulse velocity
  only with a calibration to cores), the members' condition (bar area lost to corrosion, weak
  concrete), the procedure (linear or the pushover's hinges), the model state (as built or
  retrofitted), the retrofit measures (RC jackets, FRP wraps and laminates, added members) and the
  screening checklist answers. The pack's new `existing` table gives every value and picks the
  methods by id (`linear.method` `mFactor` / `chordRotation`, `shear.method` `columnDuctility` /
  `cyclicDegradation`, `frp.method` `aci440` / `en1998`). The US pack has ASCE 41-17 / ACI
  440.2R-17, the Eurocodes pack EN 1998-3; nothing changes for a project without
  `existingBuilding` (bnbc2020 results are unchanged).
- **BNBC basis.** BNBC 2020 asks for the structural analysis of an existing building (Part 10 Sec
  1.3.2) and names strengthening and retrofitting (Part 7 Sec 5.10.3-5.10.4) without a method:
  the bnbc2020 pack's `existing` table is SAEngine practice on the ASCE 41 basis, and the
  results say so.
- **SAEngine practice (no code gives it):**
  - The analysis model of an existing building takes the materials at the pack's analysis
    strengths (ASCE 41: expected; EN 1998-3: mean), the corroded members' bars with their lost
    area (diameters × √(1 - loss)), and, retrofitted, the jacketed members enlarged with the
    jacket's bars and ties (their own object types `<type>.eb-<tags>`). In the pushover's fibre
    sections the old bars of a jacketed member lie with the jacket's at its cover; the member
    checks place them where they are. As built, the added members are left out of the model;
    they are designed as new members, not assessed.
  - Linear procedure: the run's seismic forces (the design forces with R and I) are made the
    hazard's unreduced forces by × R/I × the hazard's spectrum scale (× C1·C2·Cm for
    deformation-controlled actions); demands from G± ± E per direction; columns' two-way
    flexure combined linearly (exponent 1); the displacement ductility of the column shear's k
    is the flexural demand over κ·MCE; a column whose shear strength is below the shear at its
    flexural strength takes m = 1. The section strength is the strain compatibility of the
    pack's stress block with the strengths of the use (no φ, no partial factors other than the
    pack's brittle divisors).
  - EN 1998-3 linear: the chord rotation demand is (M/My)·θy with My and θy of the analysis
    strengths, LV = L/2, φy = 2.1 εy/h; θum with the deformation strengths (mean/CF).
  - Before and after: each run keeps its assessment per model state (`08 FEM/existing-<state>.
    json`); the other state's ratio is its own run's when it has been run, else this run's
    demands with the other state's capacities (shown as such).
  - Jackets of every pack take the EN 1998-3 A.4.2.2 monolithic factors; an FRP confinement wrap
    with fl/f'c at least the pack's minimum makes the member conforming in the m and hinge
    tables; the FRP force of a flexural laminate is reduced by ψf and the substrate's initial
    strain is taken as 0.
- **Not built (placeholders kept or added):** masonry buildings (planned page "Assessment of
  Existing Masonry Buildings"), steel members' minor-axis bending and shear, walls in the linear
  procedure (they are assessed by the nonlinear procedure's fibre walls), base isolation as a
  retrofit (B37's isolators are designed as for a new building; P6 later).

## 2026-11-05: group 2 country packs (alpha 9 track C24)

Packs `korea-kds`, `iran-2800`, `peru-e030`, `chile-nch` and `brazil-nbr` (extend
`aci318-asce7-22`), `egypt-ecp` (extends `bs8110`) and `southafrica-sans` (extends
`eurocodes`). The values were entered from knowledge of the codes (no text on this PC); each
pack's `VERIFY.md` lists them with their clauses and marks the uncertain ones. Not tested yet
(owner, 2026-11-05: no test runs this week).

- **SAEngine practice, parents.** Egypt extends `bs8110`: ECP 203 designs on the cube strength
  with 0.67 fcu/γc as BS 8110 does, and ECP 201's EN 1998-1 type spectrum is a data choice (the
  `behaviourFactor` method), not a parent. South Africa extends `eurocodes` (SANS 10160 is an
  EN 1990 / 1991 / 1998 code); SANS 10100-1 (BS 8110 type) is represented by αcc 0.85 on the
  parent's EN 1992-1-1 methods and SANS 10162-1 (CSA S16 type) is not covered (the parent's
  EN 1993-1-1 applies). Brazil extends the US pack (NBR 15421 is the ASCE 7 form, NBR 8800 AISC
  type) with NBR 6118 by the generic partial-factor ultimate and tabulated shear methods.
- **SAEngine practice, Korea.** KDS's S (zone factor × 2.0) is entered as SS = 2.5 S and
  S1 = S so the base pack's Fa SS × 2/3 gives KDS's SDS; KDS's 10-minute V0 × 1.43 is the
  3-second gust of the base pack's ASCE 7 wind method.
- **SAEngine practice, Iran.** B = B1 N depends on the zone's group: each soil type has a site
  class for zones 1-2 (I-IV) and one for zones 3-4 (IL-IVL); the project picks the one of its
  zone. The drift limit is 0.020 for all periods (0.025 below 0.7 s as a Code Value).
- **SAEngine practice, Chile.** R* is taken at each ordinate's period (NCh 433 takes it at T*:
  equal at the fundamental period, larger ordinates for the higher modes); NCh 433's own static
  coefficient (2.75 S A0 (T'/T*)^n / gR) is not built, the static method takes the spectrum at
  the period; Cmin and Cmax bound every ordinate; Cmax of Table 6.4 (by R) is written by the R0
  of the systems with that R. DS 60's boundary element trigger (δu/hw ≥ 0.007, no 1.5 factor)
  replaces ACI 318-19's.
- **SAEngine practice, Peru.** Buildings are taken as regular (Ia = Ip = 1); Ω0 (not in E.030)
  takes the ASCE 7 values of the same systems.
- **SAEngine practice, Brazil.** NBR 15421's category A zones are analysed as category B; the
  categories are read by SDS and SD1 bands that match ag on class B; Cup by SD1. NBR 6123 is
  built for class B buildings; the wall coefficients +0.8 / leeward stand for the drag
  coefficient Ca. Model I shear's 0.9 d lever and fywd ≤ 435 MPa are folded into the stirrup
  fy cap of 450 MPa.
- **SAEngine practice, Egypt.** ECP 203's shear with stirrups counts half of qcu, so the
  tabulated τc is 0.12 √(fcu/γc) for every member (members without stirrups on the safe side).
  The Type 2 spectrum (longer corner periods) is the default; the wind is the parent's BS 6399-2
  method with placeholder speeds.
- **Placeholders.** The towns' wind speeds of Iran, Peru, Chile and Egypt are placeholders (their
  wind codes are not built); every pack names this in its README.
- **Generic mechanisms (no existing pack sets them):** a shape branch's divisor `d`, `m` and
  negative powers; `shapeFactors.ductilityForm` "periodRatio" with `ratioShare`,
  `ratioPeriods`; `shapeFactors.soilFactors`, `leastSoilShare`, `capByDuctility`.

## 2026-11-05: Australia and New Zealand second remainder (alpha 9 track C18c)

`australia-as` 0.3 and `newzealand-nzs` 0.3 (VERIFY C18c-1 to C18c-60 and C18c-1 to C18c-29).
New generic methods by id: `concreteMethods.slenderness` `bucklingMagnifier`,
`concreteMethods.anchorage` `developmentFactors`, `steelLimitState.connections`
`capacityFactorJoints`. Existing methods widened by optional fields whose defaults keep every
other pack's results: `strutAndTie` (`basis`, `phiStrut`, `phiTie`, `concreteShare`,
`bottleStrut`, `nuDivisor` optional), `ductileDetailing` (`basis`, `levels`, columns `ashForm`,
`ashAxial`, `confinedByAxial`, `capacityShear`, joints `stressLimit`, `reinforcementShare`,
walls `shearAmplification`, `boundaryAsh`, `boundaryLength`, `couplingPhi`, beams
`hoopZoneOnDepth`), `concrete.walls.spacingThickness` (3 t by default).

- **Capacity-factor basis (SAEngine practice).** The C5c strut-and-tie and C8 ductile detailing
  methods were written on fcd and fyd. Under a pack without partial factors they now run on f'c
  and fy with the code's φ (`basis: "capacityFactor"`), so AS 3600 and NZS 3101 reuse them.
- **Detailing levels.** AS 3600 Appendix C rows apply to μ 3 (intermediate) frames; μ 2 frames are
  designed by the members' general rules only; μ 4 frames are detailed as μ 3 (AS 3600 leaves
  them to a special study). NZS 3101: ductile and limited ductile frames; nominally ductile by the
  general rules. Design Reinforcement sizes the hoops by the method's own (strictest) group.
- **NZS 3101 Appendix D reduced to factors (SAEngine practice).** The column capacity design is
  the strong column ratio ΣMn,col >= ω λo/φ ΣMn,beam with one ω per level (1.3 ductile, 1.0
  limited) and the columns' capacity shear 1.25 (or 1.0) (Mn,top + Mn,bottom)/clear; the wall's
  overstrength φo,w is taken as λo/φ = 1.47, not computed; the horizontal joint hoops carry
  0.5 Vjh (not the code's Ajh expression). All flagged in VERIFY.
- **Slender columns without bars.** Nc takes 0.4 Ec Ig where no bars are known to find Mub.
- **AS 4100 bolt grades.** A307 is taken as 4.6; A325, A490 and 10.9 as 8.8 (on the safe side).
- **Design Reinforcement torsion links.** Under the AS 3600 8.3 method the closed links carry T*
  on top of the shear's links, at most min(0.12 ut, 300 mm) apart.
- Nothing was run (owner rule of 2026-11-05): the tests are written, the test pass is next week.

## 2026-11-05: Australia and New Zealand remainder (alpha 9 track C18b)

`australia-as` 0.2 and `newzealand-nzs` 0.2 (VERIFY C18b-1 to C18b-42 and C18b-1 to C18b-4).
New generic methods, chosen by id (no other pack sets them, so their results are unchanged):
`concreteMethods.torsion` `torsionInteraction`, `concreteMethods.punching` `momentTransfer`,
`concreteMethods.simplifiedWalls` `simplifiedWall`, `wind.speedFactors.hillShape`, the
`dynamicResponse` form of `wind.speedFactors.gustFactor`, and `seismic.designCategories`
`byHeight`, `simpleStatic`, `dynamicRequired`.

- **SAEngine practice, torsion (AS 3600 8.3).** The slab cast with the beam is not counted in Jt
  (on the safe side); the closed links carry the shear beyond φVuc and the torsion by a linear
  sharing, (V* - φVuc)/φVus + T*/φTus <= 1; the longitudinal ΔAl is reported, not deducted from
  the flexural capacity; every torsion is designed for the full T* (no compatibility torsion
  reduction). Design Reinforcement does not add torsion links under this method: a beam short
  of them fails its row.
- **SAEngine practice, punching (AS 3600 9.3).** The moment term is written on stresses,
  V*/(u d) + M*v/(8 a d²) <= φ fcv, both directions' moments added at once; closed fitments and
  shearheads are not laid out (the slab fails with the note to thicken it, add a drop panel or
  enlarge the column).
- **SAEngine practice, walls (AS 3600 11.5, 11.6).** The simplified axial row is informative
  (the P-M3-M2 surface governs, as for the parent's empirical method); Hwe = 0.75 Hw where
  SAEngine's bracing factor says braced and restrained at both ends. The walls' minimum steel and
  detailing rows stay the parent's.
- **SAEngine practice, wind.** Mh's steep form (H/(2Lu) >= 0.45) is taken at every height, not
  only in the separation zone (on the safe side); an escarpment's downwind L2 = 10 L1 applies
  where the topography says downwind; Mlee and the elevation term are 1. Cdyn is one value at
  the roof applied to the design pressure of every level, with ζ = 0.05 unless the project gives
  the damping.
- **SAEngine practice, earthquake design category.** The EDC by height (IL1 I; IL2 to 12 m I,
  to 50 m II, above III; IL3 to 50 m II, above III; IL4 to 12 m II, above III) is used where the
  analysis knows hn; the design checks and Project Settings keep the zone rows (their detailing
  is "ordinary" for every EDC, so nothing in the design changes). The kp Z and site class
  columns of AS 1170.4 Table 2.1 are not entered. EDC I takes Fi = 0.1 Wi at every level; EDC
  III gets a note that the dynamic analysis is required.
- **Clauses.** A `designClauses` group a pack gives is given whole; a key without a
  counterpart in the pack's code is empty, so the row names the code without a clause, never
  the parent's number. The NZ pack gives its own groups (NZS 3101 numbers) so the AS 3600 ones
  are not inherited.
- **Not covered (stated in the READMEs).** AS 3600 10.4 slender columns, Clause 14 / Appendix C
  seismic detailing, 13.1-13.2 anchorage and laps, Chapters 7 and 12 strut-and-tie; NZS 3101
  Appendix D capacity design, 11.4 ductile walls, coupling beams, Chapter 15 joints; NZS 3404
  Section 12; AS 4100 Chapter 9 connections; AS 3700 masonry, AS 1720.1 and NZS 3603 timber
  (they do not fit SAEngine's engines in this version). The bar schedule stays BS 8666 (no
  separate AS/NZS shape code standard).

## 2026-11-05: Japan pack (alpha 9 track C19)

- **What was built.** `japan-bsl` (BSL Enforcement Order Art. 82-91, Notifications 1454, 1455,
  1792, 1793, AIJ RC and steel standards) extending `aci318-asce7-22`, README and `VERIFY.md`
  (81 entries). No code text was available: every value is from knowledge and listed to check.
- **Generic mechanisms (unset in the existing packs: their results are unchanged):** the design
  spectrum method `standardShearCoefficient`, the distribution `shearCoefficientAi`, the seismic
  weight by use (`liveWeight` byUse, `seismicLive`), the live load method `frameValue`
  (`frameLive`), the wind gust by height per exposure, the tables `allowableStress` and
  `horizontalCapacity` (new, not in the default pack).
- **SAEngine practice (not the law's), each overridable under Code Values:** the bars are sized by
  the parent's strength method under sizing combinations (long-term × 1.5, short-term × 1.0); the
  law's check is the allowable stress rows. Qu is read at a storey drift of 1/100 (or the largest
  shear before it) of a pushover with the Ai pattern. One Ds for the building from its worst
  member rank (FD without design ranks). Storey stiffness for Re by 12 E I / h³ of the columns and
  the walls' in-plane stiffness with the beams rigid; the weights' centre that of the masses at
  and above the storey. βu by system (frames 0, frame-walls 0.5, walls 1.0, braced 0.8).
  R = Cd = 1, Ω0 = 2.0; seismic design categories C/D and ordinary detailing for the parent's
  modules; W of uses without the law's seismic value at 50 %. The heavy-snow rows are formed
  wherever a snow case exists.
- **Fixed in passing.** `live_reduction.reduced` dropped the combinations formed after the live
  parts (fewer parts than forces) and the slenderness check then failed; they now keep their
  forces unreduced. It only showed with a live factor below 1 on columns.
- **Not done.** Bar names in SI (the engine prints pack bar names only in US units), the column
  live reduction by floors (Art. 85(2)), the braces' ranks, per-storey Ds, route 2 area ratios.

## 2026-11-05: nonlinear time history in design, record scaling and spectral matching (alpha 9 track P5)

- **What was built.** The B36 nonlinear time history now reads everything that differs between
  codes from the pack: a procedure's own least number of records, period range, ratios and a
  factor on its target spectrum (`seismic.timeHistory.targets.<procedure>`), the spectrum of a
  pair (`pairCombination`: SRSS, maximum-direction RotD100, or each component), a pair's range
  from the shorter to the longer period (`periodBasis: "bounds"`), spectral matching
  (`matching`, method `frequencyDomain`) with its own criterion (`matchedRatio`), how many
  unacceptable responses a suite may have by category, the damping model (Rayleigh or first
  mode), the member acceptance by P3's hinges (`acceptance.method: "hingeRotation"`, read from
  each record) and force-controlled actions (`forceControlled`). The US pack gets ASCE 7-22
  Ch 16 values, the Eurocodes pack EN 1998-1 values; BNBC keeps its rules and results.
- **SAEngine practice (no code gives it):**
  - Matched records are matched component by component to the pair's criterion times 1/√2
    (SRSS) or 1 (maximum direction, each component): the maximum-direction spectrum is never
    below a component's, so this meets the criterion when matching is exact. A matched suite
    that still falls short is lifted by one factor (never scaled down).
  - Matching range 0.8 × the lower to 1.25 × the upper bound of the period range, tolerance
    10 %, 20 iterations, the record first fitted by one amplitude factor; baseline: the best
    t² + t³ fit of the displacement taken off, then a line that brings velocity and
    displacement to zero at the end.
  - Rayleigh damping at T1 and 0.2 T1 (`RAYLEIGH_SECOND_SHARE`) where the pack gives no
    second period; the US pack's 2.5 % follows the commentary of ASCE 7 Ch 16.
  - Hinges over a record: each hinge's parameters at the step of its largest chord rotation,
    its demand the peak over the record; the end sections' fibre strains are rebuilt from the
    section deformations recorded at every step (the signs fitted to the recorded peaks).
  - Force-controlled actions: the column compression is taken as critical and the shear of
    beams and columns as ordinary; the strength is the member design's design strength (the
    safe side of the expected strength ASCE 7 allows); walls are not checked.
  - The Eurocodes pack checks the EN 1998-3 hinges at Significant Damage (EN 1998-1 gives no
    member deformation criteria for a new building).
- **Not built (placeholder "Record Search and Wavelet Matching"):** searching open record
  databases and time-domain wavelet matching. No third-party records are bundled.
- **Packs that extend the US or the Eurocodes pack:** the National Annex packs on the
  Eurocodes inherit its rules; the packs on the US pack (Saudi, Pakistan, Philippines,
  Indonesia, Myanmar, Canada, Mexico) replace its seismic table, so they show the time history
  procedures as not covered until they give their own `seismic.timeHistory`. IS 1893 (the IS
  pack) likewise gives none.
- **Where:** `fem/records.py`, `fem/spectral_matching.py`, `fem/nonlinear_history.py`,
  `fem/hinges.py` (P5 section), `fem/nonlinear.py` (`history_model`), the packs' `VERIFY.md`.

## 2026-11-05: China pack remainder (alpha 9 track C20b)

The rest of `china-gb`: GB 50010 torsion, punching, cracks, deflection, cover, anchorage, member
steel, slender columns and walls; the seismic grade with γRE in the member design; δn and the
vertical earthquake; GB 50017 bolts and welds and the seismic steel by grade; GB 50007 fa and
the ψs settlement. Every method is generic and picked by id (unset in every other pack: the
default pack's results do not change); `VERIFY.md` rows C20b-1 to C20b-96 list the values.
Nothing was run (owner, 2026-11-05); the tests are written.

- **SAEngine practice, γRE.** S <= R / γRE is applied as γRE × the forces of the earthquake
  combinations (by force component: bending 0.75 beams / 0.80 columns / 0.85 walls, shear and
  torsion 0.85, steel 0.75 strength / 0.80 stability), before the member checks, so Design
  Reinforcement sizes from the same forces. Columns take 0.80 at every μN (0.75 below 0.15 not
  used: on the safe side).
- **SAEngine practice, the grade's force factors.** The earthquake part of the forces (the
  combination's lateral cases) is amplified: columns' moments × ηc, their shears × ηc ηvc,
  beams' shears × ηvb, walls' in-plane shears × ηvw, on every storey and column end (the code's
  exemptions of the top storey and μN < 0.15 and its strengthened-region limits not taken: on
  the safe side; the corner columns' 1.1 and the bottom sections' factor not added: VERIFY U).
  The grade comes from the system, the model's height and the zone (C20's `seismicGrades`).
- **SAEngine practice, deflection and cracks.** The deflection under Mq = D + ψq L (ψq 0.4) is
  the analysis's scaled from its E I to B = Bs/θ (γf' = 0); the crack width under the same Mq.
- **SAEngine practice, laps and anchorage.** 25 % of the bars lapped at one section for beams,
  50 % for columns; one largest unlapped bar size (25 mm).
- **SAEngine practice, slender columns.** lc is the clear height; the sway P-Δ is the analysis's
  (a second-order run) as in the other tabulated packs.
- **SAEngine practice, GB 50007.** The qa of Project Settings > Foundation (no soil report) is
  read as fak and corrected for b and d with the clay row and γ = 18 kN/m³ (Code Values); the
  soil report's own qa is unchanged. The settlement takes Es = 1.35 E of the log and the ψs
  column at p0 >= fak (on the safe side).
- **SAEngine practice, the vertical earthquake.** The share of the gravity load by zone (5.3.3)
  goes on the dead load of the response spectrum combinations with γEv 0.5, on every member,
  when the vertical component is on; 5.3.1's FEvk of 9-degree tall buildings is not computed.
- **Where:** `design/seismic_grades.py`, `design/plastic_torsion.py`,
  `design/tension_stiffening.py`, `design/end_moment_magnifier.py`,
  `design/shear_span_walls.py`, `soil/characteristic_bearing.py`, the hooks in
  `design/check.py`, `design/walls.py`, `design/member_limits.py`, `design/tabulated_shear.py`,
  `design/steel/limit_state.py`, `fem/loads.py`, `fem/seismic_design.py`, `soil/settlement.py`,
  `substructure/shallow.py`; the pack's `README.md` and `VERIFY.md`.

## 2026-11-05: China pack (alpha 9 track C20)

Pack `china-gb` (extends `bnbc2020`), values entered from knowledge of the standards (no text on
this PC); `VERIFY.md` lists every value with its clause and marks the uncertain ones. Nothing was
run this week (owner, 2026-11-05): the tests are written, not run.

- **SAEngine practice, slots.** The intensities 6 (0.05g), 7 (0.10g), 7 (0.15g), 8 (0.20g),
  8 (0.30g), 9 (0.40g) sit in zone slots 1-6 with Z = αmax of the frequent earthquake; the
  fortification categories 丁 丙 乙 甲 in the slots I-IV with importance 1.0 (GB raises the
  measures, not the forces); the categories B (6), C (7), D (8, 9) carry the height limits and
  the required detailing level (the D limits are 8 (0.20g)'s; 8 (0.30g) and 9 are lower).
- **SAEngine practice, earthquake.** R = Ω0 = Cd = 1 (elastic design for the frequent
  earthquake, drift as computed: `driftAmplification` designForces). The design earthquake group
  is the town's (`locations.*.spectrumType`), group 3 for a custom site. λ is applied to the
  static base shear only and taken at its T1 < 3.5 s value; the response spectrum is not scaled
  to the static shear (`minimumScale` 0). The vertical earthquake and γRE are not applied.
- **SAEngine practice, two-level design.** The rare earthquake's elasto-plastic drift is the
  simplified method's on the response spectrum drift: ξy = 0.5 for every storey (a Code Value;
  the storeys' yield shears are not computed), checked at every 7-9 degree site; structures the
  simplified method does not cover take ηp 2.2 and should be checked by pushover or time history.
  The seismic grade and its factors (ηc, ηvc, ηvb, ηvw, μN, λv) are reported with the seismic
  design; the member design keeps the parent's detailing rules by the category's level.
- **SAEngine practice, materials.** γs = 1.15 for every bar grade (HRB400 then 348 MPa, not 360);
  steel γR = 1.164 for every grade (Q355's 355/305; Q235 then on the safe side); lateral-torsional
  buckling by χLT of curves b / c on Mcr in place of GB's φb.
- **Generic mechanisms (no existing pack sets them):** the spectrum method
  `influenceCoefficient`, `locations.*.spectrumType`, `seismic.driftLimits[].groups`,
  `seismic.rareDrift`, `seismic.seismicGrades`, `steelLimitState.compression.perry`.

## 2026-11-05: Turkey, Nepal and Sri Lanka packs (alpha 9 track C21)

Packs `turkey-tbdy` (extends `aci318-asce7-22`), `nepal-nbc` (extends `is-codes`) and
`srilanka` (extends `eurocodes`). The values were entered from knowledge of the codes (no text
on this PC); each pack's `VERIFY.md` lists them with their clauses and marks the uncertain ones.
Not tested yet (owner, 2026-11-05: no test runs this week).

- **SAEngine practice, TBDY categories.** The design earthquake categories DTS 1-4 (and 1a-4a)
  sit in the category slots D (DTS 1, 2), C (DTS 3) and B (DTS 4): the engine's detailing,
  height limit and joint rules read B/C/D. BKS 1-3 sit in the occupancy slots IV, III and I-II.
- **SAEngine practice, Ra(T).** `shortPeriodReduction` takes D from the system's Omega0 (the
  project's Ω0 override applies); callers that give no D (the New Building sizing, isolation,
  record targets, the worksheets' spectrum plot) keep Ra = R/I. The equivalent static
  coefficient is Sae(T)/Ra(T) of the full spectrum, its rising branch below TA included.
- **SAEngine practice, λ.** The TBDY drift ratio λ = Sae(DD-3)/Sae(DD-2) is site-specific:
  the pack's value is 1.0 (on the safe side); the project enters the site's ratio as the Code
  Value `seismic.driftServiceRatio.value`.
- **SAEngine practice, performance-based design.** The BYS 1 (tall building) requirement of TBDY
  3.4 / Bolum 13 is reported in the analysis notes with the procedures (linear DD-4, strength
  DD-2, nonlinear time history DD-1); SAEngine does not run them by itself. The pushover hazard
  levels DD-2 (LS) and DD-1 (CP, spectrum × 1.5 until the site's ratio is entered) check the
  base pack's ASCE 41 hinges, not the TBDY Bolum 5 strain limits.
- **SAEngine practice, TS 500.** Vc = 0.8 Vcr is a stress by grade in the tabulated shear method
  (no steel ratio term); ρmin of beams and the least stirrups are taken at C40 (safe up to C40);
  the least eccentricity 15 mm + 0.03 h as max(h/20, 25 mm). The areas TS 500 does not set here
  (torsion, deflection, cracking, cover, anchorage, slabs, footings) are the base pack's ACI 318.
- **SAEngine practice, Nepal.** NBC 105:2020 R = Rμ Ωu under the `shapeFactors` method (Sp = 1,
  kμ = R); Cd = Rμ with the displacement factor; one category (D) for the whole country; the SLS
  spectrum is not checked (the ULS drift governs for the usual Ωu / Ωs).
- **SAEngine practice, Sri Lanka wind.** The 1980 zone speeds (3-second gusts) are converted to
  the EN 1991-1-4 vb,0 by 1/1.53; seismic design is not covered.

## 2026-11-05: Australia and New Zealand packs (alpha 9 track C18)

Packs `australia-as` (extends `bnbc2020`) and `newzealand-nzs` (extends `australia-as`). The
values were entered from knowledge of the standards (no text on this PC); each pack's `VERIFY.md`
lists them with their clauses and marks the uncertain ones.

- **SAEngine practice, slots.** Importance levels IL1-IL4 sit in the category slots I-IV; the
  towns' Z values in zone slots 1-n (`zoneLabel` "Z = 0.08"); the earthquake design categories
  EDC I-III in the slots B, C, D. Every building is designed by the equivalent static method
  (and the modal method where chosen): the category table is the 12-50 m row for every height,
  so the EDC I simple static method (AS 1170.4 Section 5) and the EDC III rule over 50 m are not
  chosen automatically.
- **SAEngine practice, μ in R.** Under `shapeFactors` the system's R holds μ and Cd = μ/Sp (AU)
  or kdm μ/Sp with kdm 1.5 for all heights (NZ, on the safe side); Ω0 = 1.0 (no system
  overstrength factor in AS 1170.4 / NZS 1170.5). NZ's kμ is taken at each period of the modal
  spectrum (5.2.2 takes it at T1: larger Cd at short periods), T at least 0.4 s for kμ.
- **SAEngine practice, wind.** Md = 1.0, Ms = 1.0, Kc,e = 1.0 (Table 5.5 allows 0.8-0.9),
  Ka = 1.0, Mt as entered (the hill multiplier is not computed); VR / V500 by the 2011 regional
  formulas at V500 45 / 51 / 57 / 66 / 80 m/s; the serviceability wind 0.68 Wu ((37/45)², region
  A) in the service combinations.
- **SAEngine practice, concrete.** AS 3600 keeps the parent's axial cap 0.80 φ P0 in place of the
  0.05 D minimum eccentricity; the beam shear runs the simplified kv and θv (the general method's
  terms need M* at the section); Ec = 5000 √f'c (at or below Table 3.1.2). NZS 3101 vc takes
  kd = ka = kn = 1; the ductile detailing and Appendix D capacity design are the parent's rules
  (probable moments with 1.25, which is λo of 500E).
- **SAEngine practice, steel.** AS 4100 by the limit state module with γm0 = 1/0.9: λep as the
  plastic and compact limits, noncompact sections at Ze = Z, αm = the program's c1, the
  interaction by its conservative linear form, the shear buckling by the family's post-critical
  method in place of αv = (82/λw)².

## 2026-11-09

- **BNBC 2020 pack marked verified** (owner). Its `pack.json` carries `"verified": "2026-11-09"`, so the
  "values not yet verified" notice no longer shows for it; SAEngine-practice items stay labelled as such.
- **Bridges under BNBC: HL-93 traffic as SAEngine practice** (owner). BNBC carries no traffic
  loading and the RHD loading is not entered, so a pack without a traffic table uses SAEngine's
  HL-93-based data, named as such in every result (alpha 9 track L9).
- **Point clouds: LAZ and E57 are read** (owner). `lazrs` (MIT) decompresses LAZ scans and
  `pye57` (MIT, with libE57Format under BSL-1.0) reads E57 scans, every scan in its own pose, in
  metres. Both are dependencies of the backend and ship in the bundled Python. Before, these
  files were refused with a message (alpha 9 track L2).

## 2026-11-04: Canada and Mexico City packs (alpha 9 track C17)

- **What was built.** `canada-nbcc` (NBCC 2020 Part 4, CSA A23.3-19, CSA S16-19) and
  `mexico-ntc` (NTC-CDMX 2017 with the CFE wind manual), both extending `aci318-asce7-22`, each
  with README and `VERIFY.md` (89 and 42 entries). No code text was available: every value is
  from knowledge of the codes and listed for checking.
- **Generic mechanisms (any pack may use them; the existing packs do not set them, so their
  results are unchanged):** `seismic.designSpectrum.ordinates` under `mappedSpectral` (S(T) from
  the site's uniform hazard spectrum with a short-period plateau, V/W = S(T) Mv I/R with a least
  period by system group, an upper cap for Rd above a value and a higher mode table), the
  design spectrum method `ductilityOverstrength` (zone or site spectra a0, c, Ta, Tb, r or k; a
  / (Q' R)), `concreteMethods.shear` method `compressionField` (β and θ, φc and φs on each
  term), `steel.memberMethods.columnCurve` `powerCurve` and `lateralTorsional`
  `criticalMoment`, the towns' `spectrum`, `groundSnow`, `rainLoad` and `pressureFactor`,
  `snow.rainShare`, per-exposure `kzFactor` and `kzMinHeight` of the wind power law, and the
  systems' `Rd`, `Ro`, `higherModeGroup`.
- **SAEngine practice, Canada.** The towns' Sa(T) are the 2015 edition's site class C values as
  remembered, for four cities only, to be replaced with the 2020 values; other towns and site
  classes take the site's values from the NRCan calculator (the program says so). The higher
  mode factor Mv is not entered (Mv = 1, J = 1): the table must be entered before walls with
  long periods are designed. NBCC's importance categories are SAEngine's ids I-IV; the ranges of
  IE S(0.2) of the height limits are SAEngine's category letters B / C / D, High and
  Post-disaster one range up (on the safe side). Ω0 = Ro, Cd = Rd Ro. CSA A23.3 concrete runs on
  the partial-factor path (γc = 1/φc, γs = 1/φs, α1 and β1 by band, Pr,max with α1 of 60 MPa,
  c/d of grade 400); beams' shear by the simplified method (the design run has no Mf at the
  shear's station), columns', walls' shear, torsion, punching and Clause 21 detailing stay the
  parent's ACI 318-19. CSA O86 timber does not fit the timber engine in this version (the
  parent's NDS applies). The program's Cb stands for S16's ω2 (at most 2.5).
- **SAEngine practice, Mexico.** The 2004 zone spectra (Tabla 3.1) with Q' and no R are the
  default (the 2017 site-specific form with k and R applies where the project enters a site's
  SASID values); the regularity factor is a project value (1 regular). The accidental
  combinations take Wm in place of Wa (on the safe side) and the seismic weight 0.7 Wm. Z = 1.0
  marks the city as seismic; the zones are the site classes. Only Mexico City is a town; the
  barometric G of the CFE pressure is the town's pressure factor (the speed × √G). Group A's
  wind importance 1.21 is an SAEngine estimate.

## 2026-11-04: packs that adopt the US codes with local values (alpha 9 track C16)

- **What was built.** Four built-in packs that `extends: "aci318-asce7-22"`, start in SI units
  and set only what the local code changes: `saudi-sbc` (SBC 301-2018 in the ASCE 7-16 form,
  SBC 304 / 306), `pakistan-bcp` (BCP SP-2007, the UBC 1997 form), `philippines-nscp` (NSCP 2015
  Vol 1: Section 208 in the UBC 1997 form, Section 207 ASCE 7-10, Chapter 4 numbered 4xx) and
  `indonesia-sni` (SNI 1726:2019 in the ASCE 7-16 form, SNI 1727, 2847, 1729). Every value is in
  the pack's `VERIFY.md`; no code text was available. UAE / Gulf was left to track C23 (which
  built Qatar). Saudi Arabia and Indonesia use C23's `seismic.designSpectrum.siteCoefficients`
  (Fa, Fv) and the towns' `ss`, `s1`, `tl`.
- **Generic keys the packs needed (any pack may use them; the existing packs do not set them,
  so their results are unchanged):** a town's `zoneLabel` in `locations` (zones named 2A, 2B),
  and the design spectrum method `ubc97`
  (`seismic.designSpectrum.ubc97`: Ca, Cv by soil profile and Z, the near-source factors Na, Nv
  from Site > Mapped spectral values > seismic source type and distance, or Na, Nv entered; the
  least 0.8 Z Nv I W / R; Cu by Z). `ubc97` draws the same two-period spectrum and Cs bounds as
  `mappedSpectral` with 2.5 Ca for SDS and Cv for SD1 (UBC 1997 Figure 16-3 and Eqs 30-4 to 30-7
  are that form), and the zone of the town reads the category table.
- **SAEngine practice.** UBC-form codes have no Seismic Design Category: the zone takes the
  category whose detailing the code asks (Z below 0.15 B, 0.15-0.2 C, 0.3-0.4 D); Cd = 0.7 R
  (ΔM = 0.7 R ΔS); the drift limit 0.020 h for every period (the 0.025 h of T < 0.7 s not used);
  near-source factors 1.0 until the source is entered (the settings check warns in zone 4) and
  no Na ≤ 1.1 cap; SF takes SE's Ca, Cv (or Fa, Fv) with the site-specific warning. Occupancy
  category III takes I = 1.25 under BCP and NSCP (hazardous; special occupancies have 1.0 in the
  code). The town wind speeds of Saudi Arabia and Pakistan and Indonesia's 30 m/s are
  placeholders to replace; the bar sizes (SASO 8-32 mm, PNS 49 10-36 mm, SNI D10-D36, US #3-#11
  in Pakistan) and bar schedules (BS 8666 in Saudi Arabia, ACI 315 with 12 m stock elsewhere)
  are SAEngine's choice. SBC 304, NSCP Chapter 4 and SNI 2847 adopt ACI 318-14; the base pack's
  ACI 318-19 rules apply (the ACI 318-14 forms are not built in) and the clause references are
  named after the local code (NSCP renumbered 4xx).

## 2026-11-04: thin country packs (alpha 9 track C23)

- **What was built.** Four built-in packs that set only what their country changes:
  `myanmar-mnbc` (extends `aci318-asce7-22`), `bhutan` (extends `is-codes`), `qatar-qcs`
  (extends `bs8110`) and `hongkong-cop` (extends `bs8110`). Malaysia and Singapore were done as
  National Annex packs in C15. Every value is in the pack's `VERIFY.md`; no code text was
  available.
- **Generic keys (any pack may use them; the existing packs do not set them, so their results
  are unchanged):** `seismic.designSpectrum.siteCoefficients` (Fa, Fv by site class: SMS = Fa SS,
  SM1 = Fv S1 under `mappedSpectral` where SDS, SD1 and SMS, SM1 are not given), the towns'
  `ss`, `s1`, `tl` in `locations` (used where the project enters none),
  `wind.speedFactors.referencePressures` (a code's design pressure by height, the factors k1, k3,
  k4 on the pressure), `concreteMethods.ultimate.relations.<relation>.steps` and
  `ultimate.neutralAxisSteps` (values by strength band).
- **Which parent (SAEngine practice).** Qatar extends `bs8110`, not `eurocodes`: QCS 2014's
  structural references are the British Standards and its wind follows BS 6399-2. Hong Kong
  extends `bs8110`. No `uae-dubai` pack: Dubai practice is the US codes with the authority's own
  values, which SAEngine cannot state reliably; the US pack with entered values covers it.
- **SAEngine practice, Myanmar.** MNBC 2020 is read as the ASCE 7-05 form: 50-year basic wind
  speeds with 1.6W (strength) and 1.0W (allowable) combinations (on the safe side should MNBC use
  ultimate speeds), wind importance 0.87-1.15, Fa and Fv of ASCE 7-05 Tables 11.4-1 and 11.4-2,
  site classes A-F; the towns' SS and S1 are SAEngine estimates from the zone (SS ≈ 2.5 ×, S1 ≈
  1.0 × the zone's upper PGA) and the wind speeds readings by region: both must be replaced with
  MNBC's town values before design (VERIFY.md N2, N10). Metric bars and BS 8666 schedules.
- **SAEngine practice, Hong Kong.** The wind pressures are the 2004 edition's design pressures as
  known, to be replaced by the 2019 edition's (VERIFY.md H1); Sθ, the size and dynamic factor and
  the correlation factor are 1.0, the BS 6399 wall coefficients stand in for the building's force
  coefficient; εcu above C60 as steps at each band's top. Seismic not covered; steel stays BS
  5950-1.
- **SAEngine practice, Bhutan and Qatar.** Bhutan: zone IV in the west, V elsewhere, and Vb of
  the adjoining Indian regions (to be checked). Qatar: Vb = 25 m/s for every town, a town site 2
  km from the sea and the 'severe' exposure as defaults; no seismic loading; the temperature
  range is a project input (suggestion about 25 °C).

## 2026-11-04: National Annex packs on the Eurocodes (alpha 9 track C15)

- **What was built.** Four built-in packs that `extends: "eurocodes"` and set only Nationally
  Determined Parameters: `eurocodes-uk` (UK NAs to BS EN 1990-1998, bar schedules by BS 8666),
  `eurocodes-de` (DIN EN NAs, DIN 1054), `eurocodes-my` (MS EN NAs) and `eurocodes-sg` (SS EN
  NAs). Every value is in the pack's `VERIFY.md`; no annex text was available.
- **Generic keys the annexes needed (any pack may use them; the base packs do not set them, so
  BNBC 2020 and Eurocodes results are unchanged):** `concreteMethods.ultimate.alphaCCShear` (αcc
  of shear, torsion and punching), `concreteMethods.shear.nuMax` (a cap on ν1),
  `wind.altitude` (vb,0 = vb,map × (1 + factor A) with the new Site > Site altitude),
  `wind.peakVelocityPressure.profiles` / `simplified` / `useSimplified` (an annex's qp(z)
  profiles and stepped pressures in place of EN Eq 4.8), `wind.minimumLateral` (the least
  storey force as a share of the characteristic dead weight), `snow.groundLoad` (sk by the
  zone of the snow map, Site > Snow > Snow zone, and the site altitude) and
  `seismic.designCategories.zoneColumns` (which category column a zone id takes; zones not
  numbered 1, 2, ... used to index the wrong column or fail).
- **SAEngine practice.** UK: Eq NA.2a (calt = 1 + 0.001 A at every height, the conservative
  form), cdir = 1.0 in every direction, qp by EN Eq 4.8 (the NA's exposure factor figures not
  covered). DE: the NA.B profiles by default, the simplified stepped pressures by a Code Values
  override; on a hill qp × co²; DA2* applied as the A1 factors on the actions; zones 0-2
  ordinary detailing, zone 3 intermediate. SG: the 1.5 % least horizontal load applied to the
  characteristic wind storey forces (factored like the wind; on the safe side). MY: the town
  wind speeds are SAEngine's conversion of the MS 1553 gust speeds and the agR bands are read
  from memory: both must be checked before design (VERIFY.md M1, M2). A zone with agR 0 takes
  the first category column (no seismic detailing).

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
  the safe side (continuous floors engage more), to be refined (refined 2026-11-10: the bays
  the mode spreads over, see "Floor vibration modal mass over several bays"). Parking, storage and roofs have
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

## 2026-11-04: creep, shrinkage and column shortening by the pack's models (alpha 9 track P2)

The B25 column shortening (`fem/staged.py`, `fem/concrete_time.py`) now takes the creep and
shrinkage model the pack names by id in `concreteTime` and extends to walls, pre-sets and a forces
case. The bnbc2020 results are unchanged: its tabulated figures by superposition stay the B25
arithmetic, and every new part is behind a setting that is off by default.

- **Models by method id.** `aci209` (ACI 209R-92: US pack), `en1992AnnexB` (EN 1992-1-1 Annex B and
  3.1.4: Eurocodes and its National Annexes), `fibMC2010` (fib Model Code 2010: for a pack that
  wants it), and the BNBC `tabulatedCoefficient`/`tabulatedStrain` (bnbc2020; the IS pack enters
  IS 456 6.2.4-6.2.5's values in the same form). Strength in time `hyperbolic` (ACI 209R-92 Eq 2-1)
  or `exponential` (EN 1992-1-1 Eq 3.2).
- **SAEngine practice.** The modulus at an age comes from the pack's Ec rule at the strength
  reached (EN takes (fcm(t)/fcm)^0.3). The models' f'c/fck comes from each member's modulus by the
  pack's Ec rule unless the project enters it. IS 456 gives only ultimate values: their
  development in time follows ACI 209R-92's time-ratios, normalised to 30 years. ACI 209R-92
  gives no indoor/outdoor humidity: 50 % and 70 % are SAEngine defaults. χ = 0.8 where the pack
  gives no ageing coefficient.
- **Analysis method** (pack's `concreteTime.analysis`, overridable per project): `superposition`
  (B25, the default when a pack names none; bnbc2020) or `ageAdjusted` (the steel restrains the
  creep and shrinkage by the age-adjusted effective modulus; the US, Eurocodes and IS packs).
- **Construction sequence.** Casting days per level (else the floor cycle), the sustained live
  load at its own day after completion (else with the finishes), a final time in days (else the
  service life).
- **Walls and cores** (setting `walls`, off by default): the vertical shells of a wall per storey
  band, their axial force from the shells' nodal forces at the band's bottom and top. Beams that
  frame into a wall, and each column with its nearest wall, get the differential shortening.
- **Pre-set.** The shortening after casting of each level is the amount to cast it higher; the
  storey's extra length is its increase over the level below; relative to the line that shortens
  least.
- **The forces case CS** (setting `forcesCase`, off by default): while the model is derived its
  gravity cases are run once more for the columns' and walls' axial forces; each storey's creep
  and shrinkage after its floor is cast, per construction stage, is imposed on the model as
  fixed-end loads (the temperature case's method), staged like the dead load. The forces are
  relaxed by 1 / (1 + χ φ̄) (φ̄ the mean creep coefficient of the vertical members), so the case's
  deflections are of the relaxed forces too; the shortening itself is in the shortening tables.
  Its fixed-end forces are kept in `thermal.json` under `more`. The combinations take it from the
  pack's new `combinations.creepShrinkage` rows: bnbc2020 1.2D + 1.2CS + 1.6L + 0.5Lr (T includes
  creep and shrinkage, Sec 2.7.3.1 comb. 2), US 1.2D + 1.0CS + 1.6L + 0.5Lr (ASCE 7-22 2.3.4),
  Eurocodes 1.35G + 1.0CS + 1.5Q + 0.75S (γSH = 1.0, SAEngine practice for the creep part); IS and
  the legacy packs give none (analysed, not designed for).
- **Still planned:** construction loads and shoring of the partly built structure.

## 2026-11-04: staged excavation support and shoring (alpha 9 track P1)

The pack's new `excavationSupport` table holds the method ids and values; BNBC 2020 asks for
retained excavation sides and names sheet piles with tie-back anchors (Part 6 Sec 3.12, 3.16)
without a method, so in the default pack each item is **SAEngine practice where BNBC 2020 is
silent** (the 1.6H factor on the effects is BNBC's Sec 2.7.3.1). Every value is overridable in
Code Values. P7's limit-equilibrium embedment check stays as it is; P1 adds rows only when an
excavation's wall has a *wall type*, so existing projects keep their results.

- **Staged analysis (SAEngine practice).** The wall per metre on elastic-plastic springs (at
  rest to active behind, to passive in front, kh by Schmitt 1995 from the borehole's E or the
  pack's correlation), Coulomb pressures with δa = 2/3 φ' and δp = 1/3 φ' (Coulomb passive is
  taken no further than φ'/3, where it stays near the curved-surface values), hydrostatic water
  both sides (front dewatered to the dig level), adjoining footings as Boussinesq strip loads.
  Each stage is solved on the total deflection from the at-rest state (no unloading memory of
  the soil); a support placed in a stage starts from the wall's deflection at that moment, which
  is what carries the staging. A support that would pull drops out. The last stage takes P7's
  unplanned overdig. Bored and diaphragm walls use 0.7 × the uncracked EI.
- **Runs and factors.** The default pack: one characteristic run, effects × the pack's factor on
  earth pressure (1.6H); the Eurocodes pack: DA1 C1 (characteristic, × 1.35) and C2 (M2
  strengths, × 1.0), enveloped. Anchors' working loads come from the characteristic run.
- **Sections.** Sheet piles from a nominal per-metre table (JIS U types, generic Z types; VERIFY
  with the supplier), W fy / γM0 or φb Fy W (elastic); bored piles by the pack's P-M surface per
  reinforced pile (secant: every second pile unless all are reinforced), pile shear by the pile
  section rule (ACI packs) or the pack's one-way shear on bw = D, d = 0.8 D (others); diaphragm
  walls by the retaining walls' strip design both faces; soldier piles by the pack's steel
  member checks (braced at the supports) with timber lagging against the formwork rules'
  allowable stress, the soil below the dig acting on 3 × the flange width.
- **Supports.** Struts and rakers by the pack's steel member checks with the temperature force
  (ΔT 15 °C, half restrained, × 1.0) and the self weight (× 1.2); a strut's stiffness from half
  its length (symmetric pit). Walers continuous: M = w s²/10, V = 0.6 w s. Ground anchors by the
  pack's standard (BS 8081 in the default pack, EN 1997-1 8 / EN 1537 in the Eurocodes pack, PTI
  DC35.1 / FHWA GEC 4 in the US pack): tendon and bond factors, proof and lock-off loads, the
  free length beyond the active wedge from the dig level plus max(0.2 H, 1.5 m), the fixed length
  by the bond integrated along it.
- **Base.** Basal heave of a cohesive base by Bjerrum and Eide (needs the outline), piping at the
  toe by Harr's exit gradient Δh / (π d) (one wall in deep uniform soil; a flow net decides for
  layered ground), the wall's deflection reported against 0.5 % H.
- **Quantities and drawings.** The bill measures sheet piles (kg), bored and diaphragm walls'
  concrete and bars, soldier piles, lagging, struts (one per two spacings: a strut joins two
  walls), rakers, walers and anchors (number and drilled length, given or the pack's least);
  the drawings add a section of each typed wall with its stages, supports and water table.

## 2026-11-04: display units, SI or US customary (alpha 9 track C13)

- **Stored and computed in SI only** (owner, alpha 9 plan). Project Settings › Units (`units`)
  chooses how numbers are shown: `system` SI (default; the files, results and printouts exactly
  as before, and the setting is not written) or US customary, with per-quantity choices
  (lengths ft/in, member sizes in/ft, forces kip/lbf, stresses ksi/psi, pressures psf/ksf,
  moments kip·ft/kip·in, line loads kip/ft or plf, unit weights pcf/kcf, volumes ft³/yd³,
  speeds mph/ft/s). Switching converts nothing stored: the editors convert where a value is
  shown and typed, the backend where it prints. Factors from the exact definitions (NIST SP 811).
- **A pack suggests the units of a new project** (`units` in pack.json; the US pack:
  USCustomary). It applies only when a project is created with the pack (settings_for_pack of
  settings that chose none); changing the pack later keeps the project's choice. SAEngine practice.
- **The quantity of a field is its SI unit** as the descriptions already write it ("[mm]",
  "[kN/m²]"), so no field is tagged twice; a field without one can name its kind (`unitKind`).
  SAEngine practice.
- **Not converted, SAEngine practice:** temperatures (°C; an absolute temperature and a change
  convert differently and the fields do not say which), the expressions of the calculation
  worksheets (written in the code's SI form; their values, checks and units are converted, and
  the report says so), the costing (rates stay in the units of the schedule of rates), and the
  BOQ's cft, cement bags, litres and counts. (C13b below converts temperatures, the worksheets'
  expressions and the costing sheet.)
- **US bar names from the pack** (`concrete.barNames`): the US pack names its soft-metric bars
  #3–#11 (ASTM A615). Drawings and the bar bending schedule print dimensions in feet and inches
  to 1/8" (DXF architectural units, the geometry stays in mm) and levels in feet; the BBS's
  lengths in ft-in, totals in ft and masses in lb.

## 2026-11-04: display units, the remainder (alpha 9 track C13b)

What C13 left in SI, through the same two modules (`saengine.units`, `displayUnits.ts`); SI
projects print and show exactly as before. SAEngine practice throughout:

- **Temperatures convert** (owner: complete units). "°C" is a temperature (°F = 1.8 °C + 32);
  a field that holds a change names the kind `temperatureChange` (the thermal ΔTu and ΔTg, a
  timber service temperature above normal, the HVAC daily range: 1.8 °F per °C). In printed
  text a temperature is a change when "Δ", "±" or "by", "range", "rise", "drop", "change",
  "gradient" stand within the 20 characters before it, in its own clause.
- **Worksheet expressions with their values.** In US units every step whose expression is
  mathematics gets a "With values" form: the symbols replaced by the values as printed, juxtaposed
  factors joined by ×. An expression in the code's SI form (a root of a stress, a constant above
  100 or a small one of two or more digits, or marked by its kind, as ACI's 15 + 0.03h) keeps its
  SI form and gets the SI values, marked "(SI form)"; the report says so. Steps in words get none.
- **Sizes.** Member sizes in US units are written in inches to 1/8" (feet and inches when the
  project shows sizes in feet): the Members Table and plan labels (12"x20" style), the drawings'
  sizes without a unit ("300x500", "LAP 800", "150 THK"; a section designation such as
  "SHS 150x150x8" stays) and the "(mm)" columns of the drawings' tables (lengths and positions in
  feet and inches, bar size columns by the pack's bar names, a pile type's length in feet).
  "4Ø16" reads "4-#5" with a pack name.
- **Code values and placeholders.** Project Settings › Code Values shows and reads a value with
  its unit (and lists of numbers) in the display units; the greyed code values of the forms too.
- **Editors.** Substructure, soil, MEP (HVAC temperatures included), architecture, strut-and-tie
  and the walls, stairs and detailing panels show and read their numbers in the display units;
  the readouts written as SI text are converted where they are drawn (never the text a user
  types). The FEM charts' elevations and member stations are in feet, the P–M and Mx–My charts in
  kip and kip·ft.
- **Costing.** The quantity is shown in its display unit and the rate's units per unit as shown
  follow it, so every amount is the same; the BOQ editor shows a rate per display unit beside
  the schedule's rate. The embodied carbon's masses in lb with the factors per lb.
- **Still SI** (to do when wanted): the section designer's geometry and its charts, the drawings'
  MEP pipe sizes (Ø in mm), bar and mesh inputs typed as "12@150", the BOQ's cft, bags and litres,
  and SAEngine's chart tick numbers drawn in SVG by other editors' own code.

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
  display units (track C13) are to be applied. C13 applies them there (feet and inches in US
  customary units); the cutting lengths handed to the drawings stay in mm.

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

## Alpha 9 L11: office tools (2026-11-09)

- **4D programme (SAEngine practice).** Activities per level and zone (the building model's
  towers): substructure (excavation, piles, foundations, backfill), then per level the columns
  and walls below it, the floor at it, brick work once the floors two levels above are cast,
  finishes and MEP after the brick work. Durations are Σ quantity / (output per crew-day x
  crews), rounded up to whole working days, from the office's `10 BOQ/productivity.json` (a
  made-up sample ships, like the schedule of rates). The floor cycle and the casting days are
  those of Project Settings > time-dependent analysis (alpha 9 P2). The engineer's names,
  durations, start dates and own links are kept on regenerating. Dates by the critical path
  method on a working-day calendar (sample: Saturday to Thursday).
- **Cost-driven optimisation (SAEngine practice).** Per member group (object type): steel
  beams, columns and braces over every section family of the shape x every structural steel of
  03 Materials; RC rectangular beams over depth steps (default +0, +50, +100, +150 mm: a smaller
  depth needs deflection checked again) x every concrete. Passing is Design Reinforcement's own
  search (lightest passing bars, the steel proposal's checks), priced with the schedule of
  rates; branch and bound on the concrete and formwork (RC) or lightest-section (steel) lower
  bound. The forces are the last analysis's: applying an option needs the analysis and checks
  run again. RC columns and slabs are not optimised yet.
- **PDF takeoff and terrain in the bill.** Items measured on calibrated PDF pages
  (`10 BOQ/takeoff.json`) and the cut and fill of the building platform from the terrain
  (`01 Soil Report/terrain.json`) are added to the bill when it is computed, after the model's
  items of their group, coded `<group>.Dnn` and `E.Tnn` and marked `origin`; they are not in the
  materials take-off. The cut and fill are bank volumes of the TIN against the platform level
  (the building outline, the plot or a polygon, grown by a margin), with no side slopes or
  bulking; the survey datum defaults to the mean ground inside the platform at the platform
  level (stated in the notes).
- **Sun, daylight, road noise (indicative).** The sun by the NOAA equations, no refraction; the
  massing is the storeys from the slabs plus the neighbouring buildings given. The average
  daylight factor uses the BR 209 / CIBSE LG10 formula with SAEngine practice T = 0.68, M = 0.9,
  R = 0.5 and 20 % frame (editable in `06 BIM/environment.json`); no code target is applied.
  Road noise is the CRTN (1988) form without barriers or ground corrections, an orientation
  figure only.
- **MEP LOD 400.** Long-radius elbows 1.5 D (pipes), 1.0 W (rectangular ducts), 1.5 D (round
  ducts), 300 mm (trays); 6 m pipe stock, 1.5 m / 3 m duct sections, 3 m tray sections, 6 m
  spools, a hanger within 600 mm of each fitting and end; tray supports every 1.5 m (no code
  table): SAEngine practice, editable in `07 MEP/fabrication.json`. Pipe and duct support spacing
  and the fire main hanger load come from the pack's new `mepFabrication` table (bnbc2020: Part
  8 Table 8.5.14, Sec 2.11.4.8(b), Part 4 Sec 4.2.3.14 and 4.2.10.6).
- **Phasing and design options.** Phases live beside the building model (`06 BIM/phasing.json`,
  by element id) so they survive its regeneration; the first phase is what stands before the
  works (kept, not priced). Design options are saved versions (id, label, tag or branch)
  measured from their own files and priced with the current rates; results are compared only
  for the current files (results are not kept with versions).
- **Solver fixes may change default-pack results (2026-11-09).** "bnbc2020 results unchanged"
  guards code-independence work, not bug fixes in shared solvers. The GNIA arc-length phase now
  starts from at least the displacement-control step, so paths that used to run out of steps
  early now reach the limit load (a pin-ended column reaches 0.99 of the elastic critical
  factor); projects on any pack, bnbc2020 included, may report a higher, more accurate λu.
- **Floor vibration modal mass over several bays (2026-11-10).** The default modal mass of a
  continuous slab panel counts the bays its mode spreads over, as the design guides do, not
  0.25 x one bay's mass (which made ordinary continuous residential slabs fail). It stays
  SAEngine practice, marked so in the pack; a pack may set its own rule.
  Rule (`responseFactor.spread`): M = 0.25 x the bay's mass x (1 + 0.5 (nx - 1)) x (1 + 0.5
  (ny - 1)), n the bays continuous with the panel along its row of supports, ended by the
  slab's free edges and by a bay shorter than 0.7 x the panel's span, at most 4 each way;
  after SCI P354 Sec 7.3 (effective floor area over up to 4 bays, capped at the bays present)
  and AISC Design Guide 11 Ch 4 (a continuous panel's weight x 1.5 when the adjacent span is
  at least 0.7 x it). A single bay keeps the one-bay mass; the walk case (150 mm slab, 3 x 2
  bays of 6 x 5 m) goes from R 5.9-7.2 to 2.0-2.4.
- **Column-top anchorage is a design check with the pack's credits (2026-11-10).** The hook of
  top-storey column bars into the beams is checked once, for both design and drawings, and a
  hook that does not fit fails the member. The pack's reductions (confinement, side and end
  cover) apply when the detailing qualifies; the design proposal limits column bars so their
  top hooks fit the beams.
  How it qualifies (`development.hookQualify` of the pack): the column bars hook towards the
  core (corner bars along the diagonal), so the side cover is the clear distance from the bar
  to the face normal to the hook's plane and the tail cover what is left beyond the 90° tail;
  the column's end-zone ties go on through the joint. US pack (ACI 318-19 Table 25.4.3.2):
  ψo = 1.0 with side cover >= 2.5 in or 6 db, ψr = 1.0 with the hooked bars >= 6 db apart or
  Ath >= 0.4 Ahs (Ath: the tie sets within ldh, every leg; Ahs: all the column's bars, on the
  safe side), No. 11 and smaller. Default pack (Part 6 Sec 8.2.6.3(a)-(b)): x 0.7 with side
  cover >= 65 mm and tail cover >= 50 mm, x 0.8 with ties at <= 3 db along ldh, Ø36 and
  smaller. Eurocodes: α1 = 0.7 when cd = min(a/2, c1) > 3 φ (no confinement credit). A pack
  without these values takes no credit.
- **Crossing bottom bars at a joint: the secondary direction is raised (2026-11-11).** Where the
  bottom bars of beams from two directions meet at a column at the same level, the secondary
  direction's bottom bars pass one main bar diameter higher, as the secondary top bars already
  pass one diameter lower. The design uses the smaller effective depth of the raised bars for
  sagging at those beam ends, so the drawing and the check agree; a crossing the raise cannot
  resolve is still reported.
- **Brand: the SAEngine logo and its typography are the design system (2026-11-11).** The
  building mark (navy frame, blue meshed facade on a ground arc) with the "SAEngine" wordmark
  (bold "SA", regular "Engine") replaces every earlier mark: app and installer icons, splash
  and welcome pages, side bar, reports and drawings title blocks, documents and the website.
  Its colours and type set the UI's brand tokens.
- **Raised bottom bars stay straight along the whole beam (2026-11-11).** The secondary
  direction's raised bottom bars are not cranked up only at the beam ends: they stay straight
  in the second layer for the full length, as the dropped top bars do, and the beam is checked
  for sagging with the smaller effective depth all along. Cranking at the ends would win back
  only a few percent of midspan capacity (B5 of the Sample Frame: 121.5 to 126.4 kN·m), not
  at the column faces, where seismic sagging usually governs, and it would add bending work,
  longer bars and cranks in the congested zone beside the joint.
- **One way to start a project: New Project... (2026-11-11).** The start page, the File menu,
  the sidebar's ≡ menu and the command palette offer only *New Project...*; *New Building from
  Grid...* and *New Project from Template...* are gone as entries (their command ids stay and
  open the same wizard). The wizard asks the project (name, folder, *Start from*, design code,
  units), then the site and use, then the grid, storeys and structure, and creates it. *Start
  from* holds the grid (default), the building specifications and full templates of the
  installed packages, an empty building and a special structure; a full template skips the site
  and grid pages (it has its own model and settings), an empty project the grid page.
- **The chat and Sign In stay in the title bar (2026-11-11).** They are the start of the AI
  assistant, which is to work on the project itself (build and change the model, settings and
  design), not only answer questions. They are kept, not hidden.
- **The AI assistant is planned next (2026-11-11).** It moves up from the last item: the next
  round plans an assistant that builds and changes the project, with the engineer approving
  every change.
- **AI assistant scope, privacy and order (2026-11-11).** The UI/UX round comes first, then the
  AI assistant. The assistant uses VS Code's own chat (Copilot sign-in, or the engineer's own
  key for another provider) and must be able to do a whole project from one prompt, with the
  engineer approving its changes. Before any project data goes to an AI provider the engineer
  is asked in a clear dialog that says who receives it and that SAEngine never sells it.
  Sending usage or diagnostic data to the SAEngine developers is optional and off by default,
  and the app gets a bug report and feedback form.
- **Guardrails on input (2026-11-11).** Impossible or nonsense values (negative or zero sizes,
  out-of-range strengths, storeys or spans beyond physical sense) are blocked where they are
  entered, by the engineer or the assistant, with the reason in words. Deleting important data
  (a part, storeys, grids, members in bulk, results, versions) asks for confirmation; small
  edits do not.
- **Order after alpha 10 (2026-11-11):** UI/UX round, then live co-editing (Yjs over the
  office's own relay), then the shared editing actions with the missing terminal commands,
  then the AI assistant built on those actions.
- **Bug reports: public on GitHub, private by e-mail (2026-11-12).** The repository has issue
  templates (bug report, feature request, feedback) and Help > Report a Bug / Send Feedback opens
  a pre-filled GitHub issue. A report the engineer cannot make public (client, site or project
  details) goes by e-mail to publicrelations@thestudioofsadiq.tech: the form's Send As choice
  writes that e-mail, and the issue chooser and SECURITY.md name the address. Security problems
  go privately to the same address.
- **Live co-editing engine (2026-11-12).** Yjs 13.6.33, y-protocols 1.0.7, lib0 0.2.119 and
  y-websocket 3.1.0 (all MIT; owner approved the install). The engine runs in the main process
  and loads on first use; part files are merged object by object (lists of objects by `id`),
  last edit wins per field. The relay is SAEngine's own (y-websocket protocol on `ws`), hosted by
  any engineer's SAEngine on the office network or an office server; no outside service.
  @y/websocket-server was not used: it needs a pre-release Yjs 14.
- **A new project's default concrete (2026-11-12, #308).** The starting material library names
  its concrete: the first grade that meets both of the code pack's least f'c, for structural
  concrete and for members resisting earthquake forces (the default pack: 17 and 21 MPa, so
  C24.1, the grade the starting section types already use). A new project does not know its
  seismic system yet, so it starts on the safe side. Before, the first grade in the list (C20.7)
  was used and a fresh project failed the seismic minimum.
