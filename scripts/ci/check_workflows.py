"""Structural check of SAEngine's GitHub Actions workflows (.github/workflows/*.yml).

    python check_workflows.py [--actionlint PATH]

Needs PyYAML. For every workflow: it parses; it has a name, triggers, top-level
``permissions`` and ``concurrency``; every job has ``runs-on``, ``timeout-minutes`` and steps;
every step has exactly one of ``uses`` and ``run``; every action is pinned to a full commit
SHA (``owner/repo@<40 hex>``) or is local (``./``); every repository file a ``run`` script names
(``scripts/...``, ``.github/...``, ``workbench/...`` paths ending in .py, .ps1, .sh, .mjs, .cjs or
.json) exists; and ``${{ secrets.X }}`` uses only GITHUB_TOKEN (the only secret SAEngine's
workflows need). It then runs actionlint when it is found (on PATH, in the active environment's
scripts folder from the actionlint-py package, or --actionlint).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
#: Repository paths in run scripts: from the repository root, or "../" from the workbench folder
#: (the workbench job's working directory); either slash.
SCRIPT_PATH = re.compile(
    r"(?:(?<=\.\./)|(?<![\w./\\-]))"
    r"((?:scripts|\.github|workbench|python|docs)[\\/][\w./\\ -]*?"
    r"\.(?:py|ps1|sh|mjs|cjs|json|cmd))\b"
)
SECRET = re.compile(r"\$\{\{\s*secrets\.(\w+)\s*\}\}")
ALLOWED_SECRETS = {"GITHUB_TOKEN"}


def triggers(workflow: dict) -> object:
    # YAML 1.1 reads the key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def check_workflow(path: Path, repo: Path = REPO) -> list[str]:
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [f"{path.name}: YAML does not parse: {error}"]
    if not isinstance(workflow, dict):
        return [f"{path.name}: not a mapping"]
    for key in ("name", "permissions", "concurrency"):
        if key not in workflow:
            problems.append(f"{path.name}: no top-level '{key}'")
    if not triggers(workflow):
        problems.append(f"{path.name}: no 'on' triggers")
    jobs = workflow.get("jobs") or {}
    if not jobs:
        problems.append(f"{path.name}: no jobs")
    for job_id, job in jobs.items():
        where = f"{path.name}: job {job_id}"
        if "uses" in job:  # a reusable workflow call
            if not str(job["uses"]).startswith("./"):
                problems.append(f"{where}: calls a remote reusable workflow")
            continue
        for key in ("runs-on", "timeout-minutes", "steps"):
            if key not in job:
                problems.append(f"{where}: no '{key}'")
        needs = job.get("needs", [])
        for need in [needs] if isinstance(needs, str) else needs:
            if need not in jobs:
                problems.append(f"{where}: needs unknown job '{need}'")
        for index, step in enumerate(job.get("steps") or []):
            label = f"{where} step {index + 1} ({step.get('name', '?')})"
            has_uses, has_run = "uses" in step, "run" in step
            if has_uses == has_run:
                problems.append(f"{label}: needs exactly one of 'uses' and 'run'")
            if has_uses:
                uses = str(step["uses"])
                if not uses.startswith("./") and not PINNED.match(uses):
                    problems.append(f"{label}: '{uses}' is not pinned to a commit SHA")
                if uses.startswith("./") and not (repo / uses[2:]).exists():
                    problems.append(f"{label}: local action {uses} does not exist")
            if has_run:
                for match in SCRIPT_PATH.finditer(str(step["run"])):
                    name = match.group(1).strip().replace("\\", "/")
                    if "*" in name or "$" in name:
                        continue
                    if not (repo / name).exists():
                        problems.append(f"{label}: runs {name}, which does not exist")
    for secret in SECRET.findall(text):
        if secret not in ALLOWED_SECRETS:
            problems.append(
                f"{path.name}: uses the secret {secret} (only GITHUB_TOKEN is expected)"
            )
    return problems


def find_actionlint(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which("actionlint")
    if found:
        return found
    scripts = Path(sysconfig.get_path("scripts"))
    for name in ("actionlint.exe", "actionlint"):
        if (scripts / name).is_file():
            return str(scripts / name)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--actionlint", help="path of the actionlint binary")
    parser.add_argument("--no-actionlint", action="store_true")
    args = parser.parse_args(argv)
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:
        print(f"no workflows in {WORKFLOWS}", file=sys.stderr)
        return 1
    problems = [p for f in files for p in check_workflow(f)]
    for problem in problems:
        print(f"error: {problem}")
    print(f"{len(files)} workflow(s) checked: {len(problems)} problem(s)")
    status = 1 if problems else 0
    binary = None if args.no_actionlint else find_actionlint(args.actionlint)
    if binary:
        result = subprocess.run([binary, *map(str, files)], check=False, cwd=REPO)
        print(f"actionlint: {'ok' if result.returncode == 0 else 'problems found'}")
        status = status or result.returncode
    elif not args.no_actionlint:
        print("actionlint not found: skipped (pip install actionlint-py to run it)")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
