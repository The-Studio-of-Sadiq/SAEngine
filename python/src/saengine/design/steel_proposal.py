"""Design mode for structural steel: the lightest table section that passes, per object type.

Like the RC proposals (:mod:`saengine.design.proposal`), a proposal is made per object type of
04 Objects, for all the members placed with it: every candidate section of the family (the
type's own, by :func:`saengine.library.steel_sections.families_for`, or one the engineer
picks) is checked, lightest first, against every station of every combination of every
member, and the first that passes everywhere is proposed. The member with the highest
utilisation under the proposed section is the governing member. When no section of the family
passes, the type is reported ``tooSmall`` with the other families' lightest passing sections
as suggestions; nothing is changed for it.

The member checks are :func:`saengine.design.steel.check_member` (BNBC 2020 Part 6 Chapter 10:
local buckling classes, flexural and torsional buckling, lateral-torsional buckling with the
member's brace points and Cb, shear, H1 interaction), through :func:`steel_member_checker`. Each
candidate is checked in the orientation of the type's profile (an RHS lying on its side is
checked, and proposed, lying on its side). A reduced stand-in (:func:`stub_member_checks`, no
lateral-torsional buckling) is used only if :mod:`saengine.design.steel` cannot be imported,
and every entry then says so in its notes.

:func:`apply_steel_proposal` is pure (texts in, texts out), as :func:`proposal.apply_proposal`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from saengine.library import steel_sections as tbl
from saengine.library.steel_sections import SteelSection

# ─────────────────────────────────────── inputs ───────────────────────────────────────


@dataclass(frozen=True)
class SteelMaterial:
    name: str
    fy: float  # MPa
    fu: float  # MPa
    E: float = 200_000.0  # MPa
    G: float = 77_200.0  # MPa

    @classmethod
    def from_material(cls, material: Any) -> SteelMaterial:
        """From a 03 Materials ``Material`` (model or JSON dict) of category steel."""
        m = material if isinstance(material, dict) else material.model_dump()
        steel = m.get("steel") or {}
        fy = float(steel["fy"])
        fu = float(steel.get("fu") or 1.25 * fy)
        e = float((m.get("mechanical") or {}).get("E") or 200_000.0)
        nu = float((m.get("mechanical") or {}).get("nu") or 0.3)
        return cls(m.get("id") or m.get("name") or "steel", fy, fu, e, e / (2 * (1 + nu)))


@dataclass(frozen=True)
class MemberLengths:
    """Lengths in mm: ``L`` the member, ``Kx``/``Ky`` effective length factors about the
    major/minor axes, ``Lb`` the laterally unbraced length (default ``L``), ``Cb``."""

    L: float
    Kx: float = 1.0
    Ky: float = 1.0
    Lb: float | None = None
    Cb: float = 1.0

    @property
    def unbraced(self) -> float:
        return self.L if self.Lb is None else self.Lb


@dataclass(frozen=True)
class StationForces:
    """Section forces at one station under one combination: N (tension +) and shears in N,
    moments in N·mm, about the profile's x (horizontal) and y axes: ``Vx`` is the shear along
    the depth (with ``Mx``). ``s`` is the station's position along the member [m] (default:
    the stations of a combination spread evenly over its length, in the order given)."""

    combination: str | None
    N: float = 0.0
    Vx: float = 0.0  # shear along the depth (with the major-axis moment)
    Vy: float = 0.0
    Mx: float = 0.0  # major-axis moment
    My: float = 0.0
    T: float = 0.0
    s: float | None = None


@dataclass
class SteelMemberDemand:
    id: str
    #: :class:`MemberLengths` (mm), or :class:`saengine.design.steel.lengths.MemberLengths`
    #: (the member's brace points from the model, m), passed straight to the checks.
    lengths: Any
    #: :class:`StationForces`, or :class:`saengine.design.steel.members.Stations` (one per
    #: combination, as :func:`saengine.design.steel.member_stations` gives them).
    forces: list[Any]
    kind: str = "member"  # "beam", "column" or "brace"
    #: The member checks' options (:class:`saengine.design.steel.SteelOptions`: the stability
    #: design method of the run), passed to a checker that takes ``options``.
    options: Any = None


#: checker(forces, section, material, lengths, kind=...) -> [check dicts]; ``section`` is the
#: candidate in the orientation of the type's profile.
MemberChecker = Callable[..., list[dict[str, Any]]]


# ──────────────────────────────── stand-in member checks ────────────────────────────────


def _check(name, demand, capacity, unit, combination, note="", flag=False) -> dict[str, Any]:
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
    }


def _shear_area(s: SteelSection) -> tuple[float, float]:
    """(major, minor) shear areas [mm²]."""
    if s.shape in ("I", "U"):
        return s.h * s.tw, 2 * s.b * s.tf
    if s.shape == "rectangleHollow":
        return 2 * (s.h - 3 * s.tw) * s.tw, 2 * (s.b - 3 * s.tw) * s.tw
    if s.shape == "circleHollow":
        return s.A / 2, s.A / 2
    return s.h * s.tw, s.b * s.tw  # angle legs


def compression_capacity(area: float, m: SteelMaterial, kl_r: float) -> float:
    """φcPn for flexural buckling, BNBC 2020 Part 6 Sec 10.5.3 Eq 6.10.16-6.10.19 (part 2
    p. 60), φc = 0.90; no slender-element reduction."""
    if kl_r <= 0:
        return 0.9 * m.fy * area
    fe = math.pi**2 * m.E / kl_r**2
    fcr = 0.658 ** (m.fy / fe) * m.fy if fe >= 0.44 * m.fy else 0.877 * fe
    return 0.9 * fcr * area


def stub_member_checks(
    forces: Sequence[StationForces],
    s: SteelSection,
    m: SteelMaterial,
    lengths: MemberLengths,
    kind: str = "member",
) -> list[dict[str, Any]]:
    """A reduced stand-in for stream T's checks: tension yielding, flexural buckling (BNBC
    10.5.3), plastic flexure about both axes (no lateral-torsional or local buckling), shear
    and the H1-1 interaction (from memory of AISC 360). Used only when
    :mod:`saengine.design.steel` cannot be imported, and in tests."""
    note = "stand-in check (no lateral-torsional or local buckling)"
    forces = [f for f in forces if isinstance(f, StationForces)]
    lengths = _mm_lengths(lengths)
    phi_t = 0.9 * m.fy * s.A
    r_minor = s.rv if s.rv is not None else s.ry
    kl_r = max(lengths.Kx * lengths.L / s.rx, lengths.Ky * lengths.L / r_minor)
    phi_c = compression_capacity(s.A, m, kl_r)
    phi_mx, phi_my = 0.9 * m.fy * s.Zx, 0.9 * m.fy * s.Zy
    avx, avy = _shear_area(s)
    phi_vx, phi_vy = 0.9 * 0.6 * m.fy * avx, 0.9 * 0.6 * m.fy * avy
    worst: dict[str, tuple[float, float, str | None]] = {}

    def keep(name: str, demand: float, capacity: float, combination: str | None) -> None:
        u = demand / capacity if capacity > 0 else math.inf
        if name not in worst or u > worst[name][0] / max(worst[name][1], 1e-12):
            worst[name] = (demand, capacity, combination)

    for f in forces:
        if f.N >= 0:
            keep("tension yielding", f.N / 1e3, phi_t / 1e3, f.combination)
            pr, pc = f.N, phi_t
        else:
            keep("compression (flexural buckling)", -f.N / 1e3, phi_c / 1e3, f.combination)
            pr, pc = -f.N, phi_c
        keep("flexure, major axis", abs(f.Mx) / 1e6, phi_mx / 1e6, f.combination)
        keep("flexure, minor axis", abs(f.My) / 1e6, phi_my / 1e6, f.combination)
        keep("shear, major axis", abs(f.Vx) / 1e3, phi_vx / 1e3, f.combination)
        keep("shear, minor axis", abs(f.Vy) / 1e3, phi_vy / 1e3, f.combination)
        ratio = pr / pc if pc > 0 else math.inf
        bend = abs(f.Mx) / phi_mx + abs(f.My) / phi_my
        u = ratio + 8 / 9 * bend if ratio >= 0.2 else ratio / 2 + bend
        keep("combined forces (H1-1)", u, 1.0, f.combination)

    units = {"flexure": "kN·m", "combined": "-"}
    checks = [
        _check(
            name, d, c, next((v for k, v in units.items() if name.startswith(k)), "kN"), comb, note
        )
        for name, (d, c, comb) in worst.items()
    ]
    if any(f.N < 0 for f in forces):
        checks.append(_check("slenderness KL/r", kl_r, 200.0, "-", None, note, flag=True))
    return checks


def _mm_lengths(lengths: Any) -> MemberLengths:
    """:class:`MemberLengths` of either kind, in this module's (mm) form."""
    if isinstance(lengths, MemberLengths):
        return lengths
    k = getattr(lengths, "k", {}) or {}
    length = max(lengths.length, 1e-9)
    return MemberLengths(
        lengths.length * 1e3,
        k.get("x", 1.0) * lengths.x.longest() / length,
        k.get("y", 1.0) * lengths.y.longest() / length,
        lengths.ltb_top.longest() * 1e3,
    )


