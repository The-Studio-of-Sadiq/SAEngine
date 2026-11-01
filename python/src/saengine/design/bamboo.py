"""Round bamboo beams, columns and braces: permissible stress design with the code pack's
``bamboo`` table (with the bnbc2020 pack: BNBC 2020 Part 6 Chapter 4).

The pattern is the timber one (:mod:`saengine.design.timber`): the member's forces are the
code pack's allowable stress (service level) combinations of the analysis's load cases
(:func:`saengine.design.timber.asd_pieces`). Per member, at every station of every combination:

- permissible stresses of the material: the species' safe working stresses of the pack's
  table, or the tested ultimate values over the factors of safety, or the stresses per unit
  density (the shear stress only by density, where the table gives it); times the load duration
  factor of the combination (continuous, medium term with live loads, short term with wind or
  earthquake);
- the culm as a tube on its mean diameter and wall (a circle or hollow circle profile), a
  bundle column of n culms as n culms side by side (no composite action);
- bending f = M/Z, shear of the tube, axial compression P/A;
- columns: slenderness l/r at most the pack's limit, Euler buckling with the reduced I and the
  permissible E, and the bending from the initial curvature (the grading's largest bow) and
  the induced deflection (amplified by 1/(1 - P/Pcr)) combined linearly with the compression;
- truss members: compression and joint forces increased by the pack's factor;
- joints: their capacity comes from full-scale tests; a tested capacity is checked against the
  end force.

The member length is the unsupported length: bamboo joints act as hinges unless tests show
otherwise. The code gives no permissible tension stress: tension members are governed by their
joints (a note says so).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context
from saengine.design.ductile_members import _row
from saengine.design.timber.members import _flag, allowable_combinations, asd_pieces, code_name

__all__ = [
    "Bamboo",
    "BambooDesignError",
    "Culm",
    "allowable_combinations",
    "asd_pieces",
    "check_member",
    "design_bamboo_member",
    "duration_factor",
    "is_bamboo",
    "method",
]


class BambooDesignError(ValueError):
    """A bamboo member that cannot be checked."""


def _table() -> Any:
    return code_context.pack_table("bamboo")


def covered() -> bool:
    """Whether the code pack in force covers bamboo (its chain has the table)."""
    return code_context.current().has("bamboo")


def clause(key: str) -> str:
    text = (getattr(_table(), "clauses", None) or {}).get(key, "")
    return f"{code_name()} {text}".strip()


def method() -> list[str]:
    """The design report's method paragraph of bamboo members, with the pack's clauses."""
    text = (
        f"Bamboo members: permissible stress design to {clause('chapter')}, under the "
        "allowable stress combinations formed from the analysis's load cases. Safe working "
        f"stresses of the species ({clause('stresses')}), or tested values over the factors "
        f"of safety ({clause('tested')}), or stresses by density ({clause('density')}), times "
        f"the load duration factor ({clause('duration')}). Culms as tubes on their mean "
        f"diameter and wall ({clause('section')}); bending ({clause('bending')}), shear "
        f"({clause('shear')}), slenderness ({clause('slenderness')}), Euler buckling with the "
        f"reduced I ({clause('buckling')}) and the bending from the initial curvature "
        f"({clause('combined')}); truss forces increased ({clause('truss')}); joints by "
        f"tested capacity ({clause('joint')}). The member length is the unsupported length "
        "(hinged joints)."
    )
    return [text]


def is_bamboo(material: Any) -> bool:
    category = getattr(getattr(material, "category", None), "value", None)
    return category == "bamboo" and getattr(material, "bamboo", None) is not None


def find_species(name: str) -> tuple[str, Any]:
    """``(id, species)`` of the pack's table by id or botanical name (case insensitive; the
    name before any synonym in brackets, "B." for "Bambusa" accepted)."""
    species = _table().species
    key = _short(name)
    for k in species:
        if k.lower() == name.strip().lower():
            return k, species[k]

    def names(s: Any) -> set[str]:
        full = s.name.lower()
        out = {_short(full.split("(")[0])}
        if "syn." in full:
            out.add(_short(full.split("syn.")[1].strip(" )")))
        return out

    found = [(k, s) for k, s in species.items() if key in names(s)]
    if len(found) == 1:
        return found[0]
    raise BambooDesignError(f"species '{name}' is not in the code pack's bamboo table")


def _short(name: str) -> str:
    """ "bambusa tulda" and "b. tulda" alike: the genus' initial and the epithet."""
    words = name.strip().lower().replace(".", " ").split()
    return " ".join([words[0][:1], *words[1:]]) if words else ""


# ─────────────────────────────────────── stresses ───────────────────────────────────────


