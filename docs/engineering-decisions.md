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
     L, when it counts apart from L) and the ETABS import's mass-source comparison. The default
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

## 2026-11-03

- **Partitions count in full in the seismic weight W** (Sec 2.5.7.3). See item 1 above.
- **The Sample Frame's wall W1 is 250 mm** (type W250, was W200). Every structural wall in
  Seismic Design Category D is a special wall, and at 200 mm W1 was too thin for its boundary
  elements and its spandrels (8.3.4.1(c), (d)).

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