def to_stations(forces: Sequence[Any], length: float) -> list[Any]:
    """:class:`StationForces` as :class:`saengine.design.steel.members.Stations` (one per
    combination): P = -N (compression positive), Vy (along the depth) = this module's Vx, Vx =
    Vy, moments as they are [N·mm]; ``length`` [m] spreads the stations that have no ``s``.
    Stations already in that form pass through."""
    import numpy as np

    from saengine.design.steel.members import Stations

    if all(isinstance(f, Stations) for f in forces):
        return list(forces)
    groups: dict[str | None, list[StationForces]] = {}
    for f in forces:
        groups.setdefault(f.combination, []).append(f)
    result = []
    for name, group in groups.items():
        n = len(group)
        s = [
            f.s if f.s is not None else (length * i / (n - 1) if n > 1 else 0.0)
            for i, f in enumerate(group)
        ]
        order = sorted(range(n), key=lambda i: s[i])
        g = [group[i] for i in order]
        result.append(
            Stations(
                name or "",
                np.array([s[i] for i in order], dtype=float),
                np.array([-f.N for f in g], dtype=float),
                np.array([f.Mx for f in g], dtype=float),
                np.array([f.My for f in g], dtype=float),
                np.array([f.Vx for f in g], dtype=float),
                np.array([f.Vy for f in g], dtype=float),
                [f"station {k + 1}" for k in range(n)],
            )
        )
    return result


