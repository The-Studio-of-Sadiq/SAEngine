"""Alpha 9 C26: the conformance test every code pack passes ("make sure our software works at
ease with any country code").

One parametrised test over every installed design code pack (the built-in ones and a sample
user pack made by ``saengine codepack new``):

- fast (every run): the pack loads and validates; ``covers`` matches its data; every table it
  gives has sources; no inherited clause text speaks as its own (a clause's owner is the pack or
  is labelled with its parent); the earthquake and wind combinations exist or the pack declares
  them in ``notCovered``; the bar names and masses are of the pack's bar sizes; the verification
  status is stated (:mod:`saengine.codes.conformance`);
- slow (``-m slow``): a generated one-bay building derives (wind and earthquake loads), runs, gets
  Design Reinforcement and is designed under the pack.

Run: ``pytest tests/test_codes_conformance.py`` (fast), ``pytest -m slow
tests/test_codes_conformance.py`` (the buildings, some minutes per pack). Not run when written
(owner, 2026-11-05): the full test pass follows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.codes.conformance import CHECKS, check_pack, errors

SAMPLE = "sample-office-pack"


def _builtin_ids() -> list[str]:
    registry.clear_cache()
    return sorted(i.id for i in registry.list_packs() if i.scope == "builtin")


BUILTIN = _builtin_ids()


@pytest.fixture(autouse=True)
def _user_folder(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """The sample user pack in a user folder of its own; no pack of the machine takes part."""
    user = tmp_path_factory.getbasetemp() / "c26-user"
    monkeypatch.setenv("SAENGINE_USER_DATA", str(user))
    registry.clear_cache()
    _ensure_sample(user)
    registry.clear_cache()
    yield
    registry.clear_cache()


def _ensure_sample(user: Path) -> None:
    """A user pack as an office would start one: ``codepack new`` over the default pack, one
    town added, the earthquake factor of combination 5 changed, its VERIFY.md row filled."""
    from saengine.codes.template import new_pack

    packs = registry.user_kind_dir()
    folder = packs / SAMPLE
    if (folder / "pack.json").is_file():
        return
    packs.mkdir(parents=True, exist_ok=True)
    new_pack(packs, SAMPLE, "Sample office pack", "bnbc2020", edition="Sample code 2026")
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    manifest["covers"] = ["locations"]
    manifest["sources"] = [{"id": "SC", "title": "Sample code 2026", "edition": "2026"}]
    (folder / "pack.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "data" / "locations.json").write_text(
        json.dumps(
            {
                "$sources": ["Sample code 2026 Table 3 (invented for the test)"],
                "locations": {"sample-town": {"name": "Sample Town", "zone": 2, "windSpeed": 50.0}},
            }
        ),
        encoding="utf-8",
    )


ALL = [*BUILTIN, SAMPLE]


def test_every_built_in_pack_is_listed():
    assert "bnbc2020" in BUILTIN and len(BUILTIN) >= 30


def test_the_sample_user_pack_is_installed():
    info = registry.info(SAMPLE)
    assert info.scope == "user" and info.usable, info.problems
    assert info.verification is not None and info.verification.status == "unverified"


@pytest.mark.parametrize("pack_id", ALL)
def test_pack_conforms(pack_id: str):
    pack = registry.load(pack_id)
    info = registry.info(pack_id)
    assert info.usable, [p.message for p in info.problems]
    findings = check_pack(pack)
    assert {f.check for f in findings} <= set(CHECKS)
    assert not errors(findings), "\n".join(str(f) for f in errors(findings))


@pytest.mark.parametrize("pack_id", ALL)
def test_pack_verification_is_stated(pack_id: str):
    """Every built-in pack has a VERIFY.md; one with rows not ticked says "values not yet
    verified against the printed code" (Project Settings, New Building, the report)."""
    pack = registry.load(pack_id)
    status = pack.verification
    if pack.scope == "builtin":
        assert status.status in ("verified", "unverified")
    if status.status == "unverified":
        assert "values not yet verified against the printed code" in status.message


@pytest.mark.parametrize("pack_id", ALL)
def test_inherited_tables_name_their_owner(pack_id: str):
    """A table a pack inherits names the pack that supplies it, never the pack in force."""
    pack = registry.load(pack_id)
    for name in pack.tables():
        owner = pack.value_owner(name)
        if owner is None or name in pack.broken:
            continue
        assert owner[0] in pack.chain
        shown = code_context.attribute("SAEngine practice (probe)", name, pack=pack)
        if owner[0] == pack.id or owner[1] == pack.info.table_code(name):
            assert shown == "SAEngine practice (probe)"
        else:
            assert f"inherited from {owner[1]}" in shown


@pytest.mark.parametrize("pack_id", ALL)
def test_bar_names_and_masses_resolve(pack_id: str):
    from saengine.codes.bars import bar_mass
    from saengine.units import Units

    pack = registry.load(pack_id)
    if not pack.has("concrete"):
        return
    concrete = pack.table("concrete")
    names = {str(k): str(v) for k, v in (concrete.barNames or {}).items()}
    units = Units(bar_names=names)
    with code_context.using(pack):
        for dia in concrete.barDiameters.all:
            mass = bar_mass(dia)
            # Within 12 % of a round bar of its key: a designation key's nominal size is close.
            assert 0.88 < mass / (dia * dia / 162) < 1.12, (dia, mass)
            shown = units.bar(dia)
            assert shown == names.get(f"{dia:g}", f"Ø{dia:g}")


@pytest.mark.parametrize("pack_id", ALL)
def test_seismic_and_wind_combinations_or_not_covered(pack_id: str):
    from saengine.fem import seismic_design

    pack = registry.load(pack_id)
    declared = {a for f in pack._chain for a in (f.manifest.notCovered or [])}
    rows = pack.table("combinations").strength
    if "seismic" not in declared:
        assert any(r.factors.get("E") for r in rows)
        with code_context.using(pack):
            formed = seismic_design._earthquake_rows()
        assert formed and all(r.factors.get("E") for r, _ in formed)
    if "wind" not in declared:
        assert any(r.factors.get("W") for r in rows)


# ─────────────────────────── slow: a generated building under each pack ───────────────────────────


@pytest.mark.slow
@pytest.mark.parametrize("pack_id", ALL)
def test_generated_building_derives_and_designs(pack_id: str, tmp_path: Path):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    spec = {
        "name": f"Conformance {pack_id}",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": pack_id,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    with code_context.project(root):
        proposal = handlers.design_proposal(
            str(root / "08 FEM/model.results"), str(root / "08 FEM/model.osmodel")
        )
    objects_path, bim_path = root / "04 Objects/objects.json", root / "06 BIM/bim.json"
    applied = handlers.design_apply_proposal(
        objects_path.read_text(encoding="utf-8"), bim_path.read_text(encoding="utf-8"), proposal
    )
    objects_path.write_text(applied["objectsText"], encoding="utf-8")
    bim_path.write_text(applied["bimText"], encoding="utf-8")
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )
    assert report.get("members"), "no member was designed"
