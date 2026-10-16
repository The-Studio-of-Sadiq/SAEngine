"""The verification pack: its benchmarks pass, and the manual and the command line work."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from saengine.verification.cases import BY_ID, CASES
from saengine.verification.cases.analysis import newmark_average_acceleration
from saengine.verification.cases.common import Quantity, fmt
from saengine.verification.run import main, render_pdf, run_all, summary_table

#: Quantities where SAEngine is known to be off, per case: each is explained in the case's
#: notes (and in docs/verification/README.md). A fix in SAEngine turns them into passes, which
#: this test accepts; any other failing quantity fails it.
KNOWN_ISSUES = {
    # Linear tetrahedra at the meshes Project Settings allow: about 8 % stiff in bending.
    "A9": {"Tip deflection, default 1000 mm mesh", "Tip deflection, 100 mm mesh (finest allowed)"},
}


@pytest.fixture(scope="module")
def pack(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The fast cases (all of them at present), run once for the tests of this module."""
    return run_all(tmp_path_factory.mktemp("verification"), fast_only=True)


def test_every_case_passes_but_the_known_issues(pack: dict) -> None:
    fast = [c.id for c in CASES if c.fast]
    assert [r["id"] for r in pack["cases"]] == fast
    assert {"analysis", "design"} == {r["category"] for r in pack["cases"]}
    errors = {r["id"]: r["error"] for r in pack["cases"] if r["error"]}
    assert errors == {}, summary_table(pack)
    unexpected = {
        r["id"]: names
        for r in pack["cases"]
        if (names := {q["name"] for q in r["quantities"] if not q["pass"]})
        - KNOWN_ISSUES.get(r["id"], set())
    }
    assert unexpected == {}, summary_table(pack)
    for record in pack["cases"]:
        assert record["reference"]["source"] and record["reference"]["formula"]
        assert record["quantities"]
        names = {q["name"] for q in record["quantities"]}
        assert KNOWN_ISSUES.get(record["id"], set()) <= names
        if record["id"] in KNOWN_ISSUES and not record["pass"]:
            assert any("KNOWN ISSUE" in n for n in record["notes"])
        for q in record["quantities"]:
            assert set(q) == {"name", "unit", "reference", "saengine", "ratio", "tolerance", "pass"}
            assert 0 < q["tolerance"] <= 0.05
    passed = sum(r["pass"] for r in pack["cases"])
    assert pack["summary"] == {"cases": len(fast), "passed": passed, "failed": len(fast) - passed}


def test_manual_pdf_builds(pack: dict) -> None:
    pdf, warnings = render_pdf(pack)
    assert pdf.startswith(b"%PDF") and warnings == []
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    # Cover, summary, then a page or more per case.
    assert len(reader.pages) >= 2 + len(pack["cases"])
    text = "".join(page.extract_text() for page in reader.pages)
    assert "Verification Manual" in text and "Timoshenko" in text
    summary = pack["summary"]
    assert f"{summary['passed']} of {summary['cases']} cases pass" in text


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--out", str(tmp_path), "--cases", "D1", "D4", "--jobs", "1", "--pdf"]) == 0
    data = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in data["cases"]] == ["D1", "D4"]
    assert (tmp_path / "verification-manual.pdf").read_bytes().startswith(b"%PDF")
    assert "2 of 2 cases pass" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unknown case ids: Z9"):
        run_all(tmp_path, ["Z9"])


def test_quantities_compare_within_their_tolerance() -> None:
    assert Quantity("x", "mm", 10.0, 10.09, 0.01).passed
    failing = Quantity("x", "mm", 10.0, 10.11, 0.01)
    assert not failing.passed and failing.ratio == pytest.approx(1.011)
    assert not Quantity("x", "mm", 0.0, 1.0, 0.01).passed
    assert Quantity("x", "mm", 0.0, 0.0, 0.01).as_dict()["pass"] is True
    assert (fmt(23.07e9), fmt(0.0021), fmt(146.876)) == ("2.307 × 10¹⁰", "0.0021", "146.9")


def test_newmark_integrator_of_a_suddenly_applied_ground_acceleration() -> None:
    # Undamped: a step üg = a0 swings the oscillator between 0 and -2 a0/ω² (Chopra, 4.3).
    mass, stiffness, a0, dt = 1.0, (2 * math.pi) ** 2, 1.0, 0.001
    u = newmark_average_acceleration(mass, stiffness, 0.0, np.full(2001, a0), dt)
    assert u.min() == pytest.approx(-2 * a0 * mass / stiffness, rel=1e-4)
    assert abs(u[1000]) < 1e-5  # back at rest after one period (1 s)


def test_cases_are_documented() -> None:
    assert len(BY_ID) == len(CASES)
    for case in CASES:
        assert case.id[0] == {"analysis": "A", "design": "D"}[case.category]
        assert case.title and case.description and case.model