def steel_member_checker(
    forces: Sequence[Any],
    section: SteelSection,
    material: SteelMaterial,
    lengths: Any,
    kind: str = "member",
    options: Any = None,
) -> list[dict[str, Any]]:
    """The BNBC 2020 Chapter 10 checks of one member with a candidate section:
    :func:`saengine.design.steel.check_member` on the shape of the candidate's 04 Objects
    profile (in its orientation; ERW design wall thickness for hollow sections), the material
    as :class:`saengine.design.steel.Steel`, the forces as Stations (:func:`to_stations`) and
    the lengths as stream T's MemberLengths, passed through; a :class:`MemberLengths` of this
    module becomes ``MemberLengths.simple`` with lateral brace points every Lb (Cb then comes
    from the moment diagram, not from ``Cb``)."""
    from pydantic import TypeAdapter

    from saengine.design.steel import Steel, check_member, shape_properties
    from saengine.design.steel.lengths import MemberLengths as TLengths
    from saengine.library.objects import Profile

    if isinstance(lengths, MemberLengths):
        length = lengths.L / 1e3
        ltb = None
        if lengths.Lb is not None and 0 < lengths.Lb < lengths.L:
            n = math.ceil(lengths.L / lengths.Lb - 1e-9)
            ltb = [length * i / n for i in range(1, n)]
        t_lengths = TLengths.simple(length, ltb=ltb, k={"x": lengths.Kx, "y": lengths.Ky})
    else:
        t_lengths = lengths
        length = lengths.length
    profile = TypeAdapter(Profile).validate_python(section.profile())
    shape = shape_properties(profile)
    steel = Steel(material.fy, material.fu, material.E, material.name)
    stations = to_stations(forces, length)
    return check_member(shape, steel, stations, t_lengths, kind, options)


def default_checker() -> tuple[MemberChecker, bool]:
    """:func:`steel_member_checker` (True), or the stand-in when :mod:`saengine.design.steel`
    cannot be imported (False)."""
    try:
        import saengine.design.steel  # noqa: F401
    except ImportError:
        return stub_member_checks, False
    return steel_member_checker, True


def _call(checker: MemberChecker, member: SteelMemberDemand, s: SteelSection, m: SteelMaterial):
    """The checker, with the member's kind when it takes one."""
    import inspect

    try:
        params = inspect.signature(checker).parameters
    except (TypeError, ValueError):
        params = {}
    if member.options is not None and (
        "options" in params or any(p.kind is p.VAR_KEYWORD for p in params.values())
    ):
        return checker(
            member.forces, s, m, member.lengths, kind=member.kind, options=member.options
        )
    if "kind" in params or any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return checker(member.forces, s, m, member.lengths, kind=member.kind)
    return checker(member.forces, s, m, member.lengths)


