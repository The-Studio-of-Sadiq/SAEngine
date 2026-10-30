"""The rooms of the architecture as inputs of the building services: the one place they are
turned into fixture counts, population, occupancy and HVAC room groups.

The rooms are those of ``05 Floor Plan/architecture.json``; their outlines are
:func:`saengine.library.architecture.room_boundary`'s (the same faces the loads and the bill
use, never worked out again) and their uses the code pack's area uses (the same keys as their
live loads).

- **Fixtures** (plumbing, BNBC 2020 Part 8 Appendix O and Sec 6.10): every room with the wet flag
  is a kind of wet room (toilet, kitchen, ...), found from its name or given in 07 MEP
  ``plumbing.wetRooms``; each kind holds the fixtures of ``plumbing.roomFixtures``, else
  SAEngine's defaults (:data:`saengine.plumbing.tables.DEFAULT_ROOM_FIXTURES`). A story's
  counts are its wet rooms' added up.
- **Which counts are used**: a story's ``fixturesFrom`` in 07 MEP. Auto (the default) takes the
  counts typed in 07 MEP when any is given (they override the rooms), else the rooms'. The
  report says which, story by story (:attr:`StoryRooms.source`).
- **Occupancy** (Table 8.5.1): a story typed in 07 MEP keeps its row; one only the rooms give
  takes the row of its largest rooms' area use (:data:`AREA_USE_OCCUPANCY`).
- **Population** (Sec 5.6.3-5.6.4), when 07 MEP gives none: dwellings by their kitchens (as
  before, from the rooms' kitchen sinks), offices from the office rooms' net floor instead of
  the slabs', other uses from Table 8.2.3's occupant density over the rooms' net floor.
- **HVAC** (Table 8.2.3): each room's use (:data:`AREA_USE_HVAC`, refined by the room's name:
  kitchens, toilets, corridors), grouped per story; :func:`saengine.hvac.gains.room_gains`
  turns the groups into the story zone's occupants, gains and outdoor air.

:func:`with_rooms` gives the 07 MEP model with each story's fixtures, occupancy and population
resolved, so the sizing, the hydraulics, the bill and the HVAC all read the same counts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from saengine.plumbing import tables as T

#: m² per mm².
MM2 = 1e-6

#: The code pack's area uses (BNBC Table 6.2.3 rows of ``areaLoads``) as rows of Part 8 Table
#: 8.5.1 (water consumption). Uses with no water of their own (corridors, stairs, roofs) are
#: left out: they never decide a story's occupancy.
AREA_USE_OCCUPANCY: dict[str, str] = {
    "residential": "residentialFlat",
    "residentialPublic": "residentialFlat",
    "office": "office",
    "officeLobby": "office",
    "classroom": "school",
    "hospitalWard": "hospital",
    "operatingRoom": "hospital",
    "assemblyFixed": "assemblySmall",
    "assemblyMovable": "assemblySmall",
    "retailGround": "shop",
    "retailUpper": "shop",
    "storageLight": "storageLow",
    "storageHeavy": "storageModerate",
    "parking": "parking",
}

#: The code pack's area uses as rows of Part 8 Table 8.2.3 (ventilation and occupant density).
#: Roofs are outdoors: no HVAC use.
AREA_USE_HVAC: dict[str, str] = {
    "residential": "livingArea",
    "residentialPublic": "corridor",
    "office": "officeSpace",
    "officeLobby": "entryLobby",
    "corridorAbove": "corridor",
    "classroom": "classroom9plus",
    "hospitalWard": "patientRoom",
    "operatingRoom": "operatingRoom",
    "assemblyFixed": "auditorium",
    "assemblyMovable": "multiuseAssembly",
    "retailGround": "sales",
    "retailUpper": "sales",
    "storageLight": "warehouse",
    "storageHeavy": "warehouse",
    "parking": "parkingGarage",
    "stairs": "corridor",
}

_WORDS = {
    "public": r"public|common|gents|ladies|male|female|men|women|staff",
    "toilet": r"toilet|bath|w\.?c|washroom|restroom|lavatory|shower|t/?b",
    "half": r"powder|half|guest\s*w\.?c",
    "kitchen": r"kitchen\w*|kit|pantry|cook\w*",
    "laundry": r"laundry|utility|washing",
    "corridor": r"corridor|passage|lobby|hall\s*way|landing|stair\w*|circulation",
    "shaft": r"shaft|duct|service",
    "meeting": r"conference|meeting|board\s*room",
    "store": r"store|storage",
}


def _has(name: str, words: str) -> bool:
    return re.search(rf"(?<![a-z])({words})(?![a-z])", name.lower()) is not None


def wet_kind(name: str) -> str:
    """The kind of a wet room (:data:`saengine.plumbing.tables.WET_ROOM_KINDS`) from its
    name; a name that says nothing is an other wet area (a floor drain)."""
    if _has(name, _WORDS["half"]):
        return "halfBath"
    if _has(name, _WORDS["toilet"]):
        return "publicToilet" if _has(name, _WORDS["public"]) else "toilet"
    if _has(name, _WORDS["kitchen"]):
        return "kitchen"
    if _has(name, _WORDS["laundry"]):
        return "laundry"
    return "wetArea"


def is_circulation(name: str, use: str | None) -> bool:
    """A corridor, lobby or stair: where services are run first."""
    return use in ("corridorAbove", "officeLobby", "residentialPublic", "stairs") or _has(
        name, _WORDS["corridor"]
    )


def is_shaft(name: str) -> bool:
    return _has(name, _WORDS["shaft"])


@dataclass
class MepRoom:
    """A room of the architecture as the services see it."""

    id: str
    story: str
    name: str
    number: str
    use: str | None  # the code pack's area use
    wet: bool
    face: Any  # shapely Polygon: the wall centre lines around it
    net: Any  # shapely Polygon: its net floor
    area: float  # net floor [m²]
    kind: str | None = None  # wet rooms: WET_ROOM_KINDS
    kindFrom: str = ""  # "name" or "07 MEP"
    fixtures: dict[str, int] = field(default_factory=dict)
    hvacUse: str | None = None

    @property
    def label(self) -> str:
        return f"{self.number} {self.name}".strip()

    @property
    def circulation(self) -> bool:
        return is_circulation(self.name, self.use)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "story": self.story, "name": self.name, "number": self.number,
            "use": self.use, "wet": self.wet, "area": round(self.area, 2), "kind": self.kind,
            "kindFrom": self.kindFrom, "fixtures": self.fixtures, "hvacUse": self.hvacUse,
            "outline": [[round(x, 1), round(y, 1)] for x, y in self.net.exterior.coords[:-1]],
        }  # fmt: skip


@dataclass
class StoryRooms:
    """What a story's rooms give the services."""

    story: str
    rooms: list[MepRoom] = field(default_factory=list)
    fixtures: dict[str, int] = field(default_factory=dict)  # the wet rooms' counts, added up
    occupancy: str | None = None  # Table 8.5.1 row of the largest rooms' area use
    #: "rooms", "typed" or "none": where the story's fixtures come from (set by with_rooms)
    source: str = "none"
    population: float | None = None
    populationSource: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def wet(self) -> list[MepRoom]:
        return [r for r in self.rooms if r.kind is not None]

    def area_of(self, occupancy: str) -> float:
        """Net floor of the rooms whose use is that Table 8.5.1 row [m²]."""
        return sum(r.area for r in self.rooms if AREA_USE_OCCUPANCY.get(r.use or "") == occupancy)

    def hvac_groups(self) -> list[dict[str, Any]]:
        """The rooms grouped by their Table 8.2.3 use: ``[{use, area (m²), rooms: [ids]}]``,
        the largest first."""
        groups: dict[str, dict[str, Any]] = {}
        for room in self.rooms:
            if room.hvacUse is None:
                continue
            g = groups.setdefault(room.hvacUse, {"use": room.hvacUse, "area": 0.0, "rooms": []})
            g["area"] += room.area
            g["rooms"].append(room.id)
        return sorted(groups.values(), key=lambda g: -g["area"])


