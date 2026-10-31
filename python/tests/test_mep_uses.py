"""One storey-use table for the plumbing, HVAC and electrical services (07 MEP storyUses)."""

from __future__ import annotations

import json

from saengine.electrical import tables as E
from saengine.hvac import tables as H
from saengine.library.mep import parse
from saengine.mep.uses import STORY_USES
from saengine.plumbing import tables as P


def _mep(**extra):
    return parse(json.dumps({"schema": "saengine.mep/1", **extra}))


def test_every_use_maps_to_a_row_of_each_table() -> None:
    for key, use in STORY_USES.items():
        if use.plumbing is None:
            assert key in ("roof", "services")
            continue
        assert use.plumbing in P.OCCUPANCY_KEYS
        assert use.hvac in H.VENTILATION_KEYS
        assert use.electrical in E.USE_KEYS


def test_one_use_sets_all_three_services_and_the_roof_is_left_out() -> None:
    mep = _mep(
        storyUses=[
            {"story": "L1", "use": "office", "population": 40},
            {"story": "L2", "use": "parking"},
            {"story": "R", "use": "roof"},
        ],
        plumbing={"stories": [{"story": "L1", "fixtures": {"wc": 4}}, {"story": "R"}]},
        hvac={"stories": [{"story": "R", "use": "officeSpace"}]},
        electrical={},
    )
    plumbing = {s.story: s for s in mep.plumbing.stories}
    hvac = {s.story: s for s in mep.hvac.stories}
    electrical = {s.story: s for s in mep.electrical.stories}
    assert set(plumbing) == set(hvac) == set(electrical) == {"L1", "L2"}
    # The service's own entries are kept (fixtures); the use and population come from the table.
    assert plumbing["L1"].occupancy == "office" and plumbing["L1"].population == 40
    assert plumbing["L1"].fixtures.wc == 4
    assert hvac["L1"].use == "officeSpace" and hvac["L1"].occupants == 40
    assert electrical["L1"].use == "office"
    # Parking is not air-conditioned by default.
    assert hvac["L2"].use == "parkingGarage" and not hvac["L2"].conditioned


def test_without_the_table_or_a_service_nothing_changes() -> None:
    mep = _mep(plumbing={"stories": [{"story": "L1", "occupancy": "hotel"}]})
    assert mep.plumbing.stories[0].occupancy == "hotel"
    mep = _mep(storyUses=[{"story": "L1", "use": "office"}])
    assert mep.plumbing is None and mep.hvac is None and mep.electrical is None
