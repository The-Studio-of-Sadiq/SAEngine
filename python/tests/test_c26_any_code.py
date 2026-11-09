"""Alpha 9 C26: any-code readiness (owner, 2026-11-04: "make sure our software works at ease with
any country code"). Written, not run (owner, 2026-11-05): the full test pass follows.

- the response spectrum combinations from the pack's strength rows with E (was 1.2D/0.9D ± 1.0E
  for every pack), the default pack's unchanged;
- inherited clause text named after the pack that supplies it;
- the pack's bar names in SI too, and bar masses from the pack's nominal masses (ASTM No. 10 is
  0.560 kg/m, not d²/162 of 10);
- Eurocode foundation capacity design: Ω = MRd / MEd of the column at each base, q the cap;
- the IS column construction joint: shear friction as SAEngine practice under IS 456 13.4;
- the pack verification status (VERIFY.md rows not ticked, or ``verified`` in pack.json);
- the trust step of a user or project pack's hazard lookup services (default untrusted);
- ``saengine codepack new``: VERIFY.md, README sections, examples; ``codepack check``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _settings(pack_id: str = "bnbc2020", combinations: list | None = None):
    from saengine.library.settings import LoadCombination, default_project_settings

    settings = default_project_settings()
    settings.codePack = pack_id
    if combinations is not None:
        settings.combinations = [LoadCombination(**c) for c in combinations]
    return settings


# ─────────────────────────── a. response spectrum combinations ───────────────────────────


def test_default_pack_rs_combinations_are_unchanged():
    """BNBC 2020 Sec 2.7.3.1 combinations 5 and 7: 1.2D + 1.0L ± 1.0E (+Ev), 0.9D ± 1.0E (-Ev)."""
    from saengine.fem import seismic_design as sd

    settings = _settings(
        combinations=[{"name": "1.2D + 1.0L + 1.0EX", "D": 1.2, "L": 1.0, "EX": 1.0}]
    )
    options = sd.SeismicOptions(verticalComponent=False)
    with code_context.using(registry.load("bnbc2020")):
        combos = sd.seismic_combinations(settings, options, False, False)
    assert [c["name"] for c in combos] == [
        "1.2D + 1.0L ± 1.0E(RS EX)",
        "1.2D + 1.0L ± 1.0E(RS EY)",
        "0.9D ± 1.0E(RS EX)",
        "0.9D ± 1.0E(RS EY)",
    ]
    assert combos[0]["loads"] == {"D": 1.2, "L": 1.0}
    assert combos[2]["loads"] == {"D": 0.9}
    assert combos[0]["envelope"] == {"RX": 1.0}
    assert combos[0]["clause"].endswith("no. 5, E = Eh + Ev")
    assert combos[2]["clause"].endswith("no. 7, E = Eh − Ev")


def test_is_pack_rs_combinations_use_its_factors():
    """IS 1893 (Part 1) 6.3.4: 1.2(D + L + E), 1.5(D + E), 0.9D + 1.5E."""
    from saengine.fem import seismic_design as sd

    options = sd.SeismicOptions(verticalComponent=False, liveFactor=None)
    with code_context.using(registry.load("is-codes")):
        combos = sd.seismic_combinations(_settings("is-codes", []), options, False, False)
    by_dead = {(c["loads"]["D"], c["loads"].get("L")): c for c in combos}
    assert (1.2, 1.2) in by_dead and by_dead[(1.2, 1.2)]["envelope"] == {"RX": 1.2}
    assert (1.5, None) in by_dead and by_dead[(1.5, None)]["envelope"] == {"RX": 1.5}
    assert (0.9, None) in by_dead and by_dead[(0.9, None)]["envelope"] == {"RX": 1.5}
    assert by_dead[(0.9, None)]["clause"].endswith("E = Eh − Ev")


def test_eurocode_rs_combination_takes_both_signs_of_ev():
    """EN 1990 6.4.3.4 (6.12b): G + AEd + ψ2 Q, one dead load factor: Ev with both signs."""
    from saengine.fem import seismic_design as sd

    with code_context.using(registry.load("eurocodes")):
        rows = sd._earthquake_rows()
    assert sorted(s for _, s in rows) == [-1, 1]
    assert all(r.factors["D"] == 1.0 and r.factors["L"] == 0.3 for r, _ in rows)


def test_pack_without_earthquake_rows_keeps_the_generic_default():
    from saengine.fem import seismic_design as sd

    with code_context.using(registry.load("bs8110")):
        rows = sd._earthquake_rows()
    assert [(r.id, s) for r, s in rows] == [("5", 1), ("7", -1)]


# ─────────────────────────── b. inherited clause text ───────────────────────────


def test_inherited_practice_text_names_the_pack_that_supplies_it():
    pack = registry.load("is-codes")
    assert pack.inherited_from("excavationSupport") == "BNBC 2020"
    text = code_context.attribute(
        "SAEngine practice where BNBC 2020 is silent", "excavationSupport", pack=pack
    )
    assert text.endswith("[inherited from BNBC 2020; not given by Indian Standards]")
    with code_context.using(pack):
        from saengine.substructure import excavation_support

        assert "inherited from BNBC 2020" in excavation_support.cite("method")


def test_default_pack_text_is_unchanged():
    pack = registry.load("bnbc2020")
    assert pack.inherited_from("excavationSupport") is None
    text = "SAEngine practice where BNBC 2020 is silent"
    assert code_context.attribute(text, "excavationSupport", pack=pack) == text


def test_report_lists_inherited_tables_and_keeps_default_refs():
    from saengine.report import build

    assert build._inherited_tables(registry.load("bnbc2020")) == []
    inherited = dict(build._inherited_tables(registry.load("is-codes")))
    assert "excavationSupport" in inherited["BNBC 2020"]
    with code_context.using(registry.load("bnbc2020")):
        assert build._default_ref("Table 6.2.13") == " (Table 6.2.13)"
    with code_context.using(registry.load("is-codes")):  # IS 1893 has its own seismic table
        assert build._default_ref("Table 6.2.13") == ""
    with code_context.using(registry.load("bs8110")):  # inherits BNBC's seismic table
        assert build._default_ref("Table 6.2.13") == " (BNBC 2020 Table 6.2.13)"


# ─────────────────────────── c, d. bar names and masses ───────────────────────────


def test_bar_names_show_in_si_too():
    from saengine import units as u

    si = u.Units(bar_names={"10": "N10", "16": "N16"})
    assert si.si and not si.plain
    assert si.bar(16) == "N16" and si.bar(12) == "Ø12"
    assert u.convert_text("4Ø16 and Ø10 @ 150; 250 mm", si) == "4-N16 and N10 @ 150; 250 mm"
    assert u.convert_text("Ø12 @ 200", si) == "Ø12 @ 200"
    assert u.SI.plain and u.convert_text("4Ø16", u.SI) == "4Ø16"
    document = {"sections": [{"blocks": [{"t": "p", "text": "Ø16 @ 150"}]}]}
    assert u.convert_document(document, u.SI) is document
    shown = u.convert_document(document, si)
    assert shown["sections"][0]["blocks"][0]["text"] == "N16 @ 150"


def test_si_bar_column_of_a_drawing_table():
    from saengine import units as u

    si = u.Units(bar_names={"16": "HD16"})
    columns, rows = u.convert_mm_table(
        [{"title": "Ø (mm)"}, {"title": "Length (mm)"}], [["16", "3000"]], si
    )
    assert columns[0]["title"] == "size" and rows == [["HD16", "3000"]]


def test_us_bar_masses_are_the_astm_nominal_masses():
    from saengine.boq.quantities import bar_mass as boq_mass
    from saengine.drawings.bbs import bar_mass as bbs_mass

    with code_context.using(registry.load("aci318-asce7-22")):
        assert boq_mass(10) == pytest.approx(0.560)  # No. 10 (No. 3), 9.5 mm
        assert bbs_mass(36) == pytest.approx(7.907)  # No. 36 (No. 11)
    with code_context.using(registry.load("bnbc2020")):
        assert boq_mass(10) == pytest.approx(100 / 162)  # unchanged: d²/162
    with code_context.using(registry.load("brazil-nbr")):  # metric bars at the same keys
        assert bbs_mass(10) == pytest.approx(100 / 162)
    with code_context.using(registry.load("korea-kds")):  # KS D 3504 D10 is 9.53 mm
        assert bbs_mass(10) == pytest.approx(0.560)


# ─────────────────────────── e. foundation capacity design ───────────────────────────


class _Surface:
    """A section whose MRd is 300 kN·m at every axial force and direction."""

    def moment_capacity(self, pu: float, angle: float) -> float:
        return 300e6


def test_base_omega_is_mrd_over_med_of_the_governing_combination():
    from saengine.substructure.foundation_capacity import base_omega

    actions = [(500e3, 100e6, 0.0), (400e3, 0.0, 150e6), (300e3, 0.0, 0.0)]
    assert base_omega(_Surface(), 0.0, actions) == pytest.approx(2.0)  # 300 / 150
    assert base_omega(_Surface(), 30.0, [(1.0, 0.0, 0.0)]) is None


def test_member_omegas_scale_each_base_and_cap_at_q(monkeypatch):
    import numpy as np

    from saengine.substructure import foundation_capacity as fc

    rule = SimpleNamespace(
        gammaLow=1.0, gammaHigh=1.4, qLimit=3.0, omega=None, method="overstrengthFactor"
    )
    monkeypatch.setattr(fc, "rules", lambda: rule)
    monkeypatch.setattr(fc, "_gamma_q", lambda settings, r: (1.4, 3.9))
    monkeypatch.setattr(fc, "factor", lambda settings: (3.9, "how"))
    monkeypatch.setattr(fc, "member_omegas", lambda loads, strength, o, m: {"C1": 1.5, "C2": 0.8})
    base = lambda node: SimpleNamespace(nodes=[(node, np.zeros(3))])
    loads = SimpleNamespace(
        cases={
            "D": {1: np.ones(6), 2: np.ones(6), 3: np.ones(6)},
            "EX": {1: np.ones(6), 2: np.ones(6), 3: np.ones(6)},
        },
        bases={"C1": base(1), "C2": base(2), "W1": base(3)},
        unscaled_strength=[("G", {"D": 1.0}), ("G + E", {"D": 1.0, "EX": 1.0})],
        strength=[],
    )
    note = fc.apply_member_omegas(loads, None, None, None)
    assert note and "Ω of the columns" in note
    case = "EX" + fc.SUFFIX
    assert loads.cases[case][1][0] == pytest.approx(1.4 * 1.5)  # γRd Ω
    assert loads.cases[case][2][0] == pytest.approx(1.4 * 1.0)  # Ω at least 1
    assert loads.cases[case][3][0] == pytest.approx(3.9)  # a wall: the single value (q)
    assert loads.strength == [("G", {"D": 1.0}), ("G + E", {"D": 1.0, case: 1.0})]


def test_default_pack_has_no_foundation_capacity_rule():
    from saengine.substructure import foundation_capacity as fc

    with code_context.using(registry.load("bnbc2020")):
        assert fc.rules() is None


# ─────────────────────────── f. IS construction joints ───────────────────────────


def test_is_construction_joint_is_saengine_practice_under_is_456():
    from saengine.design import rc_detailing

    pack = registry.load("is-codes")
    assert pack.clause_code("detailing", "shearFriction") == "IS 456:2000"
    with code_context.using(pack):
        text = rc_detailing.clause("detailing", "shearFriction")
    assert text.startswith("IS 456:2000 13.4") and "SAEngine practice" in text
    with code_context.using(registry.load("bnbc2020")):
        assert rc_detailing.clause("detailing", "shearFriction").startswith("BNBC 2020 Part 6")


# ─────────────────────────── g. verification status ───────────────────────────


def test_verify_rows_count_the_rows_not_ticked():
    text = (
        "| # | Value | Clause | Checked |\n|---|---|---|---|\n"
        "| 1 | 1.2 | 2.3 | Verified 2026-11-20 |\n| 2 | 1.6 | 2.3 | |\n| 3 | 0.9 | 2.4 | ✓ |\n"
    )
    assert registry.verify_rows(text) == (3, 1)


def test_built_in_packs_state_their_verification():
    for info in registry.list_packs():
        if info.scope == "builtin":
            assert info.verification is not None and info.verification.status != "unstated", info.id


def test_verified_in_pack_json_marks_the_pack_verified(tmp_path: Path):
    from saengine.codes.template import new_pack

    folder = new_pack(tmp_path, "checked-pack", "Checked", "bnbc2020")
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    manifest["verified"] = "2026-11-20"
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    pack = registry.load_path(folder)
    assert pack.verification.status == "verified" and pack.verification.date == "2026-11-20"


def test_pack_options_say_unverified():
    """The pack chooser (Project Settings, New Building) reads ``verification`` (TS side:
    codePacksModel.packDescription); the backend's PackInfo carries it."""
    info = registry.info("eurocodes")
    assert info.verification is not None
    assert info.model_dump(mode="json")["verification"]["status"] == "unverified"


