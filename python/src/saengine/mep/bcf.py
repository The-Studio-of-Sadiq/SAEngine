"""BCF 3.0 (BIM Collaboration Format, buildingSMART) export and import of coordination issues.

A ``.bcf`` file is a zip: ``bcf.version`` (``VersionId="3.0"``), ``extensions.xml`` (the topic
types, statuses, priorities and users the file uses) and one folder per topic, named by its GUID,
with ``markup.bcf`` (the topic: title, status, priority, assignee, dates, description, comments
and viewpoints) and its viewpoints (``.bcfv``: the selected and coloured components by
IfcGuid, and a perspective camera looking at the issue's point). Coordinates in BCF are metres.

Import reads BCF 3.0 and 2.1 (whose comments and viewpoints sit beside the topic, not in it):
a topic whose GUID matches an issue updates its status, priority, assignee, due date, title and
description, and adds the comments the issue does not have; any other topic becomes a new issue
(source ``bcf``) with the components of its first viewpoint and the camera's target as point.
"""

from __future__ import annotations

import io
import math
import uuid
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from saengine.library.mep import Coordination, Issue, IssueComment

VERSION = "3.0"
STATUS_LABELS = {
    "new": "New",
    "active": "Active",
    "reviewed": "Reviewed",
    "approved": "Approved",
    "resolved": "Resolved",
    "closed": "Closed",
}
#: Other tools' statuses read as ours.
STATUS_ALIASES = {
    "open": "active",
    "in progress": "active",
    "inprogress": "active",
    "assigned": "active",
    "done": "resolved",
    "fixed": "resolved",
    "accepted": "approved",
}
PRIORITY_LABELS = {"low": "Low", "normal": "Normal", "high": "High", "critical": "Critical"}
TOPIC_TYPES = {"clash": "Clash", "ids": "Model check", "bcf": "Issue", "manual": "Issue"}
#: Where the camera of a viewpoint stands from the issue's point [m], and its field of view.
CAMERA_OFFSET = (6.0, -6.0, 4.5)
FIELD_OF_VIEW = 60.0
ASPECT_RATIO = 1.6


def _text(parent: ET.Element, tag: str, value: Any) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = "" if value is None else str(value)
    return element


def _xml(root: ET.Element) -> bytes:
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _vector(parent: ET.Element, tag: str, values: tuple[float, float, float]) -> None:
    element = ET.SubElement(parent, tag)
    for axis, value in zip("XYZ", values, strict=True):
        _text(element, axis, f"{value:.6g}")


def camera(point_mm: list[float]) -> dict[str, tuple[float, float, float]]:
    """A perspective camera looking at ``point_mm`` from :data:`CAMERA_OFFSET` (metres)."""
    target = tuple(v / 1e3 for v in point_mm[:3])
    eye = tuple(t + o for t, o in zip(target, CAMERA_OFFSET, strict=True))
    direction = [t - e for t, e in zip(target, eye, strict=True)]
    length = math.sqrt(sum(d * d for d in direction))
    d = [x / length for x in direction]
    # up: the world's Z made perpendicular to the direction
    up = [-d[0] * d[2], -d[1] * d[2], 1.0 - d[2] * d[2]]
    norm = math.sqrt(sum(u * u for u in up))
    return {
        "CameraViewPoint": eye,  # type: ignore[dict-item]
        "CameraDirection": tuple(d),  # type: ignore[dict-item]
        "CameraUpVector": tuple(u / norm for u in up),  # type: ignore[dict-item]
    }


def viewpoint_xml(guid: str, issue: Issue) -> bytes:
    root = ET.Element("VisualizationInfo", Guid=guid)
    components = ET.SubElement(root, "Components")
    if issue.elements:
        selection = ET.SubElement(components, "Selection")
        for element in issue.elements:
            ET.SubElement(selection, "Component", IfcGuid=element)
    ET.SubElement(components, "Visibility", DefaultVisibility="true")
    if issue.elements:
        coloring = ET.SubElement(components, "Coloring")
        color = ET.SubElement(coloring, "Color", Color="FFE51400")
        for element in issue.elements:
            ET.SubElement(color, "Component", IfcGuid=element)
    if issue.point:
        perspective = ET.SubElement(root, "PerspectiveCamera")
        for tag, values in camera(issue.point).items():
            _vector(perspective, tag, values)
        _text(perspective, "FieldOfView", FIELD_OF_VIEW)
        _text(perspective, "AspectRatio", ASPECT_RATIO)
    return _xml(root)


