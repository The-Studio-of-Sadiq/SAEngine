"""Check a verification pack result against the explicit list of expected failures.

    python -m saengine.verification --fast --out OUT        (writes OUT/verification.json)
    python check_verification.py OUT/verification.json

Fails (exit 1) when a case reports an error, when a quantity fails that
``scripts/ci/verification-expected-failures.json`` does not list, when a listed case or quantity
no longer exists, or when that list differs from ``KNOWN_ISSUES`` in
``python/tests/test_verification.py`` (one list of known issues, checked in two places). A listed
quantity that now passes is reported as a notice and accepted: a fix in SAEngine is welcome,
the list is then trimmed by hand. Writes a Markdown summary to ``GITHUB_STEP_SUMMARY`` when set.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "verification-expected-failures.json"
TEST_FILE = HERE.parent.parent / "python" / "tests" / "test_verification.py"


def load_expected(path: Path = EXPECTED) -> dict[str, set[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))["expected_failures"]
    return {case: set(names) for case, names in data.items()}


def known_issues_of_test(path: Path = TEST_FILE) -> dict[str, set[str]] | None:
    """``KNOWN_ISSUES`` of the pytest module (read as a literal, without importing it)."""
    if not path.is_file():
        return None
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "KNOWN_ISSUES" in targets and node.value is not None:
            value = ast.literal_eval(node.value)
            return {case: set(names) for case, names in value.items()}
    return None


def check(
    pack: dict, expected: dict[str, set[str]], test_list: dict[str, set[str]] | None
) -> tuple[list[str], list[str]]:
    """``(errors, notices)`` of a verification.json against the expected failures."""
    errors: list[str] = []
    notices: list[str] = []
    if test_list is not None and test_list != expected:
        errors.append(
            "verification-expected-failures.json and KNOWN_ISSUES in "
            f"python/tests/test_verification.py differ: {sorted_view(expected)} != "
            f"{sorted_view(test_list)}"
        )
    cases = {record["id"]: record for record in pack.get("cases", [])}
    if not cases:
        errors.append("the result lists no cases")
    for case_id, record in cases.items():
        if record.get("error"):
            errors.append(f"{case_id}: error: {record['error']}")
        allowed = expected.get(case_id, set())
        names = {q["name"] for q in record.get("quantities", [])}
        for quantity in record.get("quantities", []):
            name = quantity["name"]
            if quantity["pass"]:
                if name in allowed:
                    notices.append(f"{case_id}: '{name}' now passes; remove it from the list")
            elif name not in allowed:
                errors.append(
                    f"{case_id}: '{name}' fails (SAEngine {quantity['saengine']}, reference "
                    f"{quantity['reference']}, ratio {quantity['ratio']}, tolerance "
                    f"{quantity['tolerance']})"
                )
        for name in sorted(allowed - names):
            errors.append(f"{case_id}: the listed quantity '{name}' is not in the result")
    # CI and the release always run the whole (fast) pack, so a listed case missing from the
    # result was dropped or renamed: the list is stale and must be fixed by hand.
    for case_id in sorted(set(expected) - set(cases)):
        errors.append(
            f"{case_id}: listed as an expected failure but not in the result (stale entry: "
            "update verification-expected-failures.json and KNOWN_ISSUES)"
        )
    return errors, notices


def sorted_view(issues: dict[str, set[str]]) -> dict[str, list[str]]:
    return {case: sorted(names) for case, names in sorted(issues.items())}


def summary_markdown(pack: dict, errors: list[str], notices: list[str]) -> str:
    summary = pack.get("summary", {})
    lines = [
        "### Verification pack",
        "",
        (
            f"{summary.get('passed', '?')} of {summary.get('cases', '?')} cases pass; "
            f"{len(errors)} regression(s)."
        ),
        "",
        "| Case | Pass | Largest deviation |",
        "|---|---|---|",
    ]
    for record in pack.get("cases", []):
        ratios = [q["ratio"] for q in record.get("quantities", []) if q.get("ratio") is not None]
        worst = max(ratios, key=lambda r: abs(r - 1.0)) if ratios else None
        shown = f"{worst:.4f}" if isinstance(worst, (int, float)) else "-"
        lines.append(f"| {record['id']} | {'yes' if record['pass'] else 'no'} | {shown} |")
    lines += [""] + [f"- error: {e}" for e in errors] + [f"- notice: {n}" for n in notices]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result", type=Path, help="verification.json")
    parser.add_argument("--expected", type=Path, default=EXPECTED)
    parser.add_argument("--test-file", type=Path, default=TEST_FILE)
    args = parser.parse_args(argv)
    pack = json.loads(args.result.read_text(encoding="utf-8"))
    errors, notices = check(
        pack, load_expected(args.expected), known_issues_of_test(args.test_file)
    )
    for notice in notices:
        print(f"::notice::{notice}")
    for error in errors:
        print(f"::error::{error}")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(summary_markdown(pack, errors, notices))
    summary = pack.get("summary", {})
    print(
        f"{summary.get('passed', '?')} of {summary.get('cases', '?')} cases pass; "
        f"{len(errors)} regression(s), {len(notices)} notice(s)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
