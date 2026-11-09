"""Usability walk 4 (W4C-18, W4C-31): the .s2k and .std exports write the building's members
(the analysis mesh's segments joined back), the modal case and its mass source; the report's
counts agree with the file; .std titles are not doubled; SDNF does not list loads or diaphragms;
CIS/2 writes every non-zero load.

The model, by hand: two columns (C1, C2: 0 to 3.5 m at x = 0 and 6 m, fixed bases) and a beam
B1 at 3.5 m from (0, 0) to (6, 0), split by the mesh into four 1.5 m segments (nodes 3, 5, 6,
7, 4), pinned at both ends; D: 10 kN/m on the first two segments and 20 kN/m on the last two,
a 5 kN down force at the mid node; masses 1000 kg at every beam node; a modal analysis of 3
modes; one diaphragm whose master is node 8.
"""

from __future__ import annotations

import pytest

from saengine.exporters.analytical import (
    AnalyticalModel,
    Diaphragm,
    ExchangeReport,
    LoadCase,
    Material,
    Member,
    Node,
    Section,
    from_osmodel,
    joined_members,
)
from saengine.exporters.cis2 import write_cis2
from saengine.exporters.s2k import write_s2k
from saengine.exporters.sdnf import write_sdnf
from saengine.exporters.std import write_std

FIXED = (True,) * 6
PIN = (frozenset({"M2", "M3"}), frozenset())


def meshed_frame() -> AnalyticalModel:
    m = AnalyticalModel(name="Mesh")
    m.nodes[1] = Node(1, (0.0, 0.0, 0.0), FIXED)
    m.nodes[2] = Node(2, (6.0, 0.0, 0.0), FIXED)
    m.nodes[3] = Node(3, (0.0, 0.0, 3.5))
    m.nodes[4] = Node(4, (6.0, 0.0, 3.5))
    for k, x in ((5, 1.5), (6, 3.0), (7, 4.5)):
        m.nodes[k] = Node(k, (x, 0.0, 3.5))
    m.nodes[8] = Node(8, (3.0, 0.0, 3.5))
    m.materials["S355"] = Material("S355", "steel", 2e11, 0.3, 7850.0, fy=355e6, fu=490e6)
    m.sections["IPE300"] = Section(
        "IPE300", "S355", "general", {}, 5.38e-3, 8.36e-5, 6.04e-6, 2.0e-7
    )
    m.members = [
        Member("C1", 1, 3, "IPE300", kind="column", source="C1"),
        Member("C2", 2, 4, "IPE300", kind="column", source="C2"),
        Member("B1", 3, 5, "IPE300", releases=PIN, source="B1"),
        Member("B1#2", 5, 6, "IPE300", source="B1"),
        Member("B1#3", 6, 7, "IPE300", source="B1"),
        Member(
            "B1#4", 7, 4, "IPE300", releases=(frozenset(), frozenset({"M2", "M3"})), source="B1"
        ),
    ]
    m.diaphragms = [Diaphragm("D1", 8, [3, 4, 5, 6, 7])]
    m.cases = [
        LoadCase(
            "D",
            "D",
            "D: Dead",
            nodal={6: [0.0, 0.0, -5000.0, 0, 0, 0]},
            uniform={
                "B1": [0, 0, -10000.0],
                "B1#2": [0, 0, -10000.0],
                "B1#3": [0, 0, -20000.0],
                "B1#4": [0, 0, -20000.0],
            },
        ),
        LoadCase(
            "L", "L", "L", uniform={k: [0, 0, -3000.0] for k in ("B1", "B1#2", "B1#3", "B1#4")}
        ),
    ]
    m.combinations = [("1.2D+1.6L", {"D": 1.2, "L": 1.6})]
    m.masses = {k: [1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0] for k in (3, 4, 5, 6, 7)}
    m.modes = 3
    return m


def test_mesh_segments_join_back_into_members() -> None:
    report = ExchangeReport("test", ".x")
    joined = joined_members(meshed_frame(), report)
    assert [m.id for m in joined.members] == ["C1", "C2", "B1"]
    beam = joined.members[2]
    assert (beam.i, beam.j) == (3, 4)
    assert beam.releases == (frozenset({"M2", "M3"}), frozenset({"M2", "M3"}))
    dead = joined.cases[0]
    # 10 kN/m over 0-3 m, 20 kN/m over 3-6 m; the mid node's force a point load at 3 m
    assert dead.partial["B1"] == [([0, 0, -10000.0], 0.0, 3.0), ([0, 0, -20000.0], 3.0, 6.0)]
    assert dead.points["B1"] == [([0.0, 0.0, -5000.0, 0, 0, 0], 3.0)]
    assert dead.nodal == {}
    assert joined.cases[1].uniform["B1"] == [0, 0, -3000.0]
    # the masses of the inner nodes go to the ends by the lever rule: total kept
    assert sum(v[0] for v in joined.masses.values()) == pytest.approx(5000.0)
    assert joined.masses[3][0] == pytest.approx(1000 + 750 + 500 + 250)
    assert joined.diaphragms[0].nodes == [3, 4]