@dataclass(frozen=True)
class Bamboo:
    """Permissible stresses [MPa] before the duration factor: ``fb`` bending, ``fc``
    compression along the fibres, ``fv`` shear (None: not given), ``e`` the permissible E."""

    fb: float
    fc: float
    e: float
    fv: float | None
    basis: str
    group: str | None = None
    notes: tuple[str, ...] = ()

    @classmethod
    def of_material(cls, material: Any) -> Bamboo:
        props = getattr(material, "bamboo", None)
        if props is None:
            raise BambooDesignError(f"'{getattr(material, 'id', '?')}' is not a bamboo material")
        table = _table()
        density = getattr(getattr(material, "mechanical", None), "density", None)
        condition = getattr(props, "condition", "green")
        by_density = table.densityFactors[condition]
        fv = (
            float(by_density.shear) * float(density)
            if density and by_density.shear is not None
            else None
        )
        notes: list[str] = []
        tested = getattr(props, "tested", None)
        if tested is not None:
            sf = table.safetyFactors
            return cls(
                float(tested.rupture) / float(sf.bending),
                float(tested.compression) / float(sf.compression),
                float(tested.E) / float(sf.E),
                fv,
                f"tested values over the factors of safety ({clause('tested')})",
                _group_of(float(tested.rupture), float(tested.E)) if condition == "green" else None,
            )
        if getattr(props, "species", None):
            _, sp = find_species(props.species)
            if condition != "green":
                notes.append("the species' stresses are those of green bamboo (conservative)")
            return cls(
                float(sp.bending),
                float(sp.compression),
                float(sp.E),
                fv,
                f"{sp.name}, group {sp.group} ({clause('stresses')})",
                sp.group,
                tuple(notes),
            )
        e_mean = getattr(getattr(material, "mechanical", None), "E", None)
        if not density or not e_mean:
            raise BambooDesignError(
                "give the bamboo's species, tested values, or its density and E"
            )
        return cls(
            float(by_density.bending) * float(density),
            float(by_density.compression) * float(density),
            float(e_mean) / float(table.safetyFactors.E),
            fv,
            f"density {float(density):g} kg/m³, {condition} ({clause('density')}); E the "
            "material's over the factor of safety",
        )


def _group_of(rupture: float, e: float) -> str | None:
    """The strength group of green bamboo with these tested values (both limits met)."""
    for group, limit in sorted(_table().groupLimits.items(), key=lambda kv: -float(kv[1].rupture)):
        if rupture > float(limit.rupture) and e > float(limit.E):
            return group
    return None


def duration_factor(cases: dict[str, float]) -> float:
    """The factor of a combination ``{case: factor}``: short term with wind or earthquake,
    medium term with live loads, else continuous."""
    d = _table().duration
    present = {c for c, v in cases.items() if v}
    if any(c[:1] in ("W", "E") for c in present):
        return float(d.short)
    if present & {"L", "Lr"} or any(c.startswith("LP") for c in present):
        return float(d.medium)
    return float(d.continuous)


# ─────────────────────────────────────── the culm ───────────────────────────────────────


@dataclass(frozen=True)
class Culm:
    """A culm: outer diameter ``D`` and wall ``t`` [mm] (t = D/2: solid)."""

    D: float
    t: float

    @classmethod
    def of(cls, profile: Any) -> Culm:
        shape = getattr(profile, "shape", None)
        if shape == "circleHollow":
            d = 2 * float(profile.radius)
            return cls(d, min(float(profile.wallThickness), d / 2))
        if shape == "circle":
            return cls(2 * float(profile.radius), float(profile.radius))
        raise BambooDesignError(
            f"bamboo members are designed as hollow or solid circles (culms), not '{shape}'"
        )

    @property
    def d(self) -> float:
        return self.D - 2 * self.t

    @property
    def area(self) -> float:
        return math.pi / 4 * (self.D**2 - self.d**2)

    @property
    def inertia(self) -> float:
        return math.pi / 64 * (self.D**4 - self.d**4)

    @property
    def modulus(self) -> float:
        return self.inertia / (self.D / 2)

    @property
    def radius(self) -> float:
        return math.sqrt(self.inertia / self.area)

    def shear_stress(self, v: float) -> float:
        """VQ/(I·2t) at the neutral axis [MPa] (4V/3A for a solid culm)."""
        q = (self.D**3 - self.d**3) / 12
        return v * q / (self.inertia * (self.D - self.d))


# ─────────────────────────────────────── the member ───────────────────────────────────────


