"""What Run All and the part list keep of the fire report (``07 MEP/mep.summary.json``
``fire``), the same as the workbench's ``fireSummaryFile`` (fireDocument.ts) writes."""

from __future__ import annotations

from typing import Any


def _records(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def has_fire(document: dict[str, Any]) -> bool:
    """Whether 07 MEP has a fire section with anything to check (``hasFire``)."""
    fire = document.get("fire")
    if not isinstance(fire, dict):
        return False
    return any(_records(fire.get(k)) for k in ("stories", "risers", "tanks", "pumps", "mains"))


def fire_failures(raw: dict[str, Any]) -> int:
    """The failing checks of a fire report (``fireFailures``)."""
    return sum(1 for c in _records(raw.get("checks")) if c.get("ok") is False)


def fire_summary_file(document: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """``fireSummaryFile``: the counts and sizes the part list and Run All show."""
    fire = document.get("fire") if isinstance(document.get("fire"), dict) else {}
    result: dict[str, Any] = {
        "risers": len(_records(fire.get("risers"))),
        "pumps": len(_records(fire.get("pumps"))),
        "tanks": len(_records(fire.get("tanks"))),
    }
    demand = raw.get("demand") if isinstance(raw.get("demand"), dict) else None
    if demand:
        result["flow"] = demand.get("flow")
        result["reservoir"] = demand.get("volume")
    systems = (raw.get("requirements") or {}).get("systems") if isinstance(
        raw.get("requirements"), dict) else None  # fmt: skip
    result["required"] = [
        s.get("system") for s in _records(systems) if s.get("status") == "required"
    ]
    openings = raw.get("openings")
    result["openingsToAdd"] = len(openings) if isinstance(openings, list) else 0
    result["failed"] = fire_failures(raw)
    return result
