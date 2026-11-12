"""The printed design report (Part 11 Exports): the calculation report of the project, laid out
once as a document (:mod:`saengine.report.document`, as a report template chooses) and written
as a PDF (typeset with Typst) or a Word file (:mod:`saengine.report.word`)."""

from saengine.report.build import build_report, report_data
from saengine.report.document import register_section, report_document

__all__ = ["build_report", "register_section", "report_data", "report_document"]
