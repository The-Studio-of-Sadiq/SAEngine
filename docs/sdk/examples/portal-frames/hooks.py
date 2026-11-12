"""Coded templates of the portal-frames example package (SAEngine SDK).

Each generator takes the template's parameters (checked by SAEngine against its schema) and
returns the geometry as JSON: points [x, y, z] in mm, in the template's own frame (SAEngine
moves it to the origin and rotation the engineer picks). It only computes: no files, network or
processes, as the package repositories' review rules require.
"""


def portal(params):
    span = float(params["span"])
    eaves = float(params["eaves"])
    ridge = eaves + float(params["rise"])
    fixity = "fixed" if params.get("fixed", True) else "pinned"
    left_foot, right_foot = [0.0, 0.0, 0.0], [span, 0.0, 0.0]
    left_eave, right_eave = [0.0, 0.0, eaves], [span, 0.0, eaves]
    apex = [span / 2, 0.0, ridge]
    return {
        "members": [
            {"start": left_foot, "end": left_eave, "type": "MEMBER"},
            {"start": left_eave, "end": apex, "type": "MEMBER"},
            {"start": apex, "end": right_eave, "type": "MEMBER"},
            {"start": right_eave, "end": right_foot, "type": "MEMBER"},
        ],
        "supports": [
            {"at": left_foot, "fixity": fixity},
            {"at": right_foot, "fixity": fixity},
        ],
        "notes": [f"portal frame {span / 1000:g} m span, {eaves / 1000:g} m eaves"],
    }