def utilisation_of(checks: Iterable[dict[str, Any]]) -> float:
    """The largest utilisation of the strength checks (``flag`` checks only report)."""
    return max((float(c["utilisation"]) for c in checks if not c.get("flag")), default=0.0)


# ─────────────────────────────────────── proposal ───────────────────────────────────────


@dataclass
class _Trial:
    section: SteelSection
    utilisation: float
    governing: str | None
    by_check: dict[str, float] = field(default_factory=dict)


def _trial(
    s: SteelSection,
    members: Sequence[SteelMemberDemand],
    material: SteelMaterial,
    checker: MemberChecker,
    limit: float,
    stop_early: bool = True,
) -> _Trial:
    worst, governing = 0.0, None
    by_check: dict[str, float] = {}
    for member in members:
        checks = _call(checker, member, s, material)
        u = utilisation_of(checks)
        for c in checks:
            if not c.get("flag"):
                by_check[c["name"]] = max(by_check.get(c["name"], 0.0), float(c["utilisation"]))
        if governing is None or u > worst:
            worst, governing = u, member.id
        if stop_early and worst > limit:
            break
    return _Trial(s, worst, governing, by_check)


def slender_elements(s: SteelSection, material: SteelMaterial) -> list[str]:
    """The compression elements of ``s`` that are slender in uniform compression (λ > λr, BNBC
    2020 Part 6 Sec 10.2.4, Table 6.10.1, pp 3825-3829), described; empty when none, or when the
    shape cannot be classified."""
    from pydantic import TypeAdapter, ValidationError

    from saengine.design.steel.classify import compression_elements
    from saengine.design.steel.properties import shape_properties
    from saengine.library import objects as o

    try:
        shape = shape_properties(TypeAdapter(o.Profile).validate_python(s.profile()))
    except (ValidationError, ValueError, TypeError):
        return []
    return [e.describe() for e in compression_elements(shape, material.fy, material.E) if e.slender]


