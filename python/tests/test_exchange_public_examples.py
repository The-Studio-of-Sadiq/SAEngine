"""Import + export round-trip smoke tests on public structural example files.

Only ``sample-steel.STD`` (MIT License) is stored in the repository. Unlicensed public sample
files from external GitHub repositories are NEVER committed; when ``SAENGINE_PUBLIC_EXAMPLES``
points to a local folder containing them, these tests verify import and re-export on them too.
No network requests are made during tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from saengine.exporters.analytical import joined_members, project_model
from saengine.exporters.etabs import write_e2k
from saengine.exporters.exchange import FORMATS as EXPORT_FORMATS
from saengine.exporters.exchange import export_file
from saengine.importers.project import import_structural
from saengine.importers.safe import read_safe
from saengine.importers.sap2000 import read_sap2000
from saengine.importers.staad import read_staad
from saengine.library.bim import BuildingModel
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings

PUBLIC_DIR = Path(__file__).parent / "data" / "import" / "public"
ENV_VAR = "SAENGINE_PUBLIC_EXAMPLES"


@dataclass(frozen=True)
class PublicExample:
    filename: str
    fmt: str  # "e2k", "s2k", "std", "f2k"
    url: str
    licence: str
    bundled: bool = False
    expect_skipped: bool = True


# Public example sources and licence status:
# - DannCarlo/openbuilding sample-steel.STD: MIT License
#   https://raw.githubusercontent.com/DannCarlo/openbuilding/main/sample-steel.STD
# - ekarajp/Structural_Analysis_Program: NO LICENCE (never committed; read via SAENGINE_PUBLIC_EXAMPLES)
#   https://raw.githubusercontent.com/ekarajp/Structural_Analysis_Program/main/tests/data/import/safe_v12_slab.f2k
#   https://raw.githubusercontent.com/ekarajp/Structural_Analysis_Program/main/tests/data/import/sap2000_v23_portal.s2k
#   https://raw.githubusercontent.com/ekarajp/Structural_Analysis_Program/main/tests/data/import/etabs_v9_column.e2k
# - ahisham92/etabs-promax: NO LICENCE (never committed; read via SAENGINE_PUBLIC_EXAMPLES)
#   https://raw.githubusercontent.com/ahisham92/etabs-promax/main/tests/CsiProMax.Tests/samples/safe-RC-PN-v23.f2k
#   https://raw.githubusercontent.com/ahisham92/etabs-promax/main/tests/CsiProMax.Tests/samples/safe-PT-SL-v20.f2k
#   https://raw.githubusercontent.com/ahisham92/etabs-promax/main/tests/CsiProMax.Tests/samples/etabs-style.e2k
PUBLIC_EXAMPLES = [
    PublicExample(
        "sample-steel.STD",
        "std",
        "https://raw.githubusercontent.com/DannCarlo/openbuilding/main/sample-steel.STD",
        "MIT",
        bundled=True,
        expect_skipped=False,
    ),
    PublicExample(
        "safe_v12_slab.f2k",
        "f2k",
        "https://raw.githubusercontent.com/ekarajp/Structural_Analysis_Program/main/tests/data/import/safe_v12_slab.f2k",
        "none (unlicensed)",
        expect_skipped=False,
    ),
    PublicExample(
        "sap2000_v23_portal.s2k",
        "s2k",
        "https://raw.githubusercontent.com/ekarajp/Structural_Analysis_Program/main/tests/data/import/sap2000_v23_portal.s2k",
        "none (unlicensed)",
    ),
    PublicExample(
        "etabs_v9_column.e2k",
        "e2k",
        "https://raw.githubusercontent.com/ekarajp/Structural_Analysis_Program/main/tests/data/import/etabs_v9_column.e2k",
        "none (unlicensed)",
        expect_skipped=False,
    ),
    PublicExample(
        "safe-RC-PN-v23.f2k",
        "f2k",
        "https://raw.githubusercontent.com/ahisham92/etabs-promax/main/tests/CsiProMax.Tests/samples/safe-RC-PN-v23.f2k",
        "none (unlicensed)",
    ),
    PublicExample(
        "safe-PT-SL-v20.f2k",
        "f2k",
        "https://raw.githubusercontent.com/ahisham92/etabs-promax/main/tests/CsiProMax.Tests/samples/safe-PT-SL-v20.f2k",
        "none (unlicensed)",
    ),
    PublicExample(
        "etabs-style.e2k",
        "e2k",
        "https://raw.githubusercontent.com/ahisham92/etabs-promax/main/tests/CsiProMax.Tests/samples/etabs-style.e2k",
        "none (unlicensed)",
    ),
]


def _resolve_example(spec: PublicExample) -> Path:
    if spec.bundled:
        path = PUBLIC_DIR / spec.filename
        assert path.is_file(), f"missing bundled MIT example: {spec.filename}"
        return path
    folder = os.environ.get(ENV_VAR)
    if not folder:
        pytest.skip(f"{ENV_VAR} not set; skipping unlicensed example {spec.filename}")
    path = Path(folder) / spec.filename
    if not path.is_file():
        pytest.skip(f"{spec.filename} not present in {ENV_VAR}")
    return path


def _coords_set(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    return sorted((round(x, 3), round(y, 3), round(z, 3)) for x, y, z in points)


@pytest.mark.parametrize("spec", PUBLIC_EXAMPLES, ids=[s.filename for s in PUBLIC_EXAMPLES])
def test_public_example_import_and_reexport(tmp_path: Path, spec: PublicExample) -> None:
    source = _resolve_example(spec)
    first = import_structural(source, tmp_path / "first", overwrite=True)
    imported = first["report"]["imported"]
    if spec.fmt != "e2k":
        assert imported.get("joints", 0) > 0
    members = (
        imported.get("columns", 0)
        + imported.get("beams", 0)
        + imported.get("braces", 0)
        + imported.get("inclinedMembers", 0)
    )
    areas = imported.get("slabs", 0) + imported.get("walls", 0)
    assert members + areas > 0
    assert isinstance(first["report"]["skipped"], list)
    if spec.expect_skipped:
        assert first["report"]["skipped"], f"expected skipped items/tables in {spec.filename}"

    root = Path(first["root"])
    if spec.fmt == "e2k":
        bim = BuildingModel.model_validate_json((root / "06 BIM/bim.json").read_text("utf-8"))
        objs = ObjectLibrary.model_validate_json(
            (root / "04 Objects/objects.json").read_text("utf-8")
        )
        mats = MaterialLibrary.model_validate_json(
            (root / "03 Materials/materials.json").read_text("utf-8")
        )
        proj_settings = ProjectSettings.model_validate_json(
            (root / "02 Project Settings/project-settings.json").read_text("utf-8")
        )
        exported = tmp_path / f"{source.stem}_out.e2k"
        write_e2k(bim, objs, mats, proj_settings, name=first["name"]).write(exported)
        second = import_structural(exported, tmp_path / "second", overwrite=True)
        imp2 = second["report"]["imported"]
        for key in ("columns", "beams", "braces", "slabs", "walls", "stories"):
            assert imp2.get(key, 0) == imported.get(key, 0)
        return

    # Analytical exchange formats (.s2k, .std, .f2k): export_file -> TextModel + import_structural
    fmt_spec = EXPORT_FORMATS[spec.fmt]
    exported = tmp_path / f"{source.stem}_out{fmt_spec.extension}"
    out = export_file(root, spec.fmt, out_path=exported)
    assert "error" not in out
    assert exported.is_file()

    am, _, _ = project_model(root, fmt_spec.name, fmt_spec.extension)
    am = joined_members(am)
    if spec.fmt == "s2k":
        tm = read_sap2000(exported)
    elif spec.fmt == "std":
        tm = read_staad(exported)
    else:
        tm = read_safe(exported)

    expected_members = (
        sum(1 for m in am.members if m.kind != "brace") if spec.fmt == "f2k" else len(am.members)
    )
    assert len(tm.frames) == expected_members
    assert len(tm.areas) == len(am.plates)

    # Coordinate comparison in metres (TextModel joints are in mm)
    exp_node_ids = {
        *(
            n
            for m in am.members
            if not (spec.fmt == "f2k" and m.kind == "brace")
            for n in (m.i, m.j)
        ),
        *(n for p in am.plates for n in p.nodes),
        *(n.id for n in am.nodes.values() if n.supported),
    }
    expected_coords = _coords_set([am.nodes[n].xyz for n in exp_node_ids if n in am.nodes])
    got_coords = _coords_set([tuple(float(v) / 1000.0 for v in xyz) for xyz in tm.joints.values()])
    for p0, p1 in zip(expected_coords, got_coords, strict=True):
        assert p1 == pytest.approx(p0, abs=1e-3)

    # Also verify import_structural succeeds on the exported file
    second = import_structural(exported, tmp_path / "second", overwrite=True)
    assert second["report"]["imported"].get("joints", 0) == len(tm.joints)
