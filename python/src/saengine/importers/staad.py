"""Import of a STAAD.Pro input file (``.std``) into a SAEngine project.

The reader follows the STAAD command language: free-format commands, one per line or several
separated by ``;``, a trailing ``-`` continuing a line, ``*`` comment lines, ``UNIT`` lines that
may change the length and force units anywhere, and command words abbreviated as STAAD allows
(``MEMB LOAD``, ``JOINT COORD``, ``REP``, ``UNITS``, ``SELF``). It reads:

- ``STAAD SPACE|PLANE|TRUSS``, ``SET Z UP`` (otherwise Y is up and the model is turned to Z up);
- ``JOINT COORDINATES`` (also ``CYLINDRICAL [REVERSE]``) with generation (``i1 x1 y1 z1 i2 x2
  y2 z2 [inc]``), ``REPEAT`` (the previous line, or the last repetition of it) and ``REPEAT ALL``
  (everything back to the last ``REPEAT ALL`` that was followed by new data), ``JTORIG``;
- ``MEMBER INCIDENCES`` (``m i j [m2 [minc [jinc]]]``), ``ELEMENT INCIDENCES [SHELL]`` (``TO``
  generation), both with ``REPEAT`` / ``REPEAT ALL``; ``DELETE MEMBERS``;
- ``START GROUP DEFINITION``: group names (``_BEAMS``) in any list;
- ``DEFINE PMEMBER`` (physical members): ``PMEMBER PROPERTY``, ``PMEMBER CONSTANTS`` and
  ``PMEMBER LOAD`` on the members that make them up;
- ``MEMBER PROPERTY``: ``PRISMATIC YD ZD`` (rectangle), ``YD`` alone (circle), ``AX IZ`` (an
  equivalent rectangle, approximated), ``TABLE ST name`` (by name, see
  :func:`~saengine.importers.neutral.named_profile`), ``PIPE OD ID``, ``TUBE TH WT DT``;
- ``ELEMENT PROPERTY ... THICKNESS``;
- ``DEFINE MATERIAL`` (``ISOTROPIC``, ``E``, ``POISSON``, ``DENSITY``, ``TYPE``, ``STRENGTH``)
  and ``CONSTANTS`` (``MATERIAL``, ``E``, ``POISSON``, ``DENSITY``, ``BETA`` by member list, the
  built-in STEEL and CONCRETE);
- ``MEMBER RELEASE`` (bending released at both ends: pinned), ``MEMBER TRUSS`` (pinned),
  ``MEMBER OFFSET``, cables, tension- and compression-only and inactive members (reported);
- ``SUPPORTS`` (``FIXED``, ``PINNED``, ``FIXED BUT ...``; springs, inclined, enforced supports and
  generated soil springs reported);
- ``LOAD n`` (``LOADTYPE``, ``TITLE``) with ``SELFWEIGHT``, ``JOINT LOAD``, ``MEMBER LOAD`` and
  ``PMEMBER LOAD`` (``UNI``, ``CON``, ``LIN`` and ``TRAP`` as their mean over the loaded length;
  global, projected and local directions), ``ELEMENT LOAD`` (``PR``, ``TRAP`` as its mean),
  ``FLOOR LOAD``, ``REPEAT LOAD`` and ``REFERENCE LOAD`` (``DEFINE REFERENCE LOADS``);
  ``LOAD COMBINATION n``.

Member and joint loads go onto the floor-plan beams and columns (``05 Floor Plan/loads.json``,
see :mod:`saengine.importers.common`). Generated wind and seismic loads are listed as replaced
by SAEngine's own (BNBC 2020); everything else (other generated loads, design parameters,
analysis commands) is skipped and listed in the import report.
"""

from __future__ import annotations

import itertools
import math
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
    "METRES": 1000.0,
    "MET": 1000.0,
    "METE": 1000.0,
    "M": 1000.0,
    "MMS": 1.0,
    "MM": 1.0,
    "MMS.": 1.0,
    "MILLIMETER": 1.0,
    "CM": 10.0,
    "CMS": 10.0,
    "CENTIMETER": 10.0,
    "FEET": 304.8,
    "FT": 304.8,
    "FOOT": 304.8,
    "FEE": 304.8,
    "INCHES": 25.4,
    "INCH": 25.4,
    "IN": 25.4,
    "INC": 25.4,
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
    "POU": 4.4482216152605,
    "KG": 9.80665,
    "KGS": 9.80665,
    "MTON": 9806.65,
    "MTONS": 9806.65,
    "MTO": 9806.65,
    "DNS": 10.0,
    "KNEWTON": 1000.0,
}

#: STAAD's built-in materials in kN and m (E, POISSON, DENSITY [kN/m³]).
_BUILT_IN = {
    "STEEL": (2.05e8, 0.3, 76.8195, "steel"),
    "CONCRETE": (2.17185e7, 0.17, 23.5616, "concrete"),
    "ALUMINUM": (6.89476e7, 0.33, 26.6018, "steel"),
}

#: Command words and the shortest abbreviation STAAD accepts for each.
_HEADS = {
    "STAAD": 5,
    "SET": 3,
    "UNIT": 3,
    "JOINT": 3,
    "MEMBER": 3,
    "ELEMENT": 3,
    "PMEMBER": 4,
    "DEFINE": 3,
    "END": 3,
    "CONSTANTS": 4,
    "SUPPORTS": 3,
    "LOAD": 4,
    "PERFORM": 4,
    "PRINT": 3,
    "FINISH": 3,
    "PARAMETER": 4,
    "START": 4,
    "CHECK": 4,
    "SELECT": 4,
    "INPUT": 4,
    "PAGE": 4,
    "SPRING": 4,
    "INACTIVE": 4,
    "DELETE": 4,
    "CUT": 3,
    "SECTION": 4,
    "DESIGN": 4,
    "TAKE": 4,
    "STEEL": 4,
    "CONCRETE": 4,
    "PDELTA": 4,
    "CHANGE": 4,
    "SELFWEIGHT": 4,
    "REPEAT": 3,
    "FLOOR": 4,
    "CALCULATE": 4,
    "SURFACE": 4,
    "JTORIG": 4,
    "SLAVE": 4,
    "TIMBER": 4,
    "GROUP": 4,
    "MASTER": 4,
    "GENERATE": 3,
}
_SECOND = {
    "INCIDENCES": 3,
    "COORDINATES": 3,
    "PROPERTY": 3,
    "RELEASE": 3,
    "TRUSS": 3,
    "OFFSET": 3,
    "LOAD": 3,
    "CABLE": 3,
    "TENSION": 3,
    "COMPRESSION": 4,
    "CRACKED": 4,
    "CONSTANTS": 4,
    "WEIGHT": 3,
    "MATERIAL": 3,
    "PMEMBER": 4,
    "REFERENCE": 3,
    "COMBINATION": 4,
}