def _label(s: SteelSection | None, profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if s is None and profile is None:
        return None
    if s is None:
        return {"section": None, "text": f"custom {profile.get('shape')}", "profile": profile}
    return {
        "section": s.name,
        "family": s.family,
        "text": f"{s.name} ({s.mass:.1f} kg/m)",
        "profile": s.profile() if profile is None else profile,
        "mass": round(s.mass, 2),
    }


def propose_type(
    type_id: str,
    kind: str,
    name: str,
    profile: dict[str, Any],
    members: Sequence[SteelMemberDemand],
    material: SteelMaterial,
    family: str | None = None,
    checker: MemberChecker | None = None,
    limit: float = 1.0,
) -> dict[str, Any]:
    """The proposal entry of one object type (the RC proposal's shape: ``{"type", "kind",
    "name", "current", "proposed", "status", "governingMember", "members", "utilisation",
    "family", "tooSmall", "notes"}``)."""
    real = checker is not None
    if checker is None:
        checker, real = default_checker()
    notes: list[str] = []
    if not real:
        notes.append(
            "checked with the stand-in member checks (no lateral-torsional or local buckling): "
            "saengine.design.steel could not be imported"
        )
    current = tbl.match(profile)
    if tbl.is_turned(profile):
        notes.append("the box lies on its side: candidates are checked and proposed so")
    fams = tbl.families_for(profile)
    fam = family or (fams[0] if fams else None)
    entry: dict[str, Any] = {
        "type": type_id,
        "kind": kind,
        "name": name,
        "current": _label(current, profile),
        "proposed": None,
        "status": "tooSmall",
        "governingMember": None,
        "members": [m.id for m in members],
        "utilisation": {},
        "family": fam,
        "tooSmall": None,
        "notes": notes,
    }
    if fam is None:
        entry["tooSmall"] = {"reason": f"no section family for a {profile.get('shape')} profile"}
        return entry
    if current is None:
        notes.append("the current profile is not a table section")
    if not members:
        entry["tooSmall"] = {"reason": "no analysed members of this type"}
        return entry

    # Braces and columns are never proposed with slender plates (X12 of the usability walk: a
    # brace at b/t about 40): the lightest section that passes only through the slender-element
    # reduction Q is a poor pick for a member that buckles, and none for a seismic brace.
    nonslender = kind in ("brace", "column")
    skipped_slender: list[str] = []

    def first_passing(fam_name: str) -> _Trial | None:
        for s in tbl.family(fam_name):
            s = tbl.oriented(s, profile)
            if nonslender:
                slender = slender_elements(s, material)
                if slender:
                    skipped_slender.append(f"{s.name}: {slender[0]}")
                    continue
            t = _trial(s, members, material, checker, limit)
            if t.utilisation <= limit:
                return _trial(s, members, material, checker, limit, stop_early=False)
        return None

    pick = first_passing(fam)
    if pick is None:
        largest = tbl.oriented(tbl.family(fam)[-1], profile)
        t = _trial(largest, members, material, checker, limit, stop_early=False)
        suggestion = None
        for other in fams:
            if other == fam:
                continue
            alt = first_passing(other)
            if alt is not None:
                suggestion = f"{alt.section.name} ({alt.section.mass:.1f} kg/m) of {other}"
                break
        entry["tooSmall"] = {
            "reason": f"no {fam} section passes: the largest, {largest.name}, is at "
            f"{t.utilisation:.2f} (member {t.governing})",
            "suggestion": suggestion,
        }
        entry["governingMember"] = t.governing
        return entry
    if skipped_slender:  # the family runs light to heavy: all of them lighter than the pick
        notes.append(
            f"{len(skipped_slender)} lighter {fam} section(s) with slender plates in compression "
            f"passed over (BNBC 2020 Part 6 Table 6.10.1), e.g. {skipped_slender[0]}"
        )
    # the candidate is already in the profile's orientation (on its side if the type's is)
    entry["proposed"] = _label(pick.section, pick.section.profile())
    entry["governingMember"] = pick.governing
    entry["utilisation"] = {k: round(v, 3) for k, v in pick.by_check.items()}
    entry["status"] = (
        "unchanged" if current is not None and current.name == pick.section.name else "ok"
    )
    if current is not None and entry["status"] == "ok":
        delta = pick.section.mass - current.mass
        notes.append(f"{'+' if delta >= 0 else ''}{delta:.1f} kg/m against {current.name}")
    return entry


def steel_design_proposal(
    object_types: Iterable[dict[str, Any]],
    materials: dict[str, SteelMaterial],
    demands: dict[str, list[SteelMemberDemand]],
    families: dict[str, str] | None = None,
    checker: MemberChecker | None = None,
    limit: float = 1.0,
) -> dict[str, Any]:
    """The steel design proposal: ``{"mode": "steel", "types": [entry, ...], "skipped",
    "notes"}`` for the beam, column and brace types of 04 Objects (JSON dicts) whose material
    is in ``materials`` (the steel ones), with ``demands`` their members' forces by type id
    and ``families`` an optional family per type id (default: the type's own)."""
    families = families or {}
    entries, skipped = [], []
    for t in object_types:
        if t.get("kind") not in ("beam", "column", "brace") or "profile" not in t:
            continue
        material = materials.get(t.get("material", ""))
        if material is None:
            skipped.append({"type": t["id"], "reason": "not a structural steel material"})
            continue
        if t["profile"].get("shape") not in tbl.SHAPE_FAMILIES:
            skipped.append({"type": t["id"], "reason": f"no table for {t['profile']['shape']}"})
            continue
        entries.append(
            propose_type(
                t["id"],
                t["kind"],
                t.get("name", t["id"]),
                t["profile"],
                demands.get(t["id"], []),
                material,
                families.get(t["id"]),
                checker,
                limit,
            )
        )
    return {
        "mode": "steel",
        "types": entries,
        "skipped": skipped,
        "notes": [
            (
                "Lightest section of the family passing every member's checks; sections from "
                "SAEngine's standard table (library.steel_sections)."
            )
        ],
    }


def apply_steel_proposal(objects_text: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """04 Objects with the proposed profiles: ``{"objectsText", "changes"}``; entries with
    ``"apply": false`` or no proposal are left out. Pure. Raises ``ValueError`` when the text
    is not valid JSON or a type is missing."""
    from saengine.design.proposal import _change, _dump

    objects = json.loads(objects_text)
    by_id = {x["id"]: x for x in objects.get("objects", [])}
    changes = []
    for entry in proposal.get("types", []):
        if entry.get("apply") is False or not entry.get("proposed"):
            continue
        if entry.get("status") == "unchanged":
            continue
        target = by_id.get(entry["type"])
        if target is None:
            raise ValueError(f"object type '{entry['type']}' is not in 04 Objects")
        before = (entry.get("current") or {}).get("text")
        target["profile"] = entry["proposed"]["profile"]
        changes.append(
            _change(
                "04 Objects/objects.json",
                entry["type"],
                "section",
                before,
                entry["proposed"]["text"],
            )
        )
    return {"objectsText": _dump(objects, objects_text), "changes": changes}
