"""Alpha 9 C11: the clause references of the RC frame and seismic detailing rows come from the
code pack in force (``designClauses.ductileMembersRows``, ``ductileJointsRows``,
``seismicDetailingRows``, ``seismicRulesRows``).

The default pack's (BNBC 2020) row names and notes are pinned against a snapshot taken from the
modules before the clauses moved into the pack (``data/detailing_clauses_bnbc2020.json``); the
US pack names ACI 318-19 Chapter 18 clauses; a pack without the entries (one that only inherits
them from the default pack) names the rows without a clause, never BNBC's numbers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import ductile_joints as dj
from saengine.design import ductile_members as dm
from saengine.design import seismic_detailing as sd
from saengine.design import seismic_rules as sr
from saengine.design.rc import section_of
from saengine.library.objects import CircleProfile, LinearReinforcement, RectangleProfile

SNAPSHOT = Path(__file__).parent / "data" / "detailing_clauses_bnbc2020.json"

#: Clause numbers of BNBC 2020 Part 6 Chapter 8 (and the Chapter 6 / 2 ones these rows cite).
BNBC_NUMBER = re.compile(r"\b8\.[1-3]\.\d|\bEq\. 6\.\d|Figure 6\.\d|Table 6\.2\.19|\b6\.2\.3\.\d")

KN = 1e3


def _reinforcement(groups, transverse) -> LinearReinforcement:
    return LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": p, "count": n, "dia": d} for p, n, d in groups],
            "transverse": transverse,
        }
    )


def _beam():
    transverse = {
        "type": "stirrup",
        "dia": 10,
        "spacing": 150,
        "legs": 2,
        "zone": {"spacing": 100, "length": 1000, "first": 50},
        "splice": {"spacing": 100},
    }
    r = _reinforcement([("top", 4, 20), ("bottom", 4, 16)], transverse)
    return section_of(RectangleProfile(xDim=300, yDim=500), r, 25, 420), r


def _column(circle: bool = False):
    transverse = {
        "type": "tie",
        "dia": 10,
        "spacing": 150,
        "legs": 3,
        "legsX": 3,
        "zone": {"spacing": 100, "length": 600, "first": 50},
        "splice": {"spacing": 100},
    }
    if circle:
        r = _reinforcement([("perimeter", 8, 20)], {**transverse, "type": "spiral"})
        return section_of(CircleProfile(radius=250), r, 30, 420), r
    r = _reinforcement([("perimeter", 12, 20)], transverse)
    return section_of(RectangleProfile(xDim=500, yDim=500), r, 30, 420), r


def render() -> list[str]:
    """The names and notes of the detailing rows of a matrix of members (frame types, in and out
    of the seismic-force-resisting system, light and heavy axial force), the capacity-design
    rows and the method text, under the pack in force."""
    out: list[str] = []

    def rows(found) -> None:
        for row in found:
            out.extend([row["name"], row.get("note") or ""])

    beam, rb = _beam()
    for frame in dm.FRAMES:
        for lateral in (True, False):
            for axial in ((0.0, None), (900 * KN, "E1")):
                d = dm.beam_checks(
                    beam,
                    rb.transverse,
                    frame,
                    clear_span=5000,
                    axial=axial,
                    supports=[(500, 500), (300, 600)],
                    lateral=lateral,
                )
                rows(d.checks)
                out.extend(d.notes)
            d = dm.beam_checks(beam, None, frame, clear_span=None, lateral=lateral)
            rows(d.checks)
            out.extend(d.notes)
    for circle in (False, True):
        column, rc_ = _column(circle)
        for frame in dm.FRAMES:
            for lateral in (True, False):
                for pu in (0.0, 3000 * KN):
                    for full in (False, True):
                        d = dm.column_checks(
                            column,
                            rc_.transverse,
                            frame,
                            40,
                            clear_height=2600,
                            axial=(pu, "E1"),
                            lateral=lateral,
                            full_height=full,
                        )
                        rows(d.checks)
                        out.extend(d.notes)
                d = dm.column_checks(column, None, frame, 40, axial=(3000 * KN, None))
                rows(d.checks)
                out.extend(d.notes)
    for level in ("special", "intermediate"):
        rows(
            dj.beam_capacity_shear(
                beam, 5000, 60 * KN, 50 * KN, dj.Stirrups(10, 2, 100), level=level
            )
        )
        column, _ = _column()
        for direction in ((1.0, 0.0), (0.0, 1.0)):
            rows(
                dj.column_capacity_shear(
                    column,
                    0.0,
                    direction,
                    2600,
                    500 * KN,
                    2000 * KN,
                    100 * KN,
                    None,
                    dj.Stirrups(10, 3, 100),
                    level=level,
                    doubled_e_shear=150 * KN,
                )
            )
    rows(dj.column_dowel_checks("C1", 20, 420, 25, 500, 75, 16))
    rows(
        [
            dj.grade_beam_tie_check("GB1", 300, 500, 150),
            dj.grade_beam_tie_check("GB2", 300, 500, None),
        ]
    )
    for category in ("D", "B"):
        for axial in (100 * KN, 1500 * KN, 4000 * KN):
            for moment in (50e6, 500e6):
                found, notes = dj.non_sfrs_checks(
                    "B1",
                    beam,
                    axial,
                    moment,
                    80 * KN,
                    200e6,
                    150 * KN,
                    category,
                    dj.Stirrups(10, 2, 150),
                )
                rows(found)
                out.extend(notes)
    row = SimpleNamespace(row="C.5 (p. 623)", limits=(None, 0.0, 30.0), frame="intermediate")
    for sdc in ("C", "D"):
        rows(sr.system_checks("rcImf", row, sdc, 45.0))
        rows(sr.system_checks("rcImf", row, sdc, None))
    out.extend(sd.METHOD)
    return list(dict.fromkeys(out))  # the distinct strings, in order


def test_default_pack_rows_are_unchanged() -> None:
    """The bnbc2020 strings, byte for byte, as before the clauses moved into the pack."""
    assert render() == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _under(pack_id: str):
    return code_context.using(registry.load(pack_id))


def test_us_pack_cites_aci_318_chapter_18() -> None:
    with _under("aci318-asce7-22"):
        found = render()
    text = "\n".join(found)
    assert not BNBC_NUMBER.search(text), BNBC_NUMBER.search(text)
    assert "Width ≥ 250 mm (18.6.2.1(b))" in found
    assert "Clear span ≥ 4d (18.6.2.1(a))" in found
    assert any(n.startswith("Confinement Ash, bc along x, in lo (Table 18.7.5.4)") for n in found)
    assert "Tie spacing in lo (18.7.5.3)" in found
    assert any("(ACI 318-19 Chapter 18 Sec 18.6.5.1)" in n for n in found)
    # The ordinary frame tie rule of BNBC 8.3.9.2 has no ACI 318-19 counterpart: no clause.
    assert "Tie spacing in lo" in found


def test_a_pack_without_entries_names_no_clause() -> None:
    """The Eurocodes pack extends the default pack but gives none of these groups: its rows
    carry no clause rather than BNBC's numbers."""
    with _under("eurocodes"):
        found = render()
    text = "\n".join(found)
    assert not BNBC_NUMBER.search(text), BNBC_NUMBER.search(text)
    assert "Width ≥ 250 mm" in found
    assert "Least steel ratio" in found
    assert all("()" not in n for n in found)


def test_inherited_entries_are_not_the_pack_own() -> None:
    from saengine.design.clauses import own_text, text

    with _under("eurocodes"):
        assert text("ductileMembersRows", "beamWidth") == "8.3.4.1(d)"  # merged from BNBC
        assert own_text("ductileMembersRows", "beamWidth") == ""
    with _under("aci318-asce7-22"):
        assert own_text("ductileMembersRows", "beamWidth") == "18.6.2.1(b)"
        assert own_text("ductileMembersRows", "omfColumns") == ""  # BNBC's, not the US pack's
    assert own_text("ductileMembersRows", "beamWidth") == "8.3.4.1(d)"


@pytest.mark.parametrize("pack_id", ["bnbc2020", "aci318-asce7-22", "eurocodes", "is-codes"])
def test_no_empty_parentheses(pack_id: str) -> None:
    with _under(pack_id):
        found = render()
    assert all("()" not in n and "  " not in n for n in found)