#: Generated loads: the load generators' commands (SAEngine makes its own wind and seismic).
_GENERATED = re.compile(
    r"^(WIND|SEISMIC|SPECTRUM|TIME|GROUND|UBC|IBC|AIJ|CFE|NTC|RPA|NRC|IS|COLOMBIAN|TURKISH|GB|"
    r"AS|NBC|CODE|BS|EN|EURO|KOREAN|TAIWAN|IRAN|CHILE|SOUTH|NZS|PERU|NOTIONAL|ACCIDENTAL|"
    r"DIRECT|MOVING|SNOW|CALIFORNIA|NORTH|WAVE|1893|PRESSURE|TEMP|TEMPERATURE|STRAIN|"
    r"STRAINRATE|PRESTRESS|POSTSTRESS|FIXED|ONEWAY|AREA|BLAST|ASCE)$"
)
#: Generators of :data:`_GENERATED` that are not wind or earthquake loads (SAEngine does not
#: replace these with loads of its own: they are skipped).
_NOT_LATERAL = {
    "DIRECT",
    "MOVING",
    "SNOW",
    "WAVE",
    "PRESSURE",
    "TEMP",
    "TEMPERATURE",
    "STRAIN",
    "STRAINRATE",
    "PRESTRESS",
    "POSTSTRESS",
    "FIXED",
    "ONEWAY",
    "AREA",
    "BLAST",
}


