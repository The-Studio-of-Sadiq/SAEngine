"""R2-8 (re-walk 2): the design proposal checks the anchorage the drawings check. After Apply
the Sample Frame's drawings reported "C1: Column bars into foundation 410.66 needed, 401
provided" and "S2: Top X bars Ø10 hooked into the edge support W1: 205.3 needed, 180
provided". As for the beams (OI-1), the proposal now limits the slab's top bars to the sizes
whose hooks develop in the edge supports, and says how deep the foundation under a column must
be for the column's bars (the column's bars carry its forces: they are not made smaller)."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.design import proposal as P
from saengine.design.required import Options
from saengine.drawings.detailing import anchorage_rooms, hook_development
from saengine.library.bim import BuildingModel
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


def _read(relative: str) -> str:
    return (SAMPLE / relative).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sample() -> SimpleNamespace:
    building = BuildingModel.model_validate_json(_read("06 BIM/bim.json"))
    objects = ObjectLibrary.model_validate_json(_read("04 Objects/objects.json"))
    materials = MaterialLibrary.model_validate_json(_read("03 Materials/materials.json"))
    settings = ProjectSettings.model_validate_json(
        _read("02 Project Settings/project-settings.json")
    )
    rooms = anchorage_rooms(
        building, objects, materials, settings, _read("09 Substructure/substructure.json")
    )
    return SimpleNamespace(
        building=building, objects=objects, materials=materials, settings=settings,
        rooms=rooms, root=SAMPLE, collect={"members": []},
    )  # fmt: skip


def test_rooms_are_the_drawings_supports_and_foundations(sample) -> None:
    c1 = sample.rooms["columns"]["C1"]
    assert (c1["foundation"], c1["thickness"], c1["cover"], c1["mesh"]) == ("F1", 500, 75, 12)
    # S2's X edge rests on the 200 mm wall W1 (no slab beyond it); its Y edges on beams.
    assert sample.rooms["slabs"]["S2"]["X"] == [(200.0, math.inf, "W1")]


def test_slab_top_bars_are_limited_to_hooks_that_develop(sample) -> None:
    slab = next(o for o in sample.objects.objects if o.id == "S150")
    opts = Options.of({})
    designer = P.SlabDesigner(slab, 24.1, 420.0, 200000.0, opts)
    supports = {d: [(*f, "S2") for f in found] for d, found in sample.rooms["slabs"]["S2"].items()}
    designer.limit_top_bars(supports)
    room = 200 - 20  # W1 less the slab's cover
    assert hook_development(10, 420, 24.1).value == pytest.approx(205.3, abs=0.1)
    assert room < 205.3
    assert min(opts.slab_diameters) == 10
    # No slab bar's hook develops in W1: said, with the width it would need.
    assert "topX" not in designer.top_sizes
    assert designer.anchorage_notes[0] == (
        "topX bars hooked into the edge support W1 of S2: even Ø10 needs ldh 205 mm, 180 mm "
        "there (its width less the cover): a wider support (at least 225 mm), or anchor the "
        "bars beyond it"
    )
    # The 300 mm edge beams hold Ø10 and Ø12 hooks (Ø16: 329 mm > 280 mm): the top Y bars keep
    # to those.
    assert hook_development(16, 420, 24.1).value > 280 >= hook_development(12, 420, 24.1).value
    assert designer.top_sizes["topY"] == tuple(d for d in opts.slab_diameters if d <= 12)
    assert designer.anchorage_notes[1].startswith("topY bars at most Ø12: the hooks of Ø16")


def test_column_bars_into_the_foundation_ask_for_a_deeper_footing(sample) -> None:
    entry = {
        "type": "C400x600",
        "kind": "column",
        "members": ["C1"],
        "proposed": {"longitudinal": [{"position": "perimeter", "count": 10, "dia": 20}]},
        "notes": [],
    }
    warnings = P._column_anchorage([entry], sample.rooms, sample, Options.of({}))
    # ldh of Ø20 in C24.1: 0.24 x 420 x 20 / √24.1 = 410.6 mm; F1 gives 500 - 75 - 2 x 12.
    (note,) = entry["notes"]
    assert "C1 needs ldh 411 mm in F1, 401 mm there" in note
    assert "deepen F1 to at least 525 mm in 9 Substructure" in note
    assert "or use bars of at most Ø16" in note
    assert warnings == [f"C400x600: {note}"]
    # Bars that develop: no note.
    entry["proposed"]["longitudinal"][0]["dia"] = 16
    entry["notes"] = []
    assert not P._column_anchorage([entry], sample.rooms, sample, Options.of({}))
