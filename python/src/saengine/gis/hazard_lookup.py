"""Online hazard lookup by the site's coordinates (alpha 9 track C22).

The code pack names the services (its ``hazardLookup`` table,
:class:`saengine.codes.hazard_tables.HazardLookupTable`); this module only builds the query a
provider describes, sends it, and reads the values out of the answer where the provider says
they are. Nothing here knows a service or a code:

- :func:`offers`: the providers of the project's pack that cover the site, each with the exact
  query that would be sent (no network): what the consent shows;
- :func:`lookup`: sends that query (only the coordinates and the code parameters) and returns
  the values with the record to keep in the project (``site.hazardSource``); refuses without
  the caller's ``consent``;
- :func:`apply`: the settings with the values put into their fields (the UI applies them the
  same way after showing them);
- :func:`source_rows`: the report's lines naming the service, date and query.

The request goes out by the standard library (``urllib``) with a timeout and a user agent that
names SAEngine; no cookie, no project data. Offline or a failed answer: a clear message, and
nothing changes.
"""

from __future__ import annotations

import itertools
import json
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from saengine import __version__

# The table models first: hazard_tables is imported by them (it builds on their base models).
from saengine.codes import tables as _tables  # noqa: F401
from saengine.codes.hazard_tables import (
    SPECTRUM_TARGETS,
    TARGETS,
    HazardLookupTable,
    HazardProvider,
)

TABLE = "hazardLookup"
SOIL_FILE = "01 Soil Report/soil-report.json"

#: The user agent of every request: SAEngine, its version and where it comes from.
USER_AGENT = (
    f"SAEngine/{__version__} (structural engineering; site hazard lookup; "
    "+https://github.com/The-Studio-of-Sadiq/SAEngine)"
)

#: The largest answer read [bytes]: a hazard answer is a few kB; more is not a hazard answer.
MAX_ANSWER = 2_000_000

#: ``opener(request, timeout)`` -> the answer's bytes: urllib by default, a stub in the tests.
Opener = Callable[[urllib.request.Request, float], bytes]

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class LookupError_(Exception):
    """A lookup that gave no values, with a message for the engineer (``code`` says why)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ───────────────────────────── the project's side ─────────────────────────────


def _pack(settings: dict[str, Any], root: str | Path | None) -> Any:
    """The pack the settings choose, WITHOUT the project's code value overrides: a project file
    cannot redirect a provider's endpoint or query (only the pack itself names them)."""
    from saengine.codes import context as code_context
    from saengine.codes import registry

    base = code_context.find_project_root(root) if root else None
    return registry.load(registry.active_id(settings), base)


def _table(pack: Any) -> HazardLookupTable | None:
    if not pack.has(TABLE):
        return None
    table = pack.table(TABLE)
    return table if isinstance(table, HazardLookupTable) else None


def providers(pack: Any) -> list[HazardProvider]:
    """The pack's providers it may use: its own, and inherited ones marked ``inheritable``
    (a pack that extends the US pack for another country does not send its sites to USGS)."""
    table = _table(pack)
    if table is None:
        return []
    own = pack.provided_by(TABLE) == pack.id
    return [p for p in table.providers if own or p.inheritable]


def coordinates(
    soil_text: str | None = None, root: str | Path | None = None
) -> tuple[float, float] | None:
    """(latitude, longitude) of the site point of 1 Soil Report (``site.lat``/``lon``, the
    site map), from ``soil_text`` (unsaved edits) or the project's file; None without one."""
    text = soil_text
    if text is None and root:
        path = Path(root) / SOIL_FILE
        text = path.read_text(encoding="utf-8") if path.is_file() else None
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    site = data.get("site") if isinstance(data, dict) else None
    if not isinstance(site, dict):
        return None
    lat, lon = site.get("lat"), site.get("lon")
    if not _is_number(lat) or not _is_number(lon):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def code_parameters(settings: dict[str, Any], soil_text: str | None) -> dict[str, str]:
    """The project's risk (occupancy) category and the site class the analysis uses (from the
    soil report where its source says so), as the pack names them. Settings that do not
    validate: their values as typed, else the settings model's defaults."""
    from pydantic import ValidationError

    from saengine.library.settings import Occupancy, ProjectSettings, Site, resolve_site_class

    occupancy = settings.get("occupancy") if isinstance(settings.get("occupancy"), dict) else {}
    site = settings.get("site") if isinstance(settings.get("site"), dict) else {}
    category = str(occupancy.get("category") or Occupancy.model_fields["category"].default)
    site_class = str(site.get("siteClass") or Site.model_fields["siteClass"].default)
    try:
        model = ProjectSettings.model_validate(settings)
    except ValidationError:
        return {"riskCategory": category, "siteClass": site_class}
    _, info = resolve_site_class(model, soil_text)
    return {
        "riskCategory": str(model.occupancy.category),
        "siteClass": str(info.get("class") or model.site.siteClass),
    }


