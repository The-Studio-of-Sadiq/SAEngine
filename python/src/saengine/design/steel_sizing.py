"""Size Steel Members (issue #286): the lightest catalogue section per member group that passes
every strength and serviceability check under the design combinations, analysis and design
iterated until the sections stop changing.

The member checks and the "lightest passing section" search are the design mode's
(:func:`saengine.design.steel_design.proposal_entries`, :mod:`saengine.design.steel_proposal`):
this module adds only the loop around them and the options of the ribbon's Size Steel Members.

- A *group* is the set of members that share one section: an object type of 04 Objects (the
  default, ``sameSection``), or each member on its own (``sameSection`` false: members whose
  sections then differ are split into new types when the proposal is applied, as the RC
  proposal's split types are).
- Iteration k analyses the model with the sections of iteration k - 1 (the model's own the
  first time), designs every group with those forces and proposes its lightest passing section.
  When no group's section changes, the forces the proposal was checked with are the forces of
  the proposed sections: converged. Otherwise the model is analysed again with the proposed
  sections, up to ``maxIterations`` analyses; a proposal that has not converged (or that
  cycles between sections) is reported so, with the last sections proposed.
- Nothing is written to the project: :func:`size_steel` returns a proposal in the shape of
  :func:`saengine.design.proposal.apply_proposal` (``types``, ``newTypes``, ``reassign``) with
  the utilisation before (the model's own sections under the first analysis) and after (the
  proposed sections under the last analysis); the engineer applies it.

:func:`size_steel` is pure given ``analyse`` (tests pass a small frame analysis);
:func:`size_project` runs it on a project: the first analysis is the project's current results,
the later ones are run in a temporary copy of the project (derive, analyse, design checks).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The steel member kinds that are sized.
KINDS = ("beam", "column", "brace")


@dataclass
class SizingOptions:
    """Options of Size Steel Members.

    ``candidates``: section names per type id (``"*"``: every type) in place of the type's
    family; ``families``: a family per type id in place of its own; ``minDepth``/``maxDepth``:
    depth limits [mm] for every type, ``depths``: ``{type id: [min, max]}`` for one;
    ``types``: the type ids to size (default: every steel beam, column and brace type)."""

    max_iterations: int = 5
    limit: float = 1.0
    same_section: bool = True
    candidates: dict[str, list[str]] = field(default_factory=dict)
    families: dict[str, str] = field(default_factory=dict)
    min_depth: float | None = None
    max_depth: float | None = None
    depths: dict[str, list[float | None]] = field(default_factory=dict)
    types: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SizingOptions:
        d = data or {}

        def num(value: Any) -> float | None:
            try:
                x = float(value)
            except (TypeError, ValueError):
                return None
            return x if x > 0 else None

        candidates = d.get("candidates") or {}
        if isinstance(candidates, list | str):  # one list for every type
            candidates = {"*": candidates}
        candidates = {
            k: [n.strip() for n in (v.split(",") if isinstance(v, str) else v) if n.strip()]
            for k, v in candidates.items()
        }
        types = d.get("types")
        if isinstance(types, str):
            types = [t.strip() for t in types.split(",") if t.strip()] or None
        return cls(
            max_iterations=max(1, min(20, int(d.get("maxIterations") or 5))),
            limit=float(d.get("limit") or 1.0),
            same_section=bool(d.get("sameSection", True)),
            candidates={k: v for k, v in candidates.items() if v},
            families=dict(d.get("families") or {}),
            min_depth=num(d.get("minDepth")),
            max_depth=num(d.get("maxDepth")),
            depths=dict(d.get("depths") or {}),
            types=list(types) if types else None,
        )

    def limits_for(self, type_id: str) -> dict[str, Any]:
        """The ``limits`` entry of :func:`saengine.design.steel_proposal.steel_design_proposal`
        for a type."""
        lo, hi = (list(self.depths.get(type_id) or []) + [None, None])[:2]
        out: dict[str, Any] = {
            "minDepth": lo if lo is not None else self.min_depth,
            "maxDepth": hi if hi is not None else self.max_depth,
        }
        names = self.candidates.get(type_id) or self.candidates.get("*")
        if names:
            from saengine.library import steel_sections

            families = set(steel_sections.FAMILIES)
            expanded: list[str] = []
            for n in names:  # a family name stands for all its sections
                if n in families:
                    expanded += [s.name for s in steel_sections.family(n)]
                else:
                    expanded.append(n)
            out["candidates"] = expanded
        return out


#: ``analyse(profiles) -> collected``: the steel members of the model analysed with the
#: profile of each type id in ``profiles`` (and each member id, sized on its own), as
#: :func:`saengine.design.steel_design.design_member` collects them (``{"id", "kind", "type",
#: "material", "lengths", "stations", ...}``).
Analyse = Callable[[dict[str, dict[str, Any]], dict[str, str]], list[dict[str, Any]]]


def _section_name(entry_label: dict[str, Any] | None) -> str | None:
    if not entry_label:
        return None
    return entry_label.get("section") or entry_label.get("text")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", text) or "S"


def _key(profile: dict[str, Any]) -> str:
    return json.dumps(profile, sort_keys=True)


def size_steel(
    object_types: Iterable[dict[str, Any]],
    analyse: Analyse,
    options: SizingOptions | dict[str, Any] | None = None,
    report: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The sizing proposal (see the module): ``{"mode": "steelSizing", "converged",
    "iterations", "history", "types", "newTypes", "reassign", "groups", "warnings", "notes"}``.

    ``object_types``: 04 Objects types as JSON (only steel beam, column and brace types with a
    profile are sized); ``analyse``: see :data:`Analyse` (its second argument maps each member
    sized on its own to its type)."""
    from saengine.design import steel_design

    opts = options if isinstance(options, SizingOptions) else SizingOptions.from_dict(options)
    say = report or (lambda _text: None)
    types = {
        t["id"]: t
        for t in object_types
        if t.get("kind") in KINDS
        and "profile" in t
        and (opts.types is None or t["id"] in opts.types)
    }
    # Iteration state: the profile of each group (a type, or a member on its own).
    profiles: dict[str, dict[str, Any]] = {k: copy.deepcopy(t["profile"]) for k, t in types.items()}
    member_type: dict[str, str] = {}  # sized-on-its-own member -> its type
    first: dict[str, dict[str, Any]] = {}  # group -> its entry of the first design
    history: list[dict[str, Any]] = []
    seen: list[dict[str, str]] = []
    warnings: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    converged = False
    iterations = 0
    while iterations < opts.max_iterations:
        iterations += 1
        say(f"Iteration {iterations}: analysis")
        type_profiles = {k: v for k, v in profiles.items() if k in types}
        member_profiles = {k: v for k, v in profiles.items() if k not in types}
        collected = analyse({**type_profiles, **member_profiles}, dict(member_type))
        say(f"Iteration {iterations}: design")
        groups_of: dict[str, list[dict[str, Any]]] = {}
        for m in collected:
            type_id = member_type.get(m["id"], m["type"])
            if type_id not in types:
                continue
            gid = type_id if opts.same_section else m["id"]
            if gid not in profiles:  # first design: each member starts with its type's
                profiles[gid] = copy.deepcopy(profiles[type_id])
                member_type[gid] = type_id
            groups_of.setdefault(gid, []).append({**m, "type": gid})
        if not opts.same_section:
            for type_id in types:  # the types themselves are now their members' groups
                profiles.pop(type_id, None)
        originals = {
            gid: {**types[member_type.get(gid, gid)], "id": gid, "profile": profiles[gid]}
            for gid in groups_of
        }
        limits = {gid: opts.limits_for(member_type.get(gid, gid)) for gid in groups_of}
        found, notes = steel_design.proposal_entries(
            [m for ms in groups_of.values() for m in ms], originals, limits
        )
        warnings += [n for n in notes if n not in warnings]
        entries = {e["type"]: e for e in found}
        for gid, e in entries.items():
            first.setdefault(gid, e)
        proposed = {
            gid: (e.get("proposed") or {}).get("profile") or profiles[gid]
            for gid, e in entries.items()
        }
        changed = sorted(gid for gid in proposed if _key(proposed[gid]) != _key(profiles[gid]))
        names = {
            gid: _section_name(e.get("proposed") or e.get("current")) for gid, e in entries.items()
        }
        history.append(
            {
                "iteration": iterations,
                "changed": changed,
                "sections": names,
                "maxUtilisation": max(
                    (e.get("proposedUtilisation") or 0.0 for e in entries.values()), default=0.0
                ),
                "mass": round(_mass(entries), 3),
            }
        )
        if not changed:
            converged = True
            break
        state = {gid: _key(p) for gid, p in proposed.items()}
        if state in seen:
            warnings.append(
                f"the sections cycle (iteration {iterations} proposes those of an earlier one): "
                f"{', '.join(changed)}; check these groups by hand or narrow their candidates"
            )
            profiles.update(proposed)
            break
        seen.append({gid: _key(p) for gid, p in profiles.items() if gid in proposed})
        profiles.update(proposed)
    if not converged and not any("cycle" in w for w in warnings):
        warnings.append(
            f"not converged in {opts.max_iterations} iteration(s): the last sections proposed "
            "were not checked under the forces of their own analysis; apply them and run Size "
            "Steel Members again"
        )
    rows = _rows(types, member_type, first, entries, opts.same_section)
    proposal = _proposal(types, member_type, rows, opts.same_section)
    return {
        "mode": "steelSizing",
        "converged": converged,
        "iterations": iterations,
        "history": history,
        **proposal,
        "groups": rows,
        "warnings": warnings,
        "notes": [
            (
                "Lightest catalogue section per group passing every strength and serviceability "
                "check of the design combinations; analysis and design iterated until the "
                "sections stop changing. Nothing is changed until you apply the proposal."
            ),
        ],
    }