def test_s2k_writes_members_modal_case_and_mass_source() -> None:
    report = ExchangeReport("SAP", ".s2k")
    lines = [line.strip() for line in write_s2k(meshed_frame(), report).splitlines()]
    frames = [line for line in lines if line.startswith("Frame=") and "JointI=" in line]
    assert len(frames) == 3
    assert "Frame=B1   JointI=3   JointJ=4   IsCurved=No" in lines
    assert 'TABLE:  "MASS SOURCE"' in lines
    assert "MassSource=MSSSRC1   Elements=No   Masses=Yes   Loads=No   IsDefault=Yes" in lines
    assert "Case=MODAL   Type=LinModal   InitialCond=Zero   DesignType=Other" in lines
    assert any(line.startswith("Case=MODAL   ModeType=Eigen   MaxNumModes=3") for line in lines)
    assert any(line.startswith("Joint=3   CoordSys=GLOBAL   Mass1=2.5") for line in lines)
    assert (
        "Frame=B1   LoadPat=D   CoordSys=GLOBAL   Type=Force   Dir=Z   DistType=AbsDist   "
        "AbsDistA=3   AbsDistB=6   FOverLA=-20   FOverLB=-20"
    ) in lines
    assert (
        "Frame=B1   LoadPat=D   CoordSys=GLOBAL   Type=Force   Dir=Z   DistType=AbsDist   "
        "AbsDist=3   Force=-5"
    ) in lines
    counts = report.imported
    assert counts["beams"] == 1 and counts["columns"] == 2
    assert counts["loadCases"] == 2 and counts["combinations"] == 1
    assert counts["releasedEnds"] == 2
    assert counts["modalCases"] == 1


def test_std_writes_members_modal_case_and_plain_titles() -> None:
    report = ExchangeReport("STAAD", ".std")
    lines = [line.strip() for line in write_std(meshed_frame(), report).splitlines()]
    start = lines.index("MEMBER INCIDENCES")
    assert lines[start + 1 : start + 4] == ["1 1 3;", "2 2 4;", "3 3 4;"]
    assert lines[start + 4] == "DEFINE MATERIAL START"
    assert "LOAD 1 LOADTYPE Dead TITLE D: Dead" in lines
    assert not any("D: D:" in line for line in lines)
    assert "3 UNI GZ -10 0 3" in lines and "3 UNI GZ -20 3 6" in lines
    assert "3 CON GZ -5 3" in lines
    assert "LOAD 3 LOADTYPE Mass TITLE MASSES OF THE MODAL ANALYSIS" in lines
    assert "MODAL CALCULATION REQUESTED" in lines
    assert "CUT OFF MODE SHAPE 3" in lines
    assert "LOAD COMBINATION 4 1.2D+1.6L" in lines
    assert report.imported["loadCases"] == 2  # counted once
    assert report.imported["releasedEnds"] == 2


def test_std_with_masses_reads_back_without_the_mass_case() -> None:
    from saengine.importers.staad import read_staad_text

    model = read_staad_text(write_std(meshed_frame()), "Mesh.std")
    assert len(model.frames) == 3
    assert sorted(c.name.upper() for c in model.cases.values()) == ["1 D: DEAD", "2 L"]


def test_sdnf_report_lists_no_loads_or_diaphragms() -> None:
    report = ExchangeReport("SDNF", ".sdnf")
    report.carried["D"] = 100.0
    write_sdnf(meshed_frame(), report)
    data = report.to_dict()
    assert "loadCases" not in data["exported"] and "diaphragms" not in data["exported"]
    assert "combinations" not in data["exported"]
    assert data["exported"]["members"] == 3
    assert data["loads"]["exportedKN"] == {}
    skipped = " ".join(item["what"] for item in data["skipped"])
    assert "load cases" in skipped and "diaphragms" in skipped


def test_cis2_writes_every_nonzero_load() -> None:
    m = meshed_frame()
    m.diaphragms = []
    m.cases[1].nodal[5] = [0.0, 0.0, -1e-6, 0, 0, 0]  # a micro-newton: still a load
    text = write_cis2(m)
    assert "=LOAD_NODE('L 5'" in text
    assert "D: Dead" in text and "D: D:" not in text


def test_pinned_ends_counted_per_end() -> None:
    from types import SimpleNamespace as NS

    osmodel = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 3], "mass": [500, 500, 0, 0, 0, 0]},
            {"id": 2, "coords": [6, 0, 3]},
            {"id": 3, "coords": [0, 0, 3]},
            {"id": 4, "coords": [6, 0, 3]},
        ],
        "sections": [
            {
                "id": 1,
                "name": "B beam",
                "type": "ElasticSection",
                "E": 2e11,
                "A": 0.01,
                "Iz": 1e-5,
                "Iy": 8e-5,
                "G": 8e10,
                "J": 1e-7,
            },
        ],
        "elements": [
            {"id": 1, "name": "B", "type": "ElasticBeamColumn", "nodes": [3, 4], "section_id": 1},
            {"id": 2, "name": "B/pin", "type": "ZeroLength", "nodes": [1, 3]},
            {"id": 3, "name": "B/pin", "type": "ZeroLength", "nodes": [2, 4]},
        ],
        "load_patterns": [],
        "analyses": [{"id": 1, "name": "Modal", "type": "Modal", "n_modes": 6}],
    }
    report = ExchangeReport("test", ".x")
    model = from_osmodel(osmodel, NS(objects=[]), NS(materials=[]), report=report)
    pinned = [a for a in report.approximated if a["what"].startswith("pinned member ends")]
    assert pinned and pinned[0]["count"] == 2
    assert model.modes == 6
    assert model.masses == {1: [500.0, 500.0, 0.0, 0.0, 0.0, 0.0]}


def test_cis2_keeps_the_loads_on_a_structural_master() -> None:
    m = meshed_frame()
    m.diaphragms = [Diaphragm("D1", 3, [4, 5, 6, 7])]  # the master a beam node
    m.cases[0].nodal[3] = [1000.0, 0.0, 0.0, 0, 0, 0]
    report = ExchangeReport("CIS/2", ".stp")
    text = write_cis2(m, report)
    assert "=LOAD_NODE('D 3'" in text
    assert not report.not_carried.get("D")
