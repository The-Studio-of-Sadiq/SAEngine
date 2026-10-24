"""Import of a STAAD.Pro input file (``.std``) into a SAEngine project.

The reader follows the STAAD command language: free-format commands, one per line or several
separated by ``;``, a trailing ``-`` continuing a line, ``*`` comment lines, and ``UNIT`` lines
that may change the length and force units anywhere. It reads:

- ``STAAD SPACE|PLANE``, ``SET Z UP`` (otherwise Y is up and the model is turned to Z up);
- ``JOINT COORDINATES`` with generation (``i1 x1 y1 z1 i2 x2 y2 z2 [inc]``) and ``REPEAT`` /
  ``REPEAT ALL``;
- ``MEMBER INCIDENCES`` (with ``m i j [m2 [minc [jinc]]]`` and ``REPEAT``),
  ``ELEMENT INCIDENCES [SHELL]`` (with ``TO`` generation);
- ``MEMBER PROPERTY``: ``PRISMATIC YD ZD`` (rectangle), ``YD`` alone (circle), ``AX IZ``
  (an equivalent rectangle, approximated), ``TABLE ST name`` (by name, see
  :func:`~saengine.importers.neutral.named_profile`), ``PIPE OD ID``, ``TUBE TH WT DT``;
- ``ELEMENT PROPERTY ... THICKNESS``;
- ``DEFINE MATERIAL`` (``ISOTROPIC``, ``E``, ``POISSON``, ``DENSITY``, ``TYPE``, ``STRENGTH``)
  and ``CONSTANTS`` (``MATERIAL``, ``E``, ``POISSON``, ``DENSITY`` by member list, the built-in
  STEEL and CONCRETE);
- ``SUPPORTS`` (``FIXED``, ``PINNED``, ``FIXED BUT ...`` approximated);
- ``LOAD n`` (``LOADTYPE``, ``TITLE``) with ``SELFWEIGHT``, ``JOINT LOAD``, ``MEMBER LOAD``
  (``UNI``, ``CON``, ``TRAP`` as its mean), ``ELEMENT LOAD ... PR``, ``FLOOR LOAD``;
  ``LOAD COMBINATION n``.

Everything else (releases, offsets, groups, generated wind and seismic loads, design
parameters, analysis commands) is skipped and counted in the import report.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import numpy as np

from saengine.importers.common import ImportedProject, ImportReport
from saengine.importers.neutral import (
    Area,
    FileUnits,
    Frame,
    Load,
    LoadCase,
    MaterialDef,
    SectionDef,
    TextModel,
    build,
    circle_profile,
    equivalent_rectangle,
    named_profile,
    rectangle,
)
from saengine.library import objects as o

FORMAT = "STAAD.Pro"

_LENGTHS = {
    "METER": 1000.0,
    "METERS": 1000.0,
    "MET": 1000.0,
    "M": 1000.0,
    "MMS": 1.0,
    "MM": 1.0,
    "MMS.": 1.0,
    "CM": 10.0,
    "CMS": 10.0,
    "FEET": 304.8,
    "FT": 304.8,
    "FOOT": 304.8,
    "INCHES": 25.4,
    "INCH": 25.4,
    "IN": 25.4,
    "DME": 100.0,
    "KM": 1e6,
}
_FORCES = {
    "KN": 1000.0,
    "KNS": 1000.0,
    "KILONEWTON": 1000.0,
    "NEWTON": 1.0,
    "NEWTONS": 1.0,
    "NEW": 1.0,
    "N": 1.0,
    "MN": 1e6,
    "KIP": 4448.2216152605,
    "KIPS": 4448.2216152605,
    "POUND": 4.4482216152605,
    "POUNDS": 4.4482216152605,
    "LB": 4.4482216152605,
    "LBS": 4.4482216152605,
    "KG": 9.80665,
    "KGS": 9.80665,
    "MTON": 9806.65,
    "MTONS": 9806.65,
    "DNS": 10.0,
}

#: STAAD's built-in materials in kN and m (E, POISSON, DENSITY [kN/m³]).
_BUILT_IN = {
    "STEEL": (2.05e8, 0.3, 76.8195, "steel"),
    "CONCRETE": (2.17185e7, 0.17, 23.5616, "concrete"),
    "ALUMINUM": (6.89476e7, 0.33, 26.6018, "steel"),
}

_COMMANDS = {
    "STAAD",
    "SET",
    "UNIT",
    "JOINT",
    "MEMBER",
    "MEMB",
    "ELEMENT",
    "ELEM",
    "DEFINE",
    "END",
    "CONSTANTS",
    "CONSTANT",
    "SUPPORTS",
    "SUPPORT",
    "LOAD",
    "LOADING",
    "PERFORM",
    "PRINT",
    "FINISH",
    "PARAMETER",
    "PARAMETERS",
    "START",
    "CHECK",
    "SELECT",
    "INPUT",
    "PAGE",
    "SPRING",
    "INACTIVE",
    "DELETE",
    "CUT",
    "SECTION",
    "DESIGN",
    "TAKE",
    "STEEL",
    "CONCRETE",
    "PDELTA",
    "CHANGE",
    "STARTING",
}


def _num(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


class _Reader:
    def __init__(self, text: str, file: str) -> None:
        self.model = TextModel(format=FORMAT, file=file, report=ImportReport(FORMAT, file))
        self.report = self.model.report
        self.length = 1000.0
        self.force = 1000.0
        self.unit_seen = False
        self.z_up = False
        self.block = ""
        self.joints: dict[int, np.ndarray] = {}  # file axes, mm
        self.joint_lines: list[list[int]] = []
        self.repeat_all_from = 0
        self.members: dict[int, tuple[int, int]] = {}
        self.member_lines: list[list[int]] = []
        self.member_repeat_all_from = 0
        self.plates: dict[int, list[int]] = {}
        self.member_section: dict[int, str] = {}
        self.plate_thickness: dict[int, float] = {}
        self.definitions: dict[str, dict[str, float | str]] = {}
        self.defining: str | None = None
        self.member_props: dict[int, dict[str, float | str]] = {}
        self.case: LoadCase | None = None
        self.combination: tuple[str, dict[str, float]] | None = None
        self.text = text

    # ── units ──

    @property
    def units(self) -> FileUnits:
        return FileUnits(self.length, self.force)

    def unit(self, tokens: list[str]) -> None:
        for t in tokens[1:]:
            if t in _LENGTHS:
                self.length = _LENGTHS[t]
            elif t in _FORCES:
                self.force = _FORCES[t]
            else:
                self.report.skip("unknown units in UNIT lines", t)
        self.unit_seen = True
        label_l = next((t for t in tokens[1:] if t in _LENGTHS), None)
        label_f = next((t for t in tokens[1:] if t in _FORCES), None)
        if not self.model.units:
            self.model.units = " ".join(x for x in (label_l, label_f) if x)

    # ── axes ──

    def axes(self, x: float, y: float, z: float) -> np.ndarray:
        """A vector of the file's axes in SAEngine's (Z up)."""
        return np.array([x, y, z]) if self.z_up else np.array([x, -z, y])

    def vertical(self) -> str:
        return "Z" if self.z_up else "Y"

    # ── lists ──

    def id_list(self, tokens: list[str], start: int = 0) -> tuple[list[int], int]:
        """The ids of a STAAD list (``1 2 5 TO 9 BY 2``, ``ALL``) from ``tokens[start]``, and
        the index after it."""
        ids: list[int] = []
        k = start
        while k < len(tokens):
            t = tokens[k]
            if t in ("MEMB", "MEMBER", "JOINT", "JOI", "PLA", "PLATE", "ELEM", "ELEMENT", "LIST"):
                k += 1
                continue
            if t == "ALL":
                ids += sorted({*self.members, *self.plates}) or sorted(self.joints)
                k += 1
                continue
            if t == "TO" and ids and k + 1 < len(tokens) and _num(tokens[k + 1]) is not None:
                end = int(float(tokens[k + 1]))
                step = 1
                k += 2
                if k + 1 < len(tokens) and tokens[k] == "BY" and _num(tokens[k + 1]) is not None:
                    step = int(float(tokens[k + 1]))
                    k += 2
                ids += list(range(ids[-1] + step, end + 1, step))
                continue
            if t.startswith("_"):
                self.report.skip("group names in lists", t)
                k += 1
                continue
            value = _num(t)
            if value is None or value != int(value):
                break
            ids.append(int(value))
            k += 1
        return ids, k

    # ── statements ──

    def statements(self) -> list[list[str]]:
        lines: list[str] = []
        pending = ""
        for raw in self.text.splitlines():
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            if line.endswith("-"):  # continued on the next line
                pending += line[:-1] + " "
                continue
            lines.append(pending + line)
            pending = ""
        if pending:
            lines.append(pending)
        result = []
        for line in lines:
            for part in line.split(";"):
                tokens = part.replace(",", " ").upper().split()
                if tokens:
                    result.append(tokens)
        return result

    def read(self) -> TextModel:
        for tokens in self.statements():
            self.statement(tokens)
        self.finish_case()
        self.finish()
        # Horizontal axes of the file as case names use them (Y up: file Z is SAEngine -Y).
        self.model.lateral_axes = (
            {"X": ("X", 1.0), "Y": ("Y", 1.0)} if self.z_up else {"X": ("X", 1.0), "Z": ("Y", -1.0)}
        )
        if not self.unit_seen:
            self.report.approximate("files without a UNIT line: kN and m assumed")
        return self.model

    def statement(self, tokens: list[str]) -> None:
        head = tokens[0]
        if head == "UNIT":
            self.unit(tokens)
            return
        first_alpha = _num(head) is None
        if first_alpha and self.block_keyword(tokens):
            return
        if first_alpha and (head in _COMMANDS or head.startswith("LOAD")):
            self.command(tokens)
            return
        if first_alpha and head not in ("REPEAT", "TO", "ALL") and not head.startswith("_"):
            if self.block not in ("skip",):
                self.report.skip("commands not read", " ".join(tokens[:3]))
            self.block = "skip"
            return
        self.data(tokens)

    def block_keyword(self, tokens: list[str]) -> bool:
        """Lines starting with a word that belong to the current block."""
        head = tokens[0]
        if self.block == "material" and head in (
            "ISOTROPIC",
            "E",
            "POISSON",
            "DENSITY",
            "ALPHA",
            "DAMP",
            "TYPE",
            "STRENGTH",
            "G",
            "CDAMP",
        ):
            self.material_line(tokens)
            return True
        if self.block == "constants" and head in (
            "MATERIAL",
            "E",
            "POISSON",
            "DENSITY",
            "BETA",
            "G",
            "ALPHA",
            "DAMP",
            "CDAMP",
        ):
            self.constants_line(tokens)
            return True
        if self.block.startswith("load") and self.case is not None:
            if head in ("SELFWEIGHT", "SELF"):
                self.selfweight(tokens)
                return True
            if (
                len(tokens) > 1
                and tokens[1].startswith("LOAD")
                and head
                in (
                    "JOINT",
                    "MEMBER",
                    "ELEMENT",
                    "FLOOR",
                    "ONEWAY",
                    "AREA",
                    "REPEAT",
                    "WIND",
                    "TEMPERATURE",
                    "TEMP",
                )
            ):
                self.block = {
                    "JOINT": "load-joint",
                    "MEMBER": "load-member",
                    "ELEMENT": "load-element",
                    "FLOOR": "load-floor",
                }.get(head, "load-other")
                if self.block == "load-other":
                    self.report.skip(f"{head.lower()} loads (not read)", f"{self.case.name}")
                return True
            if self.block == "load-floor" and head in ("YRANGE", "XRANGE", "ZRANGE"):
                self.floor_load(tokens)
                return True
            if head in ("SEISMIC", "WIND", "SPECTRUM", "TIME", "GROUND", "PRESSURE"):
                self.report.skip("generated or dynamic loads (not read)", self.case.name)
                self.block = "load-other"
                return True
        if self.block == "supports" and head in ("FIXED", "PINNED"):
            return False
        return False

    def command(self, tokens: list[str]) -> None:
        head = tokens[0]
        second = tokens[1] if len(tokens) > 1 else ""
        if head == "STAAD":
            if second in ("PLANE", "TRUSS"):
                self.report.warn(f"STAAD {second.lower()} model: read as a 3D model")
            self.block = ""
            return
        if head == "SET":
            if second == "Z" and "UP" in tokens:
                self.z_up = True
            self.block = ""
            return
        if head in ("LOAD", "LOADING"):
            self.finish_case()
            if second.startswith("COMB"):
                rest = tokens[2:]
                number = rest[0] if rest else str(len(self.model.combinations) + 1)
                if number in ("SRSS", "ABS"):
                    self.report.skip("SRSS and ABS combinations", " ".join(tokens))
                    self.block = "skip"
                    return
                title = " ".join(rest[1:]) or f"Combination {number}"
                self.combination = (f"{number} {title}".strip(), {})
                self.block = "comb"
                return
            if second == "LIST":
                self.block = "skip"
                return
            if _num(second) is None:
                self.block = "skip"
                return
            self.new_case(second, tokens[2:])
            return
        self.finish_case()
        if head == "JOINT" and second.startswith("COORD"):
            if "CYLINDRICAL" in tokens:
                self.report.skip("cylindrical joint coordinates")
                self.block = "skip"
                return
            self.block = "joints"
            self.data(tokens[2:]) if len(tokens) > 2 else None
            return
        if head in ("MEMBER", "MEMB"):
            if second.startswith("INCI"):
                self.block = "members"
                if len(tokens) > 2:
                    self.data(tokens[2:])
                return
            if second.startswith("PROP"):
                self.block = "mprop"
                return
            if second.startswith("RELEASE"):
                self.block = "release"
                return
            if second.startswith("TRUSS"):
                self.block = "truss"
                return
            self.report.skip("member commands not read", " ".join(tokens[:2]))
            self.block = "skip"
            return
        if head in ("ELEMENT", "ELEM"):
            if second.startswith("INCI"):
                if "SOLID" in tokens:
                    self.report.skip("solid elements")
                    self.block = "skip"
                    return
                self.block = "plates"
                return
            if second.startswith("PROP"):
                self.block = "eprop"
                return
            self.block = "skip"
            return
        if head == "DEFINE":
            if second == "MATERIAL":
                self.block = "material"
                return
            self.report.skip("DEFINE commands not read", " ".join(tokens[:3]))
            self.block = "skip"
            return
        if head == "END":
            self.block = ""
            self.defining = None
            return
        if head.startswith("CONSTANT"):
            self.block = "constants"
            return
        if head.startswith("SUPPORT"):
            self.block = "supports"
            return
        if head in ("PERFORM", "PRINT", "FINISH", "PARAMETER", "PARAMETERS", "CHECK", "SELECT"):
            self.block = "skip"
            return
        if head == "START":
            if "GROUP" in tokens:
                self.report.skip("group definitions (lists by group name are skipped)")
            self.block = "skip"
            return
        self.block = "skip"

    # ── data lines per block ──

    def data(self, tokens: list[str]) -> None:
        block = self.block
        if block == "joints":
            self.joint_data(tokens)
        elif block == "members":
            self.member_data(tokens)
        elif block == "plates":
            self.plate_data(tokens)
        elif block == "mprop":
            self.member_property(tokens)
        elif block == "eprop":
            self.element_property(tokens)
        elif block == "supports":
            self.support_data(tokens)
        elif block == "release":
            ids, _ = self.id_list(tokens)
            for m in ids:
                self.report.skip("member releases (members analysed as rigidly connected)", str(m))
        elif block == "truss":
            ids, _ = self.id_list(tokens)
            for m in ids:
                self.report.approximate("truss members analysed as frame members", str(m))
        elif block == "constants":
            self.constants_line(tokens)
        elif block == "load-joint":
            self.joint_load(tokens)
        elif block == "load-member":
            self.member_load(tokens)
        elif block == "load-element":
            self.element_load(tokens)
        elif block == "comb":
            self.combination_data(tokens)
        elif block in ("load", "load-floor", "load-other", "skip", "", "material"):
            if block == "load-other" and tokens and tokens[0] == "REPEAT":
                pass
        else:
            pass

    def joint_data(self, tokens: list[str]) -> None:
        if tokens[0] == "REPEAT":
            self.repeat(tokens, joints=True)
            return
        values = [_num(t) for t in tokens]
        if any(v is None for v in values) or len(values) < 3:
            self.report.skip("joint lines not read", " ".join(tokens))
            return
        nums: list[float] = [v for v in values if v is not None]
        line: list[int] = []
        if len(nums) == 3:  # plane model: n x y
            nums = [*nums, 0.0]
        n1 = int(nums[0])
        p1 = np.array(nums[1:4]) * self.length
        self.joints[n1] = p1
        line.append(n1)
        if len(nums) >= 8:
            n2 = int(nums[4])
            p2 = np.array(nums[5:8]) * self.length
            inc = int(nums[8]) if len(nums) > 8 else 1
            steps = (n2 - n1) // inc
            for k in range(1, steps + 1):
                n = n1 + k * inc
                self.joints[n] = p1 + (p2 - p1) * k / steps
                line.append(n)
        self.joint_lines.append(line)

    def repeat(self, tokens: list[str], joints: bool) -> None:
        all_ = len(tokens) > 1 and tokens[1] == "ALL"
        values = [_num(t) for t in tokens[2 if all_ else 1 :]]
        if not values or any(v is None for v in values):
            self.report.skip("REPEAT lines not read", " ".join(tokens))
            return
        n = int(values[0] or 0)
        rest = [float(v) for v in values[1:] if v is not None]
        lines = self.joint_lines if joints else self.member_lines
        if all_:
            start = self.repeat_all_from if joints else self.member_repeat_all_from
            pattern = [i for line in lines[start:] for i in line]
        else:
            pattern = lines[-1] if lines else []
        if not pattern:
            return
        if joints:
            increment = max(self.joints)
            increments = [rest[3 * k : 3 * k + 3] for k in range(len(rest) // 3)] or [[0, 0, 0]]
            offset = np.zeros(3)
            new: list[int] = []
            for k in range(1, n + 1):
                step = increments[k - 1] if len(increments) >= n else increments[0]
                offset = offset + np.array(step + [0.0] * (3 - len(step))) * self.length
                for j in pattern:
                    self.joints[j + k * increment] = self.joints[j] + offset
                    new.append(j + k * increment)
            self.joint_lines.append(new)
            if all_:
                self.repeat_all_from = len(self.joint_lines)
        else:
            mi = int(rest[0]) if rest else max(self.members)
            ji = int(rest[1]) if len(rest) > 1 else max(self.joints)
            new = []
            for k in range(1, n + 1):
                for m in pattern:
                    i, j = self.members[m]
                    self.members[m + k * mi] = (i + k * ji, j + k * ji)
                    new.append(m + k * mi)
            self.member_lines.append(new)
            if all_:
                self.member_repeat_all_from = len(self.member_lines)

    def member_data(self, tokens: list[str]) -> None:
        if tokens[0] == "REPEAT":
            self.repeat(tokens, joints=False)
            return
        values = [_num(t) for t in tokens]
        if any(v is None for v in values) or len(values) < 3:
            self.report.skip("member lines not read", " ".join(tokens))
            return
        m, i, j = (int(v) for v in values[:3])  # type: ignore[arg-type]
        line = [m]
        self.members[m] = (i, j)
        if len(values) >= 4:
            m2 = int(values[3])  # type: ignore[arg-type]
            minc = int(values[4]) if len(values) > 4 else 1  # type: ignore[arg-type]
            jinc = int(values[5]) if len(values) > 5 else 1  # type: ignore[arg-type]
            k = 1
            while m + k * minc <= m2:
                self.members[m + k * minc] = (i + k * jinc, j + k * jinc)
                line.append(m + k * minc)
                k += 1
        self.member_lines.append(line)

    def plate_data(self, tokens: list[str]) -> None:
        if "TO" in tokens:
            k = tokens.index("TO")
            head, tail = tokens[:k], tokens[k + 1 :]
        else:
            head, tail = tokens, []
        values = [_num(t) for t in head]
        if any(v is None for v in values) or len(values) < 4:
            self.report.skip("element lines not read", " ".join(tokens))
            return
        e = int(values[0])  # type: ignore[arg-type]
        nodes = [int(v) for v in values[1:]]  # type: ignore[arg-type]
        self.plates[e] = nodes
        if tail:
            e2 = int(float(tail[0]))
            einc = int(float(tail[1])) if len(tail) > 1 else 1
            ninc = int(float(tail[2])) if len(tail) > 2 else 1
            k = 1
            while e + k * einc <= e2:
                self.plates[e + k * einc] = [n + k * ninc for n in nodes]
                k += 1

    def member_property(self, tokens: list[str]) -> None:
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if not ids or not spec:
            self.report.skip("member property lines not read", " ".join(tokens))
            return
        name = self.section(spec)
        if name is None:
            for m in ids:
                self.report.skip("member properties not read", f"{m}: {' '.join(spec[:3])}")
            return
        for m in ids:
            self.member_section[m] = name

    def section(self, spec: list[str]) -> str | None:
        kind = spec[0]
        params: dict[str, float] = {}
        for a, b in itertools.pairwise(spec[1:]):
            value = _num(b)
            if value is not None and _num(a) is None:
                params[a] = value
        sections = self.model.sections
        if kind.startswith("PRI"):
            mm = {k: v * self.length for k, v in params.items()}
            if "YD" in mm and "ZD" in mm:
                name = f"R{mm['ZD']:g}x{mm['YD']:g}"
                if any(k in mm for k in ("YB", "ZB")):
                    self.report.approximate(
                        "T and trapezoidal prismatic sections taken as rectangles", name
                    )
                sections.setdefault(name, SectionDef(name, rectangle(mm["ZD"], mm["YD"])))
                return name
            if "YD" in mm:
                name = f"D{mm['YD']:g}"
                sections.setdefault(name, SectionDef(name, circle_profile(mm["YD"] / 2)))
                return name
            if "AX" in params and "IZ" in params:
                area = params["AX"] * self.length**2
                inertia = params["IZ"] * self.length**4
                profile = equivalent_rectangle(area, inertia)
                if profile is None:
                    return None
                name = f"P{area:.0f}-{inertia:.3g}".replace("+", "")
                sections.setdefault(
                    name,
                    SectionDef(
                        name,
                        profile,
                        approximation="given by AX and IZ: a rectangle of the same area and "
                        "major inertia (minor inertia and torsion differ)",
                    ),
                )
                return name
            return None
        if kind in ("TABLE", "TA"):
            if len(spec) < 3:
                return None
            table, designation = spec[1], spec[2]
            if table != "ST":
                self.report.skip(
                    "compound table sections (double angles, tees, ...)", f"{table} {designation}"
                )
                return None
            if designation not in sections:
                profile, approximation = named_profile(designation)
                sections[designation] = SectionDef(
                    designation, profile, approximation=approximation
                )
            return designation
        if kind == "PIPE":
            if "OD" not in params or "ID" not in params:
                return None
            od, id_ = params["OD"] * self.length, params["ID"] * self.length
            name = f"PIPE{od:g}x{(od - id_) / 2:g}"
            sections.setdefault(
                name,
                SectionDef(
                    name, o.CircleHollowProfile(radius=od / 2, wallThickness=(od - id_) / 2)
                ),
            )
            return name
        if kind == "TUBE":
            if not all(k in params for k in ("TH", "WT", "DT")):
                return None
            th, wt, dt = (params[k] * self.length for k in ("TH", "WT", "DT"))
            name = f"TUBE{dt:g}x{wt:g}x{th:g}"
            sections.setdefault(
                name, SectionDef(name, o.RectangleHollowProfile(xDim=wt, yDim=dt, wallThickness=th))
            )
            return name
        return None

    def element_property(self, tokens: list[str]) -> None:
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if not ids or len(spec) < 2 or not spec[0].startswith("TH"):
            self.report.skip("element property lines not read", " ".join(tokens))
            return
        value = _num(spec[1])
        if value is None:
            return
        t = value * self.length
        for e in ids:
            self.plate_thickness[e] = t

    def material_line(self, tokens: list[str]) -> None:
        head = tokens[0]
        if head == "ISOTROPIC":
            self.defining = tokens[1] if len(tokens) > 1 else f"MAT{len(self.definitions) + 1}"
            self.definitions[self.defining] = {}
            return
        if self.defining is None:
            return
        d = self.definitions[self.defining]
        value = _num(tokens[1]) if len(tokens) > 1 else None
        if head == "E" and value is not None:
            d["E"] = self.units.mpa(value)
        elif head == "POISSON" and value is not None:
            d["nu"] = value
        elif head == "DENSITY" and value is not None:
            d["density"] = self.units.density(value)
        elif head == "TYPE" and len(tokens) > 1:
            d["kind"] = (
                "steel"
                if tokens[1].startswith("STEEL")
                else ("concrete" if tokens[1].startswith("CONC") else "")
            )
        elif head == "STRENGTH":
            for a, b in itertools.pairwise(tokens[1:]):
                v = _num(b)
                if v is None:
                    continue
                if a == "FY":
                    d["fy"] = self.units.mpa(v)
                elif a == "FU":
                    d["fu"] = self.units.mpa(v)
                elif a in ("FCU", "FC"):
                    d["fc"] = self.units.mpa(v)

    def constants_line(self, tokens: list[str]) -> None:
        head = tokens[0]
        if head in ("BETA", "G", "ALPHA", "DAMP", "CDAMP"):
            if head == "BETA":
                ids, _ = self.id_list(tokens, 2)
                for m in ids:
                    self.report.approximate(
                        "member beta angles ignored (profiles not rotated)", str(m)
                    )
            return
        if len(tokens) < 3:
            return
        target, value_token = head, tokens[1]
        ids, _ = self.id_list(tokens, 2)
        if not ids:
            ids = sorted({*self.members, *self.plates})
        if target == "MATERIAL":
            for m in ids:
                self.member_props.setdefault(m, {})["material"] = value_token
            return
        value = _num(value_token)
        if value is None:  # E STEEL ALL: the built-in or defined material's value
            for m in ids:
                self.member_props.setdefault(m, {}).setdefault("material", value_token)
            return
        key = {"E": "E", "POISSON": "nu", "DENSITY": "density"}[target]
        converted = (
            self.units.mpa(value)
            if key == "E"
            else self.units.density(value)
            if key == "density"
            else value
        )
        for m in ids:
            self.member_props.setdefault(m, {})[key] = converted

    def support_data(self, tokens: list[str]) -> None:
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if not ids or not spec:
            return
        kind = spec[0]
        if kind.startswith("FIX"):
            restraint = [True] * 6
            if "BUT" in spec:
                axis = {"FX": 0, "FY": 2, "FZ": 1, "MX": 3, "MY": 5, "MZ": 4}
                if self.z_up:
                    axis = {"FX": 0, "FY": 1, "FZ": 2, "MX": 3, "MY": 4, "MZ": 5}
                for t in spec[spec.index("BUT") + 1 :]:
                    if t in axis:
                        restraint[axis[t]] = False
                    elif t.startswith("K"):
                        self.report.approximate("spring supports taken as released", " ".join(spec))
                        break
        elif kind.startswith("PIN"):
            restraint = [True, True, True, False, False, False]
        else:
            for j in ids:
                self.report.skip("supports not read (enforced, inclined, foundation)", str(j))
            return
        for j in ids:
            self.model.supports[str(j)] = tuple(restraint)

    # ── loads ──

    def new_case(self, number: str, rest: list[str]) -> None:
        loadtype = ""
        title = " ".join(rest)
        if "LOADTYPE" in rest:
            k = rest.index("LOADTYPE")
            after = rest[k + 1 :]
            if "TITLE" in after:
                t = after.index("TITLE")
                loadtype = " ".join(after[:t])
                title = " ".join(after[t + 1 :])
            else:
                loadtype = " ".join(after)
                title = ""
        elif "TITLE" in rest:
            title = " ".join(rest[rest.index("TITLE") + 1 :])
        self.case = LoadCase(name=f"{number} {title}".strip())
        self.case.kind = _kind(loadtype, title)
        self.model.cases[number] = self.case
        self.block = "load"

    def finish_case(self) -> None:
        if self.combination is not None:
            self.model.combinations.append(self.combination)
            self.combination = None
        if self.case is not None and self.case.kind == "other" and self.case.selfweight:
            self.case.kind = "D"
        self.case = None if self.block.startswith("load") or self.block == "comb" else self.case

    def selfweight(self, tokens: list[str]) -> None:
        assert self.case is not None
        direction = tokens[1] if len(tokens) > 1 else self.vertical()
        factor = _num(tokens[2]) if len(tokens) > 2 else -1.0
        if direction != self.vertical() or factor is None:
            self.report.skip("self-weight not acting vertically", self.case.name)
            return
        if len(tokens) > 3 and tokens[3] not in ("ALL",):
            self.report.approximate(
                "self-weight on part of the model taken on all of it", self.case.name
            )
        self.case.selfweight += -factor

    def direction(self, token: str) -> np.ndarray | None:
        """The global SAEngine unit vector of a STAAD global direction (GX, GY, GZ, PX...)."""
        axis = {"GX": (1, 0, 0), "GY": (0, 1, 0), "GZ": (0, 0, 1)}
        axis.update({"PX": axis["GX"], "PY": axis["GY"], "PZ": axis["GZ"]})
        if token not in axis:
            return None
        return self.axes(*axis[token])

    def joint_load(self, tokens: list[str]) -> None:
        assert self.case is not None
        ids, k = self.id_list(tokens)
        force = np.zeros(3)
        moments = False
        for a, b in itertools.pairwise(tokens[k:]):
            v = _num(b)
            if v is None:
                continue
            if a in ("FX", "FY", "FZ"):
                force += self.axes(*{"FX": (1, 0, 0), "FY": (0, 1, 0), "FZ": (0, 0, 1)}[a]) * (
                    v * self.force
                )
            elif a in ("MX", "MY", "MZ"):
                moments = True
        if moments:
            self.report.skip("joint moments", self.case.name)
        for j in ids:
            self.case.loads.append(Load("joint", str(j), force.copy()))

    def member_load(self, tokens: list[str]) -> None:
        assert self.case is not None
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if len(spec) < 3:
            return
        kind, dir_token = spec[0], spec[1]
        numbers = [v for v in (_num(t) for t in spec[2:]) if v is not None]
        unit = self.direction(dir_token)
        local = dir_token in ("X", "Y", "Z")
        if unit is None and not local:
            self.report.skip(
                "member loads in directions not read", f"{self.case.name}: {dir_token}"
            )
            return
        if local:
            self.report.approximate(
                "member loads in local axes taken as global (local y as vertical)",
                f"{self.case.name}: {dir_token}",
            )
            unit = (
                self.axes(0, 1, 0)
                if dir_token == "Y"
                else self.axes(1, 0, 0)
                if dir_token == "X"
                else self.axes(0, 0, 1)
            )
        if dir_token.startswith("P"):
            self.report.approximate(
                "projected member loads taken on the member length", self.case.name
            )
        if kind.startswith("UNI") and numbers:
            w = numbers[0]
            length = None
            if len(numbers) >= 3:
                length = (numbers[2] - numbers[1]) * self.length
                self.report.approximate("partial uniform loads kept by their total", self.case.name)
            for m in ids:
                self.case.loads.append(
                    Load(
                        "uniform",
                        str(m),
                        unit * (w * self.force / (self.length / 1000)),
                        length=length,
                    )
                )
        elif kind.startswith("CON") and numbers:
            for m in ids:
                self.case.loads.append(Load("point", str(m), unit * (numbers[0] * self.force)))
        elif kind.startswith("TRAP") and len(numbers) >= 2:
            self.report.approximate("trapezoidal member loads taken as their mean", self.case.name)
            w = (numbers[0] + numbers[1]) / 2
            length = (numbers[3] - numbers[2]) * self.length if len(numbers) >= 4 else None
            for m in ids:
                self.case.loads.append(
                    Load(
                        "uniform",
                        str(m),
                        unit * (w * self.force / (self.length / 1000)),
                        length=length,
                    )
                )
        else:
            self.report.skip("member loads not read (moments, linear)", f"{self.case.name}: {kind}")

    def element_load(self, tokens: list[str]) -> None:
        assert self.case is not None
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if not spec or spec[0] != "PR":
            self.report.skip("element loads not read", f"{self.case.name}: {' '.join(spec[:2])}")
            return
        unit = self.direction(spec[1]) if len(spec) > 2 else None
        value = _num(spec[2] if unit is not None else spec[1]) if len(spec) > 1 else None
        if value is None:
            return
        pressure = value * self.force / (self.length / 1000) ** 2
        if len([t for t in spec if _num(t) is not None]) > 1:
            self.report.approximate(
                "partial element pressures taken on the whole element", self.case.name
            )
        for e in ids:
            vector = unit
            if vector is None:  # local z: the normal by the node order
                nodes = self.plates.get(e)
                if not nodes or any(n not in self.joints for n in nodes):
                    continue
                pts = [self.axes(*self.joints[n]) for n in nodes]
                normal = np.zeros(3)
                for p, q in zip(pts, pts[1:] + pts[:1], strict=True):
                    normal += np.cross(p - pts[0], q - pts[0])
                vector = normal / np.linalg.norm(normal)
            self.case.loads.append(Load("pressure", str(e), vector * pressure))

    def floor_load(self, tokens: list[str]) -> None:
        assert self.case is not None
        params: dict[str, list[float]] = {}
        current = None
        for t in tokens:
            v = _num(t)
            if v is None:
                current = t
                params.setdefault(t, [])
            elif current:
                params[current].append(v)
        up = "ZRANGE" if self.z_up else "YRANGE"
        load = params.get("FLOAD")
        if not load:
            return

        def span(key: str, sign: float = 1.0) -> tuple[float, float] | None:
            r = params.get(key, [])
            if len(r) < 2:
                return None
            a, b = sign * r[0] * self.length, sign * r[1] * self.length
            return (min(a, b), max(a, b))

        zrange = span(up)
        xrange = span("XRANGE")
        yrange = span("YRANGE") if self.z_up else span("ZRANGE", -1.0)
        pressure = load[0] * self.force / (self.length / 1000) ** 2
        self.case.loads.append(
            Load(
                "floor",
                "",
                np.array([0, 0, pressure]),
                zrange=zrange,
                xrange=xrange,
                yrange=yrange,
            )
        )

    def combination_data(self, tokens: list[str]) -> None:
        assert self.combination is not None
        values = [_num(t) for t in tokens]
        if any(v is None for v in values):
            return
        for a, b in zip(values[0::2], values[1::2], strict=False):
            key = str(int(a))  # type: ignore[arg-type]
            self.combination[1][key] = self.combination[1].get(key, 0.0) + float(b)  # type: ignore[arg-type]

    # ── the model ──

    def finish(self) -> None:
        m = self.model
        for j, p in self.joints.items():
            m.joints[str(j)] = self.axes(*p)
        materials: dict[tuple, str] = {}

        def material_of(n: int) -> str | None:
            props = self.member_props.get(n, {})
            base = props.get("material")
            overrides = tuple(
                sorted((k, round(float(v), 6)) for k, v in props.items() if k != "material")
            )
            if base is None and not overrides:
                return None
            key = (base, overrides)
            if key not in materials:
                defn = MaterialDef(name=str(base or "MATERIAL"))
                if base in self.definitions:
                    d = self.definitions[str(base)]
                    defn = MaterialDef(
                        name=str(base),
                        E=d.get("E"),  # type: ignore[arg-type]
                        nu=d.get("nu"),  # type: ignore[arg-type]
                        density=d.get("density"),  # type: ignore[arg-type]
                        kind=str(d.get("kind") or "") or None,
                        fy=d.get("fy"),  # type: ignore[arg-type]
                        fu=d.get("fu"),  # type: ignore[arg-type]
                        fc=d.get("fc"),  # type: ignore[arg-type]
                    )
                elif base in _BUILT_IN:
                    e, nu, rho, kind = _BUILT_IN[str(base)]
                    u = FileUnits(1000.0, 1000.0)
                    defn = MaterialDef(
                        name=str(base), E=u.mpa(e), nu=nu, density=u.density(rho), kind=kind
                    )
                    if kind == "steel":
                        self.report.approximate(
                            "built-in STEEL without a yield strength: fy 250 MPa", str(base)
                        )
                        defn.fy = 250.0
                elif base is not None:
                    self.report.approximate(
                        "materials named but not defined: values from CONSTANTS", str(base)
                    )
                for k, v in overrides:
                    setattr(defn, k, v)
                name = defn.name if not overrides else f"{defn.name}-{len(materials) + 1}"
                if overrides and base is None:
                    name = f"MATERIAL-{len(materials) + 1}"
                defn.name = name
                m.materials[name] = defn
                materials[key] = name
            return materials[key]

        for n, (i, j) in sorted(self.members.items()):
            if n in self.plates:
                continue
            section = self.member_section.get(n)
            if section is None:
                self.report.skip("members without a property", str(n))
            m.frames.append(Frame(str(n), str(i), str(j), section, material_of(n)))
        for n, nodes in sorted(self.plates.items()):
            t = self.plate_thickness.get(n)
            name = None
            if t is not None:
                name = f"SH{t:g}"
                m.area_sections.setdefault(name, SectionDef(name, thickness=t))
            m.areas.append(Area(str(n), [str(x) for x in nodes], name, material_of(n)))
        if not m.units:
            m.units = "kN, m"


def _kind(loadtype: str, title: str) -> str:
    text = f"{loadtype} {title}".upper()
    lt = loadtype.upper()
    if lt:
        if lt.startswith("DEAD"):
            return "D"
        if lt.startswith("ROOF"):
            return "Lr"
        if lt.startswith("LIVE"):
            return "L"
        if lt.startswith("WIND"):
            return "W"
        if lt.startswith(("SEISMIC", "EARTHQUAKE")):
            return "E"
    if re.search(r"\b(ROOF\s*LIVE|LR|RLL)\b", text):
        return "Lr"
    if re.search(r"\b(DEAD|DL|SELF|SW|D)\b", text):
        return "D"
    if re.search(r"\b(SUPER|SDL|FINISH|PARTITION)", text):
        return "SD"
    if re.search(r"\b(LIVE|LL|L)\b", text):
        return "L"
    if re.search(r"\b(WIND|WL|W[XYZ]?[+-]?)\b", text):
        return "W"
    if re.search(r"\b(SEISMIC|EARTHQUAKE|EQ[XYZ]?|E[XYZ][+-]?)\b", text):
        return "E"
    return "other"


def read_staad(path: str | Path) -> TextModel:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return _Reader(text, path.name).read()


def read_staad_text(text: str, file: str = "model.std") -> TextModel:
    return _Reader(text, file).read()


def import_staad(path: str | Path, name: str | None = None) -> ImportedProject:
    """The SAEngine project parts of the STAAD.Pro file at ``path``, with its import report."""
    return build(read_staad(path), name)
