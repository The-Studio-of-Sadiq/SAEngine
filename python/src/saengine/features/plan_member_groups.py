"""Groups ribbon: define member sets, evaluate filters and export group membership."""

from __future__ import annotations

import json

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    result,
    select,
    table,
    text,
)
from saengine.features.plan_common import export_csv, profile, selected_members


def _ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _group_rows(ctx: FeatureContext, raw: str) -> list[dict]:
    _, rows = profile(ctx)
    return selected_members(rows, raw)


@feature(
    "memberGroups.createGroup",
    "Create Group",
    part="floorPlan",
    fields=[
        text("name", "Group name", "North frame"),
        text("memberIds", "Member ids (comma-separated)", "B1,B2,C1"),
    ],
)
def create_group(ctx: FeatureContext, values: dict) -> dict:
    """Create a named member-set definition and validate that its members exist."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={"groupName": values["name"], "memberCount": len(rows)},
        tables=[
            table(
                "Group members",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                rows,
            )
        ],
    )


@feature(
    "memberGroups.groupRules",
    "Group Rules",
    part="floorPlan",
    fields=[
        select(
            "field",
            "Rule property",
            [("category", "Category"), ("type", "Object type"), ("story", "Storey")],
        ),
        text("equals", "Equals", "beam"),
        text("groupName", "Group name", "Concrete beams"),
    ],
)
def group_rules(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate a simple equality rule over member category, type or storey."""
    _, rows = profile(ctx)
    matched = [r for r in rows if str(r.get(values["field"], "")) == values["equals"]]
    return result(
        summary={
            "groupName": values["groupName"],
            "ruleMatches": len(matched),
            "ruleField": values["field"],
        },
        tables=[
            table(
                "Members matched by rule",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                matched,
            )
        ],
    )


@feature(
    "memberGroups.groupManager",
    "Group Manager",
    part="floorPlan",
    fields=[text("groupsJson", "Group definitions JSON", '[{"name":"Beams","members":["B1"]}]')],
)
def group_manager(ctx: FeatureContext, values: dict) -> dict:
    """Validate group names and member references in a supplied group-definition list."""
    _, rows = profile(ctx)
    known = {r["id"] for r in rows}
    try:
        groups = json.loads(values["groupsJson"])
    except ValueError as exc:
        raise FeatureInputError("Group definitions must be valid JSON.") from exc
    if not isinstance(groups, list):
        raise FeatureInputError("Group definitions must be a JSON array.")
    out = []
    for group in groups:
        members = group.get("members", [])
        if not isinstance(members, list):
            raise FeatureInputError("Each group members field must be an array.")
        missing = set(members) - known
        out.append(
            {
                "name": group.get("name", ""),
                "memberCount": len(members),
                "missingMemberCount": len(missing),
                "missingIds": ", ".join(sorted(missing)),
            }
        )
    return result(
        summary={
            "groupCount": len(out),
            "groupsWithMissingMembers": sum(r["missingMemberCount"] > 0 for r in out),
        },
        tables=[
            table(
                "Managed groups",
                [
                    ("name", "Group"),
                    ("memberCount", "Members"),
                    ("missingMemberCount", "Missing"),
                    ("missingIds", "Missing ids"),
                ],
                out,
            )
        ],
    )


