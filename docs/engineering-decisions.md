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
