"""Tests for the SAEngine local HTTP service."""

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from saengine.core.grids import GridSystem
from saengine.core.stories import StorySystem
from saengine.service.app import API_VERSION, create_server


def cantilever_payload():
    return {
        "load_case_id": 1,
        "model": {
            "joints": [
                {
                    "id": 1,
                    "coordinates": [0.0, 0.0, 0.0],
                    "restraints": [True, True, True, True, True, True],
                },
                {"id": 2, "coordinates": [4.0, 0.0, 0.0]},
            ],
            "members": [
                {
                    "id": 1,
                    "start_joint": 1,
                    "end_joint": 2,
                    "material_id": 1,
                    "section_id": 1,
                }
            ],
            "materials": [
                {"id": 1, "elastic_modulus": 200e6, "shear_modulus": 80e6}
            ],
            "sections": [
                {
                    "id": 1,
                    "area": 0.02,
                    "torsion_constant": 0.0001,
                    "moment_of_inertia_y": 0.0002,
                    "moment_of_inertia_z": 0.0002,
                }
            ],
            "load_cases": [
                {
                    "id": 1,
                    "name": "Service",
                    "joint_loads": [
                        {"joint_id": 2, "values": [0.0, -10.0, 0.0, 0.0, 0.0, 0.0]}
                    ],
                }
            ],
        },
    }


def grid_frame_payload():
    return {
        "project": {
            "grids": GridSystem.create_default(
                n_x=2, n_y=2, spacing_x=5.0, spacing_y=4.0
            ).to_dict(),
            "stories": StorySystem.create_default(
                n_stories=1, ground_height=3.0
            ).to_dict(),
        },
        "material": {
            "name": "Steel",
            "elastic_modulus": 200e6,
            "shear_modulus": 80e6,
        },
        "section": {
            "name": "Frame section",
            "area": 0.02,
            "torsion_constant": 0.0001,
            "moment_of_inertia_y": 0.0002,
            "moment_of_inertia_z": 0.0002,
        },
    }


@pytest.fixture
def service_url():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_health_endpoint_reports_service_and_api_version(service_url):
    with urlopen(f"{service_url}/api/{API_VERSION}/health") as response:
        payload = json.load(response)

    assert response.status == 200
    assert payload["service"] == "saengine"
    assert payload["status"] == "ok"
    assert payload["api_version"] == API_VERSION
    assert isinstance(payload["version"], str)


def test_unknown_endpoint_returns_json_not_found(service_url):
    with pytest.raises(HTTPError) as error:
        urlopen(f"{service_url}/api/{API_VERSION}/unknown")

    assert error.value.code == 404
    assert json.load(error.value)["error"] == "Not found"


def test_health_endpoint_rejects_post(service_url):
    request = Request(
        f"{service_url}/api/{API_VERSION}/health",
        data=b"{}",
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request)

    assert error.value.code == 405
    assert error.value.headers["Allow"] == "GET"


def test_linear_static_endpoint_solves_cantilever(service_url):
    request = Request(
        f"{service_url}/api/{API_VERSION}/analysis/linear-static",
        data=json.dumps(cantilever_payload()).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        result = json.load(response)

    free_end = next(item for item in result["displacements"] if item["joint_id"] == 2)
    assert response.status == 200
    assert result["analysis_type"] == "linear_static"
    assert free_end["values"][1] == pytest.approx(-10.0 * 4.0**3 / (3 * 200e6 * 0.0002))


def test_linear_static_endpoint_reports_invalid_model(service_url):
    payload = cantilever_payload()
    payload["model"]["members"][0]["end_joint"] = 99
    request = Request(
        f"{service_url}/api/{API_VERSION}/analysis/linear-static",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(HTTPError) as error:
        urlopen(request)

    assert error.value.code == 422
    assert "missing joint" in json.load(error.value)["error"]


def test_grid_frame_endpoint_builds_from_project_layout(service_url):
    request = Request(
        f"{service_url}/api/{API_VERSION}/models/grid-frame",
        data=json.dumps(grid_frame_payload()).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        model = json.load(response)

    assert len(model["joints"]) == 8
    assert len(model["members"]) == 8
    assert sum(all(joint["restraints"]) for joint in model["joints"]) == 4
