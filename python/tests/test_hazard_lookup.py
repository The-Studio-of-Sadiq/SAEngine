"""Alpha 9 C22: the online hazard lookup by site coordinates, with the network mocked.

The sample answers are built from the documented form of the USGS Seismic Design Web
Services (asce7-22 endpoint): ``{"request": {"status": "success", "parameters": {...}},
"response": {"data": {"sds", "sd1", "sms", "sm1", "ss", "s1", "tl", "multiPeriodDesignSpectrum":
{"periods", "ordinates"}, "multiPeriodMCErSpectrum": {...}}}}``. The numbers are made up; no
request leaves the machine (every call is given a stub opener, and :func:`urllib.request.urlopen`
is patched to fail the test if it is reached).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from saengine.codes import registry
from saengine.codes import tables as _tables  # noqa: F401 - the table models first
from saengine.codes.hazard_tables import HazardLookupTable, HazardProvider
from saengine.gis import hazard_lookup as hz

US = "aci318-asce7-22"
LA = (34.0522, -118.2437)

ANSWER = {
    "request": {
        "date": "2026-11-05T00:00:00.000Z",
        "referenceDocument": "ASCE7-22",
        "status": "success",
        "parameters": {
            "latitude": 34.0522,
            "longitude": -118.2437,
            "riskCategory": "II",
            "siteClass": "D",
            "title": "SAEngine",
        },
    },
    "response": {
        "data": {
            "pgam": 0.81,
            "sms": 2.04,
            "sm1": 1.23,
            "sds": 1.36,
            "sd1": 0.82,
            "ss": 2.1,
            "s1": 0.74,
            "sdc": "D",
            "ts": 0.6,
            "t0": 0.12,
            "tl": 8,
            "cv": 1.4,
            "multiPeriodDesignSpectrum": {
                "periods": [0.0, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
                "ordinates": [0.55, 1.1, 1.36, 1.36, 0.82, 0.41, 0.15, 0.05],
            },
            "multiPeriodMCErSpectrum": {
                "periods": [0.0, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
                "ordinates": [0.82, 1.65, 2.04, 2.04, 1.23, 0.62, 0.22, 0.08],
            },
        },
        "metadata": {},
    },
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("the tests must not reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)


class Stub:
    """An opener that records the request and answers ``body`` (or raises ``error``)."""

    def __init__(self, body: object = ANSWER, error: Exception | None = None) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.error = error
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.body


def _settings(**site: object) -> str:
    return json.dumps(
        {
            "codePack": US,
            "occupancy": {"category": "II"},
            "site": {"location": "custom", "siteClass": "SD", "siteClassSource": "entered", **site},
        }
    )


def _provider() -> HazardProvider:
    return hz.providers(registry.load(US))[0]


# ───────────────────────────── the pack's table ─────────────────────────────


def test_us_pack_names_the_usgs_asce7_22_service() -> None:
    pack = registry.load(US)
    assert pack.has("hazardLookup") and not pack.broken
    provider = _provider()
    assert provider.id == "usgs-asce7-22"
    assert provider.endpoint == "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"
    assert provider.siteClasses["SCD"] == "CD"  # ASCE 7-22 Table 20.2-1 classes BC, CD, DE
    assert "SF" not in provider.siteClasses  # class F: a site response analysis, not a lookup


def test_a_pack_extending_the_us_pack_does_not_send_its_sites_to_usgs() -> None:
    # Myanmar MNBC extends aci318-asce7-22; the provider is not inheritable.
    assert hz.providers(registry.load("myanmar-mnbc")) == []


def test_the_default_pack_has_no_provider() -> None:
    offer = hz.offers(json.dumps({}), latitude=23.8, longitude=90.4)
    assert offer["ok"] and offer["providers"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"endpoint": "http://example.org/hazard.json"},  # not https
        {"endpoint": "https://example.org/hazard.json?x=1"},  # query in the endpoint
        {"query": {"latitude": "{latitude}", "longitude": "{longitude}", "p": "{projectName}"}},
        {"query": {"x": "1"}},  # the coordinates must be sent (and nothing else of the project)
    ],
)
def test_a_provider_cannot_send_more_than_the_coordinates(change: dict) -> None:
    data = _provider().model_dump() | change
    with pytest.raises(ValueError):
        HazardProvider.model_validate(data)


def test_unknown_targets_are_refused() -> None:
    data = _provider().model_dump()
    data["values"] = [{"target": "project.name", "path": ["a"], "unit": "-"}]
    with pytest.raises(ValueError):
        HazardLookupTable.model_validate({"providers": [data]})


# ───────────────────────────── the query ─────────────────────────────


def test_query_sends_only_the_coordinates_and_code_parameters() -> None:
    url, query = hz.build_query(_provider(), *LA, {"riskCategory": "III", "siteClass": "SD"})
    assert query == {
        "latitude": "34.0522",
        "longitude": "-118.2437",
        "riskCategory": "III",
        "siteClass": "D",
        "title": "SAEngine",
    }
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.hostname == "earthquake.usgs.gov"
    assert {k: v[0] for k, v in parse_qs(parts.query).items()} == query


def test_a_site_outside_the_service_regions_is_not_sent() -> None:
    with pytest.raises(hz.LookupError_) as error:
        hz.build_query(_provider(), 23.81, 90.41, {"riskCategory": "II", "siteClass": "SD"})
    assert error.value.code == "outsideRegion"


def test_alaska_box_crosses_the_antimeridian() -> None:
    hz.build_query(_provider(), 52.0, 175.0, {"riskCategory": "II", "siteClass": "SD"})  # Attu
    hz.build_query(_provider(), 61.2, -149.9, {"riskCategory": "II", "siteClass": "SD"})


def test_site_class_f_is_not_looked_up() -> None:
    with pytest.raises(hz.LookupError_) as error:
        hz.build_query(_provider(), *LA, {"riskCategory": "II", "siteClass": "SF"})
    assert error.value.code == "siteClass"


def test_offers_show_the_exact_request_without_sending_it() -> None:
    offer = hz.offers(_settings(), latitude=LA[0], longitude=LA[1])
    assert offer["ok"] and offer["codePack"] == US
    (usgs,) = offer["providers"]
    assert usgs["host"] == "earthquake.usgs.gov"
    assert usgs["query"]["siteClass"] == "D" and usgs["query"]["riskCategory"] == "II"
    assert "problem" not in usgs


def test_coordinates_come_from_the_soil_reports_site() -> None:
    soil = json.dumps({"site": {"lat": LA[0], "lon": LA[1]}})
    assert hz.coordinates(soil) == LA
    assert hz.coordinates(json.dumps({"site": {}})) is None
    offer = hz.offers(_settings(), soil_text=json.dumps({"boreholes": []}))
    assert "problem" in offer["providers"][0]  # no site point: nothing would be sent


def test_project_overrides_cannot_redirect_the_endpoint() -> None:
    settings = json.loads(_settings())
    settings["codeOverrides"] = {
        "hazardLookup.providers[usgs-asce7-22].endpoint": "https://example.org/x.json"
    }
    offer = hz.offers(json.dumps(settings), latitude=LA[0], longitude=LA[1])
    assert offer["providers"][0]["host"] == "earthquake.usgs.gov"


# ───────────────────────────── the call and the answer ─────────────────────────────


def test_lookup_refuses_without_consent_and_sends_nothing() -> None:
    stub = Stub()
    answer = hz.lookup(
        _settings(), "usgs-asce7-22", False, latitude=LA[0], longitude=LA[1], opener=stub
    )
    assert answer == {
        "ok": False,
        "code": "consent",
        "message": "The lookup was not confirmed: nothing was sent.",
    }
    assert stub.requests == []


def test_lookup_parses_the_usgs_answer() -> None:
    stub = Stub()
    now = datetime(2026, 11, 5, 8, 30, tzinfo=UTC)
    answer = hz.lookup(
        _settings(), "usgs-asce7-22", True, latitude=LA[0], longitude=LA[1], opener=stub, now=now
    )
    assert answer["ok"], answer
    values = {v["target"]: v["value"] for v in answer["values"]}
    assert values["site.spectral.sds"] == 1.36
    assert values["site.spectral.sd1"] == 0.82
    assert values["site.spectral.s1"] == 0.74
    assert values["site.spectral.tl"] == 8.0
    assert values["site.spectral.designSpectrum"][2] == [0.2, 1.36]
    assert values["site.spectral.mcerSpectrum"][-1] == [10.0, 0.08]
    source = answer["source"]
    assert source["service"].startswith("USGS") and source["date"] == "2026-11-05T08:30:00Z"
    assert source["query"]["latitude"] == "34.0522"
    # One GET with SAEngine's user agent and the provider's timeout; no other header of note.
    (request, timeout) = stub.requests[0]
    assert request.get_method() == "GET" and timeout == 30
    assert request.get_header("User-agent").startswith("SAEngine/")
    assert request.get_header("Cookie") is None and request.data is None


def test_lookup_takes_the_site_class_of_the_soil_report_when_its_source_says_so() -> None:
    stub = Stub()
    settings = _settings(siteClassSource="soilReport", siteClass="SC")
    hz.lookup(settings, "usgs-asce7-22", True, latitude=LA[0], longitude=LA[1], opener=stub)
    # Without boreholes the entered class is used.
    assert "siteClass=C" in stub.requests[0][0].full_url


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (urllib.error.URLError(OSError("getaddrinfo failed")), "offline"),
        (TimeoutError("timed out"), "timeout"),
        (urllib.error.URLError(TimeoutError("timed out")), "timeout"),
    ],
)
def test_offline_or_slow_gives_a_clear_message(error: Exception, code: str) -> None:
    answer = hz.lookup(
        _settings(),
        "usgs-asce7-22",
        True,
        latitude=LA[0],
        longitude=LA[1],
        opener=Stub(error=error),
    )
    assert not answer["ok"] and answer["code"] == code
    assert answer["message"].endswith("Nothing was changed.")


def test_an_http_error_names_the_status() -> None:
    error = urllib.error.HTTPError("https://x", 503, "Service Unavailable", {}, None)  # type: ignore[arg-type]
    answer = hz.lookup(
        _settings(),
        "usgs-asce7-22",
        True,
        latitude=LA[0],
        longitude=LA[1],
        opener=Stub(error=error),
    )
    assert not answer["ok"] and answer["code"] == "http" and "503" in answer["message"]


def test_a_failed_status_is_refused() -> None:
    body = {"request": {"status": "error"}, "response": "Invalid site class"}
    with pytest.raises(hz.LookupError_) as error:
        hz.parse(_provider(), json.dumps(body).encode())
    assert error.value.code == "refused" and "Invalid site class" in str(error.value)


def test_not_json_and_no_values_are_refused() -> None:
    with pytest.raises(hz.LookupError_):
        hz.parse(_provider(), b"<html>maintenance</html>")
    with pytest.raises(hz.LookupError_) as error:
        hz.parse(_provider(), json.dumps({"request": {"status": "success"}}).encode())
    assert error.value.code == "empty"


def test_bad_spectra_and_values_are_left_out() -> None:
    body = json.loads(json.dumps(ANSWER))
    data = body["response"]["data"]
    data["sd1"] = None
    data["tl"] = "n/a"
    data["multiPeriodDesignSpectrum"]["ordinates"].pop()  # lengths differ
    data["multiPeriodMCErSpectrum"]["periods"][3] = 0.1  # periods must increase
    values = hz.parse(_provider(), json.dumps(body).encode())
    assert "site.spectral.sd1" not in values and "site.spectral.tl" not in values
    assert "site.spectral.designSpectrum" not in values
    assert "site.spectral.mcerSpectrum" not in values
    assert values["site.spectral.sds"] == 1.36


def test_redirects_stay_on_the_host_and_on_https() -> None:
    handler = hz._SameHostHttps("earthquake.usgs.gov")
    request = urllib.request.Request("https://earthquake.usgs.gov/ws/designmaps/asce7-22.json")
    moved = handler.redirect_request(
        request, None, 301, "Moved", {}, "http://earthquake.usgs.gov/ws/building-codes/asce7-22"
    )
    assert moved.full_url.startswith("https://earthquake.usgs.gov/")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://example.org/x")


# ───────────────────────────── applying and the report ─────────────────────────────


def test_apply_puts_the_values_in_their_fields_and_keeps_the_source() -> None:
    answer = hz.lookup(
        _settings(), "usgs-asce7-22", True, latitude=LA[0], longitude=LA[1], opener=Stub()
    )
    settings = hz.apply(json.loads(_settings()), answer["source"])
    assert settings["site"]["spectral"]["sds"] == 1.36
    assert settings["site"]["hazardSource"]["provider"] == "usgs-asce7-22"
    assert "site.spectral.sds" in settings["site"]["hazardSource"]["applied"]


def test_report_names_the_source_and_the_values_edited_since() -> None:
    from saengine.library.settings import ProjectSettings, default_project_settings

    answer = hz.lookup(
        _settings(), "usgs-asce7-22", True, latitude=LA[0], longitude=LA[1], opener=Stub()
    )
    base = default_project_settings().model_dump(mode="json")
    settings = hz.apply(base, answer["source"], ["site.spectral.sds", "site.spectral.sd1"])
    settings["site"]["spectral"]["sd1"] = 0.9  # the engineer's own value
    rows = hz.source_rows(ProjectSettings.model_validate(settings))
    ((label, text),) = rows
    assert label == "Hazard values source"
    assert "USGS Seismic Design Web Services" in text and "latitude=34.0522" in text
    assert "values from it: sds" in text and "edited since by the engineer: sd1" in text


def test_no_source_line_for_values_typed_by_hand() -> None:
    from saengine.library.settings import default_project_settings

    assert hz.source_rows(default_project_settings()) == []
