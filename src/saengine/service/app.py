"""HTTP service entry point for SAEngine's local engineering API."""

from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from saengine import __version__
from saengine.core.analysis import AnalysisError, analyze_linear_static
from saengine.core.frame import FrameMaterial, FrameModel, FrameSection
from saengine.core.frame_builder import generate_grid_frame_model
from saengine.core.grids import GridSystem
from saengine.core.stories import StorySystem

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
API_VERSION = "v1"
HEALTH_PATH = f"/api/{API_VERSION}/health"
ANALYSIS_PATH = f"/api/{API_VERSION}/analysis/linear-static"
GRID_FRAME_PATH = f"/api/{API_VERSION}/models/grid-frame"
MAX_REQUEST_BYTES = 8 * 1024 * 1024


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "SAEngine"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in (ANALYSIS_PATH, GRID_FRAME_PATH):
            self._send_json(405, {"error": "Method not allowed"}, {"Allow": "POST"})
            return
        if path != HEALTH_PATH:
            self._send_json(404, {"error": "Not found"})
            return

        self._send_json(
            200,
            {
                "service": "saengine",
                "status": "ok",
                "api_version": API_VERSION,
                "version": __version__,
            },
        )

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == HEALTH_PATH:
            self._send_json(405, {"error": "Method not allowed"}, {"Allow": "GET"})
            return
        if path not in (ANALYSIS_PATH, GRID_FRAME_PATH):
            self._send_json(404, {"error": "Not found"})
            return

        payload = self._read_json_payload()
        if payload is None:
            return
        if path == GRID_FRAME_PATH:
            self._generate_grid_frame(payload)
            return

        self._analyze_linear_static(payload)

    def _read_json_payload(self) -> dict | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_json(415, {"error": "Content-Type must be application/json"})
            return None
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "A valid Content-Length header is required"})
            return None
        if content_length <= 0:
            self._send_json(400, {"error": "A non-empty JSON request body is required"})
            return None
        if content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body is too large"})
            return None

        try:
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self._send_json(400, {"error": f"Invalid request: {error}"})
            return None
        return payload

    def _analyze_linear_static(self, payload: dict) -> None:
        try:
            if not isinstance(payload.get("model"), dict):
                raise ValueError("Request must contain a 'model' object")
            load_case_id = payload.get("load_case_id")
            if isinstance(load_case_id, bool) or not isinstance(load_case_id, int):
                raise ValueError("'load_case_id' must be an integer")
            model = FrameModel.from_dict(payload["model"])
        except (KeyError, TypeError, ValueError) as error:
            self._send_json(400, {"error": f"Invalid analysis request: {error}"})
            return
        try:
            result = analyze_linear_static(model, load_case_id)
        except AnalysisError as error:
            self._send_json(422, {"error": str(error)})
            return

        self._send_json(200, result)

    def _generate_grid_frame(self, payload: dict) -> None:
        try:
            project = payload.get("project")
            material_data = payload.get("material")
            section_data = payload.get("section")
            if not isinstance(project, dict) or not isinstance(material_data, dict):
                raise ValueError("Request must contain 'project' and 'material' objects")
            if not isinstance(section_data, dict):
                raise ValueError("Request must contain a 'section' object")
            grids_data = project.get("grids")
            stories_data = project.get("stories")
            if not isinstance(grids_data, dict) or not isinstance(stories_data, dict):
                raise ValueError("Project must contain 'grids' and 'stories' objects")

            material = FrameMaterial(
                id=1,
                name=material_data.get("name", "Material 1"),
                elastic_modulus=material_data["elastic_modulus"],
                shear_modulus=material_data["shear_modulus"],
            )
            section = FrameSection(
                id=1,
                name=section_data.get("name", "Section 1"),
                area=section_data["area"],
                torsion_constant=section_data["torsion_constant"],
                moment_of_inertia_y=section_data["moment_of_inertia_y"],
                moment_of_inertia_z=section_data["moment_of_inertia_z"],
            )
            model = generate_grid_frame_model(
                GridSystem.from_dict(grids_data),
                StorySystem.from_dict(stories_data),
                material,
                section,
            )
        except (KeyError, TypeError, ValueError) as error:
            self._send_json(400, {"error": f"Invalid grid-frame request: {error}"})
            return

        self._send_json(200, model.to_dict())

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """Create the API server; the default bind address is loopback-only."""
    return ThreadingHTTPServer((host, port), _RequestHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SAEngine local engineering service.")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Interface to bind (default: loopback)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = create_server(args.host, args.port)
    logger.info("SAEngine service listening on http://%s:%d", *server.server_address)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping SAEngine service")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
