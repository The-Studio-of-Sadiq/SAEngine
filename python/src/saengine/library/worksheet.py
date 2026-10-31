"""Calculation worksheets (``11 Exports/worksheets/<id>.json``): one hand calculation each.

A worksheet is a kind (:mod:`saengine.report.worksheets`, for example a beam in flexure, a
development length or the wind on a sign) and the values entered for it. The calculation is
never stored: it is made again from the inputs, with the design functions of SAEngine and the
code pack in force, each time the worksheet is opened or the report is printed, so a worksheet
always shows what the present code pack gives. The worksheets marked to print go into the
design report's "Calculation worksheets" section.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from saengine.library.labels import field_title

SCHEMA_ID = "saengine.worksheet/1"

#: Where a project keeps its worksheets, beside the reports they print in.
WORKSHEETS_FOLDER = "11 Exports/worksheets"

#: Ids of worksheets: their file names.
WORKSHEET_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


class Worksheet(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )

    schema_: Literal["saengine.worksheet/1"] = Field(default=SCHEMA_ID, alias="schema")
    id: str = Field(
        pattern=WORKSHEET_ID_PATTERN,
        title="Id",
        description="The worksheet's id: its file name in 11 Exports/worksheets.",
    )
    kind: str = Field(min_length=1, title="Kind", description="The calculation it makes.")
    title: str = Field(min_length=1, title="Title", description="Its heading in the report.")
    reference: str = Field(
        default="",
        title="Reference",
        description="Where it applies: a member mark, grid line or drawing (printed under the "
        "heading).",
    )
    print_: bool = Field(
        default=True,
        alias="print",
        title="Print in the report",
        description="Printed in the design report's Calculation worksheets section.",
    )
    order: int = Field(default=0, title="Order", description="Worksheets print by this, then id.")
    inputs: dict[str, float | str | bool] = Field(
        default_factory=dict,
        title="Inputs",
        description="The values entered; an input not given takes the kind's default.",
    )
    notes: str = Field(default="", title="Notes", description="Printed under the calculation.")


def worksheet_path(project_root: str | Path, worksheet_id: str) -> Path:
    return Path(project_root) / WORKSHEETS_FOLDER / f"{worksheet_id}.json"


def read_worksheet(path: Path) -> tuple[Worksheet | None, str | None]:
    """The worksheet in ``path``, or None and why it could not be read."""
    try:
        return Worksheet.model_validate(json.loads(path.read_text(encoding="utf-8"))), None
    except (OSError, ValueError, ValidationError) as error:
        first = str(error).splitlines()[0] if str(error) else type(error).__name__
        return None, f"{WORKSHEETS_FOLDER}/{path.name} could not be read ({first})"


def load_worksheets(project_root: str | Path) -> tuple[list[tuple[Path, Worksheet]], list[str]]:
    """The project's worksheets in print order (``order``, then id) and the files that could not
    be read."""
    folder = Path(project_root) / WORKSHEETS_FOLDER
    found: list[tuple[Path, Worksheet]] = []
    problems: list[str] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            sheet, problem = read_worksheet(path)
            if sheet is None:
                problems.append(str(problem))
            else:
                found.append((path, sheet))
    found.sort(key=lambda item: (item[1].order, item[1].id))
    return found, problems


def save_worksheet(project_root: str | Path, worksheet: Worksheet) -> Path:
    """Writes ``worksheet`` as ``11 Exports/worksheets/<id>.json`` and returns the path."""
    path = worksheet_path(project_root, worksheet.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(worksheet.model_dump(mode="json", by_alias=True), indent="\t")
    path.write_text(text + "\n", encoding="utf-8")
    return path