def _num(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


def _canon(token: str, table: dict[str, int]) -> str:
    """The full command word an abbreviation stands for (``MEMB`` -> ``MEMBER``,
    ``UNITS`` -> ``UNIT``), else the token."""
    for full, shortest in table.items():
        if len(token) >= shortest and (full.startswith(token) or token.startswith(full)):
            return full
    return token


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


class _Reader:
    def __init__(self, text: str, file: str) -> None:
        self.model = TextModel(format=FORMAT, file=file, report=ImportReport(FORMAT, file))
        self.report = self.model.report
        self.length = 1000.0
        self.force = 1000.0
        self.unit_seen = False
        self.z_up = False
        self.truss_model = False
        self.block = ""
        self.joints: dict[int, np.ndarray] = {}  # file axes, mm
        self.cylindrical = ""
        self.origin = np.zeros(3)
        self.origin_from = 0
        # Rows for REPEAT: each a list of ids (a data line, or one repetition).
        self.joint_rows: list[list[int]] = []
        self.joint_all_from = 0
        self.joint_all_pending = False
        self.members: dict[int, tuple[int, int]] = {}
        self.member_rows: list[list[int]] = []
        self.member_all_from = 0
        self.member_all_pending = False
        self.plates: dict[int, list[int]] = {}
        self.plate_rows: list[list[int]] = []
        self.plate_all_from = 0
        self.plate_all_pending = False
        self.groups: dict[str, list[int]] = {}
        self.group_kind = ""
        self.group_current: str | None = None
        self.pmembers: dict[int, list[int]] = {}
        self.pmember_mode = False
        self.member_section: dict[int, str] = {}
        self.plate_thickness: dict[int, float] = {}
        self.definitions: dict[str, dict[str, float | str]] = {}
        self.defining: str | None = None
        self.member_props: dict[int, dict[str, float | str]] = {}
        self.beta: dict[int, float] = {}
        self.releases: dict[int, tuple[set[str], set[str]]] = {}
        self.trusses: set[int] = set()
        self.deleted: set[int] = set()
        self.case: LoadCase | None = None
        self.case_key: str | None = None
        self.references: dict[str, LoadCase] = {}
        self.in_reference = False
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

    def local_axes(self, m: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Member ``m``'s local x, y, z in the file's axes (STAAD's rules: a vertical member's
        local z along global Z with Y up, its local y along global Y with Z up, measured; other
        members' local y in the vertical plane through them, upwards), turned by its beta."""
        if m not in self.members:
            return None
        i, j = self.members[m]
        if i not in self.joints or j not in self.joints:
            return None
        d = self.joints[j] - self.joints[i]
        if np.linalg.norm(d) < 1e-9:
            return None
        x = _unit(d)
        up = np.array([0.0, 0.0, 1.0]) if self.z_up else np.array([0.0, 1.0, 0.0])
        if abs(float(x @ up)) > 0.999:
            if self.z_up:
                y = np.array([0.0, 1.0, 0.0])
                z = np.cross(x, y)
            else:
                z = np.array([0.0, 0.0, 1.0])
                y = np.cross(z, x)
        else:
            z = _unit(np.cross(x, up))
            y = np.cross(z, x)
        b = math.radians(self.beta.get(m, 0.0))
        y, z = math.cos(b) * y + math.sin(b) * z, -math.sin(b) * y + math.cos(b) * z
        return x, y, z

    def rotation(self, m: int) -> float:
        """The member's angle as SAP2000/ETABS give it (local 2 = STAAD's local y): what the
        builder takes, from STAAD's local axes and beta."""
        axes = self.local_axes(m)
        if axes is None:
            return 0.0
        e1 = self.axes(*axes[0])
        y = self.axes(*axes[1])
        if math.hypot(e1[0], e1[1]) < 1e-3:
            e2 = np.array([1.0, 0.0, 0.0])
            e3 = np.cross(e1, e2)
        else:
            e3 = _unit(np.cross(e1, np.array([0.0, 0.0, 1.0])))
            e2 = np.cross(e3, e1)
        angle = math.degrees(math.atan2(float(y @ e3), float(y @ e2)))
        return round(angle, 6) % 360

    # ── lists ──

    def id_list(self, tokens: list[str], start: int = 0) -> tuple[list[int], int]:
        """The ids of a STAAD list (``1 2 5 TO 9 BY 2``, ``ALL``, ``_GROUP``) from
        ``tokens[start]``, and the index after it."""
        ids: list[int] = []
        k = start
        while k < len(tokens):
            t = tokens[k]
            if t in (
                "MEMB",
                "MEMBER",
                "MEMBERS",
                "JOINT",
                "JOI",
                "JOINTS",
                "PLA",
                "PLATE",
                "PLATES",
                "ELEM",
                "ELEMENT",
                "ELEMENTS",
                "LIST",
                "MEM",
                "MEMBE",
            ):
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
                if t in self.groups:
                    ids += self.groups[t]
                else:
                    self.report.skip("group names in lists that are not defined", t)
                k += 1
                continue
            value = _num(t)
            if value is None or value != int(value):
                break
            ids.append(int(value))
            k += 1
        return ids, k

    def member_ids(self, ids: list[int], tokens: list[str] | None = None) -> list[int]:
        """Members of a list of members, or of physical members in a PMEMBER command (``ALL``:
        every member)."""
        if not self.pmember_mode:
            return ids
        if tokens is not None and "ALL" in tokens:
            return sorted(self.members)
        out: list[int] = []
        for p in ids:
            if p in self.pmembers:
                out += self.pmembers[p]
            else:
                self.report.skip("physical members that are not defined", str(p))
        return out

    # ── statements ──

    def statements(self) -> list[list[str]]:
        lines: list[str] = []
        pending = ""
        for raw in self.text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("*", "<#", "#>")):
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
                tokens = part.replace(",", " ").replace('"', " ").upper().split()
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
        if _num(head) is None and not head.startswith("_"):
            canon = _canon(head, _HEADS)
            if self.block in ("joints", "members", "plates") and head == "R":
                canon = "REPEAT"
            if canon == "UNIT":
                self.unit(tokens)
                return
            tokens = [canon, *tokens[1:]]
            if len(tokens) > 1 and canon in (
                "MEMBER",
                "ELEMENT",
                "JOINT",
                "PMEMBER",
                "LOAD",
                "REPEAT",
                "DEFINE",
            ):
                tokens[1] = _canon(tokens[1], _SECOND)
        head = tokens[0]
        if self.block == "groups":
            self.group_line(tokens)
            return
        if self.block == "usertable":
            if head == "END":
                self.block = ""
            return
        first_alpha = _num(head) is None
        if first_alpha and self.block_keyword(tokens):
            return
        if first_alpha and head == "REPEAT" and self.block in ("joints", "members", "plates"):
            self.data(tokens)
            return
        if first_alpha and (head in _HEADS or head.startswith("LOAD")):
            self.command(tokens)
            return
        if first_alpha and head not in ("TO", "ALL") and not head.startswith("_"):
            if self.case is not None and self.block.startswith("load"):
                self.generated_or_unknown(tokens)
                return
            if self.block not in ("skip",):
                self.report.skip("commands not read", " ".join(tokens[:3]))
            self.block = "skip"
            return
        self.data(tokens)

    def generated_or_unknown(self, tokens: list[str]) -> None:
        """A line in a load case that is not a load the reader knows: the case stays open."""
        assert self.case is not None
        example = f"{self.case.name}: {' '.join(tokens[:3])}"
        if _GENERATED.match(tokens[0]) and tokens[0] not in _NOT_LATERAL:
            self.report.note("loads.lateral.generated", example)
        elif _GENERATED.match(tokens[0]) or (len(tokens) > 1 and tokens[1] == "LOAD"):
            self.report.skip(
                "generated loads not read (snow, temperature, prestress, moving, area and "
                "one-way loads)",
                example,
            )
        else:
            self.report.skip("load commands not read", f"{self.case.name}: {' '.join(tokens[:3])}")
        self.block = "load-other"

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
        if self.block == "joints" and head == "JTORIG":
            values = [_num(t) for t in tokens[1:4]]
            if len(values) == 3 and all(v is not None for v in values):
                shift = np.array([float(v) for v in values if v is not None]) * self.length
                for n in [j for row in self.joint_rows[self.origin_from :] for j in row]:
                    self.joints[n] = self.joints[n] + shift
            return True
        if self.block == "pmembers" and head == "PMEMBER":
            return False
        if self.block == "mesh-points" and len(tokens) >= 3 and len(head) <= 2:
            self.mesh_point(tokens)
            return True
        if self.block == "mesh" and head == "MESH":
            self.mesh(tokens)
            return True
        if self.case is not None and self.block.startswith("load"):
            if head == "SELFWEIGHT":
                self.selfweight(tokens)
                return True
            second = tokens[1] if len(tokens) > 1 else ""
            if head == "REPEAT" and second == "LOAD":
                self.block = "load-repeat"
                return True
            if head == "REFERENCE" or (head.startswith("REF") and second.startswith("LOA")):
                self.block = "load-reference"
                return True
            if second.startswith("LOAD") and head in (
                "JOINT",
                "MEMBER",
                "ELEMENT",
                "PMEMBER",
                "FLOOR",
                "ONEWAY",
                "AREA",
                "TEMPERATURE",
                "TEMP",
                "STRAIN",
                "PRESTRESS",
                "POSTSTRESS",
                "FIXED",
            ):
                self.block = {
                    "JOINT": "load-joint",
                    "MEMBER": "load-member",
                    "PMEMBER": "load-pmember",
                    "ELEMENT": "load-element",
                    "FLOOR": "load-floor",
                }.get(head, "load-other")
                if self.block == "load-other":
                    self.report.skip(f"{head.lower()} loads (not read)", f"{self.case.name}")
                return True
            if head == "SUPPORTS" and second.startswith("DISP"):
                self.report.skip("support displacements (not read)", self.case.name)
                self.block = "load-other"
                return True
            if self.block == "load-floor" and head[:3] in ("YRA", "XRA", "ZRA"):
                self.floor_load(tokens)
                return True
            if self.block == "load-reference" and re.match(r"^R\d+$", head):
                self.reference_data(tokens)
                return True
        if self.block == "supports" and head in ("FIXED", "PINNED"):
            return False
        return False

    def command(self, tokens: list[str]) -> None:
        head = tokens[0]
        second = tokens[1] if len(tokens) > 1 else ""
        if head == "STAAD":
            if second == "PLANE":
                self.report.warn("STAAD plane model: read as a 3D model")
            elif second == "TRUSS":
                self.truss_model = True
                self.report.warn("STAAD truss model: read as a 3D model, its members pinned")
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
                    self.report.note("combinations.envelope", " ".join(tokens))
                    self.block = "skip"
                    return
                title = " ".join(rest[1:]) or f"Combination {number}"
                self.combination = (f"{number} {title}".strip(), {})
                self.block = "comb"
                return
            if second == "LIST":
                self.block = "skip"
                return
            if self.in_reference and re.match(r"^R\d+$", second):
                self.new_case(second, tokens[2:], reference=True)
                return
            if _num(second) is None:
                self.block = "skip"
                return
            self.new_case(second, tokens[2:])
            return
        self.finish_case()
        if head == "JOINT" and second.startswith("COORD"):
            self.cylindrical = ""
            if "CYLINDRICAL" in tokens or "CYL" in tokens:
                self.cylindrical = "reverse" if any(t.startswith("REV") for t in tokens) else "z"
                self.report.approximate(
                    "cylindrical joint coordinates converted to Cartesian", " ".join(tokens[2:4])
                )
            self.origin_from = len(self.joint_rows)
            self.block = "joints"
            rest = [t for t in tokens[2:] if _num(t) is not None]
            if rest:
                self.data(rest)
            return
        if head in ("MEMBER", "PMEMBER"):
            self.pmember_mode = head == "PMEMBER"
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
                if len(tokens) > 2:
                    self.data(tokens[2:])
                return
            if second in ("CONSTANTS",):
                self.block = "constants"
                return
            if second in ("OFFSET", "CABLE", "TENSION", "COMPRESSION", "CRACKED"):
                self.block = "member-" + second.lower()
                if len(tokens) > 2:
                    self.data(tokens[2:])
                return
            self.report.skip("member commands not read", " ".join(tokens[:2]))
            self.block = "skip"
            return
        if head == "ELEMENT":
            self.pmember_mode = False
            if second.startswith("INCI"):
                if "SOLID" in tokens:
                    self.report.skip("solid elements")
                    self.block = "solids"
                    return
                self.block = "plates"
                return
            if second.startswith("PROP"):
                self.block = "eprop"
                return
            self.report.skip("element commands not read", " ".join(tokens[:3]))
            self.block = "skip"
            return
        if head == "DEFINE":
            if second == "MATERIAL":
                self.block = "material"
                return
            if second == "PMEMBER":
                self.block = "pmembers"
                return
            if second == "REFERENCE":
                self.in_reference = True
                self.block = ""
                return
            if second == "MESH":
                self.block = "mesh-points"
                return
            self.report.skip("DEFINE commands not read", " ".join(tokens[:3]))
            self.block = "skip"
            return
        if head == "END":
            if "REFERENCE" in tokens or (len(tokens) > 2 and tokens[2].startswith("REF")):
                self.in_reference = False
            self.block = ""
            self.defining = None
            return
        if head == "CONSTANTS":
            self.pmember_mode = False
            self.block = "constants"
            return
        if head == "SUPPORTS":
            self.block = "supports"
            return
        if head == "INACTIVE":
            self.block = "inactive"
            if len(tokens) > 2:
                self.data(tokens[2:])
            return
        if head == "DELETE":
            if second.startswith("MEM"):
                self.block = "delete"
                if len(tokens) > 2:
                    self.data(tokens[2:])
                return
            self.report.skip("DELETE commands not read", " ".join(tokens[:2]))
            self.block = "skip"
            return
        if head == "GENERATE" or (head.startswith("GEN") and second.startswith("ELE")):
            self.block = "mesh"
            return
        if head == "SPRING":
            self.report.skip("tension- or compression-only springs", " ".join(tokens[:3]))
            self.block = "skip"
            return
        if head in ("PERFORM", "PRINT", "FINISH", "PARAMETER", "CHECK", "SELECT"):
            self.block = "skip"
            return
        if head == "START":
            if "GROUP" in tokens:
                self.block = "groups"
                return
            if "USER" in tokens:
                self.block = "usertable"
                self.report.skip("user tables (UPT sections are not read)")
                return
            self.block = "skip"
            return
        self.block = "skip"

    # ── groups ──

    def group_line(self, tokens: list[str]) -> None:
        head = tokens[0]
        if head == "END":
            self.block = ""
            return
        if head in ("JOINT", "MEMBER", "ELEMENT", "GEOMETRY", "SOLID", "FLOOR"):
            self.group_kind = head
            tokens = tokens[1:]
            if not tokens:
                return
            head = tokens[0]
        if head.startswith("_"):
            self.group_current = head
            ids, _ = self.id_list(tokens, 1)
            self.groups[head] = ids
            return
        if self.group_current is not None and _num(head) is not None:
            ids, _ = self.id_list(tokens)
            self.groups[self.group_current] += ids

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
            self.release_data(tokens)
        elif block == "truss":
            ids, _ = self.id_list(tokens)
            self.trusses.update(self.member_ids(ids))
        elif block == "pmembers":
            ids, k = self.id_list(tokens)
            rest = tokens[k:]
            if len(rest) >= 2 and rest[0] == "PMEMBER" and _num(rest[1]) is not None:
                self.pmembers[int(float(rest[1]))] = ids
        elif block.startswith("member-"):
            ids, _ = self.id_list(tokens)
            what = {
                "member-offset": "member offsets ignored (members run joint to joint)",
                "member-cable": "cables analysed as ordinary members (no tension-only behaviour)",
                "member-tension": "tension-only members analysed as ordinary members",
                "member-compression": "compression-only members analysed as ordinary members",
                "member-cracked": "cracked member stiffness reductions not applied",
            }[block]
            for m in self.member_ids(ids):
                self.report.approximate(what, str(m))
            if block == "member-cable":
                self.trusses.update(self.member_ids(ids))
        elif block == "inactive":
            ids, _ = self.id_list(tokens)
            for m in ids:
                self.report.approximate(
                    "inactive members imported as active (STAAD leaves them out of an analysis)",
                    str(m),
                )
        elif block == "delete":
            ids, _ = self.id_list(tokens)
            self.deleted.update(ids)
        elif block == "constants":
            self.constants_line(tokens)
        elif block == "load-joint":
            self.joint_load(tokens)
        elif block in ("load-member", "load-pmember"):
            self.member_load(tokens, physical=block == "load-pmember")
        elif block == "load-element":
            self.element_load(tokens)
        elif block == "load-repeat":
            self.repeat_load(tokens)
        elif block == "load-reference":
            self.reference_data(tokens)
        elif block == "comb":
            self.combination_data(tokens)

    # ── geometry ──

    def joint_data(self, tokens: list[str]) -> None:
        if tokens[0] == "REPEAT":
            self.repeat(tokens, "joints")
            return
        values = [_num(t) for t in tokens]
        if any(v is None for v in values) or len(values) < 3:
            self.report.skip("joint lines not read", " ".join(tokens))
            return
        nums: list[float] = [v for v in values if v is not None]
        if len(nums) == 3:  # plane model: n x y
            nums = [*nums, 0.0]
        n1 = int(nums[0])
        p1 = np.array(nums[1:4])
        row = [n1]
        points = {n1: p1}
        if len(nums) >= 8:
            n2 = int(nums[4])
            p2 = np.array(nums[5:8])
            inc = int(nums[8]) if len(nums) > 8 else 1
            steps = (n2 - n1) // inc if inc else 0
            for k in range(1, steps + 1):
                n = n1 + k * inc
                points[n] = p1 + (p2 - p1) * k / steps
                row.append(n)
        for n, p in points.items():
            self.joints[n] = self.cartesian(p) * self.length
        self.add_row("joints", row)

    def cartesian(self, p: np.ndarray) -> np.ndarray:
        """A point of the file's coordinates (cylindrical ones converted) in its axes."""
        if not self.cylindrical:
            return p
        r = p[0]
        if self.cylindrical == "z":  # r, θ, z about global Z
            t = math.radians(p[1])
            return np.array([r * math.cos(t), r * math.sin(t), p[2]])
        t = math.radians(p[2])  # reverse: r, y, θ about global Y
        return np.array([r * math.cos(t), p[1], r * math.sin(t)])

    def add_row(self, kind: str, row: list[int]) -> None:
        prefix = {"joints": "joint", "members": "member", "plates": "plate"}[kind]
        rows = getattr(self, f"{prefix}_rows")
        rows.append(row)
        if getattr(self, f"{prefix}_all_pending"):
            setattr(self, f"{prefix}_all_from", len(rows) - 1)
            setattr(self, f"{prefix}_all_pending", False)

    def repeat(self, tokens: list[str], kind: str) -> None:
        """``REPEAT n ...`` (the last row n times) or ``REPEAT ALL n ...`` (every row back to
        the last REPEAT ALL followed by new data), numbered on from the highest id."""
        prefix = {"joints": "joint", "members": "member", "plates": "plate"}[kind]
        rows: list[list[int]] = getattr(self, f"{prefix}_rows")
        all_ = len(tokens) > 1 and tokens[1].startswith("A")
        values = [_num(t) for t in tokens[2 if all_ else 1 :]]
        if not values or any(v is None for v in values):
            self.report.skip("REPEAT lines not read", " ".join(tokens))
            return
        n = int(values[0] or 0)
        rest = [float(v) for v in values[1:] if v is not None]
        if all_ and n == 0:  # REPEAT ALL 0: starts a section to repeat
            setattr(self, f"{prefix}_all_from", len(rows))
            setattr(self, f"{prefix}_all_pending", False)
            return
        start = getattr(self, f"{prefix}_all_from")
        base = [i for row in rows[start:] for i in row] if all_ else (rows[-1] if rows else [])
        if not base:
            return
        if kind == "joints":
            increments = [rest[3 * k : 3 * k + 3] for k in range(len(rest) // 3)] or [[0, 0, 0]]
            offset = np.zeros(3)
            for k in range(1, n + 1):
                step = increments[k - 1] if len(increments) >= n else increments[0]
                offset = offset + np.array(step + [0.0] * (3 - len(step))) * self.length
                top = max(self.joints)
                new = []
                for idx, j in enumerate(base):
                    self.joints[top + 1 + idx] = self.joints[j] + offset
                    new.append(top + 1 + idx)
                rows.append(new)
        else:
            items = self.members if kind == "members" else self.plates
            mi = int(rest[0]) if rest else max(items) - min(base) + 1
            ji = int(rest[1]) if len(rest) > 1 else max(self.joints)
            for k in range(1, n + 1):
                new = []
                for e in base:
                    if kind == "members":
                        i, j = self.members[e]
                        self.members[e + k * mi] = (i + k * ji, j + k * ji)
                    else:
                        self.plates[e + k * mi] = [x + k * ji for x in self.plates[e]]
                    new.append(e + k * mi)
                rows.append(new)
        if all_:
            setattr(self, f"{prefix}_all_pending", True)

    def member_data(self, tokens: list[str]) -> None:
        if tokens[0] == "REPEAT":
            self.repeat(tokens, "members")
            return
        values = [_num(t) for t in tokens]
        if any(v is None for v in values) or len(values) < 3:
            self.report.skip("member lines not read", " ".join(tokens))
            return
        m, i, j = (int(v) for v in values[:3])  # type: ignore[arg-type]
        row = [m]
        self.members[m] = (i, j)
        if len(values) >= 4:
            m2 = int(values[3])  # type: ignore[arg-type]
            minc = int(values[4]) if len(values) > 4 else 1  # type: ignore[arg-type]
            jinc = int(values[5]) if len(values) > 5 else 1  # type: ignore[arg-type]
            k = 1
            while minc > 0 and m + k * minc <= m2:
                self.members[m + k * minc] = (i + k * jinc, j + k * jinc)
                row.append(m + k * minc)
                k += 1
        self.add_row("members", row)

    def plate_data(self, tokens: list[str]) -> None:
        if tokens[0] == "REPEAT":
            self.repeat(tokens, "plates")
            return
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
        row = [e]
        if tail:
            e2 = int(float(tail[0]))
            einc = int(float(tail[1])) if len(tail) > 1 else 1
            ninc = int(float(tail[2])) if len(tail) > 2 else 1
            k = 1
            while einc > 0 and e + k * einc <= e2:
                self.plates[e + k * einc] = [n + k * ninc for n in nodes]
                row.append(e + k * einc)
                k += 1
        self.add_row("plates", row)

    # ── generated meshes ──

    def mesh_point(self, tokens: list[str]) -> None:
        """A super-element corner of DEFINE MESH: ``A JOINT 7`` or ``A x y z``."""
        if not hasattr(self, "mesh_points"):
            self.mesh_points: dict[str, np.ndarray] = {}
        if tokens[1].startswith("JOI") and len(tokens) > 2 and _num(tokens[2]) is not None:
            n = int(float(tokens[2]))
            if n in self.joints:
                self.mesh_points[tokens[0]] = self.joints[n].copy()
            return
        values = [_num(t) for t in tokens[1:4]]
        if len(values) == 3 and all(v is not None for v in values):
            point = np.array([float(v) for v in values if v is not None])
            self.mesh_points[tokens[0]] = self.cartesian(point) * self.length

    def mesh(self, tokens: list[str]) -> None:
        """``MESH ABCD n1 [n2]``: quadrilaterals over the bilinear patch A-B-C-D, n1 along AB
        and n2 along BC; joints at existing joints' places are shared, new ones and the
        elements numbered on from the highest."""
        points = getattr(self, "mesh_points", {})
        corners = tokens[1] if len(tokens) > 1 else ""
        counts = [int(float(t)) for t in tokens[2:4] if _num(t) is not None]
        if len(corners) != 4 or not counts or any(c not in points for c in corners):
            self.report.skip(
                "mesh generation not read (triangles, unknown corners)", " ".join(tokens)
            )
            return
        n1 = counts[0]
        n2 = counts[1] if len(counts) > 1 else n1
        a, b, c, d = (points[k] for k in corners)
        index: dict[tuple[int, int, int], int] = {
            tuple(round(float(v)) for v in p): j for j, p in self.joints.items()
        }
        grid: dict[tuple[int, int], int] = {}
        for i in range(n1 + 1):
            for j in range(n2 + 1):
                u, v = i / n1, j / n2
                p = (1 - u) * (1 - v) * a + u * (1 - v) * b + u * v * c + (1 - u) * v * d
                key = tuple(round(float(x)) for x in p)
                if key not in index:
                    n = max(self.joints, default=0) + 1
                    self.joints[n] = p
                    index[key] = n
                grid[(i, j)] = index[key]
        start = max([*self.members, *self.plates], default=0) + 1
        e = start
        for j in range(n2):
            for i in range(n1):
                self.plates[e] = [
                    grid[(i, j)],
                    grid[(i + 1, j)],
                    grid[(i + 1, j + 1)],
                    grid[(i, j + 1)],
                ]
                e += 1
        self.report.approximate(
            "meshes generated from DEFINE MESH by SAEngine's reading of STAAD's rule (check the "
            "element numbering)",
            " ".join(tokens[:2]),
        )

    # ── properties ──

    def member_property(self, tokens: list[str]) -> None:
        if tokens[0] in ("AMERICAN", "BRITISH", "EUROPEAN", "INDIAN", "JAPANESE", "CANADIAN"):
            return
        ids, k = self.id_list(tokens)
        ids = self.member_ids(ids, tokens[:k])
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
        if kind == "PR" or kind.startswith("PRI"):
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
            if table == "ST" and designation in ("PIPE", "TUBE"):
                return self.section(spec[2:])
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
        values = [v for v in (_num(t) for t in spec[1:5]) if v is not None]
        if not values:
            return
        if len({round(v, 9) for v in values}) > 1:
            self.report.approximate("plates of varying thickness taken at their mean", str(ids[0]))
        t = sum(values) / len(values) * self.length
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
        if head in ("G", "ALPHA", "DAMP", "CDAMP"):
            return
        if head == "BETA":
            value = _num(tokens[1]) if len(tokens) > 1 else None
            ids, _ = self.id_list(tokens, 2)
            ids = self.member_ids(ids) or sorted(self.members)
            if value is None:
                for m in ids:
                    self.report.approximate(
                        "beta angles given as ANGLE, RANGLE or a reference point ignored",
                        f"{m} ({' '.join(tokens[1:3])})",
                    )
                return
            for m in ids:
                self.beta[m] = value
            return
        if len(tokens) < 2:
            return
        target, value_token = head, tokens[1]
        ids, _ = self.id_list(tokens, 2)
        if not ids:
            ids = sorted({*self.members, *self.plates})
        elif self.pmember_mode:
            ids = self.member_ids(ids, tokens[2:])
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

    def release_data(self, tokens: list[str]) -> None:
        ids, k = self.id_list(tokens)
        ids = self.member_ids(ids)
        spec = tokens[k:]
        if not ids or not spec:
            return
        where = spec[0]
        ends: tuple[int, ...] | None = None
        if where.startswith("STA"):
            ends = (0,)
        elif where.startswith("END"):
            ends = (1,)
        elif where.startswith("BOT"):
            ends = (0, 1)
        if ends is None:
            self.report.skip("member release lines not read", " ".join(tokens))
            return
        names = {"FX": "P", "FY": "V2", "FZ": "V3", "MX": "T", "MY": "M2", "MZ": "M3"}
        released: set[str] = set()
        springs = []
        partial: list[tuple[str, float]] = []
        rest = spec[1:]
        idx = 0
        while idx < len(rest):
            t = rest[idx]
            value = _num(rest[idx + 1]) if idx + 1 < len(rest) else None
            if t in names:
                released.add(names[t])
                idx += 1
            elif t.startswith("K") and t[1:] in names:
                springs.append(t)
                idx += 2
            elif t in ("MP", "MPX", "MPY", "MPZ") and value is not None:
                targets = {"MP": ("T", "M2", "M3"), "MPX": ("T",), "MPY": ("M2",), "MPZ": ("M3",)}[
                    t
                ]
                for name in targets:
                    partial.append((name, value))
                idx += 2
            else:
                idx += 1
        for m in ids:
            if springs:
                self.report.approximate(
                    "spring releases at member ends taken as rigid connections",
                    f"{m} ({' '.join(springs)})",
                )
            for name, factor in partial:
                if factor >= 0.5:
                    released.add(name)
                    self.report.approximate(
                        "partial moment releases of half or more taken as full releases",
                        f"{m} ({name} {factor:g})",
                    )
                else:
                    self.report.approximate(
                        "partial moment releases under half taken as rigid connections",
                        f"{m} ({name} {factor:g})",
                    )
            current = self.releases.setdefault(m, (set(), set()))
            for e in ends:
                current[e].update(released)

    def support_data(self, tokens: list[str]) -> None:
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if not spec:
            return
        kind = spec[0]
        if kind in ("ELASTIC", "PLATE", "FOUNDATION") or (len(spec) > 1 and spec[1] == "MAT"):
            self.model.springs += max(len(ids), 1)
            self.report.skip(
                "soil springs generated by STAAD (ELASTIC MAT, PLATE MAT, foundations) not "
                "imported (SAEngine's soil springs come from 9 Substructure)",
                " ".join(tokens[:4]),
            )
            return
        if not ids:
            return
        inclined = kind.startswith("INC")
        if inclined:
            self.report.approximate(
                "inclined supports taken in the global axes", " ".join(str(i) for i in ids[:5])
            )
            spec = [t for t in spec[1:] if _num(t) is None] or ["FIXED"]
            kind = spec[0]
        if kind.startswith("FIX"):
            restraint = [True] * 6
            if "BUT" in spec:
                axis = {"FX": 0, "FY": 2, "FZ": 1, "MX": 3, "MY": 5, "MZ": 4}
                if self.z_up:
                    axis = {"FX": 0, "FY": 1, "FZ": 2, "MX": 3, "MY": 4, "MZ": 5}
                springs: list[str] = []
                after = spec[spec.index("BUT") + 1 :]
                for idx, t in enumerate(after):
                    if t in axis:
                        restraint[axis[t]] = False
                    elif t.startswith("K") and t[1:] in axis:
                        restraint[axis[t[1:]]] = False
                        value = after[idx + 1] if idx + 1 < len(after) else ""
                        springs.append(f"{t} {value}")
                if springs:
                    self.model.springs += len(ids)
                    self.report.skip(
                        "spring supports: the spring directions left free (SAEngine's soil "
                        "springs come from 9 Substructure)",
                        f"{ids[0]}: {' '.join(springs)}",
                    )
        elif kind.startswith("PIN"):
            restraint = [True, True, True, False, False, False]
        else:
            for j in ids:
                self.report.skip("supports not read (enforced, multilinear, ...)", str(j))
            return
        for j in ids:
            self.model.supports[str(j)] = tuple(restraint)

    # ── loads ──

    def new_case(self, number: str, rest: list[str], reference: bool = False) -> None:
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
                loadtype = " ".join(after[:1])
                title = " ".join(after[1:])
        elif "TITLE" in rest:
            title = " ".join(rest[rest.index("TITLE") + 1 :])
        self.case = LoadCase(name=f"{number} {title}".strip())
        self.case.kind = _kind(loadtype, title)
        self.case_key = number
        if reference:
            self.references[number] = self.case
        else:
            self.model.cases[number] = self.case
        self.block = "load"

    def finish_case(self) -> None:
        if self.combination is not None:
            self.model.combinations.append(self.combination)
            self.combination = None
        if self.case is not None and self.case.kind == "other" and self.case.selfweight:
            self.case.kind = "D"
        if self.block.startswith("load") or self.block == "comb":
            self.case = None
            self.case_key = None

    def selfweight(self, tokens: list[str]) -> None:
        assert self.case is not None
        direction = tokens[1] if len(tokens) > 1 else self.vertical()
        factor = _num(tokens[2]) if len(tokens) > 2 else -1.0
        if direction not in ("X", "Y", "Z"):
            direction, factor = self.vertical(), -1.0
        if direction != self.vertical() or factor is None:
            self.report.skip("self-weight not acting vertically", self.case.name)
            return
        if len(tokens) > 3 and tokens[3] not in ("ALL",):
            self.report.approximate(
                "self-weight on part of the model taken on all of it", self.case.name
            )
        self.case.selfweight += -factor

    def add_scaled(self, source: LoadCase, factor: float) -> None:
        assert self.case is not None
        for load in source.loads:
            self.case.loads.append(
                Load(
                    load.kind,
                    load.target,
                    load.value * factor,
                    zrange=load.zrange,
                    length=load.length,
                    xrange=load.xrange,
                    yrange=load.yrange,
                )
            )
        self.case.selfweight += source.selfweight * factor

    def repeat_load(self, tokens: list[str]) -> None:
        assert self.case is not None
        values = [_num(t) for t in tokens]
        if any(v is None for v in values):
            return
        for a, b in zip(values[0::2], values[1::2], strict=False):
            key = str(int(a))  # type: ignore[arg-type]
            source = self.model.cases.get(key)
            if source is None or source is self.case:
                self.report.skip(
                    "REPEAT LOAD of cases that are not read", f"{self.case.name}: {key}"
                )
                continue
            self.add_scaled(source, float(b))  # type: ignore[arg-type]
            if self.case.kind == "other" and source.kind != "other":
                self.case.kind = source.kind

    def reference_data(self, tokens: list[str]) -> None:
        assert self.case is not None
        for a, b in itertools.pairwise(tokens):
            value = _num(b)
            if value is None or not re.match(r"^R\d+$", a):
                continue
            source = self.references.get(a)
            if source is None:
                self.report.skip("reference loads that are not defined", f"{self.case.name}: {a}")
                continue
            self.add_scaled(source, value)
            if self.case.kind == "other" and source.kind != "other":
                self.case.kind = source.kind

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
            elif a in ("MX", "MY", "MZ") and abs(v) > 0:
                moments = True
        if moments:
            self.report.note("loads.joint.moments", self.case.name)
        for j in ids:
            self.case.loads.append(Load("joint", str(j), force.copy()))

    def member_length(self, m: int) -> float:
        """Member ``m``'s length [mm] (0 when unknown)."""
        if m not in self.members:
            return 0.0
        i, j = self.members[m]
        if i not in self.joints or j not in self.joints:
            return 0.0
        return float(np.linalg.norm(self.joints[j] - self.joints[i]))

    def member_load(self, tokens: list[str], physical: bool = False) -> None:
        """A MEMBER LOAD (or PMEMBER LOAD) line: its total over the loaded length, as a uniform
        load per member (or a point load), in SAEngine's axes."""
        assert self.case is not None
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if len(spec) < 3 or not ids:
            return
        kind, dir_token = spec[0], spec[1]
        numbers = [v for v in (_num(t) for t in spec[2:]) if v is not None]
        local = dir_token in ("X", "Y", "Z")
        if self.direction(dir_token) is None and not local:
            self.report.note("loads.member.direction", f"{self.case.name}: {dir_token}")
            return
        if kind.startswith(("UMOM", "UMO", "CMOM", "CMO")):
            self.report.note("loads.member.moments", f"{self.case.name}: {kind}")
            return
        name = self.case.name
        # Per (physical) member: the list of (member, its start station, length) [mm].
        chains: list[list[tuple[int, float, float]]] = []
        for target in ids:
            if physical:
                if target not in self.pmembers:
                    self.report.skip("physical members that are not defined", str(target))
                    continue
                station = 0.0
                chain = []
                for m in self.pmembers[target]:
                    length = self.member_length(m)
                    chain.append((m, station, length))
                    station += length
                chains.append(chain)
            else:
                chains.append([(target, 0.0, self.member_length(target))])
        mm = self.length
        for chain in chains:
            total_length = sum(c[2] for c in chain)
            if total_length <= 0:
                continue
            if kind.startswith("CON"):
                if not numbers:
                    continue
                at = numbers[1] * mm if len(numbers) > 1 else total_length / 2
                at = min(max(at, 0.0), total_length)
                for m, start, length in chain:
                    if start - 1e-6 <= at <= start + length + 1e-6:
                        unit = self.load_vector(m, dir_token, name)
                        if unit is not None:
                            force = unit * (numbers[0] * self.force)
                            self.case.loads.append(Load("point", str(m), force, start=at - start))
                        break
                continue
            # Distributed: intensity w(s) linear from (s1, w1) to (s2, w2), s along the member.
            if kind.startswith("UNI"):
                if not numbers:
                    continue
                w1 = w2 = numbers[0]
                s1 = numbers[1] * mm if len(numbers) > 2 else 0.0
                s2 = numbers[2] * mm if len(numbers) > 2 else total_length
                if len(numbers) == 2:
                    s1, s2 = numbers[1] * mm, total_length
                elif len(numbers) > 2 and numbers[1] == 0 and numbers[2] == 0:
                    s1, s2 = 0.0, total_length
            elif kind.startswith("TRAP"):
                if len(numbers) < 2:
                    continue
                w1, w2 = numbers[0], numbers[1]
                s1 = numbers[2] * mm if len(numbers) >= 4 else 0.0
                s2 = numbers[3] * mm if len(numbers) >= 4 else total_length
            elif kind.startswith("LIN"):
                if len(numbers) < 2:
                    continue
                if len(numbers) >= 3 and abs(numbers[0]) + abs(numbers[1]) == 0:
                    w1 = w2 = numbers[2] / 2  # triangular, peak at mid-length: half on average
                    self.report.note("loads.member.varying", f"{name}: {chain[0][0]}")
                else:
                    w1, w2 = numbers[0], numbers[1]
                s1, s2 = 0.0, total_length
            else:
                self.report.skip("member loads not read", f"{name}: {kind}")
                continue
            s1, s2 = (min(max(s, 0.0), total_length) for s in (s1, s2))
            if s2 < s1:
                s1, s2 = s2, s1
            if s2 - s1 <= 1e-9:
                continue
            if abs(w1 - w2) > 1e-12:
                self.report.note("loads.member.varying", f"{name}: {chain[0][0]}")

            def w_at(
                s: float, w1: float = w1, w2: float = w2, s1: float = s1, s2: float = s2
            ) -> float:
                return w1 + (w2 - w1) * (s - s1) / (s2 - s1)

            for m, start, length in chain:
                a, b = max(s1, start), min(s2, start + length)
                if b - a <= 1e-9:
                    continue
                mean = (w_at(a) + w_at(b)) / 2
                unit = self.load_vector(m, dir_token, name)
                if unit is None:
                    continue
                value = unit * (mean * self.force / (mm / 1000))
                self.case.loads.append(
                    Load("uniform", str(m), value, length=b - a, start=a - start)
                )

    def load_vector(self, m: int, token: str, case_name: str) -> np.ndarray | None:
        """The SAEngine unit vector of a member load direction (projected loads scaled to the
        projected length)."""
        if token in ("X", "Y", "Z"):
            axes = self.local_axes(m)
            if axes is None:
                return None
            return self.axes(*axes["XYZ".index(token)])
        unit = self.direction(token)
        if unit is None:
            return None
        if token.startswith("P"):
            i, j = self.members.get(m, (0, 0))
            if i in self.joints and j in self.joints:
                d = self.axes(*_unit(self.joints[j] - self.joints[i]))
                return unit * math.sqrt(max(0.0, 1.0 - float(d @ unit) ** 2))
        return unit

    def element_load(self, tokens: list[str]) -> None:
        assert self.case is not None
        ids, k = self.id_list(tokens)
        spec = tokens[k:]
        if not spec:
            return
        if spec[0] == "JOINTS" or not ids:
            self.report.skip("element loads not read", f"{self.case.name}: {' '.join(tokens[:3])}")
            return
        kind = spec[0]
        if kind.startswith("PR"):
            unit = self.direction(spec[1]) if len(spec) > 2 else None
            if len(spec) > 1 and spec[1] in ("LX", "LY"):
                self.report.skip("element loads along the plate (LX, LY) not read", self.case.name)
                return
            value = _num(spec[2] if unit is not None else spec[1]) if len(spec) > 1 else None
            if value is None:
                return
            if len([t for t in spec if _num(t) is not None]) > 1:
                self.report.approximate(
                    "partial element pressures taken on the whole element", self.case.name
                )
        elif kind.startswith("TRA"):
            rest = spec[1:]
            unit = self.direction(rest[0]) if rest else None
            if rest and rest[0] in ("LX", "LY"):
                self.report.skip("element loads along the plate (LX, LY) not read", self.case.name)
                return
            if unit is not None:
                rest = rest[1:]
            values = [v for v in (_num(t) for t in rest) if v is not None]
            if not values:
                return
            value = sum(values) / len(values)
            self.report.approximate(
                "varying element pressures (TRAP) taken as their mean", self.case.name
            )
        else:
            self.report.skip("element loads not read", f"{self.case.name}: {kind}")
            return
        pressure = value * self.force / (self.length / 1000) ** 2
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
                current = _canon(t, {"XRANGE": 3, "YRANGE": 3, "ZRANGE": 3, "FLOAD": 4})
                params.setdefault(current, [])
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

        for n in sorted(self.deleted & set(self.members)):
            self.report.approximate("members deleted by DELETE MEMBERS left out", str(n))
        for n, (i, j) in sorted(self.members.items()):
            if n in self.plates or n in self.deleted:
                continue
            section = self.member_section.get(n)
            if section is None:
                self.report.skip("members without a property", str(n))
            releases = self.releases.get(n, (set(), set()))
            if n in self.trusses or self.truss_model:
                both = {"M2", "M3"}
                releases = (releases[0] | both, releases[1] | both)
                self.report.approximate(
                    "truss members analysed as frame members pinned at both ends", str(n)
                )
            m.frames.append(
                Frame(
                    str(n),
                    str(i),
                    str(j),
                    section,
                    material_of(n),
                    rotation=self.frame_rotation(n, section),
                    releases=(frozenset(releases[0]), frozenset(releases[1])),
                )
            )
        for n, nodes in sorted(self.plates.items()):
            t = self.plate_thickness.get(n)
            name = None
            if t is not None:
                name = f"SH{t:g}"
                m.area_sections.setdefault(name, SectionDef(name, thickness=t))
            m.areas.append(Area(str(n), [str(x) for x in nodes], name, material_of(n)))
        if not m.units:
            m.units = "kN, m"

    def frame_rotation(self, n: int, section: str | None) -> float:
        """The builder's angle of member ``n``: STAAD's local axes as SAP2000's angle, folded
        to 0-180° for sections symmetric about both axes (a half turn changes nothing)."""
        angle = self.rotation(n)
        sdef = self.model.sections.get(section or "")
        symmetric = sdef is not None and isinstance(
            sdef.profile,
            o.RectangleProfile
            | o.CircleProfile
            | o.IShapeProfile
            | o.RectangleHollowProfile
            | o.CircleHollowProfile,
        )
        if symmetric:
            angle %= 180
        if abs(angle) < 1e-6 or abs(angle - 360) < 1e-6:
            return 0.0
        return round(angle, 6)


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