def _mass(entries: dict[str, dict[str, Any]]) -> float:
    return sum(
        float((e.get("proposed") or e.get("current") or {}).get("mass") or 0.0)
        for e in entries.values()
    )


def _rows(
    types: dict[str, dict[str, Any]],
    member_type: dict[str, str],
    first: dict[str, dict[str, Any]],
    last: dict[str, dict[str, Any]],
    same_section: bool,
) -> list[dict[str, Any]]:
    """One row per group: the model's section and its utilisation under the first analysis,
    the proposed section and its utilisation under the last."""
    rows = []
    for gid, e in last.items():
        before = first.get(gid, e)
        current = before.get("current") or {}
        if not same_section:  # the type's own section, not the member's last trial
            current = (first.get(gid) or {}).get("current") or current
        proposed = e.get("proposed")
        rows.append(
            {
                "group": gid,
                "type": member_type.get(gid, gid),
                "kind": e.get("kind"),
                "members": e.get("members", []),
                "current": current,
                "currentSection": _section_name(current),
                "currentMass": current.get("mass"),
                "currentUtilisation": before.get("currentUtilisation"),
                "proposed": proposed,
                "proposedSection": _section_name(proposed),
                "proposedMass": (proposed or {}).get("mass"),
                "proposedUtilisation": e.get("proposedUtilisation"),
                "governingCheck": e.get("governingCheck"),
                "governingMember": e.get("governingMember"),
                "status": "tooSmall"
                if proposed is None
                else (
                    "unchanged"
                    if _key(proposed.get("profile") or {}) == _key(current.get("profile") or {})
                    else "ok"
                ),
                "tooSmall": e.get("tooSmall"),
                "family": e.get("family"),
                "notes": e.get("notes", []),
            }
        )
    return rows


