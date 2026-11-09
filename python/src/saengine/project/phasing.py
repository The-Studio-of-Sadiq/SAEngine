"""Phases of the building's elements and design options compared side by side (alpha 9 L11).

Phasing (``06 BIM/phasing.json``, :class:`Phasing`): the project's phases in order (by default
"Existing" then "New construction") and, per element of the building model (or of the
architecture), the phase it is created in and the phase it is demolished in, if any. The building
model is generated from the floor plan, so the phases live beside it, by element id, and survive
its regeneration. From them:

- :func:`status_in` says whether an element is existing, new, demolished or temporary in a phase,
  and :func:`visible_in` which elements stand in it (the BIM viewer's phase filter);
- :func:`phase_bill` splits the bill of quantities by phase: the new work of each phase (what is
  built and priced), the existing elements kept (not priced) and the demolition (its quantities,
  for a demolition item).

Design options: an option is a saved version of the project (:mod:`saengine.project.versions`: a
version id, an issue label, a tag or a branch) or the current files. :func:`compare_options`
measures each option's bill of quantities from that version's files, prices it with the project's
current schedule of rates (so options differ by design, not by rates) and lists the key figures
side by side: storeys, elements, concrete, bars, structural steel, cost, embodied carbon, and for
the current files the design checks' last summary (the results are computed caches and not kept
with versions). Option sets are kept in ``phasing.json`` too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = "saengine.phasing/1"
PHASING_FILE = "06 BIM/phasing.json"

#: The files a bill of quantities is measured from (project-relative).
BOQ_INPUTS = {
    "bim": "06 BIM/bim.json",
    "objects": "04 Objects/objects.json",
    "materials": "03 Materials/materials.json",
    "substructure": "09 Substructure/substructure.json",
    "settings": "02 Project Settings/project-settings.json",
    "mep": "07 MEP/mep.json",
    "architecture": "05 Floor Plan/architecture.json",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Phase(_Model):
    id: str
    name: str


class ElementPhase(_Model):
    created: str = Field(description="Phase id the element is built in.")
    demolished: str | None = Field(default=None, description="Phase id it is demolished in.")


class DesignOption(_Model):
    id: str
    name: str
    version: str = Field(
        default="working",
        description='A saved version (id, issue label, tag or branch) or "working".',
    )
    note: str = ""


class OptionSet(_Model):
    id: str
    name: str
    options: list[DesignOption] = Field(default_factory=list)


class Phasing(_Model):
    schema_: Literal["saengine.phasing/1"] = Field(default=SCHEMA, alias="schema")
    phases: list[Phase] = Field(
        default_factory=lambda: [
            Phase(id="existing", name="Existing"),
            Phase(id="new", name="New construction"),
        ],
        min_length=1,
        description="In order, earliest first.",
    )
    defaultPhase: str = Field(
        default="new", description="Phase of an element not listed in `elements`."
    )
    elements: dict[str, ElementPhase] = Field(default_factory=dict)
    optionSets: list[OptionSet] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids(self) -> Phasing:
        ids = [p.id for p in self.phases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate phase ids")
        if self.defaultPhase not in ids:
            raise ValueError(f"defaultPhase '{self.defaultPhase}' is not a phase")
        for element, ph in self.elements.items():
            if ph.created not in ids:
                raise ValueError(f"{element}: no phase '{ph.created}'")
            if ph.demolished is not None:
                if ph.demolished not in ids:
                    raise ValueError(f"{element}: no phase '{ph.demolished}'")
                if ids.index(ph.demolished) < ids.index(ph.created):
                    raise ValueError(f"{element}: demolished before it is created")
        return self

    def order(self, phase: str) -> int:
        return [p.id for p in self.phases].index(phase)

    def of(self, element: str) -> ElementPhase:
        return self.elements.get(element) or ElementPhase(created=self.defaultPhase)


def parse(text: str | None) -> Phasing:
    if not text or not text.strip():
        return Phasing()
    return Phasing.model_validate_json(text)


Status = Literal["existing", "new", "demolished", "temporary", "future", "gone"]


def status_in(phasing: Phasing, element: str, phase: str) -> Status:
    """The element in ``phase``: ``existing`` (built in an earlier phase, still standing), ``new``
    (built in it), ``demolished`` (taken down in it), ``temporary`` (built and taken down in it),
    ``future`` (not built yet) or ``gone`` (taken down earlier)."""
    p = phasing.order(phase)
    ph = phasing.of(element)
    created = phasing.order(ph.created)
    demolished = phasing.order(ph.demolished) if ph.demolished is not None else None
    if created > p:
        return "future"
    if demolished is not None and demolished < p:
        return "gone"
    if created == p:
        return "temporary" if demolished == p else "new"
    return "demolished" if demolished == p else "existing"


def visible_in(phasing: Phasing, elements: list[str], phase: str) -> dict[str, str]:
    """``{element: status}`` of the elements standing in (or taken down in) ``phase``."""
    out = {}
    for element in elements:
        status = status_in(phasing, element, phase)
        if status not in ("future", "gone"):
            out[element] = status
    return out


def phase_bill(bill: dict[str, Any], phasing: Phasing) -> dict[str, Any]:
    """The bill split by phase: ``{"phases": [{"phase", "name", "new": [items], "demolished":
    [items]}], "existing": [items]}``; each item ``{code, description, unit, quantity}``, its
    quantity the share of the elements of its breakdown in that phase. Items without a breakdown
    are new work of the default phase."""
    first = phasing.phases[0].id
    phases: dict[str, dict[str, dict[str, Any]]] = {
        p.id: {"new": {}, "demolished": {}} for p in phasing.phases
    }
    existing: dict[str, Any] = {}

    def add(target: dict[str, Any], item: dict[str, Any], quantity: float) -> None:
        line = target.setdefault(
            item["code"],
            {
                "code": item["code"],
                "group": item.get("group"),
                "description": item.get("description"),
                "unit": item.get("unit"),
                "quantity": 0.0,
            },
        )
        line["quantity"] += quantity

    for item in bill.get("items", []):
        if item.get("group") == "materials":
            continue
        breakdown = item.get("breakdown") or []
        if not breakdown:
            add(phases[phasing.defaultPhase]["new"], item, float(item.get("quantity") or 0.0))
            continue
        for entry in breakdown:
            q = float(entry.get("quantity") or 0.0)
            ph = phasing.of(str(entry.get("element")))
            if ph.created == first and phasing.order(first) == 0 and len(phasing.phases) > 1:
                # The first phase is what stands before the works: kept, not built.
                if ph.demolished is None:
                    add(existing, item, q)
            else:
                add(phases[ph.created]["new"], item, q)
            if ph.demolished is not None:
                add(phases[ph.demolished]["demolished"], item, q)

    def rows(lines: dict[str, Any]) -> list[dict[str, Any]]:
        return [{**v, "quantity": round(v["quantity"], 3)} for v in lines.values()]

    return {
        "phases": [
            {
                "phase": p.id,
                "name": p.name,
                "new": rows(phases[p.id]["new"]),
                "demolished": rows(phases[p.id]["demolished"]),
            }
            for p in phasing.phases
        ],
        "existing": rows(existing),
    }


def new_work_bill(bill: dict[str, Any], phasing: Phasing) -> dict[str, Any]:
    """The bill with only the new work (every phase after the first), its breakdown entries of
    existing elements left out: what the costing prices when the project has existing parts."""
    out = json.loads(json.dumps(bill))
    first = phasing.phases[0].id if len(phasing.phases) > 1 else None
    items = []
    for item in out.get("items", []):
        breakdown = item.get("breakdown") or []
        if not breakdown or first is None:
            items.append(item)
            continue
        kept = [e for e in breakdown if phasing.of(str(e.get("element"))).created != first]
        if not kept:
            continue
        if len(kept) != len(breakdown):
            item["quantity"] = round(sum(float(e.get("quantity") or 0.0) for e in kept), 3)
            item["breakdown"] = kept
        items.append(item)
    out["items"] = items
    return out


# ─────────────────────────────────── design options ───────────────────────────────────


def _totals(bill: dict[str, Any]) -> dict[str, float]:
    def total(group: str, unit: str) -> float:
        return round(
            sum(
                float(i.get("quantity") or 0.0)
                for i in bill.get("items", [])
                if i.get("group") == group and i.get("unit") == unit
            ),
            3,
        )

    return {
        "concrete": total("concrete", "m3"),
        "reinforcement": total("reinforcement", "kg"),
        "steel": total("steel", "kg"),
        "formwork": total("formwork", "m2"),
        "masonry": total("masonry", "m3"),
    }


def _model_figures(bim_text: str | None) -> dict[str, Any]:
    if not bim_text:
        return {}
    data = json.loads(bim_text)
    stories = data.get("stories") or []
    kinds: dict[str, int] = {}
    for e in data.get("elements") or []:
        kinds[str(e.get("kind"))] = kinds.get(str(e.get("kind")), 0) + 1
    elevations = [float(s.get("elevation") or 0.0) for s in stories]
    return {
        "storeys": len(stories),
        "height": round((max(elevations) - min(elevations)) / 1000, 3) if elevations else 0.0,
        "elements": kinds,
    }


def _design_summary(root: Path) -> dict[str, Any] | None:
    for path in sorted((root / "08 FEM").glob("*.results/design-summary.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return {
            k: data.get(k)
            for k in ("checked", "passed", "failed", "maxUtilisation", "governing")
            if k in data
        }
    return None


def option_figures(
    project_root: str, version: str | None, rates_text: str | None, carbon_text: str | None
) -> dict[str, Any]:
    """One option's figures: ``{"version", "model", "quantities", "cost", "carbon", "results",
    "problems"}``."""
    from saengine.boq.costing import cost_texts
    from saengine.boq.quantities import compute_boq_text
    from saengine.project import versions

    name, texts = versions.read_texts(project_root, version, BOQ_INPUTS.values())
    t = {key: texts[path] for key, path in BOQ_INPUTS.items()}
    out: dict[str, Any] = {"version": name, "model": _model_figures(t["bim"]), "problems": []}
    if not t["bim"] or not t["objects"] or not t["materials"]:
        out["problems"].append("the version has no building model, object types or materials")
        return out
    computed = compute_boq_text(
        t["bim"],
        t["objects"],
        t["materials"],
        t["substructure"],
        t["settings"],
        t["mep"],
        None,  # the plumbing tanks' designs are results, not kept with versions
        t["architecture"] or "",
    )
    if "problems" in computed:
        out["problems"] += computed["problems"]
        return out
    bill = json.loads(computed["text"])
    phasing_text = None
    if name == versions.WORKING:
        try:
            phasing_text = (Path(project_root) / PHASING_FILE).read_text(encoding="utf-8")
        except OSError:
            phasing_text = None
    else:
        _, more = versions.read_texts(project_root, version, [PHASING_FILE])
        phasing_text = more[PHASING_FILE]
    phasing = parse(phasing_text)
    if len(phasing.phases) > 1 and phasing.elements:
        bill = new_work_bill(bill, phasing)
        out["problems"].append("existing elements left out: the new work is priced")
    out["quantities"] = _totals(bill)
    priced = cost_texts(json.dumps(bill), rates_text, carbon_text)
    costing = priced.get("costing")
    if isinstance(costing, dict):
        out["cost"] = round(float(costing.get("total") or 0.0), 2)
        out["currency"] = costing.get("currency")
        out["carbon"] = round(float(costing.get("carbonTotal") or 0.0) / 1000, 3)  # t CO2e
        out["sampleRates"] = bool(priced.get("sampleRates"))
    else:
        out["problems"] += list(priced.get("problems") or [])
    out["results"] = _design_summary(Path(project_root)) if name == versions.WORKING else None
    return out


def compare_options(
    project_root: str,
    options: list[dict[str, Any]],
    rates_text: str | None = None,
    carbon_text: str | None = None,
) -> dict[str, Any]:
    """The options (``[{id?, name?, version}]``) side by side: ``{"options": [figures with
    "id", "name"], "deltas": [{figure: difference to the first option}], "notes"}``. Rates and
    carbon factors are the current ones (the project's when not given)."""
    root = Path(project_root)
    if rates_text is None:
        try:
            rates_text = (root / "10 BOQ/rates.json").read_text(encoding="utf-8")
        except OSError:
            rates_text = None
    if carbon_text is None:
        try:
            carbon_text = (root / "10 BOQ/carbon-factors.json").read_text(encoding="utf-8")
        except OSError:
            carbon_text = None
    from saengine.project.versions import VersionsError

    found = []
    for n, option in enumerate(options):
        version = option.get("version") or "working"
        try:
            figures = option_figures(project_root, version, rates_text, carbon_text)
        except VersionsError as error:
            figures = {"version": version, "problems": [str(error)]}
        found.append(
            {"id": option.get("id") or f"option{n + 1}", "name": option.get("name") or version}
            | figures
        )
    deltas = []
    base = found[0] if found else {}
    for option in found:
        delta: dict[str, float] = {}
        for key in ("cost", "carbon"):
            if isinstance(option.get(key), (int, float)) and isinstance(
                base.get(key), (int, float)
            ):
                delta[key] = round(option[key] - base[key], 3)
        for key, value in (option.get("quantities") or {}).items():
            before = (base.get("quantities") or {}).get(key)
            if isinstance(before, (int, float)):
                delta[key] = round(value - before, 3)
        deltas.append(delta)
    return {
        "options": found,
        "deltas": deltas,
        "notes": [
            (
                "Each option's quantities are measured from its version's files and priced with the "
                "current schedule of rates and carbon factors."
            ),
            (
                "Design results are kept only for the current files (results are not saved with "
                "versions): run the analysis on an option's branch to compare its checks."
            ),
        ],
    }
