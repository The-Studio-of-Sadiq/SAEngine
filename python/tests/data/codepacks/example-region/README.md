# Example region

An example code pack for docs/code-packs.md and the tests. It extends `bnbc2020` and changes:

- `locations`: adds two invented towns (Northford, Saltmarsh) and changes Chattogram's basic
  wind speed to 82 m/s; Chattogram's seismic zone and every other town come from BNBC 2020.
- `combinations`: replaces the strength combination `1.2D + 1.0E + 1.0L` by
  `1.2D + 1.0E + 0.5L`.

The values are invented. Do not use this pack for design.

Check it with `saengine codepack validate python/tests/data/codepacks/example-region`, and see
what it changes with `saengine codepack diff bnbc2020 python/tests/data/codepacks/example-region`.