@feature(
    "memberGroups.selectGroup",
    "Select Group",
    part="floorPlan",
    fields=[text("memberIds", "Group member ids", "B1,B2,C1")],
)
def select_group(ctx: FeatureContext, values: dict) -> dict:
    """Return all current member rows in an explicit saved group membership list."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={"selectedMembers": len(rows)},
        tables=[
            table(
                "Selected group members",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                rows,
            )
        ],
    )


@feature(
    "memberGroups.filterBuilder",
    "Filter Builder",
    part="floorPlan",
    fields=[
        select(
            "fieldA",
            "First field",
            [("category", "Category"), ("type", "Object type"), ("story", "Storey")],
        ),
        text("valueA", "First value", "beam"),
        select("join", "Join condition", [("and", "AND"), ("or", "OR")]),
        select(
            "fieldB",
            "Second field",
            [("category", "Category"), ("type", "Object type"), ("story", "Storey")],
        ),
        text("valueB", "Second value", "L1"),
    ],
)
def filter_builder(ctx: FeatureContext, values: dict) -> dict:
    """Apply two property-equality predicates with an explicit AND/OR join."""
    _, rows = profile(ctx)
    left = lambda r: str(r.get(values["fieldA"], "")) == values["valueA"]
    right = lambda r: str(r.get(values["fieldB"], "")) == values["valueB"]
    matched = (
        [r for r in rows if (left(r) and right(r)) if values["join"] == "and"]
        if values["join"] == "and"
        else [r for r in rows if left(r) or right(r)]
    )
    return result(
        summary={"matchedRows": len(matched), "join": values["join"]},
        tables=[
            table(
                "Filter results",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                matched,
            )
        ],
    )


@feature(
    "memberGroups.quickFilter",
    "Quick Filter",
    part="floorPlan",
    fields=[text("query", "Search member ids and type ids", "B3")],
)
def quick_filter(ctx: FeatureContext, values: dict) -> dict:
    """Find member rows whose id, type, category or storey contains the search text."""
    _, rows = profile(ctx)
    term = values["query"].casefold()
    matches = [
        r
        for r in rows
        if term
        in " ".join(str(r.get(k, "")) for k in ("id", "type", "category", "story")).casefold()
    ]
    return result(
        summary={"matchedRows": len(matches), "searchTerm": values["query"]},
        tables=[
            table(
                "Quick-filter matches",
                [("id", "Member"), ("type", "Type"), ("category", "Category"), ("story", "Storey")],
                matches,
            )
        ],
    )


@feature(
    "memberGroups.savedFilters",
    "Saved Filters",
    part="floorPlan",
    fields=[
        text(
            "filtersJson",
            "Saved filter definitions JSON",
            '[{"name":"Level 1 beams","field":"story","value":"L1"}]',
        )
    ],
)
def saved_filters(ctx: FeatureContext, values: dict) -> dict:
    """Run a set of named property filters and report each filter's result count."""
    _, rows = profile(ctx)
    try:
        filters = json.loads(values["filtersJson"])
    except ValueError as exc:
        raise FeatureInputError("Saved filters must be valid JSON.") from exc
    if not isinstance(filters, list):
        raise FeatureInputError("Saved filters must be a JSON array.")
    allowed = {"id", "category", "type", "story"}
    out = []
    for item in filters:
        if item.get("field") not in allowed:
            raise FeatureInputError(f"Unknown filter field '{item.get('field')}'.")
        out.append(
            {
                "name": item.get("name", ""),
                "field": item["field"],
                "value": item.get("value", ""),
                "matchCount": sum(
                    str(r.get(item["field"], "")) == str(item.get("value", "")) for r in rows
                ),
            }
        )
    return result(
        summary={"savedFilterCount": len(out)},
        tables=[
            table(
                "Saved filter results",
                [
                    ("name", "Filter"),
                    ("field", "Field"),
                    ("value", "Value"),
                    ("matchCount", "Matches"),
                ],
                out,
            )
        ],
    )


@feature(
    "memberGroups.saveSelection",
    "Save Selection",
    part="floorPlan",
    fields=[
        text("selectionName", "Selection name", "Roof beams"),
        text("memberIds", "Selected member ids", "B1,B2"),
    ],
)
def save_selection(ctx: FeatureContext, values: dict) -> dict:
    """Package a verified member selection as a named reusable selection definition."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={"selectionName": values["selectionName"], "savedMemberCount": len(rows)},
        tables=[
            table(
                "Saved selection",
                [("position", "Order"), ("memberId", "Member")],
                [{"position": i + 1, "memberId": r["id"]} for i, r in enumerate(rows)],
            )
        ],
    )


@feature(
    "memberGroups.recallSelection",
    "Recall Selection",
    part="floorPlan",
    fields=[text("savedMemberIds", "Saved selection ids", "B1,B2")],
)
def recall_selection(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a supplied selection set against the current member model and report stale ids."""
    _, rows = profile(ctx)
    ids = _ids(values["savedMemberIds"])
    known = {r["id"] for r in rows}
    existing = [r for r in rows if r["id"] in ids]
    stale = sorted(set(ids) - known)
    return result(
        summary={"recalledMembers": len(existing), "staleMemberIds": len(stale)},
        tables=[
            table(
                "Recalled selection",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                existing,
            )
        ],
        notes=[f"Ids no longer in the model: {', '.join(stale) if stale else 'none'}."],
    )