def _proposal(
    types: dict[str, dict[str, Any]],
    member_type: dict[str, str],
    rows: list[dict[str, Any]],
    same_section: bool,
) -> dict[str, Any]:
    """``types``/``newTypes``/``reassign`` of :func:`saengine.design.proposal.apply_proposal`."""

    def entry(row: dict[str, Any], type_id: str) -> dict[str, Any]:
        return {
            "type": type_id,
            "kind": row["kind"],
            "name": types[type_id].get("name", type_id),
            "family": row["family"] or "",
            "current": row["current"],
            "proposed": row["proposed"],
            "status": row["status"],
            "members": row["members"],
            "currentUtilisation": row["currentUtilisation"],
            "proposedUtilisation": row["proposedUtilisation"],
            "governingCheck": row["governingCheck"],
            "governingMember": row["governingMember"],
            "tooSmall": row["tooSmall"],
            "notes": row["notes"],
        }

    if same_section:
        return {"types": [entry(r, r["group"]) for r in rows], "newTypes": [], "reassign": []}
    # Each member on its own: the section most of a type's members take stays the type's; the
    # members of each other section move to a new type of that section.
    out_types, new_types, reassign = [], [], []
    taken = set(types)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    for type_id, group in by_type.items():
        buckets: dict[str, list[dict[str, Any]]] = {}
        for r in group:
            p = r["proposed"] or r["current"]
            buckets.setdefault(_key(p.get("profile") or {}), []).append(r)
        ordered = sorted(buckets.values(), key=lambda b: (-len(b), b[0]["group"]))
        main = ordered[0]
        worst = max(main, key=lambda r: r["proposedUtilisation"] or 0.0)
        e = entry(worst, type_id)
        e["members"] = [m for r in main for m in r["members"]]
        e["currentUtilisation"] = max((r["currentUtilisation"] or 0.0) for r in group)
        out_types.append(e)
        for bucket in ordered[1:]:
            label = bucket[0]["proposed"] or bucket[0]["current"]
            new_id = f"{type_id}-{_slug(_section_name(label) or 'S')}"
            n = 2
            while new_id in taken:
                new_id = f"{type_id}-{_slug(_section_name(label) or 'S')}-{n}"
                n += 1
            taken.add(new_id)
            worst = max(bucket, key=lambda r: r["proposedUtilisation"] or 0.0)
            new_types.append(
                {
                    "type": new_id,
                    "from": type_id,
                    "name": f"{types[type_id].get('name', type_id)} ({_section_name(label)})",
                    "profile": label.get("profile"),
                    "proposed": label,
                    "members": [m for r in bucket for m in r["members"]],
                    "currentUtilisation": max((r["currentUtilisation"] or 0.0) for r in bucket),
                    "proposedUtilisation": worst["proposedUtilisation"],
                }
            )
            reassign += [
                {"member": m, "from": type_id, "to": new_id} for r in bucket for m in r["members"]
            ]
    return {"types": out_types, "newTypes": new_types, "reassign": reassign}


