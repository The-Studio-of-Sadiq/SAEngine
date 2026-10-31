"""The design run's one count (N-X8 of usability walk 2) and how a member's utilisation is
ranked (N-X7): strength first, a detailing check only when it fails."""

from __future__ import annotations

from saengine.design.check import design_counts
from saengine.design.seismic_detailing import rate


def _check(name: str, utilisation: float, ok: bool = True, flag: bool = False) -> dict:
    return {
        "name": name,
        "utilisation": utilisation,
        "ok": ok,
        "flag": flag,
        "combination": "1.2D + 1.6L",
    }


def test_passing_detailing_equality_never_governs() -> None:
    # Every member read 1.00 from "lo 550 against 550 mm": the strength ratio governs now.
    entry = {
        "checks": [
            _check("Flexure (hogging)", 0.62),
            _check("Detailing: Confinement length lo (8.3.5.4(a))", 1.0),
            _check("Deflection", 1.4, ok=False, flag=True),  # reported only
        ]
    }
    rate(entry)
    assert entry["utilisation"] == 0.62 and entry["ok"]
    assert entry["strengthUtilisation"] == 0.62 and entry["detailingUtilisation"] == 1.0
    assert entry["governingCheck"] == {"name": "Flexure (hogging)", "combination": "1.2D + 1.6L"}


def test_failing_detailing_check_governs() -> None:
    entry = {
        "checks": [
            _check("Flexure (hogging)", 0.62),
            _check("Detailing: Cross-tie spacing hx (8.3.5.4(c))", 1.19, ok=False),
        ]
    }
    rate(entry)
    assert entry["utilisation"] == 1.19 and not entry["ok"]
    assert entry["governingCheck"]["name"].startswith("Detailing: Cross-tie")


def test_counts_keep_members_joints_and_building_apart() -> None:
    checked = [
        {"kind": "beam", "ok": True},
        {"kind": "beam", "ok": False},
        {"kind": "column", "ok": True},
        {"kind": "slab", "ok": True},
    ]
    skipped = [
        {"kind": "column", "reason": "no reinforcement"},
        {"kind": "slab", "reason": "not analysed as shells"},
    ]
    joints = [{"ok": True}, {"ok": False}, {"ok": False}]
    building = [{"ok": True}]
    from saengine.design import check

    skipped[0]["reason"] = check.NO_REINFORCEMENT
    counts = design_counts(checked, skipped, joints, building)
    members = counts["members"]
    assert (members["total"], members["checked"], members["passed"], members["failed"]) == (
        6,
        4,
        3,
        1,
    )
    assert members["notChecked"] == 2
    assert members["byKind"]["column"] == {
        "total": 2,
        "checked": 1,
        "passed": 1,
        "failed": 0,
        "notChecked": 1,
    }
    assert members["byKind"]["slab"]["notChecked"] == 1
    assert counts["joints"] == {"checked": 3, "passed": 1, "failed": 2}
    assert counts["building"] == {"checked": 1, "passed": 1, "failed": 0}
    assert counts["notChecked"] == {"noBars": 1, "other": 1}