@feature(
    "memberGroups.selectionColour",
    "Selection Colour",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,B2"),
        text("colourHex", "Display colour", "#2E86AB"),
    ],
    requires_project=False,
)
def selection_colour(ctx: FeatureContext, values: dict) -> dict:
    """Validate a six-digit hexadecimal color and attach it to an explicit member set."""
    if (
        len(values["colourHex"]) != 7
        or not values["colourHex"].startswith("#")
        or any(c not in "0123456789abcdefABCDEF" for c in values["colourHex"][1:])
    ):
        raise FeatureInputError("Enter a six-digit hexadecimal colour such as #2E86AB.")
    return result(
        summary={
            "memberCount": len(_ids(values["memberIds"])),
            "colour": values["colourHex"].upper(),
        }
    )


@feature(
    "memberGroups.selectionOrder",
    "Selection Order",
    part="floorPlan",
    fields=[text("memberIds", "Member ids in desired order", "B4,B1,B3")],
)
def selection_order(ctx: FeatureContext, values: dict) -> dict:
    """Preserve a deliberate selection order after verifying that all member ids exist."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={"orderedSelectionCount": len(rows)},
        tables=[
            table(
                "Selection order",
                [("position", "Position"), ("memberId", "Member")],
                [
                    {"position": i + 1, "memberId": mid}
                    for i, mid in enumerate(_ids(values["memberIds"]))
                ],
            )
        ],
    )


@feature(
    "memberGroups.invertSelection",
    "Invert Selection",
    part="floorPlan",
    fields=[text("selectedIds", "Selected ids to invert", "B1,B2")],
)
def invert_selection(ctx: FeatureContext, values: dict) -> dict:
    """Return every model member not contained in the supplied explicit selection."""
    _, rows = profile(ctx)
    selected = set(_ids(values["selectedIds"]))
    known = {r["id"] for r in rows}
    unknown = selected - known
    if unknown:
        raise FeatureInputError(f"Unknown member id(s): {', '.join(sorted(unknown))}.")
    inverse = [r for r in rows if r["id"] not in selected]
    return result(
        summary={"invertedMemberCount": len(inverse), "excludedCount": len(selected)},
        tables=[
            table(
                "Inverted selection",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                inverse,
            )
        ],
    )


@feature(
    "memberGroups.rulePriority",
    "Rule Priority",
    part="floorPlan",
    fields=[
        text("ruleNames", "Rule names in priority order", "Columns,Beams,Level 1"),
        text("priorityWeights", "Priority weights", "100,50,10"),
    ],
    requires_project=False,
)
def rule_priority(ctx: FeatureContext, values: dict) -> dict:
    """Order group rules by an explicit unique priority weight."""
    names = [x.strip() for x in values["ruleNames"].split(",") if x.strip()]
    try:
        weights = [float(x.strip()) for x in values["priorityWeights"].split(",") if x.strip()]
    except ValueError as exc:
        raise FeatureInputError("Priority weights must be numeric.") from exc
    if len(names) != len(weights) or len(set(weights)) != len(weights):
        raise FeatureInputError("Supply one unique numeric priority weight for each rule.")
    rows = sorted(
        ({"rule": name, "weight": weight} for name, weight in zip(names, weights)),
        key=lambda r: r["weight"],
        reverse=True,
    )
    return result(
        summary={"priorityRuleCount": len(rows)},
        tables=[
            table(
                "Rule evaluation order",
                [("priority", "Order"), ("rule", "Rule"), ("weight", "Priority")],
                [{"priority": i + 1, **row} for i, row in enumerate(rows)],
            )
        ],
    )


@feature(
    "memberGroups.rulePreview",
    "Rule Preview",
    part="floorPlan",
    fields=[
        select(
            "field",
            "Rule property",
            [("category", "Category"), ("type", "Type"), ("story", "Storey")],
        ),
        select(
            "comparison",
            "Comparison",
            [("equals", "Equals"), ("contains", "Contains"), ("startsWith", "Starts with")],
        ),
        text("value", "Rule value", "beam"),
    ],
)
def rule_preview(ctx: FeatureContext, values: dict) -> dict:
    """Preview the selected equality, substring or prefix rule against member properties."""
    _, rows = profile(ctx)
    needle = values["value"].casefold()

    def matches(row: dict) -> bool:
        actual = str(row.get(values["field"], "")).casefold()
        return (
            actual == needle
            if values["comparison"] == "equals"
            else needle in actual
            if values["comparison"] == "contains"
            else actual.startswith(needle)
        )

    selected = [r for r in rows if matches(r)]
    return result(
        summary={
            "matchedMembers": len(selected),
            "field": values["field"],
            "comparison": values["comparison"],
        },
        tables=[
            table(
                "Rule preview members",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                selected,
            )
        ],
    )


@feature(
    "memberGroups.ruleConflicts",
    "Rule Conflicts",
    part="floorPlan",
    fields=[
        text(
            "rulesJson",
            "Rules JSON",
            '[{"name":"All beams","field":"category","value":"beam"},{"name":"Level 1","field":"story","value":"L1"}]',
        )
    ],
)
def rule_conflicts(ctx: FeatureContext, values: dict) -> dict:
    """Find members captured by more than one equality rule in the supplied rule set."""
    _, rows = profile(ctx)
    try:
        rules = json.loads(values["rulesJson"])
    except ValueError as exc:
        raise FeatureInputError("Rules must be valid JSON.") from exc
    if not isinstance(rules, list):
        raise FeatureInputError("Rules must be a JSON array.")
    allowed = {"id", "category", "type", "story"}
    matches = {}
    for rule in rules:
        if rule.get("field") not in allowed:
            raise FeatureInputError(f"Unknown rule property '{rule.get('field')}'.")
        for row in rows:
            if str(row.get(rule["field"], "")) == str(rule.get("value", "")):
                matches.setdefault(row["id"], []).append(rule.get("name", "unnamed"))
    conflicts = [
        {"memberId": mid, "matchingRules": ", ".join(names)}
        for mid, names in matches.items()
        if len(names) > 1
    ]
    return result(
        summary={"conflictingMembers": len(conflicts), "ruleCount": len(rules)},
        tables=[
            table(
                "Rule overlaps",
                [("memberId", "Member"), ("matchingRules", "Matching rules")],
                conflicts,
            )
        ],
    )


@feature(
    "memberGroups.ruleImport",
    "Rule Import",
    part="floorPlan",
    fields=[
        text(
            "rulesJson",
            "Imported rules JSON",
            '[{"name":"Beams","field":"category","value":"beam"}]',
        )
    ],
)
def rule_import(ctx: FeatureContext, values: dict) -> dict:
    """Validate imported member-group rules and count their current model matches."""
    _, rows = profile(ctx)
    try:
        rules = json.loads(values["rulesJson"])
    except ValueError as exc:
        raise FeatureInputError("Imported rules must be valid JSON.") from exc
    if not isinstance(rules, list):
        raise FeatureInputError("Imported rules must be a JSON array.")
    allowed = {"id", "category", "type", "story"}
    out = []
    for rule in rules:
        field = rule.get("field")
        if field not in allowed:
            raise FeatureInputError(f"Imported rule field '{field}' is not supported.")
        out.append(
            {
                "name": rule.get("name", ""),
                "field": field,
                "value": rule.get("value", ""),
                "currentMatches": sum(
                    str(r.get(field, "")) == str(rule.get("value", "")) for r in rows
                ),
            }
        )
    return result(
        summary={"validRules": len(out)},
        tables=[
            table(
                "Imported rule preview",
                [
                    ("name", "Rule"),
                    ("field", "Property"),
                    ("value", "Value"),
                    ("currentMatches", "Matches"),
                ],
                out,
            )
        ],
    )


@feature(
    "memberGroups.groupRename",
    "Group Rename",
    part="floorPlan",
    fields=[
        text("oldName", "Current group name", "Beams"),
        text("newName", "New group name", "Floor beams"),
    ],
    requires_project=False,
)
def group_rename(ctx: FeatureContext, values: dict) -> dict:
    """Create a rename record for a group label while retaining its member-set identity."""
    if not values["oldName"].strip() or not values["newName"].strip():
        raise FeatureInputError("Both current and new group names are required.")
    return result(
        summary={
            "previousName": values["oldName"],
            "newName": values["newName"],
            "memberReferencesPreserved": True,
        }
    )


@feature(
    "memberGroups.groupClone",
    "Group Clone",
    part="floorPlan",
    fields=[
        text("sourceName", "Source group", "Floor beams"),
        text("newName", "Cloned group name", "Floor beams copy"),
        text("memberIds", "Source member ids", "B1,B2"),
    ],
)
def group_clone(ctx: FeatureContext, values: dict) -> dict:
    """Clone a verified member group definition under a new name."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={
            "sourceGroup": values["sourceName"],
            "newGroup": values["newName"],
            "clonedMembers": len(rows),
        },
        tables=[
            table(
                "Cloned membership",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                rows,
            )
        ],
    )


