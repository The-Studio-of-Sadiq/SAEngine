"""D2: the member design reads its clauses and code values from the code pack in force.

With the default pack (bnbc2020) the texts and values are those the design gave before the
decoupling (pinned below). A stub pack that extends bnbc2020 and overrides one table changes
only what reads that table; a pack without the design tables names only itself and reports the
checks that need them as not covered, never falling back to another code's values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import (
    clauses,
    column_shear,
    face_forces,
    rc,
    seismic_rules,
    slab,
    slender,
    stairs,
    takedown,
    torsion,
)
from saengine.design.steel import properties as steel_properties


def _stub(root: Path, tables: dict[str, dict], extends: str | None = "bnbc2020") -> Path:
    folder = root / "d2-stub"
    (folder / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": "d2-stub",
        "name": "Stub Code 2030",
        "edition": "Stub Code 2030",
        "version": "1.0.0",
        "extends": extends,
        "covers": sorted(tables),
    }
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, data in tables.items():
        (folder / "data" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


# ───────────────────────────── bnbc2020: unchanged texts and values ─────────────────────────────


def test_default_pack_texts_are_the_former_ones():
    assert face_forces.JOINT_NOTE == (
        "forces at the joints: the analysis model has no support face offsets (run the analysis "
        "again to design at the faces of the supports, BNBC 2020 Part 6 Sec 6.1.6.3)"
    )
    assert face_forces.SHEAR_CLAUSE == "BNBC 2020 Part 6 Sec 6.4.1.3.1"
    assert seismic_rules.CLAUSES["scope"] == "BNBC 2020 Part 6 Sec 8.3.1 (p. 1088)"
    assert dict(seismic_rules.CLAUSES)["omega"] == "BNBC 2020 Part 6 Sec 2.5.13.4 (p. 646)"
    assert takedown.NOTE.endswith("(BNBC 2020 Part 6 Sec 2.7.3.1); live load unreduced")
    assert "coefficient method of BNBC 2020 Part 6 Sec 6.5.8 " in slab.COEFFICIENT_METHOD
    assert "(SAEngine practice, not a BNBC clause)" in slab.COEFFICIENT_METHOD
    assert clauses.short_clause("slab", "oneWay") == "BNBC 6.1.4.3"
    assert slender.method(slender.SlenderOptions())[0].startswith(
        "Column slenderness to BNBC 2020 Part 6 Sec 6.3.10 (ACI 318-19 6.2.5, 6.6.4)"
    )


def test_default_pack_values_are_the_former_constants():
    assert (rc.PHI_TENSION, rc.PHI_TIED, rc.PHI_SPIRAL, rc.PHI_SHEAR) == (0.90, 0.65, 0.75, 0.75)
    assert (rc.EPS_CU, rc.STEEL_E, rc.FYT_SHEAR_MAX, rc.SLENDERNESS_LIMIT) == (
        0.003,
        200_000.0,
        420.0,
        22.0,
    )
    assert (slender.NONSWAY_Q, slender.SWAY_LIMIT, slender.NONSWAY_CAP) == (0.05, 22.0, 40.0)
    assert (slender.DELTA_S_MAX, slender.MOMENT_RATIO_MAX, slender.PHI_K) == (1.5, 1.4, 0.75)
    assert seismic_rules.FYT_CONFINEMENT_MAX == 700.0
    assert column_shear.ROOT_FC_MAX == torsion.ROOT_FC_MAX == 8.3
    assert steel_properties.ERW_FACTOR == 0.93
    assert (stairs.LIVE_STAIRS, stairs.LIVE_STAIRS_DWELLING) == (4.8, 2.0)
    assert stairs.TWO_R_PLUS_T == (610.0, 648.0)
    assert stairs.TABLE_4_3_5[7] == (171.0, 324.0)
    assert (stairs.HEADROOM, stairs.HEADROOM_REDUCED, stairs.FLIGHT_RISE_MAX) == (
        2150.0,
        2030.0,
        3660.0,
    )
    assert stairs.minimum_width("educational", 200)[0] == 2235.0
    # a result: Vc of a column, √f'c capped at 8.3 MPa (f'c 100 MPa)
    assert column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 100.0) == pytest.approx(
        0.17 * 8.3 * 400 * 340
    )
    assert column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 25.0) == pytest.approx(
        0.17 * 5.0 * 400 * 340
    )


# ─────────────────────────────── a stub pack that extends bnbc2020 ───────────────────────────────


def test_a_stub_pack_overriding_design_limits_changes_only_those_results(tmp_path):
    pack = registry.load_path(_stub(tmp_path, {"designLimits": {"shearRootFcMax": 7.0}}))
    high = column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 100.0)
    low = column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 25.0)
    with code_context.using(pack):
        assert column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 100.0) == pytest.approx(
            0.17 * 7.0 * 400 * 340
        )
        assert column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 25.0) == low
        assert torsion.ROOT_FC_MAX == 7.0
        # the rest of the table is inherited, other tables untouched
        assert steel_properties.ERW_FACTOR == 0.93
        assert stairs.TWO_R_PLUS_T == (610.0, 648.0)
        assert rc.PHI_SHEAR == 0.75
        # the clauses are inherited from bnbc2020 and keep its name; the code is the stub's
        assert face_forces.SHEAR_CLAUSE == "BNBC 2020 Part 6 Sec 6.4.1.3.1"
        assert clauses.code_name() == "Stub Code 2030"
    assert column_shear.concrete_shear(0.0, 1.6e5, 400.0, 340.0, 100.0) == high


def test_a_stub_pack_overriding_one_clause_changes_only_that_text(tmp_path):
    data = {"shortName": "SC", "clauses": {"faceForces": {"shear": "Art. 9.9"}}}
    pack = registry.load_path(_stub(tmp_path, {"designClauses": data}))
    with code_context.using(pack):
        assert face_forces.SHEAR_CLAUSE == "Stub Code 2030 Art. 9.9"
        # a group the stub rewrites is named after the stub (the other groups after bnbc2020)
        assert face_forces.FACE_CLAUSE == "Stub Code 2030 Part 6 Sec 6.1.6.3"
        assert seismic_rules.CLAUSES["scope"] == "BNBC 2020 Part 6 Sec 8.3.1 (p. 1088)"
        assert clauses.short_clause("slab", "oneWay") == "SC 6.1.4.3"
        assert rc.PHI_SHEAR == 0.75 and slender.DELTA_S_MAX == 1.5
    assert face_forces.SHEAR_CLAUSE == "BNBC 2020 Part 6 Sec 6.4.1.3.1"


def test_a_stub_pack_overriding_the_phi_factors_changes_the_rc_design(tmp_path):
    phi = dict(registry.load("bnbc2020").table("factors").phi)
    phi["shear"] = 0.70
    pack = registry.load_path(_stub(tmp_path, {"factors": {"phi": phi}}))
    with code_context.using(pack):
        assert rc.PHI_SHEAR == 0.70
        assert rc.PHI_TENSION == 0.90
        assert rc.phi_axial_flexure(0.01, 420.0) == 0.90
    assert rc.PHI_SHEAR == 0.75


def test_a_pack_without_the_design_tables_names_itself_and_covers_nothing(tmp_path):
    pack = registry.load_path(_stub(tmp_path, {"areaLoads": {"uses": {}}}, extends=None))
    assert not pack.has("designClauses") and not pack.has("designLimits")
    with code_context.using(pack):
        assert clauses.clause("faceForces", "face") == "Stub Code 2030"
        assert "BNBC" not in face_forces.JOINT_NOTE
        assert "BNBC" not in slab.COEFFICIENT_METHOD
        with pytest.raises(clauses.NotCovered, match="not covered by the code pack Stub Code 2030"):
            _ = stairs.TWO_R_PLUS_T
