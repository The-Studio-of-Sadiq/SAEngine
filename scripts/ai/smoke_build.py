"""Opt-in real-model smoke test: one prompt -> a designed building, with the SAEngine tools.

Runs only when SAENGINE_AI_SMOKE_KEY (an Anthropic API key) is set; never in CI. It starts the
engine's RPC server, gives a Claude model the assistant's action tools (list_actions,
describe_action, run_actions: python/tests/ai_host.py, the app's rules with the engineer always
agreeing), sends one prompt and runs the tool loop until the model is done. It writes to a local
folder (default: ./ai-smoke-<time>, outside the repository is better):

- ``project/``: the project the model built;
- ``transcript.json``: every message, tool call and answer, with their timings;
- ``summary.json``: the model, the times, the tokens, and the checks of the result (part statuses,
  failing members, the report present).

The key is read from the environment only and never written. Transcripts can hold project data:
keep them out of the repository (the default folder is git-ignored under ``ai-smoke-*``).

    set SAENGINE_AI_SMOKE_KEY=...
    python scripts/ai/smoke_build.py [--out DIR] [--model claude-opus-5-5] [--prompt "..."]

The Anthropic SDK is not part of SAEngine's environment, so the Messages API is called over HTTPS
directly (urllib).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "python"), str(REPO / "python" / "src")]

from tests.ai_host import TOOLS, Engine, Host

KEY_VARIABLE = "SAENGINE_AI_SMOKE_KEY"
API = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_PROMPT = (
    "Build a 3-storey RC residential building in Dhaka, 3x2 bays of 5 m, 3 m storeys, in the "
    "empty project folder: create the project, set the site, materials, grid, storeys, member "
    "types, members and loads, run the analysis, size the footings, Run All, apply Design "
    "Reinforcement (I ask for it), Run All again and tell me the results and what fails."
)
SYSTEM = (
    "You are SAEngine's assistant for structural engineers. You change the project only with "
    "the actions (list_actions, describe_action, run_actions). Read an action's parameters "
    "before you use it. Send edits as their own batches and run steps (writes: true) in batches "
    "of their own. When a batch is refused, read each problem and correct the values. Lengths "
    "are in mm, loads in kN/m², kN/m and kN. Report results with their status; never call a "
    "design approved: the engineer checks it."
)
MAX_TURNS = 60


def ask(key: str, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM,
        "tools": TOOLS,
        "messages": messages,
        "output_config": {"effort": "high"},
        "fallbacks": "default",  # a declined request is re-run on a fallback model
    }
    request = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": key,
            "anthropic-version": "2026-10-21",
            "anthropic-beta": "server-side-fallback-2026-07-01",
            "content-type": "application/json",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 529) and attempt < 3:
                time.sleep(
                    float(error.headers.get("retry-after") or 10 * (attempt + 1))
                )
                continue
            detail = error.read().decode("utf-8", "replace")
            raise SystemExit(f"The API answered {error.code}: {detail}") from None
    raise SystemExit("The API did not answer.")


def checks(root: Path, engine: Engine) -> dict[str, Any]:
    """What the result holds: part statuses, failing members, the report."""
    out: dict[str, Any] = {"report": (root / "11 Exports" / "report.pdf").is_file()}
    try:
        answer = engine.call(
            "actions/run",
            {
                "projectRoot": str(root),
                "steps": [
                    {"action": "results.summary", "params": {}},
                    {"action": "checks.list", "params": {"failing": True}},
                ],
            },
        )
        summary, failing = (r.get("data") for r in answer["results"][:2])
        out["parts"] = {p["part"]: p["state"] for p in (summary or {}).get("parts", [])}
        out["designCounts"] = (summary or {}).get("design", {}).get("counts")
        out["failingMembers"] = [
            m.get("id") for m in (failing or {}).get("members", [])
        ]
    except Exception as error:  # noqa: BLE001 - the checks say why they could not be read
        out["error"] = str(error)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = parser.parse_args(argv)
    key = os.environ.get(KEY_VARIABLE)
    if not key:
        print(f"{KEY_VARIABLE} is not set: the real-model smoke test is skipped.")
        return 0
    out = args.out or Path.cwd() / time.strftime("ai-smoke-%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=False)
    root = out / "project"
    started = time.monotonic()
    engine = Engine()
    messages: list[dict[str, Any]] = [{"role": "user", "content": args.prompt}]
    log: list[dict[str, Any]] = [{"role": "user", "content": args.prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    stop = "max_turns"
    try:
        host = Host(engine, root)
        for _ in range(MAX_TURNS):
            asked = time.monotonic()
            response = ask(key, args.model, messages)
            for k in usage:
                usage[k] += int((response.get("usage") or {}).get(k) or 0)
            content = response.get("content") or []
            messages.append(
                {"role": "assistant", "content": content}
            )  # thinking blocks kept
            log.append(
                {
                    "role": "assistant",
                    "seconds": round(time.monotonic() - asked, 2),
                    "stop_reason": response.get("stop_reason"),
                    "text": [b.get("text") for b in content if b.get("type") == "text"],
                    "tool_calls": [
                        {"name": b["name"], "input": b["input"]}
                        for b in content
                        if b.get("type") == "tool_use"
                    ],
                }
            )
            stop = response.get("stop_reason") or "unknown"
            if stop != "tool_use":
                break
            results = []
            for block in content:
                if block.get("type") != "tool_use":
                    continue
                ok, answer = host.call(block["name"], block.get("input") or {})
                log.append({"role": "tool", **host.transcript[-1]})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": answer
                        if isinstance(answer, str)
                        else json.dumps(answer),
                        **({} if ok else {"is_error": True}),
                    }
                )
            messages.append({"role": "user", "content": results})
        result = (
            checks(root, engine)
            if root.exists()
            else {"error": "no project was created"}
        )
    finally:
        engine.close()
    summary = {
        "model": args.model,
        "prompt": args.prompt,
        "stopReason": stop,
        "seconds": round(time.monotonic() - started, 1),
        "toolSeconds": round(
            sum(e.get("seconds", 0) for e in log if e["role"] == "tool"), 1
        ),
        "toolCalls": sum(1 for e in log if e["role"] == "tool"),
        "refused": sum(1 for e in log if e["role"] == "tool" and not e["ok"]),
        "usage": usage,
        "checks": result,
    }
    (out / "transcript.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"Written to {out}")
    return 0 if result.get("report") else 1


if __name__ == "__main__":
    raise SystemExit(main())