@feature(
    "memberGroups.groupMerge",
    "Group Merge",
    part="floorPlan",
    fields=[
        text("groupAIds", "First group member ids", "B1,B2"),
        text("groupBIds", "Second group member ids", "B2,C1"),
        text("mergedName", "Merged group name", "Combined frame"),
    ],
)
def group_merge(ctx: FeatureContext, values: dict) -> dict:
    """Merge two explicit group memberships and report unique members and overlaps."""
    a = _group_rows(ctx, values["groupAIds"])
    b = _group_rows(ctx, values["groupBIds"])
    aid = {r["id"] for r in a}
    bid = {r["id"] for r in b}
    merged = sorted(aid | bid)
    return result(
        summary={
            "mergedName": values["mergedName"],
            "uniqueMemberCount": len(merged),
            "overlapCount": len(aid & bid),
        },
        tables=[
            table(
                "Merged group members",
                [("position", "Order"), ("id", "Member")],
                [{"position": i + 1, "id": mid} for i, mid in enumerate(merged)],
            )
        ],
    )


@feature(
    "memberGroups.groupExport",
    "Group Export",
    part="floorPlan",
    fields=[
        text("groupName", "Group name", "South frame"),
        text("memberIds", "Group member ids", "B1,B2"),
        text("filename", "CSV filename", "member-group.csv"),
    ],
)
def group_export(ctx: FeatureContext, values: dict) -> dict:
    """Write explicit group membership and resolved member properties to a CSV export."""
    rows = _group_rows(ctx, values["memberIds"])
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple CSV filename without folders.")
    path = export_csv(
        ctx,
        name,
        ["groupName", "id", "category", "type", "story", "lengthM"],
        [{"groupName": values["groupName"], **row} for row in rows],
    )
    return result(
        summary={"exportedMembers": len(rows), "file": path},
        notes=[f"Wrote group membership to {path}."],
    )


