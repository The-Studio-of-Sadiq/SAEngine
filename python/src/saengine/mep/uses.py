"""The use of each storey, entered once for all the services (07 MEP ``storyUses``).

The plumbing, the HVAC and the electrical services each read a storey's use from their own
BNBC 2020 Part 8 table: the water consumption of Table 8.5.1 (occupancy), the ventilation and
occupant density of Table 8.2.3, and the load densities of Table 8.1.17. 07 MEP's storey-use
table gives a storey one use and, optionally, its population; :func:`with_story_uses` maps
them to the row of each table (:data:`STORY_USES`) for the storeys the table lists:

- an occupied use sets the plumbing story's ``occupancy``, the HVAC story's ``use`` (and
  ``conditioned`` false for parking and storage) and the electrical story's ``use``, adding the
  story to a service that lacks it; the population, when given, is the plumbing's
  ``population`` and the HVAC's ``occupants``. What else a service gives a story (fixtures,
  glazing, lighting, its own area) is kept.
- "roof" and "services" are not occupied: the story is taken out of all three, so that the
  roof is treated the same by every service.

A service that is not set up (no ``plumbing``, ``hvac`` or ``electrical`` section) is not
created. Storeys the table does not list keep what each service gives them.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class StoryUse(NamedTuple):
    label: str
    #: BNBC 2020 Part 8 Table 8.5.1 row (plumbing occupancy).
    plumbing: str | None
    #: Table 8.2.3 row (HVAC use).
    hvac: str | None
    #: Table 8.1.17 row (electrical use).
    electrical: str | None
    #: Air-conditioned by default.
    conditioned: bool = True


STORY_USES: dict[str, StoryUse] = {
    "residential": StoryUse("Residential flats", "residentialFlat", "livingArea", "residenceMulti"),
    "office": StoryUse("Offices", "office", "officeSpace", "office"),
    "retail": StoryUse("Shops", "shop", "sales", "departmentStore"),
    "supermarket": StoryUse("Supermarket", "largeShop", "supermarket", "departmentStore"),
    "restaurant": StoryUse("Restaurant", "assemblySmall", "diningRoom", "restaurant"),
    "hotel": StoryUse("Hotel rooms", "hotel", "hotelBedroom", "hotel"),
    "hospital": StoryUse("Hospital wards", "hospital", "patientRoom", "hospital"),
    "school": StoryUse("School classrooms", "school", "classroom9plus", "school"),
    "bank": StoryUse("Bank", "office", "officeSpace", "bank"),
    "assembly": StoryUse("Assembly hall", "assemblyLarge", "multiuseAssembly", "office"),
    "industrial": StoryUse("Light industry", "industryLow", "woodMetalShop", "industrial"),
    "storage": StoryUse("Storage", "storageLow", "warehouse", "warehouse", conditioned=False),
    "parking": StoryUse("Parking", "parking", "parkingGarage", "parking", conditioned=False),
    "services": StoryUse("Services, plant (not occupied)", None, None, None, conditioned=False),
    "roof": StoryUse("Roof (not occupied)", None, None, None, conditioned=False),
}
STORY_USE_KEYS = tuple(STORY_USES)


def occupied(use: str) -> bool:
    """Whether a storey of this use holds people (the roof and plant storeys do not)."""
    return STORY_USES[use].plumbing is not None


def _upsert(stories: list[Any], story: str, fields: dict[str, Any], cls: Any) -> list[Any]:
    out, found = [], False
    for entry in stories:
        if entry.story == story:
            entry = entry.model_copy(update=fields)
            found = True
        out.append(entry)
    if not found:
        out.append(cls.model_validate({"story": story, **fields}))
    return out


def with_story_uses(mep: Any) -> Any:
    """A copy of ``mep`` (a :class:`saengine.library.mep.MepModel`) whose plumbing, HVAC and
    electrical stories follow its ``storyUses`` (see the module's docstring); ``mep`` itself
    when the table is empty."""
    from saengine.library.mep import ElectricalStory, HvacStory, PlumbingStory

    uses = getattr(mep, "storyUses", None) or []
    if not uses:
        return mep
    plumbing, hvac, electrical = mep.plumbing, mep.hvac, mep.electrical
    p_stories = list(plumbing.stories) if plumbing is not None else []
    h_stories = list(hvac.stories) if hvac is not None else []
    e_stories = list(electrical.stories) if electrical is not None else []
    for entry in uses:
        row = STORY_USES[entry.use]
        if not occupied(entry.use):
            p_stories = [s for s in p_stories if s.story != entry.story]
            h_stories = [s for s in h_stories if s.story != entry.story]
            e_stories = [s for s in e_stories if s.story != entry.story]
            continue
        people = {} if entry.population is None else {"population": entry.population}
        if plumbing is not None:
            fields = {"occupancy": row.plumbing, **people}
            p_stories = _upsert(p_stories, entry.story, fields, PlumbingStory)
        if hvac is not None:
            fields = {"use": row.hvac}
            if not any(s.story == entry.story for s in h_stories):
                fields["conditioned"] = row.conditioned
            if entry.population is not None:
                fields["occupants"] = entry.population
            h_stories = _upsert(h_stories, entry.story, fields, HvacStory)
        if electrical is not None:
            e_stories = _upsert(e_stories, entry.story, {"use": row.electrical}, ElectricalStory)
    update: dict[str, Any] = {}
    if plumbing is not None:
        update["plumbing"] = plumbing.model_copy(update={"stories": p_stories})
    if hvac is not None:
        update["hvac"] = hvac.model_copy(update={"stories": h_stories})
    if electrical is not None:
        update["electrical"] = electrical.model_copy(update={"stories": e_stories})
    return mep.model_copy(update=update) if update else mep
