# Design code packs

SAEngine designs to **BNBC 2020** (the Bangladesh National Building Code) out of the box. A
*code pack* is how you make it design to the code of your own country or region instead: the
code's tables and factors (towns and their hazard, live loads, load combinations, seismic and
wind coefficients, φ factors, cover, bar sizes, detailing limits) live in a folder of plain
JSON files that you can copy, change, check and share, without changing SAEngine itself.

You do not need to be a programmer to write a pack. Most packs start from BNBC 2020 and change
only what differs in their region: a few towns, a wind speed, a combination factor.

- [Write your own country's pack](#write-your-own-countrys-pack)
- [What a pack is](#what-a-pack-is)
- [Start a pack](#start-a-pack)
- [The tables](#the-tables)
- [Inheritance: change only what differs](#inheritance-change-only-what-differs)
- [Data or formula? Hooks and trust](#data-or-formula-hooks-and-trust)
- [Check a pack](#check-a-pack)
- [Use and share a pack](#use-and-share-a-pack)
- [How to override a code value](#how-to-override-a-code-value)
- [The pack in the report](#the-pack-in-the-report)
- [Limits of this version](#limits-of-this-version)
- [Command reference](#command-reference)

## Write your own country's pack

This is the office's route from "our code is not in SAEngine" to a pack every engineer in the
office can choose in Project Settings. SAEngine has some 35 built-in packs (BNBC 2020, the US
codes, the Eurocodes and their National Annexes, the Indian Standards, and packs for most
countries in Asia, the Middle East, the Americas and Africa); start from the one closest to
your code, so you change the least.

**1. Choose the parent.** A pack *extends* another and changes only what differs. If your code
adopts ACI 318 / ASCE 7 with local values (as Saudi Arabia, Pakistan or the Philippines do),
extend `aci318-asce7-22`; for a National Annex, extend `eurocodes`; for a code derived from the
British Standards, `bs8110`; for Indian practice, `is-codes`; otherwise `bnbc2020`.

```console
> saengine codepack new xx-nbc --name "Example National Building Code 2026" --extends aci318-asce7-22 --edition "XNBC 2026" --country XX --dest .
```

The folder holds `pack.json`, one help-only file per table in `data/`, `examples/` (worked
overrides to copy into `data/`: a town, the bar names and masses, a combination row),
`VERIFY.md` (the list to check against the printed code) and a README with these steps.

**2. Override, in this order.** What changes most results first:

1. `locations` (towns with their seismic zone or mapped values and basic wind speed) and
   `occupancyCategories` (importance factors);
2. `combinations` (load factors; the rows with E also give the response spectrum
   combinations, the rows with W the wind ones), `areaLoads` (live loads), `deadLoads`;
3. `seismic` (the spectrum and its method, site classes, structural systems with their R or q,
   Cd and Ω0, drift limits) and `wind` (the pressure method and its factors);
4. the materials: `concrete` (bar sizes with their names, nominal masses where a size's key is a
   designation, covers, limits), `factors` (resistance or partial factors), `steel`;
5. the clause references the results print: `designClauses`, the `clauses` of each table and
   `$sources` in every file you change. A method your code adds (a new wind or spectrum form)
   is a generic engine module picked by id: ask for it, never write `if code == ...`.

Everything you leave out comes from the parent and the report says so: under the design basis
it lists the tables inherited, named after the pack that supplies them, and a clause text a
pack inherits ("SAEngine practice where BNBC 2020 is silent") is printed with "[inherited from
BNBC 2020; not given by <your code>]", never as your code's. Values neither gives fall back to
the named generic defaults, also listed. If your code does not design for earthquakes (or
wind), say so: `"notCovered": ["seismic"]` in `pack.json`.

**3. Check.** `saengine codepack validate <folder>` (every value against its model) and
`saengine codepack check <folder>`, the conformance checks every pack, built-in or yours, must
pass: the tables in `covers` are the ones it gives, every table it gives has sources, no text of
its own speaks for another code, earthquake and wind combinations exist (or are declared not
covered), the bar names and masses are of its bar sizes, and its verification is stated. Then
install it, make a one-bay building with it in the New Project wizard, run the analysis and
Design Reinforcement, and read the report's design basis. The test suite runs the same checks
over every installed pack (`tests/test_codes_conformance.py`; with `-m slow` it also derives
and designs a generated building under each).

**4. Verify.** Every value you enter goes into `VERIFY.md` with its clause, table or equation,
one row each. A second engineer checks each row against the printed code and writes `Verified
<date>` (or ✓) in its last column. Until every row is ticked, or `pack.json` says
`"verified": "<date>"`, SAEngine shows **values not yet verified against the printed code**
beside the pack in Project Settings, in the New Project wizard, on the Packages page and in the
report's design basis. Built-in packs follow the same rule: their `VERIFY.md` lists what their
authors entered without the printed code at hand.

**5. Share.** Keep the pack in the project (`02 Project Settings/code-packs/`: it travels with
the project and its `.civil` archive), install it in the user folder of each engineer, or zip
it. To publish it for other offices, offer it to the SAEngine marketplace index
([marketplace plan](marketplace-plan.md)): packages are reviewed, signed and listed by kind. A
pack that names an online hazard lookup service (`hazardLookup`) is asked only after each user
trusts that service on the Packages page (Trust Lookup Services...; editing the file revokes
it), the same step as hooks. Never copy the code's text, tables as printed or figures: numbers
and short clause references only.

## What a pack is

A pack is a folder:

```text
bd-coastal/
  pack.json            what the pack is: id, name, edition, which pack it extends, sources
  data/
    locations.json     one file per table the pack provides
    combinations.json
    ...
  docs/                your notes, the extracts of the code you may share, calculations
  README.md
```

`pack.json`, for a pack that starts from BNBC 2020:

```json
{
  "schema": "saengine.codePack/1",
  "id": "bd-coastal",
  "name": "Bangladesh coastal belt",
  "edition": "BNBC 2020 with the local schedule",
  "country": "BD",
  "region": "Coastal districts",
  "version": "1.0.0",
  "extends": "bnbc2020",
  "covers": ["locations", "combinations"],
  "description": "BNBC 2020 with the local towns and the 0.5L seismic combination.",
  "sources": [{ "id": "LOCAL", "title": "Local schedule", "edition": "2026" }],
  "clauses": { "locations": ["Local schedule, Table 1"] },
  "basis": { "general": "BNBC 2020 with the local schedule" },
  "author": "A. Engineer, Firm Ltd",
  "licence": "CC-BY-4.0",
  "hooks": null
}
```

| Key | What it is |
| --- | --- |
| `id` | Short id: lower-case letters, digits, `.`, `_`, `-`. Projects refer to the pack by it, so keep it once the pack is in use. |
| `name`, `edition` | Shown in Project Settings and in the report. |
| `country`, `region` | ISO country code (`BD`, `NP`, `LK`, ...) and, for a local pack, the region. |
| `version` | The version of *your pack*; raise it whenever you change a value. |
| `extends` | The pack this one starts from (`bnbc2020`); `null` for a pack that provides every table itself. |
| `covers` | The tables this pack provides. |
| `sources`, `clauses` | Where the values come from: the documents, and the clauses by table. |
| `basis` | What the report and the design method say the design follows: `general` (loads and general), `concrete`, `steel` and `method`. Each label a pack leaves out comes from the pack it extends (BNBC 2020: "BNBC 2020", "BNBC 2020 Part 6 Chapter 6", "BNBC 2020 Part 6 Chapter 10", "Strength design (LRFD)"); without any, the pack's `edition`. |
| `author`, `licence` | Who prepared it and on what terms it may be shared. |
| `hooks` | Optional Python file for formulas ([below](#data-or-formula-hooks-and-trust)); `null` for a data-only pack. |
| `requires` | Optional: what the pack needs, `{"saengine": ">=0.0.47", "packages": {"bnbc2020": ">=1.0.0"}}`. A pack that needs a newer SAEngine is not installed; a missing or too old required package is reported and the pack is not used until it is installed. |
| `kind`, `contents`, `preview` | Optional. `kind` is `designCode` (the default: leave it out); the other kinds are templates ([Other package kinds](#other-package-kinds)). `contents` lists the pack's files (default `data/*.json`); `preview` is a small card image in the folder. |

JSON has no comments. In the data files, keys that start with `$` are not data: `$help` and
`$example` are notes for you, and a few others are instructions to the loader (`$replace`,
`$remove`, `$sources`, below). `pack.json` takes only the keys above.

## Start a pack

In the app: **≡ → Code Packs… → New Code Pack…**, give the id, the name and the pack to start
from (BNBC 2020). SAEngine creates the folder and opens `pack.json`.

From a terminal (see [the command line](cli.md)):

```console
> saengine codepack new bd-coastal --name "Bangladesh coastal belt" --extends bnbc2020 --dest .
created bd-coastal
  edit bd-coastal\pack.json and the tables you change in bd-coastal\data
  then: saengine codepack validate "bd-coastal"
```

The new pack has one file in `data/` for every table of its parent. Each file holds only help:
what the table is, and under `$example` the first entries of the parent's table, so you can see
the format. As created, the pack changes nothing: it designs exactly as BNBC 2020. Then, for
each table you change:

1. write your entries next to `$help` (in the parent's format, as `$example` shows);
2. add the table's name to `covers` in `pack.json`;
3. say where the values come from: `"$sources": ["Local schedule, Table 1"]` in the file, or
   the table under `clauses` in `pack.json`.

Leave the other files as they are (or delete them): a table you do not provide comes from the
parent unchanged.

## The tables

Every table is checked against a model (the JSON Schema of each table is generated from the
same model SAEngine reads). The examples are from the BNBC 2020 pack
(`python/src/saengine/codes/packs/bnbc2020/data/`), which names the clause and page of each
table in its own `source`.

| Table | What it holds |
| --- | --- |
| `locations` | Towns with their seismic zone and basic wind speed. |
| `zoneCoefficients` | Seismic zone coefficient Z by zone. |
| `occupancyCategories` | Occupancy (risk) categories with their seismic and wind importance factors. |
| `areaLoads` | Minimum live loads by use of the floor area [kN/m²]. |
| `combinations` | Load cases (`loadCases`), the strength, temperature and gravity combinations (lists matched by `name`), the dead load factors of the seismic combinations (`seismicDeadUpper`, `seismicDeadLower`) and the overstrength (Ω0) note (`overstrength`). The BNBC pack has no service combinations. |
| `seismic` | Site classes, structural systems (R, Ω0, Cd, height limits), period coefficients, the seismic design category table, drift limits, the other numbers of the seismic analysis. |
| `wind` | Exposure categories and profiles, directionality, topographic and gust factors, pressure coefficients. |
| `materials` | Material constants and limits (εcu, Es, the grades permitted in seismic members, ...). |
| `factors` | Strength reduction factors φ of reinforced concrete. |
| `concrete` | Bar sizes, cover, minimum thickness tables, steel ratio limits, spacing, stiffness modifiers. |
| `detailing` | Detailing limits that are plain numbers: special moment frames, joints, walls, lintels. |
| `steel` | φ factors and slenderness limits of structural steel. |
| `foundations` | Pile safety factors, partial factors of skin and base resistance, strut-and-tie factors. |
| `slabCoefficients` | The two-way slab moment coefficients (BNBC Tables 6.6.8-6.6.11), their limits and the one-way coefficients. |
| `plumbing` | Water supply, drainage and rainwater (BNBC Part 8 Chapters 5-7): water demand by occupancy, storage, fixture units and the probable demand curve, velocity and pressure limits, stacks, drains and vents, septic tank and soak pit, leaders, gutters and storm drains; the pipe diameters, Hazen-Williams C, sleeves and wet-room fixtures SAEngine assumes where the code is silent. |
| `hvac` | Air-conditioning and energy (Part 8 Chapter 2, Part 3 Chapter 4): outside design conditions of the stations, inside conditions, ventilation rates and occupancy, lighting power density, glazing and overhangs; equipment loads, metabolic heat and supply air SAEngine assumes (listed in the report). |
| `electrical` | Electrical services (Part 8 Chapter 1, Sec 4.2.1): load densities, substation, transformer and generator rooms, shafts and risers, earthing, the lightning risk indices and protection; typical equipment sizes and masses for the first layout. |
| `fire` | Fire protection (Part 4): hazard classes and flows, durations, standpipe and hose pressures, pump ratings, sprinkler pipe schedules and spacing; the NFPA values the code leaves out (marked "from memory, to be checked"). |
| `steelSections` | The standard steel shapes: the nominal dimensions of each family (IPE, HEA, HEB: EN 10365; ISMB, ISMC: IS 808; equal angles: EN 10056 / IS 808; SHS, RHS, CHS: EN 10219), the walls rolled per size, the density. SAEngine computes the properties (A, I, S, Z, J, Cw) from them. |

`saengine codepack show bnbc2020` lists them with their clauses. Short examples:

**locations**: towns keyed by a short id; `zone` points into `zoneCoefficients`.

```json
{ "locations": { "dhaka": { "name": "Dhaka", "zone": 2, "windSpeed": 65.7 } } }
```

**zoneCoefficients**: Z by zone.

```json
{ "zones": { "1": 0.12, "2": 0.2, "3": 0.28, "4": 0.36 } }
```

**areaLoads**: live loads by use.

```json
{ "uses": { "office": { "name": "Office", "live": 2.4 } } }
```

**combinations**: a list of named combinations per category, each with its load factors (`D`
includes the superimposed dead load; `W` and `E` are expanded to both plan directions and
signs by SAEngine).

```json
{
  "strength": [
    { "name": "1.2D + 1.6L + 0.5Lr", "factors": { "D": 1.2, "L": 1.6, "Lr": 0.5 } }
  ],
  "seismicDeadUpper": 1.2,
  "seismicDeadLower": 0.9
}
```

**seismic**: for instance a structural system and a site class.

```json
{
  "systems": {
    "rcSmf": { "name": "RC special moment frame", "R": 8.0, "Omega0": 3.0, "Cd": 5.5,
               "heightLimits": { "B": null, "C": null, "D": null } }
  },
  "siteClasses": { "SC": { "description": "Dense sand, stiff clay", "S": 1.15,
                           "TB": 0.2, "TC": 0.6, "TD": 2.0 } }
}
```

**wind**: exposures and factors.

```json
{ "exposures": { "B": { "description": "Open terrain", "alpha": 9.5, "zg": 274.32 } },
  "directionality": 0.85, "gust": 0.85 }
```

**factors**: φ.

```json
{ "phi": { "tension": 0.9, "compressionTied": 0.65, "compressionSpiral": 0.75, "shear": 0.75 } }
```

**concrete**, **detailing**, **materials**, **steel**, **foundations**: groups of named
numbers, for instance `{"cover": {"lintel": 25.0}}`,
`{"special": {"beamRhoMax": 0.025}}`, `{"steelE": 200000.0}`,
`{"phi": {"compression": 0.9}}`, `{"sptSafety": 3.5}`. The help in each file of a new pack
shows the full list of keys of its table.

Every table also accepts `source` (the clause the table comes from, as text) and `sources`
(clauses of single entries: `{"shearSeismic": "Sec 6.2.3.3(a)"}`).

After inheritance every key the program reads must be present and in range (φ: 0 < φ ≤ 1;
ratios: 0 < x < 1). Unknown keys are refused, so a misspelt key is an error rather than ignored;
the exceptions are extra φ factors and extra bar sets, which hooks may use. The required keys of
each table are in its JSON Schema (`python/src/saengine/codes/schemas/<table>.schema.json`).

## Inheritance: change only what differs

A pack that `extends` another starts from all of its tables. In a table you provide, only what
you write changes:

- **Objects are merged key by key.** To change Chattogram's wind speed and add a town:

  ```json
  {
    "locations": {
      "chattogram": { "windSpeed": 82.0 },
      "northford": { "name": "Northford", "zone": 3, "windSpeed": 58.0 }
    }
  }
  ```

  Chattogram keeps its zone; every other town stays as in BNBC 2020.

- **Lists of named items** (the combinations) are matched by `name`: an item with a name the
  parent has changes that item, a new name is added at the end, and `"$remove": true` drops
  the parent's item:

  ```json
  {
    "strength": [
      { "name": "1.2D + 1.0E + 1.0L", "$remove": true },
      { "name": "1.2D + 1.0E + 0.5L", "factors": { "D": 1.2, "E": 1.0, "L": 0.5 } }
    ]
  }
  ```

  Other lists (bar sizes, for instance) are replaced whole by yours.

- **Drop keys**: `"$remove": ["rangpur", "sylhet"]` in an object drops those entries of the
  parent.

- **Replace a whole table**: `"$replace": true` at the top of the file (or in any object) uses
  yours instead of the parent's, without merging: for a region whose list of towns has nothing
  in common with the parent's, say.

A pack can extend a pack that extends another (`city` → `region` → `bnbc2020`). A pack in a
project may also extend its own id (`"id": "bnbc2020", "extends": "bnbc2020"`): it then patches
the built-in BNBC pack for that project only.

The example pack `python/tests/data/codepacks/example-region/` does all of this on invented
values: two towns, one wind speed, one combination. Compare it with BNBC 2020:

```console
> saengine codepack diff bnbc2020 python/tests/data/codepacks/example-region
- combinations.strength.[1.2D + 1.0E + 1.0L]: {"name": "1.2D + 1.0E + 1.0L", "factors": {...
+ combinations.strength.[1.2D + 1.0E + 0.5L]: {"name": "1.2D + 1.0E + 0.5L", "factors": {...
~ locations.source: "BNBC 2020 Part 6 Table 6.2.8 (p. 600) basic wind speeds; ..." -> "..."
~ locations.locations.chattogram.windSpeed: 80.0 -> 82.0
+ locations.locations.northford: {"name": "Northford", "zone": 3, "windSpeed": 58.0}
+ locations.locations.saltmarsh: {"name": "Saltmarsh", "zone": 1, "windSpeed": 84.5}
6 differences
```

This is the review to do before a regional pack is used: every line is a value that differs
from BNBC 2020, and nothing else does.

## Data or formula? Hooks and trust

A pack changes **numbers**. The **formulas** stay in SAEngine: the flexure and shear strength
of a section, the equivalent static base shear and its distribution, the wind pressure profile,
development lengths, punching shear, and so on. Most codes derived from ACI 318 and ASCE 7 (as
BNBC 2020 is) use the same formulas with different numbers, and a data pack is enough.

| A pack can change (data) | Needs a hook (formula) |
| --- | --- |
| towns, zones, Z, wind speeds | a different spectrum shape or base shear formula |
| live loads, importance factors | a different wind pressure method |
| load combinations and their factors | a different section strength model (another stress block, another shear formula) |
| site classes and their factors, R, Ω0, Cd, height limits, period coefficients, drift limits | a different development length or lap formula |
| φ factors, cover, bar sizes, minimum thicknesses, steel ratio limits | a different slenderness method |
| detailing limits that are plain numbers | rules that are conditions rather than numbers |
| pile safety factors, partial factors | a different bearing capacity method |

When a formula differs, a pack can name a Python file in `hooks` (`"hooks": "hooks.py"`), whose
functions replace SAEngine's functions of the same name. A hook is a program: it can do
anything a program on your computer can. So SAEngine **never runs a hook until you trust the
pack** (Code Packs page → the pack → *Trust*), the trust is recorded for exactly that code, and
**any edit of the pack's Python files withdraws the trust** until you trust it again. Built-in
packs are trusted. Trust a pack's hooks only when you know who wrote them and have read them;
a data-only pack needs no trust at all.

## Check a pack

```console
> saengine codepack validate bd-coastal
warning: pack.json: no sources or clauses: say where the values come from
bd-coastal: ok (0 errors, 1 warning)
```

`validate` reads the pack the way a project does: `pack.json`, every data file, the parent
packs, then every resolved table against its model (a negative wind speed, a missing factor, a
misspelt key are errors). It also warns about a file with values whose table is not in
`covers`, a table in `covers` whose file has only help, and a pack without sources. It exits
with code 1 when the pack has an error, so it can run in continuous integration. In the app:
Code Packs page → the pack → **Validate**.

`saengine codepack show <id or folder>` lists a pack's tables, which are its own and which are
inherited, the clauses of each, its trust state and its problems.

A pack holds data, and Python `hooks` at most: a pack with a program or script (`.exe`,
`.dll`, `.pyd`, `.bat`, `.cmd`, `.ps1`, `.js`, ...), a link, a file over 5 MB (50 MB for a
`.civil`) or over 200 MB in all is refused when installed and reported as an error when found.

## Use and share a pack

Where SAEngine finds packs (the same id in a higher place wins):

1. **the project**: `02 Project Settings/code-packs/<id>/`: the pack travels with the project,
   its versions and its `.civil` archive;
2. **your user folder**: `%APPDATA%\SAEngine\code-packs\<id>\` on Windows
   (`~/Library/Application Support/SAEngine/code-packs` on macOS, `~/.config/SAEngine/code-packs`
   elsewhere): available to every project on this computer;
3. **built-in**: `bnbc2020`, shipped with SAEngine; `eurocodes` (below); `aci318-asce7-22`, the ASCE 7-22 loads
   (its materials still fall back to `bnbc2020`; the site's SDS, SD1, S1, TL and V are entered
   from the ASCE Hazard Tool; values to check in its `VERIFY.md`); `is-codes`, the Indian
   Standards loads (below); and the two legacy packs `bs8110` and `bnbc2006` (below).

To use a pack, choose it in **02 Project Settings → Design code**, or in **New Project →
Design code**, which lists the packs installed on this computer. A project without a choice
(every project made before code packs) uses `bnbc2020`, and designs exactly as before.

The design code is the code pack alone. Project settings written before code packs also have a
`codes` section (the concrete and steel codes as labels, for instance "ACI 318-19"); it is no
longer read, the settings form no longer shows it, and it is dropped the next time the settings
are saved. The report's "Design basis" now states the pack's `basis`.

To share a pack, zip its folder and send it; the receiver installs it with **≡ → Code Packs… →
Install Code Pack…** (the zip or the folder, into the user folder or into the project), or
copies the folder into one of the places above. A project that uses a pack of its own carries it
along: send the project or its `.civil` archive and the pack goes with it.

## How to override a code value

You don't need a pack of your own to change one value for one project. Any value of the pack in
force can be overridden in the project:

1. Open **02 Project Settings → Code Values**.
2. Pick the table (`factors`, `seismic`, `combinations`, ...) and find the value. The filter
   matches words of its name.
3. Type the project's value in **This project**. Leave the field empty and the pack's value
   applies.

Overridden values are marked and listed first, each with a **Reset** button. The setting behind
the page is `codeOverrides` in `project-settings.json`, a map from a value's path to the
project's value:

```json
"codeOverrides": {
  "factors.phi.shear": 0.7,
  "seismic.systems.rcSmf.R": 7,
  "combinations.pDeltaPreload": { "D": 1.4, "SD": 1.4, "F": 1.4, "L": 0.5 },
  "combinations.strength[1.2D + 1.6L + 0.5Lr].factors.L": 1.7
}
```

- A path is the table, then the keys inside it, separated by dots. A key with dots or brackets
  in it goes in brackets. An item of a list is named by its `name` (or `id`, or its index).
- A value replaces the pack's value. A group of values (`{...}`) replaces the whole group.
- Every run uses the overrides: the analysis, the design, the drawings and the report read the
  pack with the overrides merged in, by the same merge as `extends`.
- Each override is checked against its table. An override of a value the pack does not have, of
  another kind (text for a number), or out of range (a φ above 1) is not used. It is listed with
  its path among the settings' problems and the report's warnings, and the pack's value applies.
- The overrides belong to the project, not to the pack. After switching packs they apply to the
  new pack; one the new pack has no value for is reported, not used.
- The design report lists them in **Code values overridden in this project**: the path, the
  pack's value and the project's value.

Values that belong to a member or a material (a material's E, a member's cover) are still set
on the member or material.

A few owner decisions also have their own setting, because the choice is a common one:
`analysis.partitionAllowanceCase`, `analysis.massSource.partitions` (how the partition counts in the seismic weight), `analysis.steelRigidZoneFactor` and
`site.flood.waveCombination` (see [engineering-decisions.md](engineering-decisions.md)). They
win over the pack's value and over an override of it.

### Switching packs and missing packs

Changing the pack, a setting or an override takes effect on the next run. Nothing needs to be
migrated. The kept results of a run (the design checks, the response spectrum design, the
irregularity checks) are stamped with a fingerprint of the pack's values and the overrides, so a
change never leaves an older answer in use.

A project whose pack is not installed on this computer (a project sent without its pack, say)
still opens and runs. The default pack is used instead, with a warning in Project Settings, on
the Code Values page and in the report.

### Generic defaults

A pack that lacks one value still works. The value comes from SAEngine's **generic defaults**,
`python/src/saengine/codes/generic/data/<table>.json`. These are editable data, not part of any
code. Results and the report name each one as "generic default (SAEngine practice), not given by
<pack>", and the report lists them under **Generic defaults** with their sources:

| Value | Generic default | Source |
| --- | --- | --- |
| `factors.phi.plain` | 0.60 | ACI 318-19 Table 21.2.1(g) |
| `detailing.bars` | hooks, bends, development, laps, splice zones, extents | ACI 318-19 Ch. 25, 18.6-18.10, 9.7.3, 8.7.4; ACI 318-14 25.4.3.2 (hook factors); no lap splices above 36 mm (25.5.1.1) |
| `combinations.pDeltaPreload` | 1.2 D, SD, F; 1.0 L | ASCE 7-22 Sec 2.3.6, combination 6 |
| `seismic.stabilityGravity` | 1.0 each | ASCE 7-22 Sec 12.8.7 |
| `areaLoads.partitions.loadCase` | L | ASCE 7-22 Sec 4.3.2 |
| `seismic.partitionWeight` | full | ASCE 7-22 Sec 12.7.2 (partitions in the seismic weight) |
| `flood.waveCombination` | sum | SAEngine practice (conservative) |
| `steelSeismic.practice.rigidZoneMax` | 0 | SAEngine practice (centreline model) |
| `concrete.modulus` | 4700 √f'c; 0.043 wc^1.5 √f'c | ACI 318-19 19.2.2.1 (brick aggregate: no generic rule, the normal-weight value) |
| `concrete.shrinkage` | 0.0020 below fy 420; 0.0018 × 420/fy, at least 0.0014 | ACI 318-14 Table 24.4.3.2 |

Generic defaults fill single values only, in tables the pack has. A whole table the pack lacks
is a feature it does not cover: that feature shows as "not covered by the code pack", and never
falls back to another code. A value the pack gives always wins, and a project override wins over
both.

## The pack in the report

The design report states the code pack the project was designed to on its cover ("Code
pack"): its name, id, edition and version. A pack that extends another reads "<name> (<id>),
<edition>, pack version <v>; extends BNBC 2020 (bnbc2020) for the tables it does not give". It
names the pack in force first. Tables of the extended pack that do not apply under the code
(`notApplicable` in `pack.json`) are not inherited and are listed as such. A user or project copy that
replaces a built-in pack of the same id is named with its place ("modified from the built-in
code"), and the pack's warnings are listed among the report's warnings. Keep `version` up to
date when you change a value, so that a report always says which values it used.

## Limits of this version

**What follows the project's pack today.** The project's choice (`codePack`) is read by:

- the site and hazard values of Project Settings (town, zone, Z, basic wind speed, importance
  factors, R, Ω0, Cd: `locations`, `zoneCoefficients`, `occupancyCategories`,
  `seismic.systems`), the live load minimums the settings are checked against (`areaLoads`) and
  the report's design basis;
- the loads of the analysis model: the equivalent static earthquake (spectrum: `seismic.
  siteClasses`, `dampingEta`; period: `seismic.periodCoefficients`), the seismic weight's share
  of live load (`seismic.liveShare`) and the wind pressures (`wind`: exposure profiles, Kd, Kzt,
  G, Cp);
- the response spectrum design: zone from Z, Seismic Design Category (`seismic.
  designCategories`), drift limits (`seismic.allowableDrift`), a_h (`seismic.pgaFactor`);
- the load combinations made from a pack (`combinations`), through
  `saengine.library.settings.strength_combinations(pack=...)`. A project keeps its combinations
  in its settings, and choosing a pack does not rewrite them; in the app, new projects and
  **Reset Combinations to BNBC 2020** still use BNBC 2020's: enter a pack's combinations in
  Project Settings → Load combinations.
- the seismic detailing scope of the design (which provisions of the code's earthquake chapter
  apply): the system's row of the systems table (R, Ω0, Cd, height limits per Seismic Design
  Category, frame detailing level, special walls: `seismic.systems`), the detailing level each
  category requires (`seismic.requiredDetailing`) and the material limits of special frames and
  walls (`materials`: `seismicFcMin`, `lightweightFcMax`, `lightweightDensity`,
  `seismicRebarFy`, `seismicRebarFyMax`, `gradeTolerance`, `fyActualMargin`, `fyRetestMargin`,
  `fuFyMin`);
- the building generator's choice of the seismic force-resisting system (`seismic.systems`,
  `seismic.requiredDetailing`) and its period estimate (`seismic.periodUpperFactor`);
- the steel member design's φ factors and slenderness limits (`steel.phi`: `tensionYield`,
  `tensionRupture`, `compression`, `flexure`, `shear`; `steel.slenderness`) and the steel shear
  modulus (`materials.steelShearModulus`);
- the code the report and the design method name (the manifest's `basis`);
- the cracked-section stiffness factors of the analysis model, the slender column design and
  the building generator's drift estimate (`concrete.crackedStiffness`, with `wallUncracked`
  for walls taken as uncracked);
- the concrete design's bar sizes, spacings and steel ratios (`concrete.barDiameters`,
  `spacingStep`, `minSlabSpacing`, `minStirrupSpacing`, `columnRho`, `beamRatioMax`), the slab
  design's punching φ, least strain and two-way thicknesses (`factors.phi.punching`,
  `concrete.slabStrainMin`, `concrete.twoWayThickness`), the stairs (`concrete.cover.stair`,
  `combinations.gravity`) and the building generator's slab and beam depths
  (`concrete.twoWayThickness`, `oneWaySlabThickness`, `beamThickness`);
- the walls (`concrete.walls`, `detailing.walls`, `factors.phi`: `shearSeismic`,
  `diagonalCoupling`, the wall, boundary and hoop bar sizes), the seismic detailing of special
  moment frames and their joints (`detailing.special`, `detailing.joints`, `factors.phi.joint`)
  and the lintels (`detailing.lintels`, `concrete.cover.lintel`, the lintel bar sizes);
- 9 Substructure's design report and its sizing assistant: the piles (`foundations`:
  `pileSafety`, `pileControls`, `partialSkin`, `partialBase`, `sptSafety`, `noLoadTestSafety`,
  `loadTestSafety`) and the pile caps (`foundations.strutAndTie`, `factors.phi.strutAndTie`,
  `concrete.cover.pileCap`);
- the steel member design's section table (`steelSections`: the shapes the design checks,
  their dimensions and the steel density).

**What does not follow it yet** (read from the built-in BNBC 2020 values, whatever the pack):
the concrete section design's φ factors and constants (`factors.phi`: `tension`,
`compressionTied`, `compressionSpiral`, `shear`; `materials`: `concreteStrain`, `steelE`;
`concrete`: `fytShearMax`, `slendernessLimit`), the slender column limits
(`concrete.slender`, `factors.phi.stiffnessReduction`), the steel connection factors
(`steel.phi`: `bolt`, `bearing`, `blockShear`, `weld`, `plateFlexure`; `steel.netAreaMax`), the
seismic analysis checks of `fem/seismic_design` (`seismic`: `minimumScale`,
`accidentalEccentricity`, `orthogonalShare`, `massParticipation`, the torsion limits); the
pile and pile cap checks Part 9's editor runs while you type, and the bill of quantities' lintel
bearing and cover (they read the tables above, but of BNBC 2020 until they run under the
project's pack); the analysis exporters' and importers' cracked factors; the soil part
(liquefaction's site factors); the settings editor's derived-value hints and its Code Values
panel; the building services (`plumbing`, `hvac`, `electrical`, `fire`: 07 MEP runs under the
default pack, BNBC 2020 or a user copy that replaces it) and the steel section table wherever it
is read outside the member design (the 04 Objects section list, the bill of quantities, the
drawings, the importers and exporters). A pack's values in those tables are validated and
shown, but not used: keep them equal to BNBC 2020 until a later version wires them. No design
function consults hooks yet. A pack written before a table moved into the code pack (code packs
3: the services tables and `steelSections`) that has no copy of it reads BNBC 2020's.

The project's Location must be one of BNBC 2020's towns (or "Custom" with Z and V): a pack's own
towns are validated and listed but cannot yet be chosen in the settings.

- Packs hold the code's **reference data and plain-number factors**. Design formulas are
  SAEngine's (ACI 318 / BNBC 2020 based); a pack changes them only through trusted hooks.
- The tables cover what SAEngine reads today. A code clause SAEngine does not implement cannot be
  added by a pack's data alone.
- The units are fixed: SI (kN, m, mm, MPa, m/s).
- Wind speeds are part of `locations`; a separate `windSpeeds` table is reserved for codes that
  map wind apart from the towns.
- The names of the load cases (`D`, `L`, `Lr`, `W`, `E`, `F`, `T`) are SAEngine's; a pack changes
  their factors and the combinations, not the set of load cases the program builds.
- The BNBC 2020 pack is transcribed from the values SAEngine used before code packs; the clause
  and page of each table are in its `source`. Check every value of a pack you write against the
  edition of the code that governs your project.

## Planned code packs

SAEngine is built on BNBC 2020. Three more design-code packs are planned. They are listed under
*Planned Design Codes* on the Packages page and shown disabled ("Planned") in the New Building
wizard's design code selector. Each has a page that describes its coverage:

- **ACI 318-19 + ASCE 7-22** (United States).
- **Eurocodes EN 1990–1998 with National Annexes**. There is one base pack with the
  recommended values. Each country's National Annex is a small pack that `extends` the base
  and sets only its Nationally Determined Parameters, in the same way an office pack extends
  BNBC 2020 today. **The loads part is built in** (see below); the materials are planned.
- **Indian Standards**: IS 456, 1893, 800, 875 and 13920. **The loads part is built in** as
  `is-codes` (see below); the materials (IS 456, 800, 13920) are planned.

### Eurocodes (loads and seismic): `eurocodes`

The built-in pack `eurocodes` (Eurocodes, recommended values) covers EN 1990, EN 1991-1-1,
-1-3, -1-4, -1-7 Annex D and EN 1998-1. Its README
(`python/src/saengine/codes/packs/eurocodes/README.md`) lists the tables, and `VERIFY.md` lists
every value with its clause, for checking against the printed codes. It extends BNBC 2020.
Concrete members, slabs, stairs, walls, joints, spread footings and piles design by its EN
1992-1-1, EN 1998-1 and EN 1997-1 methods (below); steel, timber, masonry, deep beams and the
other areas still use the BNBC 2020 tables and methods. The report's design method says which.

To use it, choose **Eurocodes (recommended values)** as the design code. The pack has no towns
(the National Annex maps give agR and vb,0), so set Location to **Custom** and enter agR (in g)
as Z and vb,0 as V. Then choose the terrain category (0, I, II, III or IV) under Wind and the
ground snow load sk under Site → Snow.

It chooses generic methods by id, which other packs can use too:

| Key | Values | What it does |
| --- | --- | --- |
| `seismic.designSpectrum.method` | `reducedElastic` (default), `behaviourFactor` | The design spectrum with q and the lower bound β |
| `seismic.spectrumType`, `seismic.spectra` | spectrum id → site parameters | Type 1 or Type 2 |
| `seismic.lateralForce` | `correction`, `periodTcFactor`, `minStoreys`, `distribution` (`heightPower`, `linear`) | λ, and how the base shear is distributed |
| `seismic.driftAmplification` | `overImportance` (default), `displacementFactor` | Cd·δe/I, or qd·de |
| `seismic.stability.method` | `elasticOverImportance` (default), `designDrift` | θ |
| `wind.method` | `powerLaw` (default), `peakVelocityPressure` | Storey forces from qz, or from qp(z) with cpe, ρ and cscd |
| `liveReduction.method` | `influenceArea` (default), `areaAndStoreys` | KLL·AT, or αA and αn |
| `combinations.strengthSet`, `strengthSets` | set id → combinations | EN 1990 6.10 or 6.10a/b |

#### Concrete and foundation methods (method selection)

The concrete and foundation design asks `saengine.design.method_selection` which method the
pack in force picks for each area, by id, from the pack's method tables `concreteMethods` and
`geotechnicalMethods` (`<area>.method`, or the group's presence). No id (a pack without the
group, such as BNBC 2020) is the default: the strength design with φ, unchanged. Any pack can
pick these ids; another code's method gets its own id and module beside them.

| Area | Ids | Where it is used |
| --- | --- | --- |
| `ultimate` | `partialFactors` | Sections with fcd, fyd, φ = 1 (`rc`, slabs and stairs strips, walls' and flanges' integration, lintels, footing strips); Design Reinforcement's sizing (`bars`) |
| `shear` | `variableStrut` | Beams, columns, walls' in-plane shear, slab and footing strips (VRd,c), the proposal's links |
| `torsion` | `thinWalledVariableStrut` | Beam torsion rows and the torsion the proposal adds |
| `deflection` | `spanDepthK` | Beam span/depth rows (the calculated deflection follows where a span exceeds it) |
| `cracking`, `serviceStress` | `directWidth`, `stressLimits` | Beam crack widths and stress limits (they replace the bar-spacing crack control) |
| `slenderness` | `nominalCurvature` | Column slenderness: λlim and the nominal curvature MEd |
| `punching` | `controlPerimeter` | Flat slabs (shells and frame methods) |
| `memberSteel` | (the group) | Least and largest steel and spacings of beams, columns, slabs, stairs and walls, in the checks and the proposal |
| `anchorage` | `bondStress` | Anchorage and lap lengths of the detailing and the bar schedule |
| `seismic` | `curvatureDuctility` | DCM/DCH members, joints, capacity-design shear, ductile walls; the parent's special-frame detailing does not run |
| `bearing`, `sliding` | `effectiveArea`, `interfaceFriction` | Spread footings by the design approach (the allowable-pressure rows are then reported only) |
| `piles` | `correlationFactors` | Pile caps' piles: Rc,k with ξ, Rc,d by the resistance sets |
| `strutAndTie` | `designStressLimits` | Deep beams, corbels and deep pile caps by strut-and-tie on the design strengths (`stress_fields`) |
| `interfaceShear` | `interfaceShear` | Construction joints of columns and walls (c fctd + μ σn + ρ fyd μ) |
| `ties` | `tieForces` | Peripheral, internal and column ties of the beams (in place of the integrity bars) |
| `footingPunching` | `reducedPerimeter` | Punching of footings, pile caps and rafts within 2d, the soil pressure inside deducted |
| `wallSlenderness` | `columnAnalogy` | Walls out of their plane as a strip column (nominal curvature), the out-of-plane shear |
| `barShapes` | `barShapes` | Mandrels, hooks, links' bends, compression laps and column splices of the detailing |
| `retaining` (geotechnical) | `limitStates` | Retaining walls by the design approach (Ka(φ'd), sliding, bearing on B', EQU) |

Alpha 9 C5c also made these keys of the other tables generic, chosen by method id: the seismic
table's `regularity` (`criteria`: plan and elevation, q × factor), `torsionalEffects`
(`deltaFactor`), `modalCombination` (`independence`: SRSS or CQC), `verticalComponent`
(`verticalSpectrum`), `foundationCapacity` (`overstrengthFactor`) and `spectrumTypeGuidance`;
the wind table's `orography` (`annexA3`), `structuralFactor.detailed` (`annexB`) and
`localPressures` (`areaDependent`), and `designCases` without Cases 3 and 4; the snow table's
`drift` method `shapeCoefficient`.

A project can set any area back to the default method with the override
`concreteMethods.parentMethods` (or `geotechnicalMethods.parentMethods`), a list of area
names, e.g. `"concreteMethods.parentMethods": ["torsion", "seismic"]`. The design approach is
the override `geotechnicalMethods.designApproach` (DA1, DA2, DA3).

### Indian Standards (loads and seismic): `is-codes`

The built-in pack `is-codes` (Indian Standards (IS)) covers IS 875 Parts 1 and 2 (unit weights,
imposed loads and their reduction by the floors carried), Part 3:2015 (wind: Vz = Vb k1 k2 k3
k4, pz = 0.6 Vz², pd = Kd Ka Kc pz ≥ 0.7 pz), Part 5 with IS 456 Table 18 (combinations) and IS
1893 (Part 1):2016 (zones II-V, soil types I-III, Ah = (Z/2)(I/R)(Sa/g), Ta, the least base
shear, Qi by hi², scaling to VB, drift 0.004, irregularities). It extends BNBC 2020 for the
materials, as `eurocodes` does. Its README and `VERIFY.md` (every value, its clause and how sure
it is) are in `python/src/saengine/codes/packs/is-codes/`.

It has towns: choosing it in **New Project** or the **New Project** wizard lists its 67 cities
(zone and basic wind speed), soil types and terrain categories, and a new project starts from
the pack's defaults (Delhi, soil type II, RC SMRF, terrain category 2, its live loads and
combinations), every one changeable in Project Settings. k3 is the topographic factor of Project
Settings → Wind, k4 the Code Values override `wind.speedFactors.importance`.

The generic methods and keys it adds, open to any pack:

| Key | Values | What it does |
| --- | --- | --- |
| `seismic.designSpectrum` (`reducedElastic`) | `factor`, `longPeriod` (`inverseSquare`, `constant`), `staticPlateau` | Sa = factor·Z·I/R·Cs; Sa/g constant beyond TD; no rising branch in the static method |
| `seismic.lateralForce` | `distribution: heightSquared`, `minimumShare` by zone | Qi ∝ Wi hi²; the least V / W |
| `seismic.driftAmplification` | `designForces` | Drift checked as computed; displacements Cd·de (Cd = R) |
| `seismic.periodCoefficients.<family>.planDimension` | true | T = Ct·h^m/√d |
| `wind.method` | `speedFactors` (with `speedFactors`, `cpByHeight`) | pd from the design wind speed; wall Cp by h/w and l/w |
| `liveReduction.method` | `floorCount` | Reduction by the floors carried, beams by area |
| `locations.default`, `seismic.defaultSiteClass`, `seismic.defaultSystem`, `wind.defaultExposure` | ids | A new project's choices under the pack |
| `snow` (table) | | s = factor·μ1·Ce·Ct·sk on the roof, in Lr |

A National Annex pack extends it and gives only what differs:

```json
{ "schema": "saengine.codePack/1", "id": "ec-xx", "name": "Eurocodes with the XX National Annex",
  "extends": "eurocodes", "covers": ["combinations", "seismic"] }
```

For example, `data/combinations.json` can be `{"strengthSet": "6.10ab"}` and
`data/seismic.json` `{"spectrumType": "2", "designSpectrum": {"lowerBound": 0.1}}`.

Built-in National Annexes (alpha 9 C15; each pack's README and `VERIFY.md` are in
`python/src/saengine/codes/packs/<id>/`):

| Pack | Annexes | What it sets |
| --- | --- | --- |
| `eurocodes-uk` | UK NAs to BS EN 1990-1998 | 6.10a/b with ξ 0.925 and ψ0 wind 0.5, imposed loads, vb,map by town with the altitude factor, sk by zone and altitude, αcc 0.85 / 1.0 (shear), γM2 1.10, DA1, very low seismicity, BS 8666 bar schedules |
| `eurocodes-de` | DIN EN NAs, DIN 1054 | Eq 6.10, imposed loads of Table 6.1DE, wind zones 1-4 by town with the NA.B profiles (and the simplified pressures), snow zones 1-3, αcc 0.85, CRd,c 0.15/γc, ν1 = 0.75 ν2, γM1 1.1, DA2*, seismic zones 0-3 and the combined subsoil classes |
| `eurocodes-my` | MS EN NAs | vb,0 and agR by town, αcc 0.85 / 1.0 |
| `eurocodes-sg` | SS EN NAs | vb,0 = 20 m/s, the least horizontal load 1.5 % G, αcc 0.85 / 1.0, γM2 1.10, no seismic design |

The generic keys they use, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `concreteMethods.ultimate.alphaCCShear` | αcc of fcd in shear (VRd,max), torsion (TRd,max) and punching (vRd,max); none: `alphaCC` |
| `concreteMethods.shear.nuMax` | ν1 at most this |
| `wind.altitude.factor` | vb,0 = vb,map × (1 + factor A), A = Project Settings > Site > Site altitude; the town's or the entered V is vb,map |
| `wind.peakVelocityPressure.profiles` | By terrain id: segments `{zmax, factor, exponent, zref, absolute}`, qp = factor qb (z/zref)^exponent (or factor (z/zref)^exponent kN/m² with `absolute`) in place of Eq 4.8 |
| `wind.peakVelocityPressure.simplified`, `useSimplified` | Stepped qp by vb,0, terrain and building height, the whole height at the step of h (opt-in) |
| `wind.minimumLateral.share` | Each level's wind storey force at least share × its characteristic dead weight (D + SD) |
| `snow.groundLoad` (`zoneAltitude`) | sk = factor × max(minimum, base + coefficient ((A + offset)/divisor)^exponent) by Site > Snow > Snow zone, where no ground snow load is entered |
| `seismic.designCategories.zoneColumns` | The category column of each zone id (zone 0, or more zones than columns); none: zone n takes column n - 1 |

The US and Indian packs have none of their tables, values or clause text included yet.

### Codes that adopt the US codes with local values

Built-in packs that `extends: "aci318-asce7-22"` (alpha 9 C16; README and `VERIFY.md` in each
pack folder), all starting in SI units:

| Pack | Code | What it sets |
| --- | --- | --- |
| `saudi-sbc` | SBC 301-2018, SBC 304, SBC 306 | Cities with SS, S1 and V; site classes A-F with Fa, Fv (ASCE 7-16 form); ASCE 7-16 Kz constants; bars 8-32 mm, BS 8666 schedules |
| `pakistan-bcp` | BCP SP-2007 | Zones 1, 2A, 2B, 3, 4 by town; the `ubc97` method (Ca, Cv, Na, Nv); R, Ω0, Ct; importance factors |
| `philippines-nscp` | NSCP 2015 Vol 1 | Zones 2 and 4 and V by province; the `ubc97` method; ASCE 7-10 Kz constants; importance factors; PNS 49 bars; the concrete clause references numbered 4xx |
| `indonesia-sni` | SNI 1726:2019, SNI 1727:2020, SNI 2847:2019 | Cities with SS, S1, TL; site classes SA-SF with Fa, Fv; ASCE 7-16 Kz constants; D-bar names |

Saudi Arabia and Indonesia use the site coefficients and the towns' SS, S1, TL of the thin
country packs (below). The generic keys these packs add, open to any pack (a pack without them
behaves as before):

| Key | What it does |
| --- | --- |
| `locations.<town>.zoneLabel` | The zone as the code names it (2A) in the location list |
| `seismic.designSpectrum.method: ubc97` with `ubc97` | Ca, Cv by soil profile at `zValues`; × Na, Nv (`na`, `nv` by source type: (km, factor) points) from `nearSourceFrom`; V ≥ `nearSourceFactor` Z Nv I W/R; `periodUpper` (Z from, Cu) steps. The spectrum and Cs are `mappedSpectral`'s with 2.5 Ca for SDS and Cv for SD1; the town's zone reads `designCategories` |

A project under a `ubc97` pack enters the seismic source type and distance (or Na and Nv) in
Site > Mapped spectral values; without them Na = Nv = 1.0 and the settings check warns where the
factors apply.

### Legacy British Standards: `bs8110`

The built-in pack `bs8110` (alpha 9 C10) covers BS 6399-1/-2/-3 (imposed loads and their
reduction, wind by the standard method with Sb by height and distance from the sea), the BS 8110-1
Table 2.1 combinations, BS 8110-1:1997 concrete (with BS 8110-2 crack widths and deflections) by
the C8 family of tabulated methods, and BS 5950-1:2000 steel members by the limit state steel
method. The British Standards give no seismic loading: its towns have Z = 0 and no earthquake
cases are made. It extends BNBC 2020 for the rest (torsion, flat slabs, walls, footings,
connections, masonry, timber), named BNBC 2020 in the report. README and `VERIFY.md`:
`python/src/saengine/codes/packs/bs8110/`.

### The previous Bangladesh code: `bnbc2006`

The built-in pack `bnbc2006` (BNBC 1993, reissued 2006) extends BNBC 2020 and overrides only the
three seismic zones, the base shear V = Z I C W / R with C = 1.25 S / T^(2/3) <= 2.75, the period,
R, the top force, the fastest-mile wind method with Cz and CG, the load combinations and the
strength reduction factors of its ultimate strength design. README and `VERIFY.md`:
`python/src/saengine/codes/packs/bnbc2006/`.

The generic keys these two packs add, open to any pack (absent: the behaviour before):

| Key | What it does |
| --- | --- |
| `concreteMethods.shear.depthFactor` | τc × (reference / d)^exponent, at least min (BS 8110 (400/d)^1/4) |
| `concreteMethods.ultimate.eccentricityMax`, `relations.ecmOffset` | e0 at most this; Ecm = offset + c (fcm/div)^e |
| `concreteMethods.deflection.tensionMoment`, `leverArm` | kt = a + (b - fs) / (c (d0 + M/bd²)) (BS 8110 Table 3.10) |
| `concreteMethods.columns.slenderness.unbracedLimit` | the short-column limit of sway storeys |
| `steelLimitState.compression.robertson`, `flexure.robertson` | the curves' constants as Robertson's a (α = a π √(E/fy) / 1000) |
| `steelLimitState.shear.yieldShare`, `designStrength` | shear yield = share × fy; py by thickness per grade |
| `seismic.designSpectrum.shapePlateau`, `descendingExponent`, `leastCoefficient` | the plateau, the power of TC/T and the least C/R of `reducedElastic` |
| `seismic.lateralForce.topForce` | Ft = factor T V at most maxShare V when T > periodFrom |

### Thin country packs (alpha 9 C23)

Small built-in packs that extend a family pack and set only what the country changes (each
pack's README and `VERIFY.md` are in `python/src/saengine/codes/packs/<id>/`; the Malaysian and
Singapore annexes are the National Annex packs above):

| Pack | Extends | What it sets |
| --- | --- | --- |
| `myanmar-mnbc` | `aci318-asce7-22` | MNBC 2020: towns with the zone, SS, S1 and V; Fa, Fv and site classes A-F; the 1.6W combinations and wind importance of the ASCE 7-05 form; ASCE 7-05 exposure constants; metric bars; SI |
| `bhutan` | `is-codes` | Towns with the IS seismic zone (IV west, V elsewhere) and Vb |
| `qatar-qcs` | `bs8110` | QCS 2014: towns with Vb (BS 6399-2), a coastal default terrain, the 'severe' exposure; no seismic loading |
| `hongkong-cop` | `bs8110` | HK CoP Wind 2019 pressures by height; HK CoP Concrete 2013 γm, stress block and x/d by grade, Ec, vc to C80, vmax 7 N/mm²; HK imposed loads; no seismic loading |

The generic keys they add, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `seismic.designSpectrum.siteCoefficients` (`fa`, `fv`) | Under `mappedSpectral`: SMS = Fa SS, SM1 = Fv S1 by site class (linear between the points) where SDS, SD1 and SMS, SM1 are not given; a site-study class is read as its assumed class |
| `locations.*.ss`, `s1`, `tl` | A town's mapped values, used where the project enters none (Site > Mapped spectral values win) |
| `wind.speedFactors.referencePressures` | By terrain, (height, kN/m²) points: pz = q(z) k1 k3 k4 (the factors on the pressure), the basic speed not used |
| `concreteMethods.ultimate.relations.<relation>.steps` | (fck up to, value) bands in place of base and the high relation (stress block depth, εcu, ...) |
| `concreteMethods.ultimate.neutralAxisSteps` | (fck up to, xu/d) bands of the neutral axis limit where the grade is known |

### Japan (alpha 9 C19)

`japan-bsl` (Building Standard Law Enforcement Order Art. 82-91, MOC/MLIT Notifications 1454,
1455, 1792, 1793, AIJ RC and steel standards) extends `aci318-asce7-22`; README and VERIFY.md
in the pack. The generic keys it adds, open to any pack (a pack without them behaves as before):

| Key | What |
| --- | --- |
| `seismic.designSpectrum.method` `standardShearCoefficient` with `shearCoefficient` | C = Z Rt C0 I / R (Rt of T and the site class's TC: plateau, parabolic transition, longFactor TC/T), C0 of the primary design and of the ultimate check (`fem/shear_coefficient.py`) |
| `seismic.lateralForce.distribution` `shearCoefficientAi` | storey shears Qi = V Ai αi, Ai = 1 + (1/√αi - αi) k T / (1 + m T) |
| `seismic.liveWeight` `byUse` with `areaLoads.uses[].seismicLive` | each use's live load counts in W as seismicLive / live |
| `liveReduction.method` `frameValue` with `areaLoads.uses[].frameLive` | beams and columns take frameLive / live of the floor's use |
| `wind.exposures.<id>.gustByHeight` | G by the building's height per exposure (`fem.loads.gust_factor`) |
| table `allowableStress` (method `elasticSection`) | long-term / short-term allowable stress rows of RC beams and columns (cracked elastic section, allowable shear with α) and steel members, under `combinations.allowable`, `longTerm` naming the long-term rows (`design/allowable_stress.py`) |
| table `horizontalCapacity` (method `requiredCapacity`) | Qu (pushover, at `capacityDrift`) >= Qun = Ds Fes Qud per storey; Ds by material, rank and βu; Fs, Fe of Rs, Re; member ranks and the mean shear strength (`fem/horizontal_capacity.py`, `design/member_rank.py`) |

### Canada and Mexico City (alpha 9 C17)

| Pack | Extends | What it sets |
| --- | --- | --- |
| `canada-nbcc` | `aci318-asce7-22` | NBCC 2020 Part 4: companion-load combinations, IE / IW / IS, the towns' Ss, Sr, q1/50 and (four cities) Sa(T); S = Is [Ss Cb Cw Cs + Sr]; Ce, Cg 2.0, Cp by H/D; V = S(Ta) Mv IE W / (Rd Ro) with its bounds, Ft, Ta, Rd / Ro and height limits; CSA A23.3-19 φc / φs, α1 / β1, Pr,max, the simplified (and general) shear method; CSA S16-19 column curve n = 1.34 and lateral-torsional buckling by Mu; bars 10M-55M; SI |
| `mexico-ntc` | `aci318-asce7-22` | NTC-CDMX 2017: 1.3 / 1.5 and 1.1 combinations, Wm, Group A × 1.5; the Mexico City zone spectra (I-IIId) reduced by Q' (and the 2017 site form with k and R); drifts Q × elastic; 1.5 es ± 0.1 b; CFE wind Frz by terrain category and the barometric G; NTC-Concreto FR; NTC-Acero column curve n = 1.4 and Mu; bars #2.5-#12; SI |

The generic keys they add, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `seismic.designSpectrum.ordinates` | Under `mappedSpectral`: S(T) from the site's (or town's) uniform hazard spectrum with the plateau max Sa(shortPeriods); SDS, SD1 of the bands = S(bandPeriods); V/W = S(T) Mv I/R, at least S(minimumPeriod of the system's higherModeGroup) Mv I/R, at most max(share S(T)) I/R of capShares for Rd >= capFromRd; Mv bilinear in higherMode by S(a)/S(b) and T |
| `seismic.designSpectrum.method` `ductilityOverstrength` (`ductility`) | Spectra by site class (a0, c, Ta, Tb, r; or k) reduced by Q' (system R = Q), the regularity factor and, with k, R = k1 R0(Q) + k2 |
| `seismic.systems.*.Rd`, `Ro`, `higherModeGroup` | A code's R as Rd Ro, the group of the higher mode table and the least period |
| `locations.*.spectrum`, `groundSnow`, `rainLoad`, `pressureFactor` | A town's Sa(T) points, ground snow, rain load and a factor on the velocity pressure (the speed × √factor) |
| `snow.rainShare` | Sr × share × Is added to the roof snow |
| `wind.exposures.*.kzFactor`, `kzMinHeight` | The power law's factor and least height of one exposure |
| `concreteMethods.shear` method `compressionField` | Vr = φc λ β √f'c bw dv + φs Av fy dv cot θ / s <= share φc f'c bw dv, β and θ simplified (or general from εx) |
| `steel.memberMethods.columnCurve` `powerCurve`, `curveExponent` | Fcr = Fy (1 + λ^2n)^(-1/n) with n by section family |
| `steel.memberMethods.lateralTorsional` `criticalMoment`, `ltbCurve`, `omega2Max` | Mu = ω2 π/L √(E Iy G J + (π E/L)² Iy Cw); a Mp (1 - b Mp/Mu) <= Mp above c Mp, else Mu |

### Australia and New Zealand (alpha 9 C18)

| Pack | Extends | What it sets |
| --- | --- | --- |
| `australia-as` | `bnbc2020` | AS/NZS 1170.0 importance levels and combinations (1.35G, 1.2G + 1.5Q, 1.2G + ψc Q + Wu, 0.9G + Wu, G + ψE Q + Eu), AS/NZS 1170.1 imposed actions and ψa; AS/NZS 1170.2:2021 VR by region and annual probability, Mz,cat TC1-TC4, Md, Ms, Mt; AS 1170.4 Z of the towns, kp, classes Ae-Ee with Ch(T), μ and Sp, V = kp Z Ch(T1) Sp/μ W, T1 = 1.25 kt hn^0.75, 1.5 % drift; AS 3600:2018 φ by kuo, α2 and γ, α1, beam shear by kv and θv, Ec, deflection, bars N10-N40; AS 4100:2020 φ 0.9, λe classes, αc with αb, αm αs; SI |
| `newzealand-nzs` | `australia-as` | NZS 1170.5 Z of the towns, R by importance level, classes A-E with Ch(T), N(T,D), Sp and kμ from μ, the least Cd, Ft = 0.08 V, 2.5 % drift; NZS 3101:2006 A3 φ 0.85 / 0.75, the axial cap 0.85 φ N0, α1 and β1, vc = (0.07 + 10 ρw) √f'c, Ec 4700 √f'c, bars HD10-HD40; NZS 3404 members as AS 4100; wind regions NZ1-NZ4; SI |

The generic keys they add, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `seismic.designSpectrum.method` `shapeFactors` (`shapeFactors`) and `seismic.siteClasses.*.shape` | Cd(T) = (Z I) Ch(T) N(T,D) Sp / kμ with R standing for μ: Ch(T) from the class's branches (a + b T + c (t0/T)^n <= most), Sp of (μ, Sp) points, kμ = μ or (μ - 1) T / ductilityPeriod + 1 (soft classes their own), Z I within hazardMin / hazardMax, least (leastZShare Z + leastOffset, leastFloor) × I, Nmax(T) within faultDistance |
| `materials.stressBlock` (`alpha`, `gamma`, `squash`) | The strength design's block stress α f'c over γ c and the squash share of P0, each linear in f'c within bounds (empty: 0.85 f'c over β1 c) |
| `factors.phiTransition` `neutralAxisDepth` | φ = intercept - slope kuo within the compression and tension φ (empty: ACI's interpolation by εt) |
| `factors.axialCap` | φPn,max = share φ P0, tied and spiral (empty: 0.80 / 0.85) |
| `concrete.shearStress` | vc = min(max(base + ratioFactor ρw, least), most) λ √f'c of beams (empty: ACI 318 Table 22.5.5.1) |
| `concreteMethods.shear.betaNoStirrupsMax` | The compression field method's β without the least links at most this |
| `steelLimitState.compression.slendernessReduction` | αc by λn = (KL/r) √kf √(fy/fref), αa, αb of the curve, η and ξ (AS 4100 6.3.3 form) in place of χ |
| `steelLimitState.flexure.slendernessReduction` | Mb = c1 αs Ms <= Ms, αs = share [√((Ms/Mo)² + offset) - Ms/Mo] (AS 4100 5.6.1.1 form) in place of χLT |

### China (alpha 9 C20)

| Pack | Extends | What it sets |
| --- | --- | --- |
| `china-gb` | `bnbc2020` | GB 55001-2021 combinations (1.3G + 1.5Q, ψc 0.7 / 0.6) and GB 55002-2021 1.3(G + 0.5Q) + 1.4E; GB 50009-2012 live loads (2021 values), the reduction by floors, wk = βz μs μz w0 with μz of A-D, μs 0.8/-0.5, βz >= 1.2, roof snow μr s0, 37 cities with w0, s0, intensity and design group; GB 50011-2010 αmax frequent and rare, Tg by group and site class I0-IV, the influence coefficient spectrum with η1, η2, γ, Geq = 0.85 GE, Fi ∝ Gi Hi, λ, drift 1/550-1/1000, the rare earthquake's elasto-plastic drift by ηp, seismic grades 一-四; GB 50010-2010 fc = fck/1.4 C20-C80, α1 β1 εcu, 0.9(fc A + fy' As'), 0.7 ft b h0 + fyv Asv h0/s, bars Φ6-Φ40; GB 50017-2017 f = fy/γR, S1-S5, φ of classes a-d, γx 1.05; SI |

The generic keys it adds, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `seismic.designSpectrum.method` `influenceCoefficient` (`influence`) | Sa = Z I/R × α(T)/αmax with Z holding αmax: riseStart at T = 0 to η2 at risePeriod, η2 to Tg (the class's TC), η2 (Tg/T)^γ to tailFrom Tg, η2 (1/tailFrom)^γ - η1 (T - tailFrom Tg) to longest; γ, η1, η2 = base + (ref - ζ)/(a + b ζ) >= least; the rare earthquake's αmax by zone and its Tg increase |
| `locations.*.spectrumType` | The town's `seismic.spectra` id (GB's design earthquake group), applied as `seismic.spectrumType` unless the project overrides it |
| `seismic.driftLimits[].groups` | A drift row for the systems of these groups (`systems.*.group`) |
| `seismic.rareDrift` (`amplifiedElastic`) | Δup = ηp Δue, Δue = the response spectrum drift × α_rare(T1)/α(T1), ηp by group, storeys and ξy, at most [θp] h by group; in the seismic design summary (`rareDrift`) and its notes |
| `seismic.seismicGrades` | The grade by the zone's intensity column (raised by occupancy category), the system's group and the height; its level and factors in the summary (`seismicGrade`) and notes |
| `steelLimitState.compression.perry` | A buckling curve by its Perry constants: φ = 1 - a1 λn² to the plateau, else [(a2 + a3 λn + λn²) - √((a2 + a3 λn + λn²)² - 4 λn²)] / (2 λn²) |

The C20b remainder adds these generic keys (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `concreteMethods.ultimate.designYields`, `axialYieldShare` | fyd tabulated by fyk (GB 50010 Table 4.2.3-1 type) in place of fyk/γs; the axial cap's steel term on fyd |
| `concreteMethods.torsion` `plasticModulus` | Torsion on Wt = b²(3h - b)/6 with the concrete's share × βt, closed links for T and V, Astl (`design/plastic_torsion.py`) |
| `concreteMethods.punching` `rootStress` with `strength: "tensile"` | c βh fctd η, η = min(ratioBase + ratioFactor βc, a + αs d/(b b0)), βh by depth |
| `concreteMethods.cracking` `effectiveTensionRatio`, `deflection` `longTermStiffness` | wmax = αcr ψ σs/Es (c1 cs + c2 deq/ρte) and B = Bs/θ under Mq (`design/tension_stiffening.py`) |
| `concreteMethods.cover.conditions.*.beamCover`, `anchorage.lapFactors` (`minLength`, `largeBarFactor`, `lapMinLength`, `columnLapShare`) | Beams' and columns' own cover; la = ζa lab >= floor, laps ζl la, la,E = ζa,E la (the seismic grade's `anchorage` factor) |
| `concreteMethods.memberLimits.beamMinRatio` (`beamMinTensile`, `slabMinTensile`, `sideFaceEach`) | Least steel max(ratio, c fctd/fyd) on b h; side bars per face |
| `concreteMethods.columns.slenderness` `endMomentMagnifier` | M = Cm ηns M2 from the signed end moments, with the exemption by M1/M2, N/(fc A) and lc/i (`design/end_moment_magnifier.py`) |
| `concreteMethods.shearSpanWalls` `shearSpanRatio` | Wall shear 1/(λ - c) (a ft t h0 + b N) + c' fyv Ash h0/sv, its seismic terms (`design/shear_span_walls.py`) |
| `seismic.gradeDesign` `gradeFactors` and `seismicGrades.grades.*.detailing` | The grade's ηc, ηvc, ηvb, ηvw on the earthquake part of the forces, γRE on the earthquake combinations, the checks of μN, λv, end zones and least steel (`design/seismic_grades.py`) |
| `seismic.lateralForce.topForce.cornerFactor`, `offsets` | Ft = (factor T + offset by TC) V where T > cornerFactor TC (GB δn) |
| `seismic.verticalComponent` `gravityShare` | Ev / G by zone, × combinationShare on D in the response spectrum combinations |
| `steelLimitState.connections` `designShear`, `designTension`, `pretension`, `bearingStrength`, `slipFactor`, `welds.filletStrengths` | Bolt and weld strengths tabulated by grade and electrode in place of the partial-factor formulas |
| `steelLimitState.seismic.gradeFrames` | The steel seismic frame kind by the building's seismic grade |
| `foundations.shallow.widthDepthCorrection`, `layerwiseSettlement` | fa = fak + ηb γ (b - b0) + ηd γm (d - d0) of a qa given without a soil report; s = ψs Σ p0/Es (z ᾱ) (`soil/characteristic_bearing.py`) |

### Turkey, Nepal and Sri Lanka (alpha 9 C21)

| Pack | Extends | What it sets |
| --- | --- | --- |
| `turkey-tbdy` | `aci318-asce7-22` | TBDY 2018: DD-2 SS, S1 of example cities (site-specific: the AFAD map), site classes ZA-ZF with FS, F1, the horizontal spectrum with TL = 6 s, BKS 1-3 (I 1.5, 1.2, 1.0), DTS by SDS (categories D, C, B), R and D of Tablo 4.1 with Ra(T), ΔFN = 0.0075 N Vt, Vt ≥ 0.04 I SDS W, γE 0.80, λ δ/h ≤ 0.008 κ / 0.016 κ, BYS 1-8 and the tall building (BYS 1) performance-based requirement, 11-record suites; TS 500 / TBDY 4.4.4 combinations; TS 500 concrete (γmc 1.5, γms 1.15, k1, Vc = 0.8 Vcr, punching, minimum steel) with TBDY Bolum 7 ductile detailing; Ø8-Ø32 bars; DD-2 / DD-1 pushover hazard levels; SI |
| `nepal-nbc` | `is-codes` | NBC 105:2020: Z of 14 municipalities (0.25-0.40), soil types A-D with Ch(T), I 1.0 / 1.25 / 1.5, Cd(T) = Ch(T) Z I / (Rμ Ωu), T1 = 1.25 kt H^0.75, ULS drift 0.025; the NBC 105 3.6 combinations; IS 456 concrete and IS 800 steel from the parent; SI |
| `srilanka` | `eurocodes` | The Sri Lankan wind zones 1-3 (49, 43, 33 m/s gusts as vb,0 by 1/1.53) for 16 towns; no seismic design (zone 0); the Eurocodes' recommended values for the rest |

The generic keys they add, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `seismic.designSpectrum.shortPeriodReduction` (method `overstrengthRamp`) | Under `mappedSpectral`: Ra(T) = D + (R/I - D) T/TS below TS, R/I beyond, D the system's Omega0; the design spectrum Sa/Ra and the equivalent static Sa(T)/Ra(T) within `csLimits` |
| `seismic.driftLimits[].concrete` | A drift row for concrete (true) or other (false) systems only |
| `seismic.driftServiceRatio` (`value`, `label`) | The drift limits divided by λ (λ δ/h ≤ limit) |
| `seismic.performanceBased` | Height classes by the building's height and the category's column, and the rules (classes or categories) that require a performance-based design with their objectives (hazard, level, procedure: linear, strength, pushover, nonlinearHistory), reported in the analysis notes (`fem/performance_requirements.py`) |
| `seismic.lateralForce.topForce.storeyFactor` | Ft = storeyFactor × N × V at the top, N the number of levels (periodFrom, factor, maxShare now optional) |
| `seismic.siteClasses.*.shape[].c2`, `n2` | A second power term c2 (t0/T)^n2 of a spectral shape branch |

### Russia and the CIS (alpha 9 C25)

| Pack | Extends | What it sets |
| --- | --- | --- |
| `russia-sp` | `bnbc2020` | SP 20.13330.2016: the first and second limit state groups as the strength and service combinations, γf (1.1 / 1.3 / 1.4 / 1.4), ψt 1.0 / 0.9 / 0.7, the floor live loads of Table 8.3 with ψA1 and ψn1, the snow regions I-VIII (S0 = μ Sg), the wind regions Ia-VII with k(ze) of terrain A-C, ze by the proportions and the pulsation ζ ν; SP 14.13330.2018: 25 cities with the OSR-2015 intensities on the maps A, B, C (the map by the occupancy), soil categories I-IV with β(T) and the one-point shift, Sik = K0 K1 A β Kψ ηik (K0 as the importance, R = 1/K1), ηk of a linear mode, the special combination 0.9 / 0.5, the close-mode combination, height limits by intensity; SP 63.13330.2018: Rb, Rbt, Eb of B15-B60 with γb1, Rs of A240 / A400 / A500C, the rectangular block with ξR or the nonlinear deformation model, shear by the inclined section, punching, cracks, deflection, cover, anchorage and laps, least steel, bars Ø6-Ø40; SP 16.13330.2017: Ry of C245-C390 with γm, φ of the curves a, b, c; SP 22.13330.2016: the design resistance R; SI |

The generic keys it adds, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `locations.*.mapZones` with `seismic.hazardMaps` (`maps`, `default`, `byOccupancy`) | The town's zone on the hazard map of the project's occupancy category (OSR-2015 A, B, C type), in `derived` (`hazardMap` in the values) |
| `seismic.lateralForce.correctionMethod` `linearMode` | The static base shear × (Σ W h)² / (Σ W Σ W h²), the share of a linear first mode (SP 14 ηk) |
| `wind.referenceHeight` `proportions` | The windward wall at ze of h and the windward width (h <= b, b < h <= 2b, h > 2b) under `powerLaw` |
| `wind.pulsation` (`rho`, `chi`, `values`) with `exposures.*.pulsationZeta` | G(z) = 1 + ζ(ze) ν in place of the gust factor, ζ = pulsationZeta (z/zg)^(-1/α), ν of the table by the windward width and the height |
| `concreteMethods.ultimate.designStrengths` | (fck, fcd, fctd, Ecm) rows: the code's rounded design strengths by class (× αcc, αct) in place of fck/γc and the relations |
| `concreteMethods.ultimate.cubePrefix` | Classes named by the cube strength ("B25") |
| `concreteMethods.ultimate.stressBlock` `bilinear`, `trilinear` | The two- and three-linear diagrams of a nonlinear deformation model, integrated over the section's mesh (the section in equilibrium under a plane strain distribution) |
| `concreteMethods.shear.inclinedSection` (method `qbQsw`) | Beam shear Q <= Qb + Qsw at the projection c giving the least (Qb = φb2 fctd b h0²/c within bounds, Qsw = φsw qsw c0), the strut φb1 fcd b h0; Design Reinforcement inverts it |
| `concreteMethods.shear.stirrupYieldShare`, `stirrupYieldMax` | The links' design yield × share, at most the cap (Rsw = 0.8 Rs <= 300 MPa) |
| `foundations.shallow.designResistance` (method `frictionAngleFactors`) | R = γc1 γc2 / k (Mγ kz b γ + Mq d γ' + Mc c) of the soil report's founding layer, qa = R - σv, in place of the bearing capacity over FS |

### Group 2 country packs (alpha 9 C24)

| Pack | Extends | What it sets |
| --- | --- | --- |
| `korea-kds` | `aci318-asce7-22` | KDS 41 17 00:2019: zones I / II as SS = 2.5 S, S1 = S (S 0.22, 0.14) for 13 towns, site classes S1-S6 with Fa, Fv by S, importance 1.5 / 1.2 / 1.0; the base pack's ASCE 7 spectrum, R, Cd, Ω0 and drift; wind V0 × 1.43 on the base pack's method; KDS 14 20 φ (0.85 tension, 0.70 spirals, 0.55 plain); bars D10-D32; SI |
| `iran-2800` | `aci318-asce7-22` | Standard 2800 (4th ed.): A 0.35-0.20 by zone for 14 towns, soil types I-IV with B = B1 N (site classes for zones 1-2 and 3-4), I 0.8-1.4, C = A B I / Ru ≥ 0.12 A I, Ru / Ω0 / Cd, T = 0.05 H^0.9 ...; INBC Part 9 φc 0.65, φs 0.85 on the materials; bars Φ8-Φ32; placeholder wind speeds; SI |
| `peru-e030` | `aci318-asce7-22` | E.030 2018: Z 0.45-0.10 for 14 towns, soil profiles S0-S3 with S by zone, TP, TL, C(T), U 1.5 / 1.3 / 1.0, R0, C/R ≥ 0.11, T = hn/CT, drift 0.007 / 0.010 / 0.005 with 0.75 R; E.060 combinations (1.4D + 1.7L ...) and φ (0.70 tied, 0.85 shear); inch bar names; SI |
| `chile-nch` | `aci318-asce7-22` | NCh 433 + DS 61: A0 0.20-0.40 g for 14 towns, soil types A-E with S, T0, p, α(T), R* = 1 + T/(0.10 T0 + T/R0), Cmin = A0 S/6g, Cmax by R, drift 0.002 under the design forces, I 0.6-1.2; NCh 3171 combinations (1.4E); DS 60 wall boundary trigger (δu/hw ≥ 0.007); bars Ø8-Ø36; SI |
| `brazil-nbr` | `aci318-asce7-22` | NBR 15421: ag of 14 towns as SS = 2.5 ag, S1 = ag with Ca, Cv (no 2/3), Cs ≥ 0.01, Cup; NBR 6123: V0, S2 = b Fr (z/10)^p of categories I-V, S3, q = 0.613 Vk² (speedFactors); NBR 8681 combinations; NBR 6118 γc 1.4, γs 1.15, 0.85 fcd over 0.8 x, shear model I; bars Ø5-Ø40; SI |
| `egypt-ecp` | `bs8110` | ECP 201-2012: ag 0.10-0.30 g (zones 1-5B) for 14 towns, the EN 1998-1 type spectrum (behaviourFactor) with two spectrum types, γI 0.8-1.4, R, λ 0.85; ECP 203 combinations; ECP 203 concrete on the parent's BS 8110 methods (γs 1.15, 0.67 fcu/1.5 over 0.8 c, Ec 4400 √fcu, short columns 0.35 fcu Ac + 0.67 fy As, shear qcu / qmax); bars Ø8-Ø32; SI |
| `southafrica-sans` | `eurocodes` | SANS 10160: vb,0 and ag of 14 towns, ground types 1-4 (one spectrum), the STR combinations as the strengthSets "sans"; SANS 10100-1 αcc 0.85 on the parent's EN 1992-1-1; SANS 10162-1 not covered (EN 1993-1-1); SI |

The generic keys they add, open to any pack (a pack without them behaves as before):

| Key | What it does |
| --- | --- |
| `seismic.siteClasses.*.shape[].d`, `m` | The branch divided by 1 + d (t0/T)^m; a negative power (n, n2, m) is a power of T/t0 and its term is 0 at T = 0 (NCh 433 α) |
| `seismic.designSpectrum.shapeFactors.ductilityForm` "periodRatio" with `ratioShare`, `ratioPeriods` | kμ = 1 + T / (ratioShare T0 + T/μ), T0 by site class (NCh 433 R*) |
| `seismic.designSpectrum.shapeFactors.soilFactors` | The soil factor S on Cd by site class and the site's Z, as (Z from, S) steps (E.030 Table 3) |
| `seismic.designSpectrum.shapeFactors.leastSoilShare` | Cd at least this × Z I S (E.030 C/R ≥ 0.11, NCh 433 Cmin) |
| `seismic.designSpectrum.shapeFactors.capByDuctility` | (μ, share): Cd at most share × Z I S (NCh 433 Cmax) |

## Other package kinds

The same `pack.json` and the same registry hold the other packages of the marketplace
([marketplace-plan.md](marketplace-plan.md)); `kind` says which:

| Kind | Holds | Checked against | User folder |
| --- | --- | --- | --- |
| `designCode` (default) | `data/<table>.json` | the table models | `%APPDATA%\SAEngine\code-packs\` |
| `structureTemplate` | `templates/*.json`: presets of a built-in shape (`{"name": "Warren truss 24 m", "shape": {"kind": "planeTruss", ...}}`) | the Generate panel's shape model (`structure-template.schema.json`) | `%APPDATA%\SAEngine\packages\structure-templates\` |
| `buildingTemplate` | `spec.json` (a New Building specification) or `template.civil` (an inputs-only project) | the generator's `BuildingSpec` (`building-template.schema.json`), the archive check | `%APPDATA%\SAEngine\packages\building-templates\` |

Templates are installed for the user only (applying one copies it into the project), take no
`extends`, and share the built-in folder and the trust of hooks with design codes. Ids are one
namespace across kinds. Applying templates (the Generate panel, the New Project wizard) comes in
a later round; for now they are listed, validated and installed:
`saengine codepack list --kind all`, `saengine codepack validate <folder> --kind structureTemplate`.

A full building template (`template.civil`) must hold inputs only: an archive with results, a
soil report (`01 Soil Report`), deliverables (`11 Exports`) or the version history (`.git`) is
refused by `validate` and by the install.

SAEngine ships one template package built in: `saengine-shapes`, the presets of the six
parametric shapes (their Generate panel starting values, which the tests keep equal to the
panel's, and a few named variants). It and BNBC 2020 are also published, as read-only mirrors, in
the marketplace's package repositories: edit them here and copy them there with
`scripts/marketplace/mirror_packages.py` (the repositories' CI refuses a mirror that differs from
the SAEngine commit it names).

## Command reference

| Command | What it does |
| --- | --- |
| `saengine codepack list [--kind KIND\|all] [--root PROJECT]` | The installed packs: built-in, user, and the project's with `--root`; design codes unless `--kind` says otherwise. |
| `saengine codepack show <id or folder> [--kind KIND] [--root PROJECT]` | A pack's details: inheritance, tables (own or inherited) with their clauses, requires, contents, hooks and trust, problems. |
| `saengine codepack new <id> --dest <dir> [--name N] [--extends bnbc2020] [--edition E] [--country C] [--author A]` | Creates `<dir>/<id>/`, a pack that extends `--extends` (`--extends ""` for none). |
| `saengine codepack validate <folder> [--kind KIND] [--root PROJECT]` | Checks a pack; exit code 1 when it has errors, or with `--kind` when it is of another kind. |
| `saengine codepack check <id or folder> [--root PROJECT]` | The conformance checks every pack must pass (covers, sources, clause ownership, earthquake and wind combinations or `notCovered`, bar names and masses, verification stated); exit code 1 when it does not conform. |
| `saengine codepack diff <a> <b> [--root PROJECT]` | The differences of two packs (ids or folders), table by table and key by key: `+` only in b, `-` only in a, `~` changed. |

`saengine package ...` is the same command. Every command takes `--json` (one JSON document on stdout, as the other `saengine` commands)
and `-q`. Exit codes: 0 ok, 1 the pack has errors (`validate`), 2 usage (unknown pack, bad id,
existing folder), 3 error. `check` exits 1 when the pack does not conform.