@dataclass
class RoomInputs:
    """The rooms of a project by story, with what they give the services."""

    stories: dict[str, StoryRooms] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def rooms(self) -> list[MepRoom]:
        return [r for s in self.stories.values() for r in s.rooms]

    def story(self, story: str) -> StoryRooms | None:
        return self.stories.get(story)


def _hvac_use(room: MepRoom, residential: bool) -> str | None:
    """A room's Table 8.2.3 use: its kind or name first (kitchens, toilets, corridors), then
    its area use."""
    if room.kind in ("toilet", "halfBath"):
        return "dwellingToilet" if residential else "publicToilet"
    if room.kind == "publicToilet":
        return "publicToilet"
    if room.kind == "kitchen":
        return "dwellingKitchen" if residential else "kitchenCooking"
    if room.kind == "laundry":
        return "laundryStorage"
    if is_shaft(room.name):
        return None
    if room.circulation:
        return "entryLobby" if room.use == "officeLobby" else "corridor"
    if _has(room.name, _WORDS["meeting"]):
        return "conferenceRoom"
    if _has(room.name, _WORDS["store"]) and room.use not in ("storageLight", "storageHeavy"):
        return "storageRoom"
    if room.use in AREA_USE_HVAC:
        return AREA_USE_HVAC[room.use]
    return None