# ───────────────────────────── the query ─────────────────────────────


def build_query(
    provider: HazardProvider, latitude: float, longitude: float, params: dict[str, str]
) -> tuple[str, dict[str, str]]:
    """(the request URL, its query) of ``provider`` for the site: the templates filled with
    the coordinates (rounded to the provider's decimals) and the code parameters in the
    service's words. Raises :class:`LookupError_` where the site or a parameter is not one the
    service takes."""
    if provider.regions and not any(r.contains(latitude, longitude) for r in provider.regions):
        names = ", ".join(r.name for r in provider.regions if r.name)
        raise LookupError_(
            "outsideRegion",
            f"{provider.service} gives values only for sites in "
            f"{names or 'its own region'}; the site ({latitude:.4f}, {longitude:.4f}) is outside. "
            "Enter the values by hand.",
        )
    fill: dict[str, str] = {
        "latitude": f"{round(latitude, provider.decimals):.{provider.decimals}f}",
        "longitude": f"{round(longitude, provider.decimals):.{provider.decimals}f}",
    }
    used = {p for t in provider.query.values() for p in _PLACEHOLDER.findall(t)}
    if "riskCategory" in used:
        value = provider.riskCategories.get(params.get("riskCategory", ""))
        if value is None:
            raise LookupError_(
                "riskCategory",
                f"{provider.service} takes no risk category for occupancy category "
                f"{params.get('riskCategory') or '(none)'}.",
            )
        fill["riskCategory"] = value
    if "siteClass" in used:
        value = provider.siteClasses.get(params.get("siteClass", ""))
        if value is None:
            raise LookupError_(
                "siteClass",
                f"{provider.service} gives no values for site class "
                f"{params.get('siteClass') or '(none)'} (a site-specific study, or values by "
                "hand).",
            )
        fill["siteClass"] = value
    query = {
        name: _PLACEHOLDER.sub(lambda m: fill[m.group(1)], template)
        for name, template in provider.query.items()
    }
    return f"{provider.endpoint}?{urlencode(query)}", query