@feature(
    "memberGroups.temporaryHide",
    "Temporary Hide",
    part="floorPlan",
    fields=[text("memberIds", "Member ids to hide", "B1,B2")],
)
def temporary_hide(ctx: FeatureContext, values: dict) -> dict:
    """Separate selected members from remaining model rows for a temporary hidden view."""
    _, rows = profile(ctx)
    hidden = selected_members(rows, values["memberIds"])
    {r["id"] for r in hidden}
    return result(
        summary={"temporarilyHidden": len(hidden), "remainingVisible": len(rows) - len(hidden)},
        tables=[
            table(
                "Hidden members",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                hidden,
            )
        ],
    )


@feature(
    "memberGroups.revealGroup",
    "Reveal Group",
    part="floorPlan",
    fields=[text("memberIds", "Member ids to reveal", "B1,B2")],
)
def reveal_group(ctx: FeatureContext, values: dict) -> dict:
    """Resolve hidden group ids and return the member rows that should be restored to view."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={"revealedMembers": len(rows)},
        tables=[
            table(
                "Revealed group members",
                [("id", "Member"), ("category", "Category"), ("type", "Type")],
                rows,
            )
        ],
    )


@feature(
    "memberGroups.isolateMembers",
    "Isolate Members",
    part="floorPlan",
    fields=[text("memberIds", "Member ids to isolate", "B1,B2")],
)
def isolate_members(ctx: FeatureContext, values: dict) -> dict:
    """Return an isolated member set plus count of model members hidden from the view."""
    _, rows = profile(ctx)
    visible = selected_members(rows, values["memberIds"])
    return result(
        summary={"isolatedCount": len(visible), "hiddenCount": len(rows) - len(visible)},
        tables=[
            table(
                "Isolated members",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                visible,
            )
        ],
    )


@feature(
    "memberGroups.groupSnapshot",
    "Group Snapshot",
    part="floorPlan",
    fields=[
        text("groupName", "Group name", "Core wall lines"),
        text("memberIds", "Group member ids", "W1,C1,C2"),
    ],
)
def group_snapshot(ctx: FeatureContext, values: dict) -> dict:
    """Capture a deterministic snapshot table of group members and their current geometry."""
    rows = _group_rows(ctx, values["memberIds"])
    return result(
        summary={
            "groupName": values["groupName"],
            "snapshotMembers": len(rows),
            "totalLengthM": sum(r.get("lengthM", 0) for r in rows),
        },
        tables=[
            table(
                "Group snapshot",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("type", "Type"),
                    ("story", "Storey"),
                    ("lengthM", "Length", "m"),
                    ("areaM2", "Area", "m²"),
                ],
                rows,
            )
        ],
    )
