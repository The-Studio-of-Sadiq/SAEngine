"""Builds the SAEngine User Manual PDF from the Markdown chapters of this folder.

The chapters are converted to Typst markup (a small converter for the Markdown used here:
headings, paragraphs, lists, tables, images, block quotes, code blocks, emphasis, inline code and
links) and compiled with the ``typst`` Python package:

    .venv\\Scripts\\python docs\\manual\\build.py [--typ manual.typ] [--out SAEngine-User-Manual.pdf]

``--typ`` also writes the generated Typst source, for checking it.
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

VERSION = "0.0.42"

CHAPTERS = [
    "README.md",
    "00-getting-started.md",
    "01-soil-report.md",
    "02-project-settings.md",
    "03-materials.md",
    "04-objects.md",
    "05-floor-plan.md",
    "06-bim.md",
    "07-mep.md",
    "08-fem.md",
    "09-substructure.md",
    "10-boq.md",
    "11-exports.md",
    "12-importing.md",
    "13-reference.md",
    "14-packages.md",
    "glossary.md",
]

TUTORIALS = [
    "tutorials/01-sample-project.md",
    "tutorials/02-six-storey-building.md",
    "tutorials/03-soil-and-footings.md",
    "tutorials/04-etabs-import.md",
]

# Characters with a meaning in Typst markup; escaped with a backslash in text.
_SPECIAL = set("\\*_`$#[]<>@~/=-+'\"")


def label_of(path: str) -> str:
    return "ch-" + re.sub(r"[^a-z0-9]+", "-", Path(path).stem.lower()).strip("-")


def escape(text: str) -> str:
    return "".join("\\" + c if c in _SPECIAL else c for c in text)


def string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


_INLINE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<img>!\[[^\]]*\]\([^)]+\))"
    r"|(?P<link>\[[^\]]+\]\([^)]+\))"
    r"|(?P<bold>\*\*.+?\*\*)"
    r"|(?P<ital>(?<![\w*])\*(?!\s)[^*]+?\*(?![\w*])|(?<!\w)_(?!\s)[^_]+?_(?!\w))"
)


class Converter:
    def __init__(self, source: str):
        self.source = source  # the chapter's path relative to HERE, for links and images

    # Inline -------------------------------------------------------------------------------

    def inline(self, text: str) -> str:
        out = []
        pos = 0
        for m in _INLINE.finditer(text):
            out.append(escape(text[pos:m.start()]))
            kind, token = m.lastgroup, m.group()
            if kind == "code":
                out.append("#raw(" + string(token[1:-1]) + ")")
            elif kind == "bold":
                out.append("#strong[" + self.inline(token[2:-2]) + "]")
            elif kind == "ital":
                out.append("#emph[" + self.inline(token[1:-1]) + "]")
            elif kind == "link":
                label, target = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token).groups()
                out.append(self.link(label, target))
            else:  # an image inside a paragraph: shown as its alt text
                out.append(escape(re.match(r"!\[([^\]]*)\]", token).group(1)))
            pos = m.end()
        out.append(escape(text[pos:]))
        return "".join(out)

    def link(self, label: str, target: str) -> str:
        text = self.inline(label)
        if re.match(r"https?://", target):
            return "#link(" + string(target) + ")[" + text + "]"
        path = target.split("#", 1)[0]
        if not path:
            return text
        resolved = (HERE / Path(self.source).parent / path).resolve()
        try:
            rel = resolved.relative_to(HERE).as_posix()
        except ValueError:
            rel = None
        if (rel in CHAPTERS or rel in TUTORIALS) and resolved.exists():
            return "#link(<" + label_of(rel) + ">)[" + text + "]"
        # Files outside the manual (docs/cli.md, the e2k file, ...): name them.
        shown = resolved.relative_to(HERE.parent.parent).as_posix() if HERE.parent.parent in resolved.parents else path
        if label.strip("`") == shown or label.strip("`") == Path(shown).name:
            return text
        return text + " (" + "#raw(" + string(shown) + "))"

    # Blocks -------------------------------------------------------------------------------

    def convert(self, markdown: str) -> str:
        lines = markdown.replace("\r\n", "\n").split("\n")
        out: list[str] = []
        i = 0
        first_heading = True
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            if line.startswith("```"):
                lang = line[3:].strip()
                body = []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    body.append(lines[i])
                    i += 1
                i += 1
                args = "block: true, " + (f"lang: {string(lang)}, " if lang and lang != "console" else "")
                out.append("#block(fill: luma(245), inset: 8pt, radius: 3pt, width: 100%)[#raw(" + args + string("\n".join(body)) + ")]")
                continue
            m = re.match(r"(#{1,6})\s+(.*)", line)
            if m:
                level = len(m.group(1))
                text = self.inline(m.group(2))
                if level == 1 and first_heading:
                    out.append("#chapter[" + text + "] <" + label_of(self.source) + ">")
                    first_heading = False
                else:
                    out.append("=" * min(level, 4) + " " + text)
                i += 1
                continue
            if line.lstrip().startswith("|"):
                rows = []
                while i < len(lines) and lines[i].lstrip().startswith("|"):
                    rows.append(lines[i].strip())
                    i += 1
                out.append(self.table(rows))
                continue
            m = re.match(r"\s*!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
            if m:
                out.append(self.image(m.group(1), m.group(2)))
                i += 1
                continue
            if line.lstrip().startswith(">"):
                quote = []
                while i < len(lines) and lines[i].lstrip().startswith(">"):
                    text = lines[i].lstrip()[1:]
                    quote.append(text[1:] if text.startswith(" ") else text)
                    i += 1
                out.append("#note[" + Converter(self.source).convert("\n".join(quote)) + "]")
                continue
            if re.match(r"\s*([-*]|\d+\.)\s+", line):
                block = []
                while i < len(lines) and lines[i].strip() and (re.match(r"\s*([-*]|\d+\.)\s+", lines[i]) or lines[i].startswith(" ")):
                    block.append(lines[i])
                    i += 1
                out.append(self.lists(block))
                continue
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,6}\s|\s*\||```|\s*>|\s*!\[|\s*([-*]|\d+\.)\s)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(self.inline(" ".join(para)))
        return "\n\n".join(out)

    def lists(self, block: list[str]) -> str:
        items: list[tuple[int, str, str]] = []  # (indent, marker, text)
        for line in block:
            m = re.match(r"(\s*)([-*]|\d+\.)\s+(.*)", line)
            if m:
                items.append((len(m.group(1)), m.group(2) if m.group(2)[0].isdigit() else "-", m.group(3)))
            elif items:
                indent, marker, text = items[-1]
                items[-1] = (indent, marker, text + " " + line.strip())
        indents = sorted({indent for indent, _, _ in items})
        out = []
        for indent, marker, text in items:
            depth = indents.index(indent)
            out.append("  " * depth + marker + " " + self.inline(text))
        return "\n".join(out)

    def table(self, rows: list[str]) -> str:
        # "\|" is a pipe inside a cell, not a separator.
        cells = [[c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row.strip()[1:-1])] for row in rows]
        cells = [r for r in cells if not all(re.fullmatch(r":?-{3,}:?", c) for c in r if c)]
        n = max(len(r) for r in cells)
        cells = [r + [""] * (n - len(r)) for r in cells]
        lengths = [max(len(r[c]) for r in cells) for c in range(n)]
        widths = ", ".join(f"{max(1.0, math.sqrt(length)):.1f}fr" for length in lengths)
        parts = [f"#table(columns: ({widths},), table.header("]
        parts.append(", ".join("[#strong[" + self.inline(c) + "]]" for c in cells[0]))
        parts.append("),")
        for row in cells[1:]:
            parts.append("  " + ", ".join("[" + self.inline(c) + "]" for c in row) + ",")
        parts.append(")")
        return "\n".join(parts)

    def image(self, alt: str, target: str) -> str:
        path = (HERE / Path(self.source).parent / target).resolve()
        if not path.exists():
            return "#missing[" + escape(target) + "]"
        rel = path.relative_to(HERE).as_posix()
        return "#figure(image(" + string(rel) + ", width: 100%), caption: [" + self.inline(alt) + "])"


PREAMBLE = r"""
#set document(title: "SAEngine User Manual", author: "SAEngine")
#set page(paper: "a4", margin: (x: 2cm, top: 2.2cm, bottom: 2.2cm),
  header: context { if counter(page).get().first() > 2 [#set text(8pt, fill: luma(110)); SAEngine User Manual #h(1fr) version VERSION] },
  footer: context { if counter(page).get().first() > 1 [#set text(8pt, fill: luma(110)); #h(1fr) #counter(page).display() #h(1fr)] })
#set text(font: ("Segoe UI", "Libertinus Serif", "New Computer Modern"), size: 9.5pt, lang: "en")
#set par(justify: false, leading: 0.6em, spacing: 0.9em)
#set heading(numbering: none)
#show heading.where(level: 2): it => block(above: 1.4em, below: 0.7em, text(13pt, weight: "bold", fill: rgb("#0b5cad"), it.body))
#show heading.where(level: 3): it => block(above: 1.2em, below: 0.6em, text(11pt, weight: "bold", it.body))
#show heading.where(level: 4): it => block(above: 1em, below: 0.5em, text(10pt, weight: "bold", it.body))
#show raw: set text(font: ("Cascadia Mono", "Consolas", "DejaVu Sans Mono"), size: 8.5pt)
#show link: set text(fill: rgb("#0b5cad"))
#set table(stroke: 0.5pt + luma(190), inset: 5pt, fill: (_, y) => if y == 0 { luma(235) })
#show table: set text(8.5pt)
#show figure.caption: set text(8.5pt, fill: luma(80))
#show figure: set block(breakable: false, above: 1em, below: 1.2em)

#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  block(below: 1em, text(20pt, weight: "bold", it.body))
}
#show outline.entry.where(level: 1): it => { v(0.6em, weak: true); strong(it) }
#let chapter(body) = heading(level: 1, body)
#let part(body, intro) = {
  heading(level: 1, body)
  intro
}
#let note(body) = block(fill: rgb("#eef4fb"), stroke: (left: 3pt + rgb("#0b5cad")), inset: 9pt, width: 100%, body)
#let missing(name) = block(stroke: 1pt + red, inset: 8pt)[Missing image: #name]

#page(header: none, footer: none)[
  #v(25%)
  #text(30pt, weight: "bold")[SAEngine User Manual]
  #v(0.5em)
  #text(14pt)[Structural analysis and design to BNBC 2020]
  #v(2em)
  #text(11pt)[Version VERSION (Pre Alpha 5)]
  #v(1fr)
  #text(9pt, fill: luma(90))[SAEngine is free software under the GNU Affero General Public License v3.0. This manual describes the program as it is in this version; check every result independently before using it for construction. All projects, boreholes and models in it are synthetic.]
]

#page(header: none)[
  #outline(title: [Contents], depth: 2, indent: 1.5em)
]
""".replace("VERSION", VERSION)


def build() -> str:
    parts = [PREAMBLE]
    for chapter in CHAPTERS:
        markdown = (HERE / chapter).read_text(encoding="utf-8")
        if chapter == "README.md":
            # The index's contents list is replaced by the PDF's own outline.
            markdown = markdown.split("## Contents", 1)[0] + "## Conventions" + markdown.split("## Conventions", 1)[1]
        parts.append(Converter(chapter).convert(markdown))
    parts.append("#part[Tutorials][Four step-by-step tutorials, each from a project you can make yourself. All data in them is synthetic.]")
    for tutorial in TUTORIALS:
        if not (HERE / tutorial).exists():
            print(f"warning: {tutorial} is missing")
            continue
        parts.append(Converter(tutorial).convert((HERE / tutorial).read_text(encoding="utf-8")))
    return "\n\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--typ", type=Path, help="also write the Typst source here")
    parser.add_argument("--out", type=Path, default=HERE / "SAEngine-User-Manual.pdf")
    args = parser.parse_args()
    import typst

    source = build()
    if args.typ:
        args.typ.write_text(source, encoding="utf-8")
    # Typst reads the images relative to the project root, which must contain the source.
    typ = HERE / ".manual.typ"
    typ.write_text(source, encoding="utf-8")
    try:
        typst.compile(str(typ), output=str(args.out), root=str(HERE))
    finally:
        typ.unlink(missing_ok=True)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