# ─────────────────────────── h. hazard lookup trust ───────────────────────────


def _user_lookup_pack() -> str:
    from saengine.codes.template import new_pack

    us = registry.load("aci318-asce7-22")
    lookup = us.data("hazardLookup")
    for provider in lookup.get("providers", []):
        provider["inheritable"] = False
    folder = new_pack(registry.user_kind_dir(), "office-lookup", "Office", "aci318-asce7-22")
    data = {"$sources": ["the office's copy of the US service entry"], **lookup}
    (folder / "data" / "hazardLookup.json").write_text(json.dumps(data), encoding="utf-8")
    registry.clear_cache()
    return "office-lookup"


def test_user_pack_lookup_services_need_trust():
    from saengine.gis import hazard_lookup as hz

    pack_id = _user_lookup_pack()
    pack = registry.load(pack_id)
    assert not pack.lookup_trusted
    assert hz.providers(pack) == []
    assert "not trusted" in hz.untrusted_note(pack)
    assert registry.info(pack_id).untrustedLookups == [pack_id]
    registry.set_lookup_trusted(pack_id, True)
    pack = registry.load(pack_id)
    assert pack.lookup_trusted and hz.providers(pack)
    assert hz.untrusted_note(pack) == ""
    # Editing the file revokes the trust.
    path = Path(pack.path) / "data" / "hazardLookup.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["providers"][0]["endpoint"] = "https://example.invalid/api"
    path.write_text(json.dumps(data), encoding="utf-8")
    registry.clear_cache()
    assert not registry.load(pack_id).lookup_trusted