class _SameHostHttps(urllib.request.HTTPRedirectHandler):
    """Redirects stay on the provider's host and on https (an ``http://`` location of the same
    host is followed as ``https://``): the coordinates go nowhere else, never in clear."""

    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.hostname or "") != self.host or target.scheme not in ("http", "https"):
            raise urllib.error.URLError(f"the service redirected to another site ({newurl})")
        if target.scheme == "http":
            newurl = urlunsplit(target._replace(scheme="https"))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, timeout: float, opener: Opener | None = None) -> bytes:
    """The answer to a GET of ``url``: urllib with ``timeout`` and :data:`USER_AGENT` (no
    cookies, no other header); ``opener`` replaces the network (the tests). Raises
    :class:`LookupError_` for no network, a timeout or an HTTP error."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, method="GET"
    )
    try:
        if opener is not None:
            return opener(request, timeout)
        host = urlsplit(url).hostname or ""
        network = urllib.request.build_opener(_SameHostHttps(host))
        with network.open(request, timeout=timeout) as answer:
            return answer.read(MAX_ANSWER + 1)
    except urllib.error.HTTPError as error:
        body = b""
        try:
            body = error.read(MAX_ANSWER)
        except Exception:  # noqa: BLE001, S110 - the status is enough
            pass
        detail = _error_text(body)
        raise LookupError_(
            "http", f"The service answered {error.code} {error.reason}{detail}."
        ) from error
    except TimeoutError as error:
        raise LookupError_(
            "timeout", f"The service did not answer within {timeout:g} s (offline or busy)."
        ) from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, TimeoutError | socket.timeout):
            raise LookupError_(
                "timeout", f"The service did not answer within {timeout:g} s (offline or busy)."
            ) from error
        raise LookupError_(
            "offline", f"The service could not be reached ({reason}): no network connection?"
        ) from error
    except OSError as error:
        raise LookupError_("offline", f"The service could not be reached ({error}).") from error


def _error_text(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ""
    for key in ("message", "error", "detail"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, str) and value.strip():
            return f": {value.strip()[:300]}"
    return ""


# ───────────────────────────── the answer ─────────────────────────────


def _at(data: Any, path: str) -> Any:
    """The value at a dotted path (``response.data.sds``; a number names a list item)."""
    node = data
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return None
    return node


def _first(data: Any, paths: list[str]) -> Any:
    for path in paths:
        value = _at(data, path)
        if value is not None:
            return value
    return None


def parse(provider: HazardProvider, raw: bytes) -> dict[str, Any]:
    """The values of an answer, settings field -> value in the field's unit (a spectrum: its
    (T, Sa) points); a value the answer lacks, or that is not a positive number, is left out.
    Raises :class:`LookupError_` for an answer that is not JSON, that the provider's ``status``
    marks as failed, or that gives none of the values."""
    if len(raw) > MAX_ANSWER:
        raise LookupError_("answer", "The service's answer is too large to be a hazard answer.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise LookupError_("answer", "The service's answer is not JSON.") from error
    for path, wanted in provider.status.items():
        found = _at(data, path)
        if str(found) != wanted:
            message = _first(data, provider.message)
            raise LookupError_(
                "refused",
                f"{provider.service} gave no values"
                + (f": {str(message)[:300]}" if message else f" ({path} is {found!r})")
                + ".",
            )
    out: dict[str, Any] = {}
    for spec in provider.values:
        if spec.target in SPECTRUM_TARGETS:
            periods, ordinates = _first(data, spec.periods), _first(data, spec.ordinates)
            points = _spectrum(periods, ordinates, spec.scale)
            if points:
                out[spec.target] = points
            continue
        value = _first(data, spec.path)
        if _is_number(value) and value > 0:
            out[spec.target] = round(float(value) * spec.scale, 6)
    if not out:
        raise LookupError_("empty", f"{provider.service} gave none of the values for this site.")
    return out


def _spectrum(periods: Any, ordinates: Any, scale: float) -> list[list[float]]:
    """(T, Sa) points of two arrays of equal length; [] where they are not."""
    if not isinstance(periods, list) or not isinstance(ordinates, list):
        return []
    if len(periods) != len(ordinates) or len(periods) < 2:
        return []
    points: list[list[float]] = []
    for t, sa in zip(periods, ordinates, strict=True):
        if not _is_number(t) or not _is_number(sa) or t < 0 or sa < 0:
            return []
        points.append([round(float(t), 6), round(float(sa) * scale, 6)])
    if any(b[0] <= a[0] for a, b in itertools.pairwise(points)):
        return []  # periods must increase
    return points


# ───────────────────────────── the calls ─────────────────────────────


def _settings_of(settings_text: str | None) -> dict[str, Any]:
    try:
        data = json.loads(settings_text) if settings_text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _offer(provider: HazardProvider, pack: Any) -> dict[str, Any]:
    return {
        "id": provider.id,
        "kind": provider.kind,
        "service": provider.service,
        "publisher": provider.publisher,
        "reference": provider.reference,
        "host": provider.host,
        "endpoint": provider.endpoint,
        "documentation": provider.documentation,
        "terms": provider.terms,
        "timeout": provider.timeout,
        "targets": [
            {"target": v.target, "label": v.label or v.target.rsplit(".", 1)[-1]}
            for v in provider.values
        ],
        "codePack": pack.id,
    }


def offers(
    settings_text: str | None,
    soil_text: str | None = None,
    root: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """What a lookup would do, with no network: ``{ok, codePack, coordinates, params,
    providers: [{id, service, publisher, host, documentation, terms, targets, url, query,
    problem}], manualNote}``. ``url``/``query`` are exactly what would be sent; ``problem``
    why a provider cannot be asked for this site (outside its region, a site class it does not
    take). Coordinates: ``latitude``/``longitude`` (the wizard), else 1 Soil Report's site."""
    from saengine.codes import CodePackError

    settings = _settings_of(settings_text)
    try:
        pack = _pack(settings, root)
    except CodePackError as error:
        return {"ok": False, "code": "codePack", "message": str(error)}
    at = (
        (float(latitude), float(longitude))
        if _is_number(latitude) and _is_number(longitude)
        else coordinates(soil_text, root)
    )
    params = code_parameters(settings, soil_text)
    table = _table(pack)
    out: list[dict[str, Any]] = []
    for provider in providers(pack):
        offer = _offer(provider, pack)
        if at is None:
            offer["problem"] = (
                "The site has no coordinates: place the site point on the map in 01 Soil "
                "Report (Site), or enter its latitude and longitude."
            )
        else:
            try:
                offer["url"], offer["query"] = build_query(provider, at[0], at[1], params)
            except LookupError_ as error:
                offer["problem"] = str(error)
        out.append(offer)
    return {
        "ok": True,
        "codePack": pack.id,
        "codeName": pack.edition or pack.name,
        "coordinates": {"latitude": at[0], "longitude": at[1]} if at else None,
        "params": params,
        "providers": out,
        "manualNote": table.manualNote if table is not None else "",
    }


