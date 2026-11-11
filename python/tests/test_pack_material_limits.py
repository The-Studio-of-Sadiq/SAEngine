"""Owner decision 2026-11-12: every code pack sets its own input limits on materials
(``materials.structuralFcMin``: below it the f'c guardrail warns; ``materials.rebarFyMax``: above
it the fy guardrail blocks) from its own design code, and no pack's materials table shows the
default pack's (BNBC 2020) text.

A pack may take the two limits from a parent of the same code family only (the Eurocode
National Annex packs from ``eurocodes``, the Indian-Standards countries from ``is-codes``, Qatar
from ``bs8110``).
"""

from __future__ import annotations

import re

import pytest

from saengine.codes import registry

#: The default pack and its older edition: the only packs that may cite BNBC.
BNBC_FAMILY = {"bnbc2020", "bnbc2006"}
#: Packs that take the limits from a parent of the same code family (the parent's name).
SAME_FAMILY = {
    "eurocodes-de": "Eurocodes",
    "eurocodes-my": "Eurocodes",
    "eurocodes-sg": "Eurocodes",
    "eurocodes-uk": "Eurocodes",
    "srilanka": "Eurocodes",
    "bhutan": "Indian Standards",
    "nepal-nbc": "Indian Standards",
    "qatar-qcs": "British Standards",
}
DEFAULT_TEXT = re.compile(r"BNBC|Part 6|Bangladesh|BDS")


def _building_packs() -> list[str]:
    return sorted(
        {
            info.id
            for info in registry.list_packs()
            if info.scope == "builtin" and registry.load(info.id).has("materials")
        }
    )


PACKS = _building_packs()


def test_every_pack_is_listed() -> None:
    assert len(PACKS) >= 30
    assert {"aci318-asce7-22", "eurocodes", "is-codes", "china-gb"} <= set(PACKS)


@pytest.mark.parametrize("pack_id", PACKS)
def test_pack_sets_its_own_material_limits(pack_id: str) -> None:
    pack = registry.load(pack_id)
    assert not pack.broken
    materials = pack.table("materials")
    assert materials.structuralFcMin is not None and materials.structuralFcMin > 0
    assert materials.rebarFyMax is not None and materials.rebarFyMax > 0
    for key in ("structuralFcMin", "rebarFyMax"):
        assert materials.sources.get(key), (pack_id, key)
    # The pack's own bar grades are never refused by its own limit.
    for grade in materials.rebarGrades:
        assert grade.fy <= materials.rebarFyMax, (pack_id, grade.id)
    inherited = pack.inherited_from("materials")
    if pack_id in SAME_FAMILY:
        assert inherited == SAME_FAMILY[pack_id], pack_id
    else:
        assert inherited is None, (pack_id, inherited)


@pytest.mark.parametrize("pack_id", [p for p in PACKS if p not in BNBC_FAMILY])
def test_materials_table_never_names_the_default_pack(pack_id: str) -> None:
    dumped = repr(registry.load(pack_id).table("materials").model_dump())
    found = DEFAULT_TEXT.findall(dumped)
    assert not found, (pack_id, found)


def test_limits_of_the_main_codes() -> None:
    expected = {
        "bnbc2020": (17.0, 550.0),
        "aci318-asce7-22": (17.0, 690.0),
        "eurocodes": (12.0, 600.0),
        "eurocodes-uk": (12.0, 600.0),
        "australia-as": (20.0, 500.0),
        "canada-nbcc": (20.0, 500.0),
        "brazil-nbr": (20.0, 600.0),
        "bs8110": (25.0, 500.0),
        "is-codes": (20.0, 600.0),
        "china-gb": (13.4, 500.0),
    }
    for pack_id, (fc, fy) in expected.items():
        materials = registry.load(pack_id).table("materials")
        assert materials.structuralFcMin == pytest.approx(fc), pack_id
        assert materials.rebarFyMax == pytest.approx(fy), pack_id
    aci = registry.load("aci318-asce7-22").table("materials").sources
    assert "Table 19.2.1.1" in aci["structuralFcMin"]
    assert "Table 20.2.2.4(a)" in aci["rebarFyMax"]