def test_built_in_lookup_needs_no_trust():
    from saengine.gis import hazard_lookup as hz

    pack = registry.load("aci318-asce7-22")
    assert pack.lookup_trusted and hz.providers(pack)


# ─────────────────────────── 4. pack authoring ───────────────────────────


def test_new_pack_writes_verify_readme_and_examples(tmp_path: Path):
    from saengine.codes.template import new_pack

    folder = new_pack(tmp_path, "office-pack", "Office pack", "eurocodes")
    readme = (folder / "README.md").read_text(encoding="utf-8")
    for heading in ("## What to override first", "## Check it", "## Verify it", "## Share it"):
        assert heading in readme
    assert "saengine codepack check" in readme
    verify = (folder / "VERIFY.md").read_text(encoding="utf-8")
    assert registry.verify_rows(verify) == (1, 1)
    examples = {p.name for p in (folder / "examples").glob("*.json")}
    assert {"locations.json", "combinations.json", "concrete.json"} <= examples
    # The examples are not read: the new pack still changes nothing.
    pack = registry.load_path(folder)
    assert pack.data("combinations") == registry.load("eurocodes").data("combinations")


def test_codepack_check_command(capsys: pytest.CaptureFixture[str]):
    from saengine.cli.codepack import main

    assert main(["check", "bnbc2020"]) == 0
    out = capsys.readouterr().out
    assert "bnbc2020: conforms" in out and "verified" in out


def test_rows_of_conformance_findings_are_readable():
    from saengine.codes.conformance import Finding

    finding = Finding("error", "sources", "no sources", "wind")
    assert str(finding) == "error: sources [wind]: no sources"
    assert finding.as_dict()["table"] == "wind"