def _fixtures_of(kind: str, plumbing: Any) -> dict[str, int]:
    for entry in getattr(plumbing, "roomFixtures", None) or []:
        if entry.kind == kind:
            return _counts(entry.fixtures)
    return dict(T.DEFAULT_ROOM_FIXTURES[kind])


def kind_fixtures(plumbing: Any) -> dict[str, dict[str, Any]]:
    """Each kind of wet room with its label, the fixtures it holds in this project and whether
    the project gives them (else SAEngine's defaults), for the editor."""
    own = {e.kind for e in getattr(plumbing, "roomFixtures", None) or []}
    return {
        kind: {"label": label, "fixtures": _fixtures_of(kind, plumbing), "project": kind in own}
        for kind, label in T.WET_ROOM_KINDS.items()
    }


def _counts(fixtures: Any) -> dict[str, int]:
    from saengine.plumbing.demand import FIXTURES

    return {k: int(getattr(fixtures, k)) for k in FIXTURES if getattr(fixtures, k)}


def room_inputs(arch: Any, bim: Any, plumbing: Any = None) -> RoomInputs:
    """The rooms of ``arch`` (an Architecture) on the stories of ``bim`` (a BuildingModel),
    with their kinds and fixtures from ``plumbing`` (07 MEP's, for its room settings)."""
    from saengine.library import architecture as arch_lib

    out = RoomInputs()
    if arch is None or bim is None or not arch.rooms:
        return out
    elevations = {s.id: s.elevation for s in bim.stories}
    own = {w.room: w for w in (getattr(plumbing, "wetRooms", None) or [])}
    for room in arch.rooms:
        if room.story not in elevations:
            out.notes.append(f"{room.id}: no story '{room.story}' in 06 BIM; not used")
            continue
        found = arch_lib.room_boundary(arch, room, elevations)
        if found is None:
            out.notes.append(f"{room.id}: not enclosed by walls or separators; not used")
            continue
        face, net = found
        item = MepRoom(
            room.id, room.story, room.name, room.number, room.occupancy, room.wet, face, net,
            net.area * MM2,
        )  # fmt: skip
        if room.wet:
            setting = own.get(room.id)
            if setting is not None and setting.kind is not None:
                item.kind, item.kindFrom = setting.kind, "07 MEP"
            else:
                item.kind, item.kindFrom = wet_kind(room.name), "name"
            if setting is not None and setting.fixtures is not None:
                item.fixtures = _counts(setting.fixtures)
            else:
                item.fixtures = _fixtures_of(item.kind, plumbing)
        elif _has(room.name, _WORDS["kitchen"]) or _has(room.name, _WORDS["toilet"]):
            out.notes.append(
                f"{item.label or room.id} ({room.story}): not marked wet in the architecture; "
                "no fixtures counted"
            )
        out.stories.setdefault(room.story, StoryRooms(room.story)).rooms.append(item)
    for story in out.stories.values():
        for room in story.wet:
            for key, count in room.fixtures.items():
                story.fixtures[key] = story.fixtures.get(key, 0) + count
        areas: dict[str, float] = {}
        for room in story.rooms:
            occupancy = AREA_USE_OCCUPANCY.get(room.use or "")
            if occupancy is not None:
                areas[occupancy] = areas.get(occupancy, 0.0) + room.area
        if areas:
            story.occupancy = max(areas, key=lambda k: areas[k])
        residential = (
            T.OCCUPANCIES[story.occupancy].group.startswith("A") if story.occupancy else True
        )
        for room in story.rooms:
            room.hvacUse = _hvac_use(room, residential)
    return out


