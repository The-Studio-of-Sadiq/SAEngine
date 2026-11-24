"""Overview team-directory and workload commands."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.overview_common import (
    csv_text,
    json_text,
    require_project,
    settings_dict,
    write_export,
)


def _team(ctx: FeatureContext) -> list[dict[str, Any]]:
    raw = settings_dict(ctx)
    team = raw.get("team", []) if isinstance(raw.get("team"), list) else []
    return [item for item in team if isinstance(item, dict)]


@feature(
    "overviewTeam.addMember",
    "Add Member",
    part="settings",
    fields=[text("name", "Member name", ""), text("role", "Role", "")],
    requires_project=True,
)
def add_member(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Add a team member to project settings."""
    root = require_project(ctx, "adding a team member")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    if not isinstance(team, list):
        team = []
        raw["team"] = team
    team.append({"name": values["name"], "role": values["role"]})
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"memberCount": len(team)},
        tables=[table("Team", [("name", "Name"), ("role", "Role")], team)],
    )


@feature(
    "overviewTeam.assignRole",
    "Assign Role",
    part="settings",
    fields=[text("name", "Member name", ""), text("role", "Role", "")],
    requires_project=True,
)
def assign_role(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign or update a team member role."""
    root = require_project(ctx, "assigning a role")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found["role"] = values["role"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "role": values["role"]})


@feature(
    "overviewTeam.disciplineTag",
    "Discipline Tag",
    part="settings",
    fields=[text("name", "Member name", ""), text("discipline", "Discipline", "")],
    requires_project=True,
)
def discipline_tag(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tag a team member with a discipline."""
    root = require_project(ctx, "tagging a team member")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found["discipline"] = values["discipline"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "discipline": values["discipline"]})


@feature(
    "overviewTeam.availability",
    "Availability",
    part="settings",
    fields=[
        text("name", "Member name", ""),
        number("hours", "Available hours", 40.0, unit="h", min=0),
    ],
    requires_project=True,
)
def availability(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set member availability hours."""
    root = require_project(ctx, "editing availability")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found["availabilityHours"] = values["hours"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "availabilityHours": values["hours"]})


@feature(
    "overviewTeam.assignTask",
    "Assign Task",
    part="settings",
    fields=[text("name", "Member name", ""), text("task", "Task", "")],
    requires_project=True,
)
def assign_team_task(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign a named task to a team member."""
    root = require_project(ctx, "assigning a team task")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found.setdefault("tasks", [])
    if isinstance(found["tasks"], list):
        found["tasks"].append(values["task"])
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "task": values["task"]})


