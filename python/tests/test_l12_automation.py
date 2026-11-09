"""Alpha 9 L12: the office server's authentication, the results it hands back, visual programs,
design studies' parameters and the drawing automation."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from saengine.automation import graph as g
from saengine.automation import studies
from saengine.office import client
from saengine.office.server import MAX_FAILURES, OfficeServer, hash_token, make_server

TOKEN = "correct-horse-battery-staple"


# ─────────────────────────────────────────── office server ───────────────────────────────────────────


@pytest.fixture
def office(tmp_path):
    server = OfficeServer(tmp_path, hash_token(TOKEN))
    httpd = make_server(server, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _post(url: str, token: str | None, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(url + "/rpc", data=json.dumps(body).encode(), method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


INFO = {"jsonrpc": "2.0", "id": 1, "method": "office/info", "params": {}}


def test_office_server_refuses_without_the_token(office) -> None:
    _, url = office
    status, body = _post(url, None, INFO)
    assert status == 401 and body == {"error": "unauthorized"}
    status, body = _post(url, "wrong-token", INFO)
    assert status == 401 and body == {"error": "unauthorized"}
    # A refused request learns nothing about the jobs.
    status, body = _post(url, "", {**INFO, "method": "office/listJobs"})
    assert status == 401 and "jobs" not in body


def test_office_server_locks_out_after_repeated_failures(office) -> None:
    _, url = office
    for _ in range(MAX_FAILURES):
        assert _post(url, "wrong", INFO)[0] == 401
    # Locked: even the right token is refused for a while (no guessing at speed).
    assert _post(url, TOKEN, INFO)[0] == 429


def test_office_server_answers_with_the_token(office) -> None:
    _, url = office
    status, body = _post(url, TOKEN, INFO)
    assert status == 200
    assert body["result"]["server"] == "SAEngine office server"
    status, body = _post(
        url, TOKEN, {**INFO, "method": "office/createJob", "params": {"steps": ["rm -rf"]}}
    )
    assert "error" in body  # only Run All's steps
    status, body = _post(
        url, TOKEN, {**INFO, "method": "office/status", "params": {"jobId": "../x"}}
    )
    assert "error" in body


def test_office_server_refuses_uploads_without_the_token(office) -> None:
    server, url = office
    job = server.create({})
    request = urllib.request.Request(url + job["uploadPath"], data=b"PK", method="PUT")
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=10)
    assert refused.value.code == 401
    assert server.jobs[job["jobId"]].state == "waitingForUpload"


def test_results_stay_inside_the_project(tmp_path) -> None:
    project = tmp_path / "P"
    (project / "06 BIM").mkdir(parents=True)
    (project / "06 BIM" / "bim.json").write_text("edited meanwhile", "utf-8")
    archive = tmp_path / "results.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("08 FEM/model.results/manifest.json", "{}")
        z.writestr("06 BIM/bim.json", "{}")
        z.writestr("../outside.txt", "x")
        z.writestr(".git/config", "x")
        z.writestr("C:/Windows/x.txt", "x")
    sent = {"06 BIM/bim.json": "0" * 64}  # what was sent differs from the file now
    result = client.apply_results(project, archive, sent)
    assert result["written"] == ["08 FEM/model.results/manifest.json"]
    assert result["kept"] == ["06 BIM/bim.json"]
    assert sorted(result["refused"]) == sorted(
        ["../outside.txt", ".git/config", "C:/Windows/x.txt"]
    )
    assert not (tmp_path / "outside.txt").exists()
    assert (project / "06 BIM" / "bim.json").read_text("utf-8") == "edited meanwhile"


def test_client_refuses_other_than_http_urls() -> None:
    with pytest.raises(client.OfficeError):
        client.rpc("file:///etc/passwd", TOKEN, "office/info")


# ─────────────────────────────────────────── graphs ───────────────────────────────────────────


def _graph(nodes, edges):
    return {"schema": g.SCHEMA, "name": "t", "nodes": nodes, "edges": edges}


def _edge(a, pa, b, pb):
    return {"from": {"node": a, "port": pa}, "to": {"node": b, "port": pb}}


def test_graph_runs_in_dependency_order() -> None:
    graph = _graph(
        [
            {"id": "show", "type": "output.show"},
            {"id": "mul", "type": "math.multiply", "params": {"b": 1.1}},
            {"id": "h", "type": "value.number", "params": {"value": 3000}},
        ],
        [_edge("h", "value", "mul", "a"), _edge("mul", "result", "show", "value")],
    )
    run = g.run_graph(graph)
    assert run.order == ["h", "mul", "show"]
    assert run.outputs["show"]["value"] == pytest.approx(3300)
    assert run.to_json()["ok"] is True


def test_graph_stops_downstream_of_a_failure_and_finds_loops() -> None:
    graph = _graph(
        [
            {"id": "a", "type": "math.divide", "params": {"a": 1, "b": 0}},
            {"id": "b", "type": "output.show"},
            {"id": "c", "type": "value.number", "params": {"value": 2}},
        ],
        [_edge("a", "result", "b", "value")],
    )
    run = g.run_graph(graph)
    assert "a" in run.errors and run.skipped == ["b"] and run.outputs["c"]["value"] == 2
    loop = _graph(
        [{"id": "x", "type": "math.add"}, {"id": "y", "type": "math.add"}],
        [_edge("x", "result", "y", "a"), _edge("y", "result", "x", "a")],
    )
    assert any("loop" in p for p in g.check_graph(loop))
    unknown = _graph([{"id": "x", "type": "shell.exec"}], [])
    assert any("unknown type" in p for p in g.check_graph(unknown))


def test_graph_paths_stay_in_the_project(tmp_path) -> None:
    with pytest.raises(g.GraphError):
        g.project_file(tmp_path, "../secrets.json")
    with pytest.raises(g.GraphError):
        g.project_file(tmp_path, ".git/config")
    doc = {"stories": [{"elevation": 0}, {"elevation": 3000}]}
    g.set_path(doc, "stories/1/elevation", 3200)
    assert g.get_path(doc, ["stories", 1, "elevation"]) == 3200


# ─────────────────────────────────────────── studies ───────────────────────────────────────────


def test_study_variants_all_and_one_at_a_time() -> None:
    study = {
        "schema": studies.SCHEMA,
        "id": "s",
        "parameters": [
            {"kind": "gridSpacing", "values": [0.9, 1.0, 1.1]},
            {"kind": "concreteGrade", "values": ["C24.1", "C30"]},
        ],
    }
    assert len(studies.variants(study)) == 6
    study["combine"] = "oneAtATime"
    values = [v["values"] for v in studies.variants(study)]
    assert values == [[0.9, "C24.1"], [1.0, "C24.1"], [1.1, "C24.1"], [0.9, "C30"]]
    study["parameters"][0]["values"] = list(range(1, 40))
    study["combine"] = "all"
    with pytest.raises(studies.StudyError):
        studies.variants(study)


def test_study_parameters_edit_the_parts(tmp_path) -> None:
    (tmp_path / "05 Floor Plan").mkdir()
    (tmp_path / "04 Objects").mkdir()
    (tmp_path / "03 Materials").mkdir()
    plan = {
        "grids": {
            "x": [{"label": "A", "position": 0}, {"label": "B", "position": 6000}],
            "y": [{"label": "1", "position": 1000}, {"label": "2", "position": 6000}],
        },
        "stories": [
            {"id": "B", "elevation": 0},
            {"id": "1", "elevation": 4000},
            {"id": "2", "elevation": 7000},
            {"id": "3", "elevation": 10000},
        ],
    }
    (tmp_path / "05 Floor Plan" / "floor-plan.json").write_text(json.dumps(plan), "utf-8")
    objects = {
        "objects": [
            {
                "id": "C1",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 400},
            }
        ]
    }
    (tmp_path / "04 Objects" / "objects.json").write_text(json.dumps(objects), "utf-8")
    materials = {
        "materials": [
            {"id": "C24.1", "category": "concrete"},
            {"id": "C30", "category": "concrete"},
            {"id": "S275", "category": "steel"},
        ]
    }
    (tmp_path / "03 Materials" / "materials.json").write_text(json.dumps(materials), "utf-8")

    studies.apply_parameter(tmp_path, {"kind": "gridSpacing", "axis": "y"}, 1.2)
    plan = json.loads((tmp_path / "05 Floor Plan" / "floor-plan.json").read_text("utf-8"))
    assert [gl["position"] for gl in plan["grids"]["y"]] == [1000, 7000]  # from the first line
    assert [gl["position"] for gl in plan["grids"]["x"]] == [0, 6000]

    studies.apply_parameter(tmp_path, {"kind": "storeyHeight"}, 3200)
    plan = json.loads((tmp_path / "05 Floor Plan" / "floor-plan.json").read_text("utf-8"))
    assert [s["elevation"] for s in plan["stories"]] == [0, 4000, 7200, 10400]

    studies.apply_parameter(tmp_path, {"kind": "concreteGrade"}, "C30")
    studies.apply_parameter(tmp_path, {"kind": "sectionScale", "kinds": ["column"]}, 1.24)
    obj = json.loads((tmp_path / "04 Objects" / "objects.json").read_text("utf-8"))["objects"][0]
    assert obj["material"] == "C30"
    assert (obj["profile"]["xDim"], obj["profile"]["yDim"]) == (370, 495)  # to 5 mm
    with pytest.raises(studies.StudyError):
        studies.apply_parameter(tmp_path, {"kind": "concreteGrade"}, "S275")


# ─────────────────────────────────────────── drawing automation ───────────────────────────────────────────


def test_drawing_automation_dimensions_tags_and_undoes(tmp_path) -> None:
    import ezdxf

    from saengine.drawings import automation
    from saengine.drawings.sheets.layout import new_document, tag

    doc = new_document(100)
    msp = doc.modelspace()
    for x in (0, 6000, 12000):
        msp.add_line((x, -500), (x, 5500), dxfattribs={"layer": "S-GRID"})
    for y in (0, 5000):
        msp.add_line((-500, y), (12500, y), dxfattribs={"layer": "S-GRID"})
    column = msp.add_lwpolyline(
        [(-150, -200), (150, -200), (150, 200), (-150, 200)],
        close=True,
        dxfattribs={"layer": "S-COLS"},
    )
    tag(column, mark="C1")
    path = tmp_path / "S-101 Plan.dxf"
    doc.saveas(path)

    first = automation.automate_sheet(path, ["dimension", "tag"])
    # x: two bays and the overall; y: one bay, which is the overall too (not drawn twice).
    assert first["results"]["dimension"]["added"] == 3 + 1
    assert first["results"]["tag"]["added"] == 1
    again = automation.automate_sheet(path, ["dimension", "tag"])
    assert again["results"]["dimension"]["added"] == 0  # nothing missing any more
    assert again["results"]["tag"]["added"] == 0
    undone = automation.automate_sheet(path, ["undo"])
    assert undone["results"]["undo"]["removed"] == 5
    reread = ezdxf.readfile(str(path)).modelspace()
    assert len(reread.query("DIMENSION")) == 0
    assert not [t for t in reread.query("TEXT") if t.dxf.text == "C1"]