def check_member(
    culm: Culm,
    bamboo: Bamboo,
    stations: Sequence[Any],
    length: float,
    kd: dict[str, float] | None = None,
    kind: str = "beam",
    options: Any = None,
) -> list[dict[str, Any]]:
    """The checks of a member: ``stations`` per combination (P compression positive [N], Mx, My
    [N·mm], Vy, Vx [N]); ``length`` the unsupported length [mm]; ``kd`` per combination its load
    duration factor; ``options`` the type's :class:`BambooMember` data."""
    table = _table()
    kd = kd or {}
    n = int(getattr(options, "culms", 1) or 1) if options is not None else 1
    truss = bool(getattr(options, "truss", False)) if options is not None else False
    increase = float(table.trussForceIncrease) if truss else 1.0
    area, inertia, z = culm.area * n, culm.inertia * n, culm.modulus * n
    col = table.column
    p_cr = math.pi**2 * bamboo.e * float(col.inertiaFactor) * inertia / length**2
    e0 = float(col.initialCurvature) * length
    tag_n = f"; {n} culms" if n > 1 else ""
    rows: dict[str, dict[str, Any]] = {}

    def offer(key: str, row: dict[str, Any]) -> None:
        if key not in rows or row["utilisation"] > rows[key]["utilisation"]:
            rows[key] = row

    compressed = False
    for st in stations:
        name = st.combination
        k = float(kd.get(name, 1.0))
        tag = f"; duration factor {k:.2f}" if abs(k - 1) > 1e-9 else ""
        for j in range(len(st.s)):
            p = float(st.P[j])
            m = math.hypot(float(st.Mx[j]), float(st.My[j]))
            v = math.hypot(float(st.Vy[j]), float(st.Vx[j]))
            offer(
                "fb",
                _row(
                    f"Bending f = M/Z ({clause('bending')})",
                    m / z,
                    k * bamboo.fb,
                    "MPa",
                    name,
                    f"M = {m / 1e6:.2f} kN·m{tag}{tag_n}",
                ),
            )
            if bamboo.fv is not None and v > 0:
                offer(
                    "fv",
                    _row(
                        f"Shear of the culm ({clause('shear')})",
                        culm.shear_stress(v / n),
                        k * bamboo.fv,
                        "MPa",
                        name,
                        f"V = {v / 1e3:.2f} kN{tag}",
                    ),
                )
            if p <= 0:
                continue
            compressed = True
            pc = p * increase
            fc = pc / area
            offer(
                "fc",
                _row(
                    f"Compression along the fibres ({clause('stresses')})",
                    fc,
                    k * bamboo.fc,
                    "MPa",
                    name,
                    f"P = {pc / 1e3:.2f} kN{' (truss: increased)' if truss else ''}{tag}",
                ),
            )
            offer(
                "pcr",
                _row(
                    f"Euler buckling, {float(col.inertiaFactor):g} I ({clause('buckling')})",
                    pc / 1e3,
                    p_cr / 1e3,
                    "kN",
                    name,
                    f"l = {length:.0f} mm, E = {bamboo.e:.0f} MPa",
                ),
            )
            amp = 1 / (1 - pc / p_cr) if pc < p_cr else math.inf
            fbt = (m + pc * e0) * amp / z
            ratio = fc / (k * bamboo.fc) + fbt / (k * bamboo.fb)
            offer(
                "pm",
                _row(
                    f"Compression and bending with the initial curvature ({clause('combined')})",
                    ratio,
                    1.0,
                    "",
                    name,
                    f"e0 = {e0:.0f} mm, amplified {amp:.2f}" if math.isfinite(amp) else "buckles",
                ),
            )
    out = list(rows.values())
    if compressed or kind != "beam":
        out.append(
            _row(
                f"Slenderness l/r ({clause('slenderness')})",
                length / culm.radius,
                float(col.maxSlenderness),
                "",
                None,
                f"r = {culm.radius:.1f} mm of one culm",
            )
        )
    wall = float(table.minWallThickness)
    if culm.t < culm.D / 2 and culm.t < wall:
        out.append(
            _flag(
                _row(
                    f"Wall thickness of load-bearing culms, preferably ({clause('wall')})",
                    culm.t,
                    wall,
                    "mm",
                    None,
                    "advisory",
                    utilisation=wall / culm.t,
                )
            )
        )
    for row in out:
        row.setdefault("flag", False)
    return out