@feature(
    "overviewTeam.capacityView", "Capacity View", part="settings", fields=[], requires_project=True
)
def capacity_view(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display team availability and required task estimates."""
    rows = [
        {
            "name": item.get("name", ""),
            "capacity": item.get("availabilityHours", 0),
            "tasks": len(item.get("tasks", [])) if isinstance(item.get("tasks"), list) else 0,
        }
        for item in _team(ctx)
    ]
    return result(
        summary={"memberCount": len(rows)},
        tables=[
            table(
                "Team capacity",
                [("name", "Name"), ("capacity", "Capacity", "h"), ("tasks", "Tasks")],
                rows,
            )
        ],
    )


@feature(
    "overviewTeam.utilisationChart",
    "Utilisation Chart",
    part="settings",
    fields=[],
    requires_project=True,
)
def utilisation_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Chart team member task counts against available hours."""
    rows = [
        {
            "name": item.get("name", ""),
            "hours": item.get("availabilityHours", 0),
            "tasks": len(item.get("tasks", [])) if isinstance(item.get("tasks"), list) else 0,
        }
        for item in _team(ctx)
    ]
    return result(
        summary={"memberCount": len(rows)},
        tables=[
            table(
                "Team utilisation",
                [("name", "Name"), ("hours", "Available", "h"), ("tasks", "Task count")],
                rows,
            )
        ],
    )


@feature(
    "overviewTeam.rebalanceLoad",
    "Rebalance Load",
    part="settings",
    fields=[number("targetTasks", "Target tasks per member", 3.0, unit="tasks", min=0)],
    requires_project=True,
)
def rebalance_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Flag members above the configured task-count target."""
    rows = []
    for item in _team(ctx):
        task_count = len(item.get("tasks", [])) if isinstance(item.get("tasks"), list) else 0
        rows.append(
            {
                "name": item.get("name", ""),
                "taskCount": task_count,
                "status": "OVER" if task_count > values["targetTasks"] else "OK",
            }
        )
    return result(
        summary={"memberCount": len(rows), "overTarget": sum(r["status"] == "OVER" for r in rows)},
        tables=[
            table(
                "Load rebalance",
                [("name", "Name"), ("taskCount", "Tasks"), ("status", "Status")],
                rows,
            )
        ],
    )


@feature(
    "overviewTeam.contactCard",
    "Contact Card",
    part="settings",
    fields=[text("name", "Member name", "")],
    requires_project=True,
)
def contact_card(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display contact details for one team member."""
    item = next((item for item in _team(ctx) if item.get("name") == values["name"]), None)
    if item is None:
        raise FeatureInputError("Enter an existing team member name.")
    return result(
        summary={
            "name": item.get("name", ""),
            "email": item.get("email", ""),
            "role": item.get("role", ""),
        }
    )


@feature(
    "overviewTeam.companyDetail",
    "Company Detail",
    part="settings",
    fields=[text("company", "Company", "")],
    requires_project=True,
)
def company_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Store a project company name."""
    root = require_project(ctx, "editing company detail")
    raw = settings_dict(ctx)
    raw.setdefault("project", {})["company"] = values["company"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"company": values["company"]})


@feature(
    "overviewTeam.phoneDirectory",
    "Phone Directory",
    part="settings",
    fields=[],
    requires_project=True,
)
def phone_directory(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List team phone fields."""
    rows = [{"name": item.get("name", ""), "phone": item.get("phone", "")} for item in _team(ctx)]
    return result(
        summary={"memberCount": len(rows)},
        tables=[table("Phone directory", [("name", "Name"), ("phone", "Phone")], rows)],
    )


@feature(
    "overviewTeam.exportDirectory",
    "Export Directory",
    part="settings",
    fields=[text("filename", "CSV filename", "team-directory")],
    requires_project=True,
)
def export_directory(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the team directory to CSV."""
    rows = _team(ctx)
    name = values["filename"].strip().replace(" ", "-") or "team-directory"
    path = write_export(
        ctx,
        "11 Exports",
        f"{name}.csv",
        csv_text(["name", "role", "discipline", "email", "phone"], rows),
    )
    return result(
        summary={"memberCount": len(rows), "exportPath": str(path)},
        notes=[f"Team directory written to {path}."],
    )


@feature(
    "overviewTeam.accessControl",
    "Access Control",
    part="settings",
    fields=[text("name", "Member name", ""), text("access", "Access level", "Review")],
    requires_project=True,
)
def access_control(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set member access level."""
    root = require_project(ctx, "editing access control")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found["access"] = values["access"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "access": values["access"]})


@feature(
    "overviewTeam.userGroup",
    "User Group",
    part="settings",
    fields=[text("name", "Member name", ""), text("group", "User group", "")],
    requires_project=True,
)
def user_group(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign a team member to a user group."""
    root = require_project(ctx, "assigning a user group")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found["group"] = values["group"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "group": values["group"]})


@feature(
    "overviewTeam.projectAccess",
    "Project Access",
    part="settings",
    fields=[text("member", "Member or group", ""), text("access", "Access", "Read")],
    requires_project=True,
)
def project_access(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a project-access record."""
    path = write_export(
        ctx,
        "11 Exports",
        "project-access.json",
        json_text({"member": values["member"], "access": values["access"]}),
    )
    return result(
        summary={"member": values["member"], "access": values["access"], "exportPath": str(path)}
    )


@feature(
    "overviewTeam.skillMatrix",
    "Skill Matrix",
    part="settings",
    fields=[
        text("name", "Member name", ""),
        text("skill", "Skill", ""),
        number("level", "Skill level", 3.0, unit="level", min=0, max=5),
    ],
    requires_project=True,
)
def skill_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set a skill level for a team member."""
    root = require_project(ctx, "editing skill matrix")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found.setdefault("skills", {})
    if isinstance(found["skills"], dict):
        found["skills"][values["skill"]] = values["level"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"name": values["name"], "skill": values["skill"], "level": values["level"]}
    )


@feature(
    "overviewTeam.softwareProficiency",
    "Software Proficiency",
    part="settings",
    fields=[
        text("name", "Member name", ""),
        text("software", "Software", "SAEngine"),
        number("level", "Proficiency", 3.0, unit="level", min=0, max=5),
    ],
    requires_project=True,
)
def software_proficiency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record software proficiency for a member."""
    root = require_project(ctx, "editing software proficiency")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found.setdefault("software", {})
    if isinstance(found["software"], dict):
        found["software"][values["software"]] = values["level"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"name": values["name"], "software": values["software"], "level": values["level"]}
    )


@feature(
    "overviewTeam.trainingLog",
    "Training Log",
    part="settings",
    fields=[text("name", "Member name", ""), text("training", "Training", "")],
    requires_project=True,
)
def training_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Append a training entry to a team member."""
    root = require_project(ctx, "editing training log")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found.setdefault("training", [])
    if isinstance(found["training"], list):
        found["training"].append(values["training"])
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "training": values["training"]})


@feature(
    "overviewTeam.teamBulletin",
    "Team Bulletin",
    part="settings",
    fields=[text("message", "Bulletin message", "")],
    requires_project=True,
)
def team_bulletin(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a team bulletin Markdown file."""
    path = write_export(
        ctx, "11 Exports", "team-bulletin.md", f"# Team Bulletin\n\n{values['message']}\n"
    )
    return result(summary={"messageLength": len(values["message"]), "exportPath": str(path)})


@feature(
    "overviewTeam.notificationRule",
    "Notification Rule",
    part="settings",
    fields=[text("event", "Event", "Task due"), text("recipient", "Recipient", "")],
    requires_project=True,
)
def notification_rule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a local notification rule."""
    path = write_export(
        ctx,
        "11 Exports",
        "notification-rule.json",
        json_text({"event": values["event"], "recipient": values["recipient"]}),
    )
    return result(
        summary={
            "event": values["event"],
            "recipient": values["recipient"],
            "exportPath": str(path),
        }
    )


@feature(
    "overviewTeam.shiftSchedule",
    "Shift Schedule",
    part="settings",
    fields=[text("name", "Member name", ""), text("shift", "Shift", "")],
    requires_project=True,
)
def shift_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set a team member shift."""
    root = require_project(ctx, "editing shift schedule")
    raw = settings_dict(ctx)
    team = raw.setdefault("team", [])
    found = next(
        (item for item in team if isinstance(item, dict) and item.get("name") == values["name"]),
        None,
    )
    if found is None:
        raise FeatureInputError("Enter an existing team member name.")
    found["shift"] = values["shift"]
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(summary={"name": values["name"], "shift": values["shift"]})


@feature(
    "overviewTeam.teamActivity", "Team Activity", part="settings", fields=[], requires_project=True
)
def team_activity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List team members and their stored task or activity counts."""
    rows = [
        {
            "name": item.get("name", ""),
            "role": item.get("role", ""),
            "taskCount": len(item.get("tasks", [])) if isinstance(item.get("tasks"), list) else 0,
        }
        for item in _team(ctx)
    ]
    return result(
        summary={"memberCount": len(rows)},
        tables=[
            table(
                "Team activity", [("name", "Name"), ("role", "Role"), ("taskCount", "Tasks")], rows
            )
        ],
    )