def _population(entry: Any, story: StoryRooms) -> tuple[float | None, str]:
    """A story's persons from its rooms when 07 MEP gives none: None for dwellings (their
    kitchens give them, :func:`saengine.plumbing.demand.story_population`)."""
    from saengine.hvac import tables as H

    row = T.OCCUPANCIES[entry.occupancy]
    if row.group.startswith("A") and row.unit == "person":
        return None, ""
    if row.group == "E1":
        area = story.area_of(entry.occupancy)
        if area > 0:
            return area / T.OFFICE_AREA_PER_PERSON, (
                f"{area:.0f} m² of office rooms / {T.OFFICE_AREA_PER_PERSON} m² per person "
                f"({T.PAGES['5.6.3']})"
            )
        return None, ""
    people = 0.0
    parts = []
    for group in story.hvac_groups():
        density = H.VENTILATION[group["use"]].density
        if density:
            people += density * group["area"] / 100.0
            parts.append(f"{group['area']:.0f} m² x {density:g}/100 m²")
    if people <= 0:
        return None, ""
    return people, f"{' + '.join(parts)} (Part 8 Table 8.2.3 occupant density of the rooms)"


def _typed(entry: Any) -> bool:
    fixtures = entry.fixtures
    return bool(_counts(fixtures)) or any(o.count for o in fixtures.other)


def with_rooms(mep: Any, inputs: RoomInputs | None) -> tuple[Any, list[dict[str, Any]]]:
    """``mep`` (a MepModel) with each plumbing story's fixtures, occupancy and population taken
    from the rooms where they are used (:attr:`StoryRooms.source`), and stories the rooms add;
    and the source of each story's fixtures for the report: ``[{story, source, rooms,
    fromRooms, typed, occupancy, population, populationSource, note}]``. The model is returned
    unchanged without plumbing or rooms."""
    from saengine.library.mep import Fixtures, PlumbingStory

    plumbing = mep.plumbing
    if plumbing is None or inputs is None or not inputs.stories:
        rows = []
        for entry in plumbing.stories if plumbing is not None else []:
            rows.append(_row(entry.story, "typed", None, entry, entry.population, ""))
        return mep, rows
    entries = {e.story: e for e in plumbing.stories}
    order = [e.story for e in plumbing.stories] + [s for s in inputs.stories if s not in entries]
    stories = []
    rows = []
    for name in order:
        entry = entries.get(name)
        rooms = inputs.story(name)
        if entry is None:
            if rooms is None or not rooms.wet:
                continue  # rooms without wet rooms give a story no plumbing of its own
            entry = PlumbingStory(story=name, occupancy=rooms.occupancy or "residentialFlat")
            occupancy_note = (
                f"occupancy {T.OCCUPANCIES[entry.occupancy].label} from the rooms' area use"
                if rooms.occupancy
                else "occupancy: the rooms give no area use; moderate apartment taken"
            )
        else:
            occupancy_note = ""
        wanted = entry.fixturesFrom
        use_rooms = (
            rooms is not None
            and bool(rooms.wet)
            and (wanted == "rooms" or (wanted == "auto" and not _typed(entry)))
        )
        update: dict[str, Any] = {}
        note = occupancy_note
        if use_rooms:
            assert rooms is not None
            update["fixtures"] = Fixtures(**rooms.fixtures)
            source = "rooms"
        else:
            source = "typed" if _typed(entry) or rooms is None or not rooms.wet else "none"
            if wanted == "rooms":
                note = "fixtures from the rooms asked for, but the story has no wet rooms"
            elif rooms is not None and rooms.wet:
                note = (
                    f"the typed counts override the {len(rooms.wet)} wet room(s) "
                    "of the architecture"
                )
        population, population_source = entry.population, ""
        if entry.population is None and rooms is not None:
            population, population_source = _population(entry, rooms)
            if population is not None:
                update["population"] = round(population, 1)
        resolved = entry.model_copy(update=update) if update else entry
        stories.append(resolved)
        if rooms is not None:
            rooms.source = source
            rooms.population, rooms.populationSource = population, population_source
        rows.append(_row(name, source, rooms, entry, population, population_source, note))
    new = plumbing.model_copy(update={"stories": stories})
    return mep.model_copy(update={"plumbing": new}), rows