def markup_xml(issue: Issue, viewpoint: str | None, files: list[str], author: str) -> bytes:
    root = ET.Element("Markup")
    if files:
        header = ET.SubElement(root, "Header")
        listed = ET.SubElement(header, "Files")
        for name in files:
            entry = ET.SubElement(listed, "File", IsExternal="true")
            _text(entry, "Filename", name)
            _text(entry, "Reference", name)
    topic = ET.SubElement(
        root,
        "Topic",
        Guid=issue.guid,
        TopicType=TOPIC_TYPES.get(issue.source, "Issue"),
        TopicStatus=STATUS_LABELS[issue.status],
    )
    _text(topic, "Title", issue.title or issue.id)
    _text(topic, "Priority", PRIORITY_LABELS[issue.priority])
    labels = ET.SubElement(topic, "Labels")
    _text(labels, "Label", issue.id)
    if issue.test:
        _text(labels, "Label", issue.test)
    _text(topic, "CreationDate", issue.created or issue.modified)
    _text(topic, "CreationAuthor", author)
    if issue.modified:
        _text(topic, "ModifiedDate", issue.modified)
        _text(topic, "ModifiedAuthor", author)
    if issue.dueDate:
        _text(topic, "DueDate", issue.dueDate)
    if issue.assignedTo:
        _text(topic, "AssignedTo", issue.assignedTo)
    if issue.story:
        _text(topic, "Stage", issue.story)
    if issue.description:
        _text(topic, "Description", issue.description)
    if issue.comments:
        comments = ET.SubElement(topic, "Comments")
        for comment in issue.comments:
            entry = ET.SubElement(comments, "Comment", Guid=comment.guid or str(uuid.uuid4()))
            _text(entry, "Date", comment.date)
            _text(entry, "Author", comment.author or author)
            _text(entry, "Comment", comment.text)
    if viewpoint:
        viewpoints = ET.SubElement(topic, "Viewpoints")
        entry = ET.SubElement(viewpoints, "ViewPoint", Guid=viewpoint)
        _text(entry, "Viewpoint", f"{viewpoint}.bcfv")
    return _xml(root)


def extensions_xml(issues: list[Issue], author: str) -> bytes:
    root = ET.Element("Extensions")
    for tag, child, values in (
        ("TopicTypes", "TopicType", sorted(set(TOPIC_TYPES.values()))),
        ("TopicStatuses", "TopicStatus", list(STATUS_LABELS.values())),
        ("Priorities", "Priority", list(PRIORITY_LABELS.values())),
        ("Users", "User", sorted({author, *(i.assignedTo for i in issues if i.assignedTo)})),
    ):
        group = ET.SubElement(root, tag)
        for value in values:
            _text(group, child, value)
    return _xml(root)


def export_bcf(
    coordination: Coordination, files: list[str] | None = None, ids: list[str] | None = None
) -> bytes:
    """The BCF 3.0 zip of the issues of ``coordination`` (those of ``ids``, else all);
    ``files`` are the IFC models the topics refer to."""
    author = coordination.author or "SAEngine"
    issues = [i for i in coordination.issues if ids is None or i.id in ids]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        version = ET.Element("Version", VersionId=VERSION)
        archive.writestr("bcf.version", _xml(version))
        archive.writestr("extensions.xml", extensions_xml(issues, author))
        for issue in issues:
            guid = issue.guid or str(uuid.uuid4())
            issue = issue.model_copy(update={"guid": guid})
            viewpoint = str(uuid.uuid5(uuid.UUID(guid), "viewpoint")) if issue.point else None
            archive.writestr(
                f"{guid}/markup.bcf", markup_xml(issue, viewpoint, files or [], author)
            )
            if viewpoint:
                archive.writestr(f"{guid}/{viewpoint}.bcfv", viewpoint_xml(viewpoint, issue))
    return buffer.getvalue()


# ─────────────────────────────────────────── import ───────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    return next((c for c in parent if _local(c.tag) == name), None)


def _child_text(parent: ET.Element | None, name: str) -> str:
    element = _find(parent, name)
    return (element.text or "").strip() if element is not None else ""


def _all(parent: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in parent.iter() if _local(e.tag) == name]


def status_of(label: str) -> str:
    key = label.strip().lower()
    for ours, theirs in STATUS_LABELS.items():
        if key == theirs.lower():
            return ours
    return STATUS_ALIASES.get(key, "active")


def priority_of(label: str) -> str:
    key = label.strip().lower()
    if key in PRIORITY_LABELS:
        return key
    return {"medium": "normal", "major": "high", "minor": "low", "blocker": "critical"}.get(
        key, "normal"
    )


def _vector_of(parent: ET.Element | None) -> list[float] | None:
    if parent is None:
        return None
    try:
        return [float(_child_text(parent, axis)) for axis in "XYZ"]
    except ValueError:
        return None


