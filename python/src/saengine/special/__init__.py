"""Bridges and special structures (alpha 9 track L9).

The structures entered in Project Settings → Bridges and Special Structures
(:mod:`saengine.library.special_structures`), each computed with the project's code pack:

- :mod:`saengine.special.moving_loads`: traffic load models moved along influence lines (and the
  lanes of a deck grillage's influence surfaces), the envelope of their effects with the dynamic
  allowance and the multiple presence factors;
- :mod:`saengine.special.bridges`: girder bridges (line girders or a deck grillage), the girders'
  strength and service checks by the pack's concrete methods, bearings, expansion joints and
  load rating;
- :mod:`saengine.special.towers`: lattice towers under wind by the faces' solidity, their member
  checks, and the wind of rooftop towers on the building;
- :mod:`saengine.special.shells`: silos (Janssen), chimneys (along-wind and vortex shedding) and
  cooling towers (a shell of revolution under the wind's pressure distribution);
- :mod:`saengine.special.offshore`: fixed jackets and monopiles under waves (Airy, stream
  function), current and wind by Morison's equation;
- :mod:`saengine.special.piping`: pipe runs under sustained, thermal and occasional loads, their
  stresses against the pack's piping allowables and the nozzle loads;
- :mod:`saengine.special.frame`: the linear 3D frame analyses they share (OpenSeesPy, the engine
  of the building's analysis), :mod:`saengine.special.project`: the project's run, the report
  section and the bill of quantities.
"""