# ─────────────────────────────────────── on a project ───────────────────────────────────────


def size_project(
    project_root: str | Path,
    options: dict[str, Any] | None = None,
    report: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """:func:`size_steel` on the project at ``project_root``: the first analysis is the
    project's current results (Run All or Analyse first), the later ones are run in a temporary
    copy of the project, which is removed afterwards. Returns the proposal, or ``{"error"}``."""
    import shutil
    import tempfile

    from saengine.design.proposal import apply_proposal
    from saengine.design.required import gather
    from saengine.pipeline import run_all
    from saengine.pipeline.design_mode import gathered as kept_gathering
    from saengine.pipeline.project import open_project, write_text

    project = open_project(project_root)
    model = project.file("fem")
    out_dir = run_all.results_folder(model)
    if not out_dir.is_dir() or not run_all.results_current(model):
        return {
            "error": "Analyse the model first (Run All, or Analyse): Size Steel Members starts "
            "from the current analysis results."
        }
    objects_text = project.text("objects") or ""
    bim_text = project.text("bim") or ""
    objects = json.loads(objects_text)
    opts = SizingOptions.from_dict(options)
    original = {t["id"]: t.get("profile") for t in objects.get("objects", [])}
    work = Path(tempfile.mkdtemp(prefix="saengine-sizing-"))
    copy_root = work / project.root.name
    state = {"copied": False}

    def analyse(profiles: dict[str, dict[str, Any]], member_type: dict[str, str]):
        same = all(
            _key(p) == _key(original.get(k) or {}) for k, p in profiles.items() if k in original
        ) and not any(k not in original for k in profiles)
        if same:
            found = kept_gathering(out_dir, model, substructure=False)
            return list(found.collect.get("steel", []))
        if not state["copied"]:
            shutil.copytree(
                project.root,
                copy_root,
                ignore=shutil.ignore_patterns("*.results", ".git", "node_modules"),
            )
            state["copied"] = True
        copied = open_project(copy_root)
        rows = [
            {
                "group": gid,
                "type": member_type.get(gid, gid),
                "kind": None,
                "members": [gid] if gid in member_type else [],
                "current": {"profile": original.get(member_type.get(gid, gid))},
                "proposed": {"profile": p, "section": gid, "text": gid},
                "currentUtilisation": None,
                "proposedUtilisation": None,
                "governingCheck": None,
                "governingMember": None,
                "status": "ok",
                "tooSmall": None,
                "family": "sizing",
                "notes": [],
            }
            for gid, p in profiles.items()
        ]
        types = {t["id"]: t for t in objects.get("objects", [])}
        trial = _proposal(types, member_type, rows, not member_type)
        applied = apply_proposal(objects_text, bim_text, trial)
        write_text(copied.file("objects"), applied["objectsText"])
        write_text(copied.file("bim"), applied["bimText"])
        step = run_all.StepResult("derive")
        run_all._derive(copied, step)  # Run All's own derive step
        fem = copied.file("fem")
        outcome = run_all.run_analysis(fem)
        if outcome["status"] != "done":
            raise RuntimeError(outcome.get("message") or outcome["status"])
        return list(gather(run_all.results_folder(fem), fem, False).collect.get("steel", []))

    try:
        return size_steel(objects.get("objects", []), analyse, opts, report)
    except (RuntimeError, run_all.StepFailure, ValueError) as error:
        return {"error": f"Size Steel Members stopped: {error}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


__all__ = ["KINDS", "SizingOptions", "size_project", "size_steel"]