def lookup(
    settings_text: str | None,
    provider_id: str,
    consent: bool,
    soil_text: str | None = None,
    root: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    opener: Opener | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Asks the provider for the site's values: ``{ok, values: [{target, label, value, unit,
    current}], source}`` (``source`` the ``site.hazardSource`` record to keep), or ``{ok:
    false, code, message}``. Refused without ``consent`` (the engineer's yes to the request
    shown). Only the query of :func:`build_query` is sent."""
    if consent is not True:
        return {
            "ok": False,
            "code": "consent",
            "message": "The lookup was not confirmed: nothing was sent.",
        }
    from saengine.codes import CodePackError

    settings = _settings_of(settings_text)
    try:
        pack = _pack(settings, root)
    except CodePackError as error:
        return {"ok": False, "code": "codePack", "message": str(error)}
    provider = next((p for p in providers(pack) if p.id == provider_id), None)
    if provider is None:
        return {
            "ok": False,
            "code": "provider",
            "message": f"{pack.edition or pack.name} has no hazard service '{provider_id}'. "
            "Enter the values by hand.",
        }
    at = (
        (float(latitude), float(longitude))
        if _is_number(latitude) and _is_number(longitude)
        else coordinates(soil_text, root)
    )
    if at is None:
        return {
            "ok": False,
            "code": "coordinates",
            "message": "The site has no coordinates: place the site point on the map in 01 "
            "Soil Report (Site), or enter its latitude and longitude. Nothing was sent.",
        }
    try:
        url, query = build_query(provider, at[0], at[1], code_parameters(settings, soil_text))
        values = parse(provider, fetch(url, provider.timeout, opener))
    except LookupError_ as error:
        return {"ok": False, "code": error.code, "message": f"{error} Nothing was changed."}
    date = (now or datetime.now(UTC)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    source = {
        "provider": provider.id,
        "service": provider.service,
        "publisher": provider.publisher,
        "reference": provider.reference,
        "codePack": pack.id,
        "date": date,
        "url": url,
        "query": query,
        "values": values,
        "applied": list(values),
    }
    labels = {v.target: v.label or v.target.rsplit(".", 1)[-1] for v in provider.values}
    return {
        "ok": True,
        "values": [
            {
                "target": target,
                "label": labels.get(target, target),
                "value": value,
                "unit": TARGETS[target],
                "current": _get(settings, target),
            }
            for target, value in values.items()
        ],
        "source": source,
    }


# ───────────────────────────── applying and reporting ─────────────────────────────


def _get(settings: dict[str, Any], target: str) -> Any:
    node: Any = settings
    for key in target.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def apply(
    settings: dict[str, Any], source: dict[str, Any], targets: list[str] | None = None
) -> dict[str, Any]:
    """The settings (plain JSON, changed in place and returned) with the looked-up values in
    their fields (``targets``: only those; default all) and the record in
    ``site.hazardSource``. The fields stay editable."""
    values = source.get("values") if isinstance(source.get("values"), dict) else {}
    chosen = [t for t in (targets if targets is not None else list(values)) if t in values]
    for target in chosen:
        if target not in TARGETS:
            continue
        *path, last = target.split(".")
        node = settings
        for key in path:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[last] = values[target]
    site = settings.setdefault("site", {})
    site["hazardSource"] = {**source, "applied": chosen}
    return settings


def _same(a: Any, b: Any) -> bool:
    if _is_number(a) and _is_number(b):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))
    if isinstance(a, list | tuple) and isinstance(b, list | tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def source_rows(settings: Any) -> list[list[str]]:
    """The report's rows naming where looked-up values came from: ``[["Hazard values source",
    "<service> (<publisher>), <reference>, <date>: <query>; <fields>"]]``, each field marked
    whether it still equals the service's value or was edited since; [] when the values were
    entered by hand."""
    site = getattr(settings, "site", None)
    record = getattr(site, "hazardSource", None)
    if record is None:
        return []
    data = settings.model_dump(mode="json")
    kept, edited = [], []
    for target in record.applied:
        given = record.values.get(target)
        label = target.rsplit(".", 1)[-1]
        (kept if _same(_get(data, target), given) else edited).append(label)
    query = ", ".join(f"{k}={v}" for k, v in record.query.items())
    who = record.service + (f" ({record.publisher})" if record.publisher else "")
    text = (
        f"{who}{', ' + record.reference if record.reference else ''}, looked up "
        f"{record.date} by the site's coordinates: {query or record.url}"
    )
    if kept:
        text += f"; values from it: {', '.join(kept)}"
    if edited:
        text += f"; edited since by the engineer: {', '.join(edited)}"
    return [["Hazard values source", text + "."]]


__all__ = [
    "USER_AGENT",
    "LookupError_",
    "apply",
    "build_query",
    "code_parameters",
    "coordinates",
    "fetch",
    "lookup",
    "offers",
    "parse",
    "providers",
    "source_rows",
]
