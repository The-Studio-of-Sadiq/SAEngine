# Dhaka 6-storey residential, 3 × 2 bays

The first spec template, built into SAEngine: the New Building wizard starts from it (the wizard
has no starting values of its own). It is a building specification (`spec.json`, SAEngine's
`BuildingSpec`); applying it prefills the wizard, and the generator builds the floor plan and
sizes the members. The package repository `saengine-building-templates` publishes a read-only
mirror of this folder.

| | |
| --- | --- |
| Grid | X: 3 × 6000 mm, Y: 2 × 5000 mm |
| Storeys | 6: ground 3600 mm, typical 3200 mm |
| System | RC frame, isolated footings |
| Materials | concrete C27.6, bars B420DWR (Grade 500 is not allowed in special frames, BNBC 2020 Part 6 Sec 8.3.3.4(b)) |
| Site | Dhaka, site class SD assumed until a soil report gives one |
| Use | residential, occupancy category II |

Needs the BNBC 2020 design code package. Licence: CC-BY-4.0.
