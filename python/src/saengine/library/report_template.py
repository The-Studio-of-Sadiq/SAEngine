"""Report templates (``11 Exports/report-templates/<id>.json``): what the design report prints.

A template chooses the sections of the design report and their order, the detail of each
(summary or full calculations), the cover and the letterhead, and which members the member
design tables and the appendix print. The report is built once (:mod:`saengine.report.document`)
and typeset as PDF or written as Word from the same document, so a template applies to both.

A template is a file of its own so it can be copied between projects and, later, shared as a
marketplace item; the project settings (Design report → Template) say which one the project
prints. Without a template file the built-in default applies: every section, full detail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from saengine.library.labels import field_title

SCHEMA_ID = "saengine.reportTemplate/1"

#: Where a project keeps its report templates, beside the reports they print.
TEMPLATES_FOLDER = "11 Exports/report-templates"

#: The template the project prints when its settings name none (or one that is missing).
DEFAULT_TEMPLATE_ID = "default"

#: Ids of report templates: their file names.
TEMPLATE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"

#: The sections of the report in their default order, each with its heading. "worksheets" is the
#: place calculation worksheets print (they plug in through
#: :func:`saengine.report.document.register_section`); "appendix" is always printed last
#: (landscape pages).
SECTIONS: dict[str, str] = {
    "basis": "Design basis",
    "soil": "Soil and foundations",
    "foundations": "Foundations",
    "model": "Analysis model",
    "results": "Analysis results",
    "design": "Member design",
    "seismic": "Seismic detailing",
    "worksheets": "Calculation worksheets",
    "mep": "MEP coordination",
    "plumbing": "Plumbing",
    "hvac": "HVAC coordination",
    "electrical": "Electrical coordination",
    "fire": "Fire protection",
    "boq": "Bill of quantities",
    "limitations": "Limitations and notes",
    "appendix": "Appendix: element checks",
}

SectionId = Literal[tuple(SECTIONS)]  # type: ignore[valid-type]

#: Member kinds the design tables group by (``saengine.design`` element kinds).
MEMBER_KINDS = ["column", "beam", "slab", "wall", "brace", "staircase", "member"]

MemberKind = Literal[tuple(MEMBER_KINDS)]  # type: ignore[valid-type]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class ReportSection(_Model):
    id: SectionId = Field(
        title="Section",
        json_schema_extra={"enumDescriptions": list(SECTIONS.values())},
    )
    include: bool = Field(default=True, title="Print")
    detail: Literal["inherit", "summary", "full"] = Field(
        default="inherit",
        title="Detail",
        description="Summary: the results and the governing values; full: every table and the "
        "calculations of each element. Inherit: the template's detail.",
        json_schema_extra={"enumDescriptions": ["As the template", "Summary", "Full"]},
    )
    title: str | None = Field(
        default=None,
        title="Heading",
        description="Another heading for the section; empty: its own.",
    )


class Cover(_Model):
    show: bool = Field(default=True, title="Print a cover page")
    title: str = Field(default="Structural Design Report", min_length=1, title="Title")
    subtitle: str | None = Field(default=None, title="Subtitle")
    showStatus: bool = Field(
        default=True,
        title="Design result",
        description="The design result (pass, fail, incomplete) on the cover. A report whose "
        "members fail says so on its cover; turn this off only for a report of inputs.",
    )
    showTitleBlock: bool = Field(
        default=True,
        title="Signature block",
        description="The title block of the drawings (Project Settings → Drawings) for the "
        "signatures.",
    )
    note: str | None = Field(
        default=None,
        title="Note",
        description="Text printed on the cover above the disclaimer (a submission note).",
    )


class Letterhead(_Model):
    enabled: bool = Field(default=False, title="Print a letterhead")
    organisation: str | None = Field(
        default=None,
        title="Organisation",
        description="The firm's name; empty: the firm of the drawings' title block.",
    )
    lines: list[str] = Field(
        default_factory=list,
        title="Lines",
        description="Address, telephone, e-mail: one per line, under the name.",
    )
    logo: str | None = Field(
        default=None,
        title="Logo",
        description="A PNG or JPEG file, its path relative to the project folder.",
        pattern=r"(?i)^[^:*?\"<>|]+\.(png|jpe?g)$",
    )


class MemberSelection(_Model):
    kinds: list[MemberKind] = Field(
        default_factory=list,
        title="Kinds",
        description="The kinds of member the member tables and the appendix print; empty: all.",
    )
    storeys: list[str] = Field(
        default_factory=list,
        title="Storeys",
        description="Storey names (Grids & Stories); empty: all.",
    )
    ids: list[str] = Field(
        default_factory=list,
        title="Members",
        description="Member ids; empty: all (of the kinds and storeys).",
    )
    failingOnly: bool = Field(default=False, title="Only failing members")
    appendix: Literal["settings", "governing", "all", "none"] = Field(
        default="settings",
        title="Appendix",
        description="Which elements the appendix prints every check of: as the project settings "
        "(Design report → Appendix), the governing element of each type and storey and every "
        "failing one, all, or none.",
        json_schema_extra={
            "enumDescriptions": ["As the project settings", "Governing", "All", "None"]
        },
    )


def default_sections() -> list[ReportSection]:
    return [ReportSection(id=section) for section in SECTIONS]


class ReportTemplate(_Model):
    schema_: Literal["saengine.reportTemplate/1"] = Field(default=SCHEMA_ID, alias="schema")
    id: str = Field(
        default=DEFAULT_TEMPLATE_ID,
        pattern=TEMPLATE_ID_PATTERN,
        title="Id",
        description="The template's id: its file name in 11 Exports/report-templates.",
    )
    name: str = Field(default="Full design report", min_length=1, title="Name")
    description: str | None = Field(default=None, title="Description")
    detail: Literal["summary", "full"] = Field(
        default="full",
        title="Detail",
        description="Summary: results and governing values, for a submission or a client; full: "
        "every table and every element's calculations, for checking.",
        json_schema_extra={"enumDescriptions": ["Summary", "Full calculations"]},
    )
    contents: bool = Field(default=True, title="Table of contents")
    paper: Literal["a4", "us-letter"] = Field(
        default="a4", title="Paper", json_schema_extra={"enumDescriptions": ["A4", "US Letter"]}
    )
    sections: list[ReportSection] = Field(
        default_factory=default_sections,
        title="Sections",
        description="The sections in the order they print. A section left out of the list is "
        "not printed; a section without content in this project is skipped.",
    )
    cover: Cover = Field(default_factory=Cover, title="Cover")
    letterhead: Letterhead = Field(default_factory=Letterhead, title="Letterhead")
    members: MemberSelection = Field(default_factory=MemberSelection, title="Member selection")


def default_report_template() -> ReportTemplate:
    return ReportTemplate()


def summary_report_template() -> ReportTemplate:
    """A short report for a submission or a client: the results without the calculations."""
    return ReportTemplate(
        id="summary",
        name="Summary report",
        description="The results and governing values, without the calculations of each element.",
        detail="summary",
        sections=[ReportSection(id=s) for s in SECTIONS if s not in ("appendix", "worksheets")],
        members=MemberSelection(appendix="none"),
    )


#: Templates every project has without a file: id → template.
BUILT_IN = {
    DEFAULT_TEMPLATE_ID: default_report_template,
    "summary": summary_report_template,
}


def template_path(project_root: str | Path, template_id: str) -> Path:
    return Path(project_root) / TEMPLATES_FOLDER / f"{template_id}.json"


def load_template(
    project_root: str | Path, template_id: str | None = None
) -> tuple[ReportTemplate, list[str]]:
    """The template ``template_id`` of the project (its file, else a built-in one, else the
    default) and what was wrong with it. ``template_id`` None: the one the project settings
    name, read by the caller; here the default."""
    wanted = template_id or DEFAULT_TEMPLATE_ID
    problems: list[str] = []
    path = template_path(project_root, wanted)
    if path.is_file():
        try:
            return ReportTemplate.model_validate(json.loads(path.read_text(encoding="utf-8"))), []
        except (OSError, ValueError, ValidationError) as error:
            first = str(error).splitlines()[0] if str(error) else type(error).__name__
            problems.append(
                f"The report template {TEMPLATES_FOLDER}/{path.name} could not be read "
                f"({first}); the default template was printed."
            )
            return default_report_template(), problems
    if wanted in BUILT_IN:
        return BUILT_IN[wanted](), []
    problems.append(
        f"There is no report template '{wanted}' ({TEMPLATES_FOLDER}/{wanted}.json); the default "
        "template was printed."
    )
    return default_report_template(), problems


def list_templates(project_root: str | Path) -> list[dict[str, str]]:
    """The templates the project can print: built-in ones and its files (a file with a built-in
    id replaces it). ``[{id, name, source: "builtIn" | "project", path?}]``."""
    found: dict[str, dict[str, str]] = {
        tid: {"id": tid, "name": make().name, "source": "builtIn"} for tid, make in BUILT_IN.items()
    }
    folder = Path(project_root) / TEMPLATES_FOLDER
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            try:
                template = ReportTemplate.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                name = template.name
            except (OSError, ValueError, ValidationError):
                name = f"{path.stem} (cannot be read)"
            found[path.stem] = {
                "id": path.stem,
                "name": name,
                "source": "project",
                "path": str(path),
            }
    return list(found.values())


def save_template(project_root: str | Path, template: ReportTemplate) -> Path:
    """Writes ``template`` as ``11 Exports/report-templates/<id>.json`` and returns the path."""
    path = template_path(project_root, template.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(template.model_dump(mode="json", by_alias=True), indent="\t")
    path.write_text(text + "\n", encoding="utf-8")
    return path
