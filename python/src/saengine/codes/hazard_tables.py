"""Table model of the online hazard lookup by site coordinates (alpha 9 track C22).

A code pack may name public web services that give the site's seismic (or wind, snow) hazard
values for a latitude and longitude: the ``hazardLookup`` table. Each provider is data: the
service's name and publisher, its ``https`` endpoint, the query it is sent (templates that may
use only the site's coordinates and the code parameters of :data:`PLACEHOLDERS`), how the
project's risk (occupancy) category and site class become the service's values, and where each
value is in the service's JSON answer, with its unit. The engine
(:mod:`saengine.gis.hazard_lookup`) has no service of its own; a pack without the table, or
without a provider, shows "Enter values by hand".

The lookup is opt-in (the global setting "Allow online hazard lookups", default off) and asks
before every call; only the query below leaves the machine.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, TableModel, _Row

#: The Project Settings fields a provider may fill, with the unit each is kept in. These are
#: SAEngine's settings (not a code's), so any pack's provider fills the same fields.
TARGETS: dict[str, str] = {
    "site.spectral.sds": "g",
    "site.spectral.sd1": "g",
    "site.spectral.sms": "g",
    "site.spectral.sm1": "g",
    "site.spectral.ss": "g",
    "site.spectral.s1": "g",
    "site.spectral.tl": "s",
    "site.spectral.designSpectrum": "g",
    "site.spectral.mcerSpectrum": "g",
    "site.zoneCoefficient": "g",
    "site.windSpeed": "m/s",
    "site.snow.groundLoad": "kN/m²",
}

#: The spectrum targets: (T [s], Sa [g]) points from two arrays of the answer.
SPECTRUM_TARGETS = frozenset({"site.spectral.designSpectrum", "site.spectral.mcerSpectrum"})

#: What a query template may use: the site's coordinates and the code parameters. Nothing else
#: of the project can be put into a request.
PLACEHOLDERS = frozenset({"latitude", "longitude", "riskCategory", "siteClass"})

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class HazardRegion(_Row):
    """A latitude/longitude box the service gives values for (a site outside every box of a
    provider that has boxes is not sent)."""

    name: str = ""
    south: float = Field(ge=-90, le=90)
    north: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    east: float = Field(ge=-180, le=180, description="East edge; below west: the box crosses 180°.")

    @model_validator(mode="after")
    def _ordered(self) -> HazardRegion:
        if self.south > self.north:
            raise ValueError("hazardLookup region: south is above north")
        return self

    def contains(self, latitude: float, longitude: float) -> bool:
        if not self.south <= latitude <= self.north:
            return False
        if self.west <= self.east:
            return self.west <= longitude <= self.east
        return longitude >= self.west or longitude <= self.east


class HazardValue(_Row):
    """One value of the answer: where it is (dotted paths into the JSON answer, the first one
    found is taken) and the factor to the unit of its settings field (:data:`TARGETS`). A
    spectrum (designSpectrum, mcerSpectrum) is two arrays: ``periods`` [s] and ``ordinates``."""

    target: str = Field(description="The settings field it fills (one of TARGETS).")
    label: str = Field(default="", description="How the results name it (SDS, SD1, ...).")
    path: list[str] = Field(
        default_factory=list, description="Dotted paths of a single value; the first found."
    )
    periods: list[str] = Field(default_factory=list, description="Spectrum: periods' paths.")
    ordinates: list[str] = Field(default_factory=list, description="Spectrum: ordinates' paths.")
    unit: str = Field(description="The service's unit of the value, as its documentation says.")
    scale: Positive = Field(
        default=1.0, description="Factor from the service's unit to the settings field's."
    )

    @model_validator(mode="after")
    def _paths(self) -> HazardValue:
        if self.target not in TARGETS:
            raise ValueError(f"hazardLookup: unknown target '{self.target}'")
        if self.target in SPECTRUM_TARGETS:
            if not self.periods or not self.ordinates:
                raise ValueError(f"hazardLookup: {self.target} needs periods and ordinates")
        elif not self.path:
            raise ValueError(f"hazardLookup: {self.target} needs a path")
        return self


class HazardProvider(_Row):
    """A public web service of hazard values by coordinates."""

    id: str = Field(min_length=1)
    kind: Literal["seismic", "wind", "snow", "multi"] = "seismic"
    service: str = Field(min_length=1, description="The service's name, as the consent shows.")
    publisher: str = Field(default="", description="Who runs the service.")
    reference: str = Field(
        default="", description="The code edition the values are for (ASCE 7-22, ...)."
    )
    endpoint: str = Field(description="The https URL the query is sent to.")
    query: dict[str, str] = Field(
        description="Query parameter -> its value, a template of PLACEHOLDERS ({latitude}, "
        "{longitude}, {riskCategory}, {siteClass}) and fixed text."
    )
    format: Literal["json"] = Field(default="json", description="The answer's format.")
    status: dict[str, str] = Field(
        default_factory=dict,
        description="Dotted path -> the value an answer with values has there (else refused).",
    )
    message: list[str] = Field(
        default_factory=list, description="Dotted paths of the service's error message."
    )
    riskCategories: dict[str, str] = Field(
        default_factory=dict,
        description="The project's occupancy (risk) category -> the service's value.",
    )
    siteClasses: dict[str, str] = Field(
        default_factory=dict,
        description="The pack's site class id -> the service's value; a class not listed is "
        "not looked up (it needs a site-specific study, say).",
    )
    values: list[HazardValue] = Field(min_length=1)
    regions: list[HazardRegion] = Field(
        default_factory=list, description="Where the service gives values; empty: anywhere."
    )
    decimals: int = Field(
        default=4, ge=0, le=8, description="Decimals of the coordinates sent (4: about 10 m)."
    )
    timeout: Positive = Field(default=30.0, le=120, description="Seconds before giving up.")
    documentation: str = Field(default="", description="The service's public documentation.")
    terms: str = Field(default="", description="The service's terms of use (a URL or note).")
    inheritable: bool = Field(
        default=False,
        description="False: only the pack whose own data file names the provider uses it (a "
        "pack that extends it, for another country, does not send its sites there).",
    )

    @model_validator(mode="after")
    def _check(self) -> HazardProvider:
        url = urlsplit(self.endpoint)
        if url.scheme != "https" or not url.hostname:
            raise ValueError(f"hazardLookup {self.id}: the endpoint must be an https URL")
        if url.query or url.fragment or "{" in self.endpoint:
            raise ValueError(f"hazardLookup {self.id}: the endpoint takes no query or template")
        for name, template in self.query.items():
            unknown = set(_PLACEHOLDER.findall(template)) - PLACEHOLDERS
            if unknown:
                raise ValueError(
                    f"hazardLookup {self.id}: query {name} uses {', '.join(sorted(unknown))} "
                    f"(only {', '.join(sorted(PLACEHOLDERS))} may be sent)"
                )
        used = {p for t in self.query.values() for p in _PLACEHOLDER.findall(t)}
        if not {"latitude", "longitude"} <= used:
            raise ValueError(f"hazardLookup {self.id}: the query must send the coordinates")
        if "riskCategory" in used and not self.riskCategories:
            raise ValueError(f"hazardLookup {self.id}: riskCategory needs riskCategories")
        if "siteClass" in used and not self.siteClasses:
            raise ValueError(f"hazardLookup {self.id}: siteClass needs siteClasses")
        targets = [v.target for v in self.values]
        if len(set(targets)) != len(targets):
            raise ValueError(f"hazardLookup {self.id}: a target is filled twice")
        return self

    @property
    def host(self) -> str:
        return urlsplit(self.endpoint).hostname or ""


class HazardLookupTable(TableModel):
    """The pack's hazard services by site coordinates (see the module notes)."""

    providers: list[HazardProvider] = Field(default_factory=list)
    manualNote: str = Field(
        default="",
        description="What the engineer does where no provider covers the site (the code's "
        "maps or tool by hand).",
    )

    @model_validator(mode="after")
    def _unique(self) -> HazardLookupTable:
        ids = [p.id for p in self.providers]
        if len(set(ids)) != len(ids):
            raise ValueError("hazardLookup: provider ids must be unique")
        return self


__all__ = [
    "PLACEHOLDERS",
    "SPECTRUM_TARGETS",
    "TARGETS",
    "HazardLookupTable",
    "HazardProvider",
    "HazardRegion",
    "HazardValue",
]