def _row(
    story: str,
    source: str,
    rooms: StoryRooms | None,
    entry: Any,
    population: float | None,
    population_source: str,
    note: str = "",
) -> dict[str, Any]:
    typed = _counts(entry.fixtures) if entry is not None else {}
    return {
        "story": story,
        "source": source,
        "rooms": [r.id for r in rooms.wet] if rooms is not None else [],
        "fromRooms": dict(rooms.fixtures) if rooms is not None else {},
        "typed": typed,
        "occupancy": entry.occupancy if entry is not None else None,
        "population": population,
        "populationSource": population_source
        or ("entered" if entry is not None and entry.population is not None else ""),
        "note": note,
    }


# ─────────────────────────────────────── files ───────────────────────────────────────


@lru_cache(maxsize=8)
def _parsed(arch_text: str, bim_text: str, plumbing_json: str) -> RoomInputs:
    from saengine.library import architecture as arch_lib
    from saengine.library.bim import BuildingModel
    from saengine.library.mep import Plumbing

    arch = arch_lib.parse(arch_text)
    bim = BuildingModel.model_validate_json(bim_text)
    plumbing = Plumbing.model_validate_json(plumbing_json) if plumbing_json else None
    return room_inputs(arch, bim, plumbing)


def read_room_inputs(root: str | Path, plumbing: Any = None) -> tuple[RoomInputs | None, str]:
    """The room inputs of a project (``plumbing``: 07 MEP's, for its room settings), and a
    problem ("" when none, or when the project has no architecture). Kept for the same files,
    so the sizing, the hydraulics and the HVAC of one report work them out once."""
    from saengine.library import architecture as arch_lib

    root = Path(root)
    try:
        arch_text = (root / arch_lib.ARCHITECTURE_FILE).read_text(encoding="utf-8")
        bim_text = (root / "06 BIM/bim.json").read_text(encoding="utf-8")
    except OSError:
        return None, ""
    plumbing_json = plumbing.model_dump_json() if plumbing is not None else ""
    try:
        inputs = _parsed(arch_text, bim_text, plumbing_json)
    except ValueError as error:
        return None, f"{arch_lib.ARCHITECTURE_FILE}: not read for the services ({error})"
    # Copies: with_rooms sets each story's source and population on its StoryRooms.
    return _copy(inputs), ""


def _copy(inputs: RoomInputs) -> RoomInputs:
    return RoomInputs(
        {
            k: StoryRooms(s.story, list(s.rooms), dict(s.fixtures), s.occupancy)
            for k, s in inputs.stories.items()
        },
        list(inputs.notes),
    )


def stamp(root: str | Path) -> str:
    """The stamp of the architecture file the rooms come from ("" without one)."""
    from saengine.library import architecture as arch_lib

    try:
        text = (Path(root) / arch_lib.ARCHITECTURE_FILE).read_text(encoding="utf-8")
    except OSError:
        return ""
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