def joint_rows(
    joint: Any, stations: Sequence[Any], truss: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The joint at both ends: its tested capacity against the largest end force."""
    table = _table()
    kind = table.joints.kinds.get(joint.kind)
    fastening = table.joints.fastenings.get(joint.fastening)
    increase = float(table.trussForceIncrease) if truss else 1.0
    force = 0.0
    where = None
    for st in stations:
        for j in (0, len(st.s) - 1):
            f = abs(float(st.P[j])) * increase
            if f > force:
                force, where = f, st.combination
    out = {
        "kind": kind.label if kind else joint.kind,
        "fastening": fastening.label if fastening else joint.fastening,
        "kindClause": kind.source if kind else None,
        "fasteningClause": fastening.source if fastening else None,
        "force": round(force / 1e3, 2),
    }
    if fastening is not None:
        for key in ("wireDiameter", "pinDiameter", "plateThickness", "plywoodThickness"):
            value = getattr(fastening, key, None)
            if value is not None:
                out[key] = float(value)
    if joint.testedCapacity is None:
        out["note"] = f"capacity from full-scale tests required ({clause('joint')})"
        return [], out
    row = _row(
        f"Joint, tested capacity ({clause('joint')})",
        force / 1e3,
        float(joint.testedCapacity),
        "kN",
        where,
        f"{out['kind']}, {out['fastening']}" + ("; truss force increased" if truss else ""),
    )
    row["flag"] = False
    return [row], out


def design_bamboo_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    factors: Sequence[dict[str, float]] | None = None,
    turned: bool = False,
) -> dict[str, Any]:
    """The design report entry of one bamboo beam, column or brace (as the timber one:
    ``{id, kind, type, members, checks, utilisation, ok, material, bamboo}``). ``pieces``: its
    analysis elements with the allowable stress combinations' forces; ``factors``: each
    combination's ``{case: factor}``. Raises :class:`BambooDesignError`."""
    from saengine.design.steel.lengths import positions
    from saengine.design.steel.members import member_stations

    if not pieces:
        raise BambooDesignError("not in the analysis results")
    culm = Culm.of(object_type.profile)
    bamboo = Bamboo.of_material(material)
    options = getattr(object_type, "bamboo", None)
    s, _ = positions(pieces, 2)
    length = float(s[-1] - s[0]) * 1000.0
    stations = member_stations(pieces, combinations, turned)
    kd = (
        {n: duration_factor(f) for n, f in zip(combinations, factors, strict=True)}
        if factors
        else {}
    )
    checks = check_member(culm, bamboo, stations, length, kd, kind, options)
    notes = list(bamboo.notes)
    if bamboo.fv is None:
        notes.append(
            f"shear not checked: no permissible shear for this material ({clause('shear')})"
        )
    if any(float(x) < 0 for st in stations for x in st.P):
        notes.append("tension: the code gives no permissible tension stress; the joints govern")
    joint = getattr(options, "joint", None) if options is not None else None
    joint_out = None
    if joint is not None:
        rows, joint_out = joint_rows(joint, stations, bool(getattr(options, "truss", False)))
        checks += rows
        if "note" in joint_out:
            notes.append(f"joint: {joint_out['note']}")
    strength = [c for c in checks if not c["flag"]]
    n = int(getattr(options, "culms", 1) or 1) if options is not None else 1
    entry: dict[str, Any] = {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        "bamboo": {
            "label": f"Ø{culm.D:g} x {culm.t:g} bamboo" + (f", {n} culms" if n > 1 else ""),
            "basis": bamboo.basis,
            "group": bamboo.group,
            "stresses": {"fb": bamboo.fb, "fc": bamboo.fc, "fv": bamboo.fv, "E": bamboo.e},
            "length": round(length, 0),
            "code": code_name(),
            "clause": clause("chapter"),
            "notes": notes,
        },
    }
    if joint_out is not None:
        entry["bamboo"]["joint"] = joint_out
    return entry


def design_members(
    todo: Sequence[tuple[str, Any, Any, Sequence[Any], bool]],
    case_forces: dict[str, Any],
    names: Sequence[str],
    factors: Sequence[dict[str, float]],
    checked: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> bool:
    """The bamboo members of ``todo`` (``(id, object type, material, pieces, turned)``) under
    the allowable stress combinations ``names``/``factors`` of the per-case forces
    ``case_forces``: entries to ``checked``, the ones that cannot be checked to ``skipped``.
    True when one was checked."""
    seen = False
    for member_id, object_type, material, own, turned in todo:
        try:
            entry = design_bamboo_member(
                member_id,
                object_type.kind,
                object_type,
                material,
                asd_pieces(own, case_forces, factors),
                names,
                factors,
                turned,
            )
        except BambooDesignError as error:
            skipped.append(
                {
                    "id": member_id,
                    "kind": object_type.kind,
                    "type": object_type.id,
                    "reason": f"bamboo not checked: {error}",
                }
            )
            continue
        checked.append(entry)
        seen = True
    return seen
