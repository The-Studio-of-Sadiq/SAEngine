# Changelog

What changed in each release, for engineers. Each release's full notes and setup are on
[Releases](https://github.com/The-Studio-of-Sadiq/SAEngine/releases). SAEngine is pre-alpha:
check every result independently.

## Pre-Alpha 10 — 0.0.49 (13 Nov 2026)

The last pre-alpha. From here on releases are alpha.

- **The AI assistant builds and changes projects:** the SAEngine mode in the title-bar chat
  (GitHub Copilot sign-in or your own API key) creates a whole building from one prompt, runs it,
  designs it and writes the report, through the same 59 actions as the command line
  (`saengine action`) and scripts. Every change shows as a change set to accept or undo, every run
  asks first, and the AI is refused what the engineer would be refused. See the video in
  [videos/](videos/).
- **Shared actions:** `saengine action list|describe|run|batch`, the RPC and SDK 1.1.0.
- **Speed:** a 10-storey Run All down from 7.2 to 2.7 minutes (alpha 10, wave 1).
- **A clearer window:** the stage bar (Site & Soil › Model › Loads › Analysis › Design › Drawings ·
  BOQ · Report) showing done, out of date or failing; the model view in the centre, Properties on
  the right and Tables below, with one selection everywhere; VS Code's developer tools out of the
  way unless developer mode is on.
- **One New Project wizard** with the project, site and use, and the grid and storeys.
- **The new SAEngine logo and typography** across the app.
- **Trust:** impossible input refused with the reason; delete confirmation for important data; a
  consent dialog before any data goes to an AI provider; diagnostics off by default; Help › Report
  a Bug / Send Feedback, sent publicly as a GitHub issue or privately by e-mail.
- **Live co-editing:** several engineers in one part at once over a relay on the office network,
  with each colleague's selected members outlined on the plan in their colour.
- **Each code pack sets its own least f'c and greatest fy.**
- **Detailing:** one direction's bottom bars raised at crossing beam joints.
- **Fixes:** the engine no longer hangs on opening a project (a lock-order deadlock); the ≡ File
  menu opens on Windows; Properties shows the selection once and applies a field when you leave
  it; a rotated column's label is no longer drawn twice.

## Pre-Alpha 9 — 0.0.48 (11 Nov 2026)

The design code becomes a full setting: 34 code packs beside BNBC 2020 (ACI 318 + ASCE 7, the
Eurocodes with National Annexes, the Indian Standards and packs for 25 other countries and
legacy codes), display units per project (SI or US), base isolators and dampers, pushover
acceptance, nonlinear time history, staged construction with creep and shrinkage, assessment and
retrofit, and more exchange formats.

## Pre-Alpha 8 — 0.0.47 (3 Nov 2026)

Most of the remaining BNBC 2020 provisions; the design code as a setting with BNBC 2020 as the
default pack and every value overridable; shear walls in Design Reinforcement.

## Pre-Alpha 7 (29 Oct 2026)

The site plot on the map and the floor plan; bored piles with pile caps on their own pile grid; a
first architecture layer whose walls and rooms load the model and go into the bill. The release
check ran on a 10-storey building.

## Pre-Alpha 6 (28 Oct 2026)

The usability release: every screen walked as an engineer would, from the soil report to the
exports, and what got in the way fixed. Run All says exactly what it did and did not do.

## Pre-Alpha 5 — 0.0.42 (24 Oct 2026)

The structural office prototype: from the soil report to construction drawings, with design mode,
ductile detailing, walls, stairs, steel members, and imports from ETABS, STAAD.Pro and SAP2000.

## Pre-Alpha 4 — 0.0.34 (18 Oct 2026)

Building services in 7 MEP for the structural engineer who coordinates them: plumbing with the RC
tanks, HVAC loads with EnergyPlus, electrical loads.

## Pre-Alpha 3 (18 Oct 2026)

The chain from the ground up, from the soil report to the exports, with MEP coordination
(equipment loads, sleeves and openings, clash checks).

## Pre-Alpha 2 (17 Oct 2026)

A simpler, more minimal interface.

## Pre-Alpha (16 Oct 2026)

The first public build.
