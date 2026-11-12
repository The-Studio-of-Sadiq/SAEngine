"""The assistant's action tools (list_actions, describe_action, run_actions) over the real engine's
JSON-RPC server, for the playbook test (tests/test_ai_playbook.py) and the opt-in real-model
smoke script (scripts/ai/smoke_build.py).

It follows the app's rules (``contrib/saengineAi/browser/aiActionTools.ts``): a batch whose steps
write to disk (``writes`` in the catalogue: run steps and project.create) holds only those and
queries, runs with ``write`` after the engineer agrees (here: always) and answers what it wrote;
any other batch is worked out as a change set the engineer accepts (here: always; its texts are
then saved, as the app saves the project before its next run). A refused batch changes nothing
and its problems go back word for word. Not a second implementation of the app: a stand-in for
the window so the engine's side of the contract runs end to end in Python.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class Engine:
    """The engine's stdio JSON-RPC server (``python -m saengine.rpc``)."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "saengine.rpc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.next_id = 0

    def call(self, method: str, params: dict[str, Any]) -> Any:
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        body = json.dumps(message).encode()
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()
        while True:  # notifications (logs) come before the answer
            length = None
            while True:
                line = self.proc.stdout.readline().strip()
                if not line:
                    break
                name, _, value = line.partition(b":")
                if name.lower() == b"content-length":
                    length = int(value)
            if length is None:
                raise RuntimeError("the engine stopped")
            answer = json.loads(self.proc.stdout.read(length))
            if answer.get("id") == self.next_id:
                break
        if "error" in answer:
            raise RuntimeError(answer["error"].get("message"))
        return answer["result"]

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait()


#: The tools as the app offers them to a model (names and schemas of aiTools.ts).
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_actions",
        "description": "The catalogue of SAEngine actions (name, kind, writes, summary): edits, "
        "queries and runs that build and change a whole project, from project.create to the "
        "report. writes: true means the action writes to disk itself (run steps, "
        "project.create).",
        "input_schema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["edit", "query", "run"]}},
            "additionalProperties": False,
        },
    },
    {
        "name": "describe_action",
        "description": "One action with its parameters (JSON schema) and the parts it changes. "
        "Read it before using an action the first time.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_actions",
        "description": "Runs a batch of actions on the project, in order, all or nothing: if a "
        "step fails nothing changes and the answer names the step and each refused value, so "
        "correct those and send it again. Edits come back as ONE change set the engineer "
        "accepts or rejects. A batch with steps that write to disk (writes: true) may hold only "
        "those and queries, so send edits in a batch of their own first; it runs after the "
        "engineer agrees, and the engineer can stop it (cancelled: what was done is said).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"action": {"type": "string"}, "params": {"type": "object"}},
                        "required": ["action"],
                    },
                },
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
]


class Host:
    """The window's side of the tools: one project folder, the engineer always agreeing."""

    def __init__(self, engine: Engine, root: Path) -> None:
        self.engine, self.root = engine, root
        self.catalogue = {a["name"]: a for a in engine.call("actions/list", {})}
        self.transcript: list[dict[str, Any]] = []

    def call(self, name: str, args: dict[str, Any]) -> tuple[bool, Any]:
        """(ok, answer) of the tool ``name``; recorded in :attr:`transcript` with its time."""
        started = time.monotonic()
        if name in ("list_actions", "describe_action", "run_actions"):
            try:
                ok, answer = getattr(self, name)(**args)
            except TypeError as error:  # arguments the tool does not take
                ok, answer = False, f"{name}: {error}"
        else:
            ok, answer = False, f"There is no tool {name}."
        self.transcript.append(
            {
                "tool": name,
                "args": args,
                "ok": ok,
                "answer": answer,
                "seconds": round(time.monotonic() - started, 2),
            }
        )
        return ok, answer

    def list_actions(self, kind: str | None = None) -> tuple[bool, Any]:
        found = [a for a in self.catalogue.values() if kind is None or a["kind"] == kind]
        rows = [
            {"name": a["name"], "kind": a["kind"], "writes": a["writes"], "summary": a["summary"]}
            for a in found
        ]
        return True, {"actions": rows}

    def describe_action(self, name: str) -> tuple[bool, Any]:
        info = self.catalogue.get(name)
        if info is None:
            return False, f'No action "{name}". The actions: {", ".join(self.catalogue)}.'
        return True, {k: info[k] for k in ("name", "kind", "writes", "summary", "params_schema")}

    def run_actions(
        self, steps: list[dict[str, Any]], title: str | None = None
    ) -> tuple[bool, Any]:
        unknown = [s.get("action") for s in steps if s.get("action") not in self.catalogue]
        if unknown:
            return False, f"Unknown action(s): {', '.join(map(str, unknown))}."
        infos = [self.catalogue[s["action"]] for s in steps]
        writes = any(i["writes"] for i in infos)
        if writes:
            edits = [i["name"] for i in infos if i["kind"] == "edit" and not i["writes"]]
            if edits:
                return False, (
                    "A batch with steps that write to disk holds only those and queries. Send "
                    f"the edits ({', '.join(edits)}) as a batch of their own first."
                )
        answer = self.engine.call(
            "actions/run", {"projectRoot": str(self.root), "steps": steps, "write": writes}
        )
        results = [
            {k: v for k, v in r.items() if v not in (None, [], "") and k != "data"}
            | ({"data": r["data"]} if r.get("data") is not None else {})
            for r in answer["results"]
        ]
        if not answer["ok"]:
            written = answer.get("written") or []
            head = (
                "Stopped by the engineer."
                if answer.get("cancelled")
                else "Refused: the batch is all or nothing."
            )
            if written:
                head += f" Written before the failed step and kept: {', '.join(written)}."
            else:
                head += " Nothing was changed."
            return False, {"note": head, "failedStep": answer["failed_step"], "results": results}
        if not writes and answer["changes"]:
            # The engineer accepts the change set; the app saves it before the next run.
            for path, text in answer["changes"].items():
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8", newline="")
            return True, {
                "decision": "accepted",
                "files": sorted(answer["changes"]),
                "results": results,
            }
        return True, {"written": answer.get("written") or [], "results": results}