def _viewpoint(data: bytes) -> tuple[list[str], list[float] | None]:
    """The selected components and the camera's target (mm, a viewpoint 6 m ahead when the
    camera does not say) of a ``.bcfv``."""
    root = ET.fromstring(data)
    selection = _find(_find(root, "Components"), "Selection")
    components = [
        c.get("IfcGuid", "")
        for c in (selection if selection is not None else [])
        if _local(c.tag) == "Component" and c.get("IfcGuid")
    ]
    point = None
    for kind in ("PerspectiveCamera", "OrthogonalCamera"):
        cam = _find(root, kind)
        eye = _vector_of(_find(cam, "CameraViewPoint"))
        direction = _vector_of(_find(cam, "CameraDirection"))
        if eye and direction:
            length = math.sqrt(sum(d * d for d in direction)) or 1.0
            reach = math.sqrt(sum(o * o for o in CAMERA_OFFSET))
            point = [round((e + d / length * reach) * 1e3, 1) for e, d in zip(eye, direction)]
            break
    return components, point


def read_bcf(data: bytes) -> list[dict[str, Any]]:
    """The topics of a BCF 2.1 or 3.0 zip: ``[{"guid", "title", "status", "priority",
    "assignedTo", "dueDate", "description", "created", "modified", "comments": [{"guid",
    "date", "author", "text"}], "elements", "point"}]``."""
    topics: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        for name in sorted(names):
            if not name.endswith("markup.bcf"):
                continue
            folder = name[: -len("markup.bcf")]
            root = ET.fromstring(archive.read(name))
            topic = _find(root, "Topic")
            if topic is None:
                continue
            comments = [
                {
                    "guid": c.get("Guid", ""),
                    "date": _child_text(c, "Date"),
                    "author": _child_text(c, "Author"),
                    "text": _child_text(c, "Comment"),
                }
                for c in _all(root, "Comment")
                if c.get("Guid") is not None or _find(c, "Date") is not None
            ]
            elements: list[str] = []
            point = None
            for viewpoint in _all(root, "ViewPoint") + _all(root, "Viewpoints"):
                file_name = _child_text(viewpoint, "Viewpoint")
                if file_name and folder + file_name in names:
                    elements, point = _viewpoint(archive.read(folder + file_name))
                    break
            topics.append(
                {
                    "guid": topic.get("Guid") or folder.strip("/"),
                    "title": _child_text(topic, "Title"),
                    "status": status_of(topic.get("TopicStatus") or "Active"),
                    "priority": priority_of(_child_text(topic, "Priority") or "Normal"),
                    "assignedTo": _child_text(topic, "AssignedTo"),
                    "dueDate": _child_text(topic, "DueDate"),
                    "description": _child_text(topic, "Description"),
                    "created": _child_text(topic, "CreationDate"),
                    "modified": _child_text(topic, "ModifiedDate"),
                    "comments": comments,
                    "elements": elements,
                    "point": point,
                }
            )
    return topics


def merge_bcf(
    coordination: Coordination, topics: list[dict[str, Any]]
) -> tuple[Coordination, dict[str, int]]:
    """``coordination`` with the BCF ``topics`` merged in (see the module's docstring), and
    the counts ``{"updated", "added", "comments"}``."""
    issues = [i.model_copy(deep=True) for i in coordination.issues]
    by_guid = {i.guid: i for i in issues if i.guid}
    taken = {i.id for i in issues}
    counts = {"updated": 0, "added": 0, "comments": 0}
    for topic in topics:
        comments = [IssueComment(**c) for c in topic["comments"] if c["text"]]
        issue = by_guid.get(topic["guid"])
        if issue is None:
            n = 1
            while f"B{n}" in taken:
                n += 1
            taken.add(f"B{n}")
            issue = Issue(
                id=f"B{n}",
                guid=topic["guid"],
                title=topic["title"][:200],
                source="bcf",
                status=topic["status"],
                priority=topic["priority"],
                assignedTo=topic["assignedTo"],
                dueDate=topic["dueDate"],
                description=topic["description"],
                elements=topic["elements"],
                point=topic["point"],
                created=topic["created"],
                modified=topic["modified"] or topic["created"],
                comments=comments,
            )
            issues.append(issue)
            by_guid[issue.guid] = issue
            counts["added"] += 1
            counts["comments"] += len(comments)
            continue
        issue.status = topic["status"]
        issue.priority = topic["priority"]
        for name in ("assignedTo", "dueDate", "title", "description"):
            if topic[name]:
                setattr(issue, name, topic[name][:200] if name == "title" else topic[name])
        if topic["modified"]:
            issue.modified = topic["modified"]
        known = {c.guid for c in issue.comments if c.guid}
        known_text = {(c.date, c.text) for c in issue.comments}
        for comment in comments:
            if (comment.guid and comment.guid in known) or (comment.date, comment.text) in (
                known_text
            ):
                continue
            issue.comments.append(comment)
            counts["comments"] += 1
        counts["updated"] += 1
    return coordination.model_copy(update={"issues": issues}), counts
